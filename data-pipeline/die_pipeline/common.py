"""Shared helpers for the Drought Intelligence Explorer data pipeline.

Everything that more than one step needs lives here: configuration loading
and path resolution, month arithmetic, the application data contract
(registries, indicator file mapping, classification semantics), and the
wide-CSV writer that produces files byte-compatible with the web app.
"""

from __future__ import annotations

import calendar
import csv
import json
import os
import sys
from datetime import date

import numpy as np
import yaml

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------#
# Configuration
# ---------------------------------------------------------------------------#

def load_config(path: str | None = None) -> dict:
    """Load config.yaml (default: the one shipped next to this package)."""
    if path is None:
        path = os.path.join(PIPELINE_DIR, "config.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["_config_path"] = os.path.abspath(path)
    cfg["_pipeline_dir"] = PIPELINE_DIR
    return cfg


def resolve(cfg: dict, *parts: str) -> str:
    """Resolve a possibly-relative path against the config file location."""
    p = os.path.join(*parts)
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(os.path.dirname(cfg["_config_path"]), p))


def app_root(cfg: dict) -> str:
    return resolve(cfg, cfg["paths"]["app_root"])


def boundaries_path(cfg: dict) -> str:
    p = cfg["paths"].get("boundaries")
    if p:
        return resolve(cfg, p)
    return os.path.join(app_root(cfg), "data", "boundaries", "india_districts.geojson")


def registry_path(cfg: dict) -> str:
    p = cfg["paths"].get("registry")
    if p:
        return resolve(cfg, p)
    return os.path.join(app_root(cfg), "data", "districts.csv")


def raw_dir(cfg: dict, sub: str | None = None) -> str:
    d = resolve(cfg, cfg["paths"]["raw"], sub) if sub else resolve(cfg, cfg["paths"]["raw"])
    os.makedirs(d, exist_ok=True)
    return d


def processed_dir(cfg: dict, *sub: str) -> str:
    d = resolve(cfg, cfg["paths"]["processed"], *sub)
    os.makedirs(d, exist_ok=True)
    return d


def processed_file(cfg: dict, *parts: str) -> str:
    """A file path under processed/ — ensures the parent, not the file."""
    p = resolve(cfg, cfg["paths"]["processed"], *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def app_data_dir(cfg: dict, *sub) -> str:
    d = os.path.join(app_root(cfg), "data", *sub)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------#
# Month arithmetic
# ---------------------------------------------------------------------------#

def month_range(start: str, end: str) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) tuples between 'YYYY-MM' strings."""
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append((y, m))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def ym(t: tuple[int, int]) -> str:
    return f"{t[0]:04d}-{t[1]:02d}"


def dates_ok(s: str) -> bool:
    """True if s is a well-formed 'YYYY-MM' month label."""
    try:
        y, m = int(s[:4]), int(s[5:7])
        return len(s) == 7 and s[4] == "-" and 1 <= m <= 12 and 1800 <= y <= 2200
    except (ValueError, TypeError, IndexError):
        return False


def days_in_month(t: tuple[int, int]) -> int:
    return calendar.monthrange(t[0], t[1])[1]


def month_bounds(s: str) -> tuple[date, date]:
    y, m = map(int, s.split("-"))
    return date(y, m, 1), date(y, m, days_in_month((y, m)))


# ---------------------------------------------------------------------------#
# Application data contract
# ---------------------------------------------------------------------------#

# indicator id -> csv file name (must stay in sync with metadata.json)
INDICATOR_FILES = {
    "spi_1": "spi_01.csv", "spi_3": "spi_03.csv", "spi_6": "spi_06.csv",
    "spi_12": "spi_12.csv",
    "spei_1": "spei_01.csv", "spei_3": "spei_03.csv", "spei_6": "spei_06.csv",
    "spei_12": "spei_12.csv",
    "sma": "soil_moisture.csv", "vci": "vci.csv",
}

# Decimals written to the app CSVs (mirrors the shipped application data).
INDICATOR_DECIMALS = {"sma": 0, "vci": 0}  # default 2 for z-score indicators

Z_FAMILIES = ("spi", "spei")


def indicator_decimals(indicator_id: str) -> int:
    return INDICATOR_DECIMALS.get(indicator_id, 2)


def load_registry(cfg: dict) -> tuple[list[dict], list[dict]]:
    """Read districts.csv / states.csv from the app (or a test fixture).

    Returns (districts, states) as ordered lists of dicts. District order is
    the canonical row order of every wide CSV — identical to the app.
    """
    dpath = registry_path(cfg)
    with open(dpath, newline="", encoding="utf-8") as fh:
        districts = [r for r in csv.DictReader(fh) if r.get("district_id")]
    spath = os.path.join(os.path.dirname(dpath), "states.csv")
    states = []
    if os.path.exists(spath):
        with open(spath, newline="", encoding="utf-8") as fh:
            states = [r for r in csv.DictReader(fh) if r.get("state_id")]
    for d in districts:
        d["area_km2"] = float(d["area_km2"])
        d["centroid_lon"] = float(d["centroid_lon"])
        d["centroid_lat"] = float(d["centroid_lat"])
    return districts, states


def classify(value: float, classes: list[dict]) -> dict | None:
    """Port of the app's data-loader classification (same boundary rules)."""
    if not np.isfinite(value):
        return None
    for c in classes:
        lo = -np.inf if c.get("min") is None else c["min"]
        hi = np.inf if c.get("max") is None else c["max"]
        lo_ok = value > lo or (c.get("minClosed") is True and value == lo)
        hi_ok = value < hi or (c.get("maxClosed") is True and value == hi)
        if lo_ok and hi_ok:
            return c
    return None


def write_wide_csv(path: str, districts: list[dict], date_cols: list[str],
                   mat: np.ndarray, decimals: int) -> None:
    """Write one indicator matrix in the app's wide-CSV contract.

    district_id,district_name,state_name,<YYYY-MM>... ; empty cell = missing.
    Names are CSV-quoted when they contain commas/quotes so that PapaParse
    on the app side reads the same number of columns the writer emits.
    """
    n, t = mat.shape
    if (n, t) != (len(districts), len(date_cols)):
        raise ValueError(f"matrix {mat.shape} does not match registry/dates "
                         f"({len(districts)} x {len(date_cols)})")

    def _field(s: str) -> str:
        s = str(s)
        return f'"{s.replace(chr(34), chr(34) * 2)}"' if ("," in s or '"' in s) else s

    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write("district_id,district_name,state_name," + ",".join(date_cols) + "\n")
        for i, d in enumerate(districts):
            vals = []
            for j in range(t):
                v = mat[i, j]
                vals.append("" if not np.isfinite(v) else f"{v:.{decimals}f}")
            fh.write(f"{_field(d['district_id'])},{_field(d['district_name'])},"
                     f"{_field(d['state_name'])}," + ",".join(vals) + "\n")


def read_wide_csv(path: str) -> tuple[list[str], list[str], np.ndarray]:
    """Read an app wide-CSV back into (district_ids, date_cols, matrix)."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    date_cols = [c for c in header[3:]]
    ids = [r[0] for r in rows[1:] if r]
    mat = np.full((len(ids), len(date_cols)), np.nan)
    for i, r in enumerate(rows[1:]):
        if not r:
            continue
        for j in range(len(date_cols)):
            raw = r[3 + j].strip() if 3 + j < len(r) else ""
            if raw != "":
                try:
                    mat[i, j] = float(raw)
                except ValueError:
                    pass
    return ids, date_cols, mat


# ---------------------------------------------------------------------------#
# Default indicator definitions (used when building metadata from scratch,
# e.g. in the offline self-test; identical to the shipped metadata).
# ---------------------------------------------------------------------------#

SPI_CLASSES = [
    {"key": "extreme_drought",  "label": "Extreme drought",  "color": "#8F252F", "min": None,  "max": -2.0, "minClosed": False, "maxClosed": True},
    {"key": "severe_drought",   "label": "Severe drought",   "color": "#B94747", "min": -2.0,  "max": -1.5, "minClosed": False, "maxClosed": True},
    {"key": "moderate_drought", "label": "Moderate drought", "color": "#D97745", "min": -1.5,  "max": -1.0, "minClosed": False, "maxClosed": True},
    {"key": "mild_drought",     "label": "Mild drought",     "color": "#E9BE54", "min": -1.0,  "max": -0.5, "minClosed": False, "maxClosed": True},
    {"key": "near_normal",      "label": "Near normal",      "color": "#72A982", "min": -0.5,  "max": 0.5,  "minClosed": False, "maxClosed": False},
    {"key": "mildly_wet",       "label": "Mildly wet",       "color": "#A3C1CC", "min": 0.5,   "max": 1.0,  "minClosed": True,  "maxClosed": False},
    {"key": "moderately_wet",   "label": "Moderately wet",   "color": "#7BA7BE", "min": 1.0,   "max": 1.5,  "minClosed": True,  "maxClosed": False},
    {"key": "severely_wet",     "label": "Severely wet",     "color": "#4F91B8", "min": 1.5,   "max": 2.0,  "minClosed": True,  "maxClosed": False},
    {"key": "extremely_wet",    "label": "Extremely wet",    "color": "#2A5F85", "min": 2.0,   "max": None, "minClosed": True,  "maxClosed": False},
]
SMA_CLASSES = [
    {"key": "extreme_drought",  "label": "Extreme anomaly",  "color": "#8F252F", "min": None,  "max": -50.0, "minClosed": False, "maxClosed": True},
    {"key": "severe_drought",   "label": "Severe anomaly",   "color": "#B94747", "min": -50.0, "max": -30.0, "minClosed": False, "maxClosed": True},
    {"key": "moderate_drought", "label": "Moderate anomaly", "color": "#D97745", "min": -30.0, "max": -15.0, "minClosed": False, "maxClosed": True},
    {"key": "mild_drought",     "label": "Mild anomaly",     "color": "#E9BE54", "min": -15.0, "max": -5.0,  "minClosed": False, "maxClosed": True},
    {"key": "near_normal",      "label": "Near normal",      "color": "#72A982", "min": -5.0,  "max": 5.0,   "minClosed": False, "maxClosed": False},
    {"key": "wet",              "label": "Wet anomaly",      "color": "#4F91B8", "min": 5.0,   "max": None,  "minClosed": True,  "maxClosed": False},
]
VCI_CLASSES = [
    {"key": "extreme_drought",  "label": "Extreme vegetation stress",  "color": "#8F252F", "min": 0.0,  "max": 10.0, "minClosed": True,  "maxClosed": True},
    {"key": "severe_drought",   "label": "Severe vegetation stress",   "color": "#B94747", "min": 10.0, "max": 20.0, "minClosed": False, "maxClosed": True},
    {"key": "moderate_drought", "label": "Moderate vegetation stress", "color": "#D97745", "min": 20.0, "max": 30.0, "minClosed": False, "maxClosed": True},
    {"key": "mild_drought",     "label": "Mild vegetation stress",     "color": "#E9BE54", "min": 30.0, "max": 40.0, "minClosed": False, "maxClosed": True},
    {"key": "near_normal",      "label": "Normal vegetation condition","color": "#72A982", "min": 40.0, "max": 60.0, "minClosed": False, "maxClosed": False},
    {"key": "wet",              "label": "Favourable conditions",      "color": "#4F91B8", "min": 60.0, "max": 100.0, "minClosed": True, "maxClosed": True},
]

DEFAULT_INDICATORS = [
    ("spi_1",   "SPI-1",   "spi",  "Standardized Precipitation Index, 1-month", 1),
    ("spi_3",   "SPI-3",   "spi",  "Standardized Precipitation Index, 3-month", 3),
    ("spi_6",   "SPI-6",   "spi",  "Standardized Precipitation Index, 6-month", 6),
    ("spi_12",  "SPI-12",  "spi",  "Standardized Precipitation Index, 12-month", 12),
    ("spei_1",  "SPEI-1",  "spei", "Standardized Precipitation Evapotranspiration Index, 1-month", 1),
    ("spei_3",  "SPEI-3",  "spei", "Standardized Precipitation Evapotranspiration Index, 3-month", 3),
    ("spei_6",  "SPEI-6",  "spei", "Standardized Precipitation Evapotranspiration Index, 6-month", 6),
    ("spei_12", "SPEI-12", "spei", "Standardized Precipitation Evapotranspiration Index, 12-month", 12),
    ("sma",     "Soil Moisture Anomaly", "land", "Soil Moisture Anomaly (SMA)", 3),
    ("vci",     "Vegetation Condition Index", "land", "Vegetation Condition Index (VCI)", 1),
]


def default_indicator_specs() -> list[dict]:
    """Indicator specs identical in shape to metadata.json entries."""
    out = []
    for iid, label, family, name, accum in DEFAULT_INDICATORS:
        classes = SPI_CLASSES if family in Z_FAMILIES else (SMA_CLASSES if iid == "sma" else VCI_CLASSES)
        out.append({
            "id": iid, "label": label, "family": family, "name": name,
            "units": "z-score" if family in Z_FAMILIES else "%",
            "accumulation_months": accum,
            "file": f"data/drought/{INDICATOR_FILES[iid]}",
            "classes": classes,
            "scale": [-3, 3] if family in Z_FAMILIES else ([-80, 80] if iid == "sma" else [0, 100]),
        })
    return out


def load_app_metadata(cfg: dict) -> dict | None:
    p = os.path.join(app_data_dir(cfg), "metadata.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------#
# Console helpers
# ---------------------------------------------------------------------------#

def banner(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def hr() -> None:
    print("-" * 74)


def die(msg: str, code: int = 1) -> None:
    print(f"\n[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)
