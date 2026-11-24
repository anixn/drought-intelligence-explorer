#!/usr/bin/env python3
"""Build final-size Scientific Data figures for the DIE v2.0.0 descriptor.

All figures are designed at 7.2 inches width with Roboto text no smaller than
10 pt. Each figure is written as vector PDF and 300-dpi PNG. No scientific
processing is performed: the script reads released metadata, validation
products, cross-validation Parquet and boundary GeoJSON.

Run:
    python publication-scientific-data/make_figures.py
    python publication-scientific-data/make_figures.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.colors import Normalize
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, PathPatch, Rectangle
from matplotlib.path import Path as MplPath
from matplotlib.text import Text
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pyproj import Transformer
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "figures"
GENERATED = "2026-11-24T00:00:00Z"
SEED = 20261103
WIDTH = 7.2

ERA_A = "#6B7D3A"
ERA_B = "#22756B"
ERA_C = "#A6452F"
INK = "#211C15"
MUTED = "#5E5548"
GRID = "#D8D0C2"
PAPER = "#F6F1E6"
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
VERMILLION = "#D55E00"
PURPLE = "#CC79A7"
SKY = "#56B4E9"
GOLD = "#B8892D"

IND_ORDER = ["spi_01", "spi_03", "spi_06", "spi_12", "spei_01", "spei_03", "spei_06", "spei_12", "sma", "vci"]
IND_LABEL = {"spi_01": "SPI-1", "spi_03": "SPI-3", "spi_06": "SPI-6", "spi_12": "SPI-12",
             "spei_01": "SPEI-1", "spei_03": "SPEI-3", "spei_06": "SPEI-6", "spei_12": "SPEI-12",
             "sma": "SMA", "vci": "VCI"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(rel: str) -> Any:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def source_record(rel: str) -> dict[str, Any]:
    p = ROOT / rel
    return {"path": rel, "sha256": sha256(p), "bytes": p.stat().st_size}


def year_fraction(ym: str) -> float:
    y, m = (int(v) for v in ym.split("-"))
    return y + (m - 1) / 12.0


def register_fonts() -> None:
    regular = HERE / "fonts" / "Roboto-Regular.ttf"
    bold = HERE / "fonts" / "Roboto-Bold.ttf"
    if not regular.exists() or not bold.exists():
        raise FileNotFoundError("Roboto static fonts are required in publication-scientific-data/fonts/")
    font_manager.fontManager.addfont(str(regular))
    font_manager.fontManager.addfont(str(bold))


def style() -> None:
    register_fonts()
    plt.rcParams.update({
        "font.family": "Roboto", "font.size": 10,
        "axes.titlesize": 11, "axes.titleweight": "bold",
        "axes.labelsize": 11, "axes.labelweight": "bold",
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "axes.linewidth": 0.6,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelsize": 10, "ytick.labelsize": 10,
        "xtick.major.width": 0.45, "ytick.major.width": 0.45,
        "xtick.major.size": 3.0, "ytick.major.size": 3.0,
        "text.color": INK, "legend.fontsize": 10, "legend.frameon": False,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "pdf.fonttype": 42, "ps.fonttype": 42, "axes.grid": False,
    })


def panel_label(ax: Any, label: str) -> None:
    ax.text(-0.10, 1.05, label, transform=ax.transAxes, fontsize=11, fontweight="bold",
            va="bottom", ha="left", color=INK)


def clean_axes(ax: Any, grid_axis: str | None = None) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.45)
    ax.set_axisbelow(True)


def save_figure(fig: Any, stem: str) -> dict[str, Any]:
    for artist in fig.findobj(match=Text):
        size = artist.get_fontsize()
        if size < 9.99:
            raise ValueError(f"{stem}: text below 10 pt: {artist.get_text()!r} at {size}")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob(f"{stem}.*"):
        old.unlink()
    pdf = OUT / f"{stem}.pdf"
    png = OUT / f"{stem}.png"
    metadata = {"Title": stem, "Author": "Ankit Deshmukh",
                "Subject": "Drought Intelligence Explorer v2.0.0 Scientific Data manuscript",
                "CreationDate": datetime(2026, 11, 24), "ModDate": datetime(2026, 11, 24)}
    fig.savefig(pdf, bbox_inches="tight", pad_inches=0.06, metadata=metadata)
    fig.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.06,
                metadata={"Software": "DIE publication figure builder", "Creation Time": GENERATED})
    plt.close(fig)
    return {"pdf": {"path": f"figures/{stem}.pdf", "sha256": sha256(pdf), "bytes": pdf.stat().st_size},
            "png": {"path": f"figures/{stem}.png", "sha256": sha256(png), "bytes": png.stat().st_size}}


def box(ax: Any, x: float, y: float, w: float, h: float, title: str, body: str,
        color: str, title_size: float = 11, body_size: float = 10) -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.010",
                                linewidth=0.9, edgecolor=color, facecolor="white", zorder=2))
    ax.add_patch(Rectangle((x, y + h - 0.014), w, 0.014, facecolor=color, edgecolor="none", zorder=3))
    ax.text(x + w / 2, y + h - 0.040, title, ha="center", va="top", fontsize=title_size,
            fontweight="bold", color=color, zorder=4)
    ax.text(x + w / 2, y + h - 0.092, body, ha="center", va="top", fontsize=body_size,
            color=INK, linespacing=1.25, zorder=4)


def arrow(ax: Any, x1: float, y1: float, x2: float, y2: float, color: str = MUTED) -> None:
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=10,
                                 linewidth=0.9, color=color, shrinkA=1, shrinkB=1, zorder=1))


class Geometry:
    def __init__(self, district_path: Path, state_path: Path):
        self.transformer = Transformer.from_crs("EPSG:4326", "+proj=laea +lat_0=22.5 +lon_0=79.5 +datum=WGS84 +units=m +no_defs", always_xy=True)
        self.districts = self._features(district_path)
        self.states = self._features(state_path)
        all_xy = np.vstack([p.vertices for p in self.districts.values()])
        self.xmin, self.ymin = all_xy.min(axis=0)
        self.xmax, self.ymax = all_xy.max(axis=0)

    def _ring_path(self, rings: list[list[list[float]]]) -> MplPath:
        verts: list[tuple[float, float]] = []
        codes: list[int] = []
        for ring in rings:
            arr = np.asarray(ring, dtype=float)
            x, y = self.transformer.transform(arr[:, 0], arr[:, 1])
            xy = np.column_stack([x / 1000.0, y / 1000.0])
            if len(xy) < 3:
                continue
            verts.extend(map(tuple, xy))
            codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(xy) - 2) + [MplPath.CLOSEPOLY])
        return MplPath(verts, codes)

    def _features(self, path: Path) -> dict[str, MplPath]:
        gj = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, MplPath] = {}
        for feat in gj["features"]:
            fid = feat.get("id") or feat["properties"].get("id") or feat["properties"].get("sid")
            geom = feat["geometry"]
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            rings: list[list[list[float]]] = []
            for poly in polys:
                rings.extend(poly)
            out[fid] = self._ring_path(rings)
        return out

    @staticmethod
    def _segments(paths: Iterable[MplPath]) -> list[np.ndarray]:
        lines = []
        for p in paths:
            idx = np.flatnonzero(p.codes == MplPath.MOVETO)
            for a, b in zip(idx[:-1], idx[1:]):
                lines.append(p.vertices[a:b])
        return lines

    def draw_base(self, ax: Any, values: dict[str, float] | None = None,
                  norm: Normalize | None = None, district_edges: bool = True) -> Any:
        patches = [PathPatch(p, facecolor="none", edgecolor="none") for p in self.districts.values()]
        pc = PatchCollection(patches, match_original=False, edgecolor="none", linewidth=0)
        if values is None:
            pc.set_facecolor("#ECE7DC")
        else:
            ids = list(self.districts)
            arr = np.asarray([values.get(i, np.nan) for i in ids], dtype=float)
            pc.set_array(arr); pc.set_cmap("viridis"); pc.set_norm(norm or Normalize(0, 1))
            rgba = pc.get_cmap()(pc.norm(arr)); rgba[~np.isfinite(arr)] = (0.82, 0.81, 0.78, 1)
            pc.set_facecolor(rgba)
        ax.add_collection(pc)
        if district_edges:
            ax.add_collection(LineCollection(self._segments(self.districts.values()), colors="#B8B0A2",
                                             linewidths=0.10, alpha=0.60))
        ax.add_collection(LineCollection(self._segments(self.states.values()), colors="#554D42",
                                         linewidths=0.35, alpha=0.90))
        ax.set_xlim(self.xmin - 40, self.xmax + 40); ax.set_ylim(self.ymin - 40, self.ymax + 40)
        ax.set_aspect("equal"); ax.axis("off")
        x, y = self.xmin + 120, self.ymin + 100
        ax.plot([x, x + 500], [y, y], color=INK, lw=1.5)
        ax.plot([x, x], [y - 20, y + 20], color=INK, lw=0.8)
        ax.plot([x + 500, x + 500], [y - 20, y + 20], color=INK, lw=0.8)
        ax.text(x + 250, y + 30, "500 km", ha="center", va="bottom", fontsize=10, color=INK)
        return pc


def fig01_architecture(meta: dict[str, Any], catalog: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.9))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.text(0.02, 0.97, "Three labelled eras, one district-month contract", fontsize=13, fontweight="bold", va="top")
    ax.text(0.02, 0.915, "Record windows are facts; reference and comparison windows remain explicit.",
            fontsize=10, color=MUTED, va="top")
    box(ax, 0.02, 0.56, 0.30, 0.25, "Era A · Atlas",
        "Atlas v2 · 0.05°\nSPEI-1/4/12 · 1901–2025\n724-district reconstruction", ERA_A)
    box(ax, 0.35, 0.56, 0.30, 0.25, "Era B · Gridded product",
        "CHIRPS · ERA5-Land · MODIS\n10 indices · 1981–2026\nSources kept separate", ERA_B)
    box(ax, 0.68, 0.56, 0.30, 0.25, "Era C · Projections",
        "CMIP6 · QDM · Hargreaves\n8 indices · 2 SSPs\n2015–2100 · 8 models", ERA_C)
    for x in (0.17, 0.50, 0.83):
        arrow(ax, x, 0.55, x, 0.45)
    box(ax, 0.16, 0.27, 0.68, 0.17, "Common published schema",
        "Core: district_id · year · month · value\nEra/scenario/statistic = partition keys + metadata\nMissing rows absent · sample size retained", INK)
    arrow(ax, 0.36, 0.26, 0.27, 0.18); arrow(ax, 0.64, 0.26, 0.73, 0.18)
    box(ax, 0.05, 0.035, 0.42, 0.14, "Versioned Parquet + catalog",
        "Zenodo · HTTP Range\nExact paths · SHA-256", BLUE)
    box(ax, 0.53, 0.035, 0.42, 0.14, "Browser analytical engine",
        "DuckDB-WASM · SQL\nMaps · exports · no backend", PURPLE)
    a_start, a_end = meta["era_a"]["window"]
    c_years = catalog["eras"]["projections"]["years"]
    return fig, {"A": [a_start, a_end], "B": [meta["period"]["start"], meta["period"]["end"]],
                 "C": [min(c_years), max(c_years)], "districts": 724}


def count_catalog_paths(node: Any, prefix: str) -> int:
    if isinstance(node, str):
        return int(node.startswith(prefix))
    if isinstance(node, dict):
        return sum(count_catalog_paths(v, prefix) for v in node.values())
    if isinstance(node, list):
        return sum(count_catalog_paths(v, prefix) for v in node)
    return 0


def fig02_projection(models: dict[str, Any], subset: dict[str, Any], catalog: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    fig, ax = plt.subplots(figsize=(WIDTH, 5.6))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.text(0.02, 0.97, "Era-C processing, validation and ensemble construction", fontsize=13, fontweight="bold", va="top")
    ax.text(0.02, 0.915, "One coherent recompute over the full projection record; no partial-record concatenation.",
            fontsize=10, color=MUTED, va="top")
    listed = len(models["models"]); processed = sum(1 for m in models["models"] if m.get("era_c_ensemble", True))
    n_subset = len(subset["subset"]); n_parts = count_catalog_paths(catalog["variables"], "data/parquet/projections/")
    n_ind = sum(1 for v in catalog["variables"] if "projections" in v.get("eras", []))
    xs = (0.03, 0.35, 0.67)
    box(ax, xs[0], 0.66, 0.30, 0.17, "1 · Inventory",
        f"{listed} listed · {processed} processed\nDaily pr/tasmax/tasmin", BLUE)
    box(ax, xs[1], 0.66, 0.30, 0.17, "2 · Regrid",
        "Conservative precipitation\nBilinear temperature · 0.25°", BLUE)
    box(ax, xs[2], 0.66, 0.30, 0.17, "3 · QDM",
        "Cell × calendar month\nIMD 1981–2020\nFull SSP fit", ERA_C)
    arrow(ax, 0.335, 0.745, 0.345, 0.745); arrow(ax, 0.655, 0.745, 0.665, 0.745)
    arrow(ax, 0.82, 0.65, 0.82, 0.56)
    box(ax, xs[2], 0.39, 0.30, 0.17, "4 · Indices",
        "Hargreaves PET\nSPI/SPEI 1/3/6/12", ERA_C)
    box(ax, xs[1], 0.39, 0.30, 0.17, "5 · Districts",
        "LAEA overlap weights\n724-district fabric", ERA_C)
    box(ax, xs[0], 0.39, 0.30, 0.17, "6 · Validation + subset",
        f"1981–2014 gate\n8-metric rank to {n_subset} models", INK)
    arrow(ax, 0.665, 0.475, 0.655, 0.475); arrow(ax, 0.345, 0.475, 0.335, 0.475)
    arrow(ax, 0.18, 0.38, 0.18, 0.29)
    box(ax, 0.03, 0.08, 0.44, 0.22, "7 · Ensemble products",
        "Median · p25 · p75 · agreement\nDirection + exact denominator", PURPLE)
    box(ax, 0.53, 0.08, 0.44, 0.22, "8 · Published partitions",
        f"2 SSPs × {n_ind} indicators\n{n_parts:,} files\nCatalog + archive checksums", GREEN)
    arrow(ax, 0.47, 0.19, 0.525, 0.19)
    return fig, {"listed": listed, "processed": processed, "subset": n_subset, "partitions": n_parts,
                 "indicators": n_ind, "reference": [1981, 2020], "comparison": [1981, 2014]}


def fig03_coverage(meta: dict[str, Any], catalog: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    fig = plt.figure(figsize=(WIDTH, 5.4), constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 2.2])
    ax1 = fig.add_subplot(gs[0]); ax2 = fig.add_subplot(gs[1])
    a0, a1 = meta["era_a"]["window"]; cy = catalog["eras"]["projections"]["years"]
    eras = [("A · Atlas", a0, a1 + 0.99, ERA_A),
            ("B · 10", year_fraction(meta["period"]["start"]), year_fraction(meta["period"]["end"]) + 1/12, ERA_B),
            ("C · 8 indicators × 2 SSPs", min(cy), max(cy), ERA_C)]
    for i, (label, start, end, color) in enumerate(eras):
        y = 2 - i; ax1.barh(y, end-start, left=start, height=0.48, color=color)
        ax1.text(start+3, y, label, va="center", ha="left", color="white", fontsize=10, fontweight="bold")
    ax1.axvspan(1981, 2020.99, color=MUTED, alpha=0.08)
    ax1.set_xlim(1895, 2105); ax1.set_ylim(-0.6, 2.6); ax1.set_yticks([])
    ax1.set_xticks([1901, 1950, 1981, 2000, 2026, 2050, 2100]); ax1.set_xlabel("Year")
    ax1.set_title("Era coverage", loc="left"); clean_axes(ax1, "x"); panel_label(ax1, "a")
    inds = {i["id"]: i for i in meta["indicators"]}
    for pos, iid in enumerate(IND_ORDER):
        rec = inds[iid.replace("_0", "_")]; y = 9-pos
        start = year_fraction(rec["available_from"]); end = year_fraction(rec["available_to"]) + 1/12
        family = rec["family"]
        color = BLUE if family == "spi" else ERA_B if family == "spei" else GOLD if iid == "sma" else GREEN
        ax2.barh(y, end-start, left=start, height=0.62, color=color)
        ax2.text(start+0.12, y, IND_LABEL[iid], va="center", ha="left", color="white", fontsize=10, fontweight="bold")
    ax2.axvspan(1981, 2020.99, color=MUTED, alpha=0.08)
    ax2.set_xlim(1980.5, 2027.2); ax2.set_ylim(-0.7, 9.7); ax2.set_yticks([])
    ax2.set_xticks([1981, 1990, 2000, 2010, 2020, 2026]); ax2.set_xlabel("Year")
    ax2.set_title("Era-B availability by indicator", loc="left"); clean_axes(ax2, "x"); panel_label(ax2, "b")
    fig.suptitle("Record windows and indicator availability", fontsize=13, fontweight="bold")
    return fig, {"eras": eras, "indicators": [{"id": i, "label": IND_LABEL[i],
                    "from": inds[i.replace("_0", "_")]["available_from"],
                    "to": inds[i.replace("_0", "_")]["available_to"]} for i in IND_ORDER]}


def screenshot_figure(stem: str, title: str, panels: list[tuple[str, str, str, str]],
                      footer: str = "https://drought.ankitdeshmukh.com/") -> tuple[Any, dict[str, Any]]:
    """Compose four live-dashboard captures with readable 10 pt annotations."""
    fig, axs = plt.subplots(2, 2, figsize=(WIDTH, 7.4))
    fig.subplots_adjust(left=0.04, right=0.96, top=0.86, bottom=0.07, hspace=0.78, wspace=0.12)
    records = []
    for ax, (filename, label, heading, analysis) in zip(axs.flat, panels):
        path = HERE / "screenshots" / filename
        if not path.exists():
            raise FileNotFoundError(path)
        img = plt.imread(path)
        ax.imshow(img, interpolation="lanczos", aspect="auto")
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.add_patch(Rectangle((0, 0), 1, 1, fill=False, edgecolor=GRID, linewidth=0.7, transform=ax.transAxes))
        panel_label(ax, label)
        ax.set_title(heading, loc="left", pad=7)
        ax.text(0.0, -0.03, textwrap.fill(analysis, width=52, break_long_words=False),
                transform=ax.transAxes, ha="left", va="top", fontsize=10, color=INK, linespacing=1.25)
        records.append({"panel": label, "window": heading, "analysis": analysis,
                        "screenshot": f"screenshots/{filename}", "sha256": sha256(path)})
    fig.suptitle(title, fontsize=13, fontweight="bold", x=0.04, ha="left", y=0.985)
    fig.text(0.04, 0.945, footer, fontsize=10, color=MUTED, ha="left")
    return fig, {"panels": records, "site": footer}


def fig07_record_windows() -> tuple[Any, dict[str, Any]]:
    return screenshot_figure("fig07_record_windows", "Record workspace and analytical lenses", [
        ("overview.png", "a", "Overview", "Current-month choropleth, affected area, severity, district counts and animated evolution."),
        ("historical.png", "b", "Historical Analysis", "Frequency, duration, severity, recurrence, annual trends and FDR-corrected district significance."),
        ("events.png", "c", "Drought Events", "Runs-analysis catalogue: onset, end, duration, peak, severity, recovery and censoring."),
        ("propagation.png", "d", "Propagation & Relationships", "Pairwise lag correlation from −12 to +12 months, bootstrap intervals and optimal-lag maps."),
    ])


def fig08_v2_products() -> tuple[Any, dict[str, Any]]:
    return screenshot_figure("fig08_v2_products", "Reconstruction, cross-validation and projection products", [
        ("atlas.png", "a", "Atlas", "1901–2025 SPEI-1/4/12 scrubber, drought-class shares and historical drought anchors."),
        ("crossval.png", "b", "Cross-validation", "Era A–B agreement, bias/RMSD maps, monthly agreement and seam uncertainty."),
        ("projections.png", "c", "Future Projections", "Scenario and time-window controls, ensemble median/spread, agreement maps and model context."),
        ("summary.png", "d", "Drought to 2100", "Direction-of-change agreement, drought-share/duration/severity deltas and per-state summaries."),
    ])


def fig09_access_documentation() -> tuple[Any, dict[str, Any]]:
    return screenshot_figure("fig09_access_documentation", "Query, documentation and district-level access", [
        ("engine.png", "a", "Engine Lab", "Read-only Parquet SQL, catalogue inspection, query timing, bytes read and CSV export."),
        ("documentation.png", "b", "Documentation", "Methods, governance, licences, reality checks, status, downloads and the SQL field guide."),
        ("district-profile.png", "c", "District profile", "One-district headline, ten-indicator strip, long-term trend, event catalogue and labelled era context."),
        ("tour.png", "d", "Guided tour", "Standalone onboarding: era primer, product map, navigation and interpretation guardrails."),
    ])


def fig04_study_area(geom: Geometry) -> tuple[Any, dict[str, Any]]:
    fig = plt.figure(figsize=(WIDTH, 5.6), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[4.6, 2.1])
    ax = fig.add_subplot(gs[0]); info = fig.add_subplot(gs[1])
    geom.draw_base(ax)
    ax.set_title("District reporting fabric", loc="left")
    info.axis("off")
    info.text(0.0, 1.0, "Native source grids", fontsize=11, fontweight="bold", va="top")
    info.text(0.0, 0.86, "CHIRPS  0.05°\nAtlas  0.05°\nERA5-Land  0.1°\nMODIS  1 km\nCMIP6 to 0.25°",
              fontsize=10, va="top", linespacing=1.45)
    info.text(0.0, 0.48, "Reporting unit", fontsize=11, fontweight="bold", va="top")
    info.text(0.0, 0.36, "724 districts\n36 States/UTs\n2011-era lineage\nLAEA area weights",
              fontsize=10, va="top", linespacing=1.45)
    fig.suptitle("Study area and spatial support", fontsize=13, fontweight="bold")
    return fig, {"districts": len(geom.districts), "states": len(geom.states),
                 "native_grids": {"CHIRPS": "0.05°", "Atlas": "0.05°", "ERA5-Land": "0.1°", "MODIS": "1 km", "CMIP6": "0.25°"}}


def fig05_imd(imd: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    rows = imd["indicators"]; labels = [r["label"] for r in rows]; y = np.arange(len(rows))
    fig, axs = plt.subplots(2, 2, figsize=(WIDTH, 6.2), constrained_layout=True)
    ax = axs[0, 0]; vals = [r["r_median"] for r in rows]
    ax.barh(y, vals, color=[BLUE if l.startswith("SPI") else ERA_B for l in labels], height=0.62)
    ax.set_yticks(y, labels); ax.invert_yaxis(); ax.set_xlim(0, 1); ax.set_xlabel("Median district Pearson r")
    ax.set_title("Correlation", loc="left")
    for yy, v in zip(y, vals): ax.text(v+0.015, yy, f"{v:.3f}", va="center", fontsize=10)
    clean_axes(ax, "x"); panel_label(ax, "a")
    ax = axs[0, 1]; vals = [r["bias"] for r in rows]
    ax.barh(y, vals, color=[BLUE if l.startswith("SPI") else ERA_B for l in labels], height=0.62)
    ax.axvline(0, color=INK, lw=0.8); ax.set_yticks(y, labels); ax.invert_yaxis(); ax.set_xlim(-0.05, 0.025)
    ax.set_xlabel("Area-weighted bias, IMD − era B (z)"); ax.set_title("Systematic offset", loc="left")
    for yy, v in zip(y, vals): ax.text(v+(0.001 if v >= 0 else -0.001), yy, f"{v:+.3f}", va="center",
                                       ha="left" if v >= 0 else "right", fontsize=10)
    clean_axes(ax, "x"); panel_label(ax, "b")
    ax = axs[1, 0]; x = np.arange(len(rows)); w = 0.36
    state = [100*r["state"] for r in rows]; exact = [100*r["class_exact"] for r in rows]
    ax.bar(x-w/2, state, w, label="Drought state", color=GREEN); ax.bar(x+w/2, exact, w, label="Exact class", color=GOLD)
    ax.set_xticks(x, labels, rotation=30, ha="right"); ax.set_ylim(0, 100); ax.set_ylabel("Agreement (%)")
    ax.set_title("Categorical agreement", loc="left"); ax.legend(loc="upper right")
    clean_axes(ax, "y"); panel_label(ax, "c")
    ax = axs[1, 1]; tr = imd["trends"]; x = np.arange(len(tr)); w = 0.36
    imd_n = [r["imd_fdr"] for r in tr]; era_n = [r["era_b_fdr"] for r in tr]
    ax.bar(x-w/2, imd_n, w, label="IMD", color=MUTED); ax.bar(x+w/2, era_n, w, label="Era B", color=ERA_B)
    ax.set_xticks(x, [r["label"] for r in tr]); ax.set_ylabel("Significant districts")
    ax.set_title("Annual trends after BH-FDR", loc="left")
    for i, r in enumerate(tr): ax.text(i, max(imd_n[i], era_n[i])+14, f"{r['sign_agree']*100:.1f}% sign\nagreement",
                                       ha="center", fontsize=10, color=MUTED)
    ax.set_ylim(0, max(era_n+imd_n)*1.30); ax.legend(loc="upper left"); clean_axes(ax, "y"); panel_label(ax, "d")
    fig.suptitle("Independent IMD benchmark, 1981–2025", fontsize=13, fontweight="bold")
    return fig, {"period": imd["period"], "base": imd["base"], "indicators": rows, "trends": tr}


def fig06_crossval(cv: pd.DataFrame, geom: Geometry) -> tuple[Any, dict[str, Any]]:
    variables = ["spei_01", "spei_12"]
    fig, axs = plt.subplots(2, 2, figsize=(WIDTH, 5.8), constrained_layout=True)
    norm = Normalize(0, 1); summary = {}
    for ax, var, label in zip(axs[0], variables, ["a", "b"]):
        sub = cv[cv["variable"] == var].copy(); vals = dict(zip(sub["district_id"].astype(str), sub["r"].astype(float)))
        geom.draw_base(ax, values=vals, norm=norm)
        ax.set_title(f"{IND_LABEL[var]} · district correlation", loc="left"); panel_label(ax, label)
        sm = plt.cm.ScalarMappable(norm=norm, cmap="viridis"); cb = fig.colorbar(sm, ax=ax, fraction=0.05, pad=0.02)
        cb.set_label("Pearson r", fontsize=10); cb.ax.tick_params(labelsize=10)
        finite = sub["r"].replace([np.inf, -np.inf], np.nan).dropna()
        summary[var] = {"districts": int(len(sub)), "median_r": float(finite.median()),
                        "p10_r": float(finite.quantile(.1)), "p90_r": float(finite.quantile(.9)),
                        "mean_bias": float(sub["bias"].mean())}
    ax = axs[1, 0]; arrays = [cv.loc[cv["variable"] == v, "r"].dropna().to_numpy() for v in variables]
    bp = ax.boxplot(arrays, tick_labels=["SPEI-1", "SPEI-12"], patch_artist=True, widths=.5,
                    medianprops={"color": INK, "linewidth": 1.2}, whiskerprops={"color": MUTED}, capprops={"color": MUTED})
    for patch, color in zip(bp["boxes"], [ERA_A, ERA_B]): patch.set_facecolor(color); patch.set_alpha(.45)
    ax.set_ylabel("District Pearson r"); ax.set_ylim(0, 1.02); ax.set_title("Correlation distribution", loc="left")
    clean_axes(ax, "y"); panel_label(ax, "c")
    ax = axs[1, 1]; arrays = [cv.loc[cv["variable"] == v, "bias"].dropna().to_numpy() for v in variables]
    bp = ax.boxplot(arrays, tick_labels=["SPEI-1", "SPEI-12"], patch_artist=True, widths=.5,
                    medianprops={"color": INK, "linewidth": 1.2}, whiskerprops={"color": MUTED}, capprops={"color": MUTED})
    for patch, color in zip(bp["boxes"], [ERA_A, ERA_B]): patch.set_facecolor(color); patch.set_alpha(.45)
    ax.axhline(0, color=INK, lw=.8); ax.set_ylabel("District mean difference (z)")
    ax.set_title("Bias distribution, era B − era A", loc="left"); clean_axes(ax, "y"); panel_label(ax, "d")
    fig.suptitle("Era A–B overlap agreement, 1981–2014", fontsize=13, fontweight="bold")
    return fig, {"window": [1981, 2014], "variables": summary}


def gate_fraction(report: dict[str, Any], key: str) -> dict[str, Any]:
    g = report["gates"][key]
    return {"pass": bool(g["pass"]), "cells": int(g.get("region_cells", 0)),
            "breaches": int(g.get("region_breaches", 0)), "fraction": float(g.get("region_breach_frac", 0))}


def fig07_gcm(hist: dict[str, Any], ssp: dict[str, Any], subset: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    fig = plt.figure(figsize=(WIDTH, 5.8), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1.0])
    ax1 = fig.add_subplot(gs[0, 0]); ax2 = fig.add_subplot(gs[0, 1]); ax3 = fig.add_subplot(gs[1, :])
    cells = hist["gates"]["consistency"]["cells"]; national = []
    for key, val in cells.items():
        p = key.split("/")
        if len(p) == 3 and p[1] == "all" and p[2] == "national": national.append((p[0], float(val["sd_ratio"])))
    national.sort(key=lambda x: IND_ORDER.index(x[0]) if x[0] in IND_ORDER else 99)
    vals = [v for _, v in national]; y = np.arange(len(vals))
    ax1.axvspan(.7, 1.4, color=GREEN, alpha=.10); ax1.axvline(1, color=MUTED, lw=.8, ls="--")
    ax1.scatter(vals, y, s=32, color=ERA_C, zorder=3)
    for yy, v in zip(y, vals): ax1.text(v+.012, yy, f"{v:.3f}", va="center", fontsize=10)
    ax1.set_yticks(y, [IND_LABEL.get(k, k) for k, _ in national]); ax1.invert_yaxis(); ax1.set_xlim(.65, 1.46)
    ax1.set_xlabel("Ensemble/reference SD ratio"); ax1.set_title("Historical national shape", loc="left")
    clean_axes(ax1, "x"); panel_label(ax1, "a")
    hc = gate_fraction(hist, "consistency"); he = gate_fraction(hist, "drought_statistics"); ht = gate_fraction(hist, "tails")
    shape = ssp["gates"]["distribution_shape"]["scenarios"]; s245 = shape["ssp245"]; s585 = shape["ssp585"]
    rows = [("Consistency", hc, 20, BLUE), ("Events", he, 25, BLUE), ("Tails", ht, 25, BLUE),
            ("SSP245", {"cells": s245["region_cells"], "breaches": s245["region_breaches"], "fraction": s245["region_breach_frac"], "pass": s245["pass"]}, 20, ERA_C),
            ("SSP585", {"cells": s585["region_cells"], "breaches": s585["region_breaches"], "fraction": s585["region_breach_frac"], "pass": s585["pass"]}, 20, ERA_C)]
    x = np.arange(len(rows)); fracs = [100*r[1]["fraction"] for r in rows]
    ax2.bar(x, fracs, color=[r[3] for r in rows], width=.62)
    for i, r in enumerate(rows):
        g, tol = r[1], r[2]; ax2.hlines(tol, i-.35, i+.35, color=VERMILLION, lw=1, linestyle="--")
        ax2.text(i, fracs[i]+.8, f"{fracs[i]:.1f}%", ha="center", fontsize=10)
    tick_labels = [f"{r[0]}\n{r[1]['breaches']}/{r[1]['cells']}" for r in rows]
    ax2.set_xticks(x, tick_labels, rotation=25, ha="right"); ax2.set_ylim(0, 31); ax2.set_ylabel("Outside tolerance (%)")
    ax2.set_title("Gate outcomes", loc="left"); clean_axes(ax2, "y"); panel_label(ax2, "b")
    seam = ssp["gates"]["seam_continuity"]["scenarios"]
    ax3.axis("off"); ax3.set_title("Historical–scenario seam continuity", loc="left"); panel_label(ax3, "c")
    for i, (key, label) in enumerate((("ssp245", "SSP2-4.5"), ("ssp585", "SSP5-8.5"))):
        x0 = .27 + i*.46; s = seam[key]
        ax3.add_patch(FancyBboxPatch((x0-.09, .40), .18, .24, boxstyle="round,pad=.01,rounding_size=.03",
                                     facecolor=GREEN, edgecolor="none"))
        ax3.text(x0, .52, "PASS", ha="center", va="center", fontsize=11, color="white", fontweight="bold")
        ax3.text(x0, .20, f"{label}\n0/{s['cells']} breaches", ha="center", va="center", fontsize=11)
    fig.suptitle("CMIP6 correction-skill and release-gate evidence", fontsize=13, fontweight="bold")
    return fig, {"national_sd_ratios": [{"variable": k, "sd_ratio": v} for k, v in national],
                 "historical_gates": {"consistency": hc, "events": he, "tails": ht},
                 "ssp_shape": {"ssp245": {k: s245[k] for k in ("pass", "region_cells", "region_breaches", "region_breach_frac")},
                               "ssp585": {k: s585[k] for k in ("pass", "region_cells", "region_breaches", "region_breach_frac")}},
                 "seam": {k: {"pass": seam[k]["pass"], "cells": seam[k]["cells"], "breaches": seam[k]["breaches"]} for k in seam},
                 "subset": subset["subset"]}


def fig08_service(meta: dict[str, Any], pointer: dict[str, Any], status: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.9))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.text(.02, .97, "Versioned data service and reproducibility loop", fontsize=13, fontweight="bold", va="top")
    ax.text(.02, .915, "Archived files, exact paths, browser SQL and executable checks form one traceable chain.",
            fontsize=10, color=MUTED, va="top")
    stages = [("1 · Archive", "Zenodo DOI\nCC BY 4.0", GREEN),
              ("2 · Catalog", "Exact paths\nPartition keys", BLUE),
              ("3 · Static host", "Immutable data\nRange · CORS", BLUE),
              ("4 · Engine", "DuckDB-WASM\nWorker · SQL", PURPLE),
              ("5 · Reuse", "Maps · charts\nExports · links", ERA_B)]
    xs = [.01, .21, .41, .61, .81]
    for i, (title, body, color) in enumerate(stages):
        box(ax, xs[i], .64, .18, .18, title, body, color)
        if i < 4: arrow(ax, xs[i]+.185, .73, xs[i]+.205, .73)
    ax.text(.02, .55, "Executable verification gates", fontsize=11, fontweight="bold")
    selftest_n = int(status["verification"][0]["detail"].split()[0]); regression_n = int(status["verification"][1]["detail"].split()[0])
    checks = [("data-pipeline/selftest.py", f"{selftest_n} deterministic assertions"),
              ("scripts/regression_check.py", f"{regression_n} baseline values"),
              ("scripts/verify_reality_checks.py --check", "3 documented-event checks"),
              ("scripts/reproduce_figures.py --check", "published figure/table artifacts"),
              ("gcm-pipeline/selftest_gcm.py", "synthetic end-to-end world")]
    for i, (cmd, desc) in enumerate(checks):
        y = .46 - i*.075
        ax.add_patch(FancyBboxPatch((.02, y-.027), .96, .055, boxstyle="round,pad=.003,rounding_size=.006",
                                    facecolor=PAPER, edgecolor=GRID, linewidth=.6))
        ax.text(.035, y, cmd, ha="left", va="center", fontsize=10, color=INK)
        ax.text(.965, y, desc, ha="right", va="center", fontsize=10, color=MUTED)
    ax.text(.5, .035, f"Software {meta['doi']['v2_0_0']} · Dataset {meta['doi']['dataset_v2_0_0']} · {pointer['snapshot']}",
            ha="center", va="center", fontsize=10, color=MUTED)
    return fig, {"software_doi": meta["doi"]["v2_0_0"], "dataset_doi": meta["doi"]["dataset_v2_0_0"],
                 "snapshot": pointer["snapshot"], "checks": checks}


def build() -> dict[str, Any]:
    style()
    OUT.mkdir(parents=True, exist_ok=True)
    for pattern in ("fig*.pdf", "fig*.png"):
        for old in OUT.glob(pattern):
            old.unlink()
    meta = load_json("data/metadata.json"); catalog = load_json("data/parquet/catalog.json")
    pointer = load_json("data/data-source.json"); status = load_json("data/status.json")
    imd = load_json("data/imd_validation.json"); hist = load_json("gcm-pipeline/validation/validation_report.json")
    ssp = load_json("gcm-pipeline/validation/ssp/validation_report_ssp.json")
    subset = yaml.safe_load((ROOT / "gcm-pipeline/validation/best_subset.yaml").read_text(encoding="utf-8"))
    models = yaml.safe_load((ROOT / "gcm-pipeline/config/models.yaml").read_text(encoding="utf-8"))
    cv = pq.read_table(ROOT / "data/parquet/cross_validation/per_district_1981_2014.parquet").to_pandas()
    geom = Geometry(ROOT / "data/boundaries/india_districts.geojson", ROOT / "data/boundaries/india_states.geojson")
    assert len(geom.districts) == 724 and len(geom.states) == 36
    assert cv.groupby("variable").size().to_dict() == {"spei_01": 718, "spei_12": 718}
    figures = {}
    for stem, func, args in [
        ("fig01_architecture", fig01_architecture, (meta, catalog)),
        ("fig02_projection_pipeline", fig02_projection, (models, subset, catalog)),
        ("fig03_coverage", fig03_coverage, (meta, catalog)),
        ("fig04_imd_benchmark", fig05_imd, (imd,)),
        ("fig05_atlas_overlap", fig06_crossval, (cv, geom)),
        ("fig06_gcm_validation", fig07_gcm, (hist, ssp, subset)),
        ("fig07_record_windows", fig07_record_windows, ()),
        ("fig08_v2_products", fig08_v2_products, ()),
        ("fig09_access_documentation", fig09_access_documentation, ()),
    ]:
        fig, data = func(*args); figures[stem] = {"data": data, **save_figure(fig, stem)}; print("built", stem)
    inputs = ["data/metadata.json", "data/parquet/catalog.json", "data/data-source.json", "data/status.json",
              "data/imd_validation.json", "gcm-pipeline/config/models.yaml", "gcm-pipeline/validation/validation_report.json",
              "gcm-pipeline/validation/ssp/validation_report_ssp.json", "gcm-pipeline/validation/best_subset.yaml",
              "data/parquet/cross_validation/per_district_1981_2014.parquet", "data/boundaries/india_districts.geojson",
              "data/boundaries/india_states.geojson", "assets/js/ducklab.js",
              "publication-scientific-data/screenshots/overview.png",
              "publication-scientific-data/screenshots/historical.png",
              "publication-scientific-data/screenshots/events.png",
              "publication-scientific-data/screenshots/propagation.png",
              "publication-scientific-data/screenshots/atlas.png",
              "publication-scientific-data/screenshots/crossval.png",
              "publication-scientific-data/screenshots/projections.png",
              "publication-scientific-data/screenshots/summary.png",
              "publication-scientific-data/screenshots/engine.png",
              "publication-scientific-data/screenshots/documentation.png",
              "publication-scientific-data/screenshots/district-profile.png",
              "publication-scientific-data/screenshots/tour.png"]
    payload = {"schema": "die-publication-figures/2.0", "generated": GENERATED, "seed": SEED,
               "synthetic_data": False, "font": "Roboto", "minimum_font_pt": 10, "width_in": WIDTH,
               "figures": figures, "inputs": [source_record(rel) for rel in inputs]}
    (HERE / "figure_data.json").write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)+"\n", encoding="utf-8", newline="\n")
    sums = [f"{sha256(OUT/f'{stem}.{ext}')}  figures/{stem}.{ext}" for stem in figures for ext in ("pdf", "png")]
    (HERE / "FIGURE_SHA256SUMS.txt").write_text("\n".join(sums)+"\n", encoding="utf-8", newline="\n")
    print(f"PASS: {len(figures)} final-size Roboto figures, {len(figures)*2} files")
    return payload


def check() -> int:
    data = json.loads((HERE / "figure_data.json").read_text(encoding="utf-8")); problems = []
    for rec in data["inputs"]:
        p = ROOT / rec["path"]
        if not p.exists() or sha256(p) != rec["sha256"]: problems.append(f"input changed: {rec['path']}")
    for line in (HERE / "FIGURE_SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, rel = line.split("  ", 1); p = HERE / rel
        if not p.exists() or sha256(p) != expected: problems.append(f"output mismatch: {rel}")
    if problems:
        print("FAIL:\n"+"\n".join(problems)); return 1
    print(f"PASS: {len(data['inputs'])} inputs and {len(data['figures'])*2} figure files verified")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); args = ap.parse_args()
    raise SystemExit(check() if args.check else 0 if build() else 0)
