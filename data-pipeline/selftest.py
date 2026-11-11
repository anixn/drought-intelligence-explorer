#!/usr/bin/env python3
"""Offline end-to-end self-test of the data pipeline.

Builds a miniature but physically consistent synthetic world (5 districts,
2 states, 0.25 degree grid, 1986-2026), writes monthly GeoTIFFs for all four
variables (including a strong 2015 monsoon drought, a wet 2020, cloud gaps
in NDVI and one missing soil month), then runs the REAL pipeline functions:

    zonal_stats -> indicators -> export_app -> validate

and asserts scientific and contract properties of the result:

    * SPI/SPEI marginals ~ N(0, 1) over the base period
    * the injected 2015 drought is visible in SPI-3 (lower than climatology)
    * VCI within [0, 100]; SMA mostly within [-100, 100]
    * every finite value classifies under the metadata classes
    * the wide-CSV contract matches the registry (rows, ids, month columns)
    * metadata switches to static-research, summaries + manifest written
    * validate.py reports zero errors

No network access and no credentials are needed. Run:

    python selftest.py            (or: python run.py selftest)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from die_pipeline import common                      # noqa: E402

SELFTEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".selftest")

# synthetic world geometry: 2x2.5 degree box around 20N, 78E
BBOX = [77.0, 19.0, 79.5, 21.0]
RES = 0.25
YEARS = (1986, 2026)          # history window 1986-01 .. 2026-06
HIST_END = "2026-06"
NDVI_START = "2000-02"
DROUGHT_YEAR = 2015
WET_YEAR = 2020
SOIL_GAP = "2019-07"

# district layout (rectangles tiled inside the bbox)
DISTRICTS = [
    # (slug, name, state_id, state_name, w, s, e, n)
    ("teststatea-north",  "North Test",  "teststatea", "Test State A", 77.0, 20.0, 79.5, 21.0),
    ("teststatea-south1", "South One",   "teststatea", "Test State A", 77.0, 19.0, 78.25, 20.0),
    ("teststatea-south2", "South Two",   "teststatea", "Test State A", 78.25, 19.0, 79.5, 20.0),
    ("teststateb-east",   "East Test",   "teststateb", "Test State B", 78.5, 19.5, 79.5, 20.5),
    ("teststateb-west",   "West Test",   "teststateb", "Test State B", 77.0, 19.25, 78.0, 19.75),
]

PRECIP_CLIM = np.array([12, 15, 22, 28, 40, 115, 280, 260, 175, 60, 25, 16], dtype=float)
PET_CLIM = np.array([95, 110, 150, 180, 205, 195, 165, 155, 145, 125, 105, 92], dtype=float)
NDVI_CLIM = np.array([0.30, 0.32, 0.36, 0.40, 0.42, 0.45, 0.55, 0.60, 0.55, 0.45, 0.36, 0.31])


# ---------------------------------------------------------------------------#
# world construction
# ---------------------------------------------------------------------------#

def geodesic_rect_area(w, s, e, n) -> float:
    """True geodesic area (km2) of a lat/lon rectangle — never degree math."""
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    lons = [w, e, e, w, w]
    lats = [s, s, n, n, s]
    area_m, _ = geod.polygon_area_perimeter(lons, lats)
    return abs(area_m) / 1e6


def write_fixture_app(base: str) -> None:
    data = os.path.join(base, "app", "data")
    os.makedirs(os.path.join(data, "boundaries"), exist_ok=True)

    drows, srows, feats = [], [], []
    for slug, name, sid, sname, w, s, e, n in DISTRICTS:
        area = geodesic_rect_area(w, s, e, n)
        drows.append({"district_id": slug, "district_name": name,
                      "state_name": sname, "state_id": sid,
                      "area_km2": f"{area:.2f}",
                      "centroid_lon": f"{(w + e) / 2:.4f}",
                      "centroid_lat": f"{(s + n) / 2:.4f}"})
        feats.append({
            "type": "Feature",
            "properties": {"id": slug, "district": name, "state": sname, "sid": sid},
            "geometry": {"type": "Polygon",
                         "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
        })
    states = {}
    for r, f in zip(drows, DISTRICTS):
        states.setdefault(r["state_id"], {"state_name": r["state_name"], "area": 0.0,
                                          "n": 0, "lon": [], "lat": []})
        st = states[r["state_id"]]
        st["area"] += float(r["area_km2"])
        st["n"] += 1
        st["lon"].append(float(r["centroid_lon"]))
        st["lat"].append(float(r["centroid_lat"]))
    for sid, st in states.items():
        srows.append({"state_id": sid, "state_name": st["state_name"],
                      "area_km2": f"{st['area']:.2f}", "n_districts": st["n"],
                      "centroid_lon": f"{np.mean(st['lon']):.4f}",
                      "centroid_lat": f"{np.mean(st['lat']):.4f}"})

    import csv as _csv
    with open(os.path.join(data, "districts.csv"), "w", newline="") as fh:
        w_ = _csv.DictWriter(fh, fieldnames=list(drows[0].keys()))
        w_.writeheader()
        w_.writerows(drows)
    with open(os.path.join(data, "states.csv"), "w", newline="") as fh:
        w_ = _csv.DictWriter(fh, fieldnames=list(srows[0].keys()))
        w_.writeheader()
        w_.writerows(srows)
    with open(os.path.join(data, "boundaries", "india_districts.geojson"), "w") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh)


SELFTEST_CONFIG = """
region:
  name: India (self-test fixture)
  bbox: [{bw}, {bs}, {be}, {bn}]
history:
  start: "1986-01"
  end: null
base_period:
  spi_spei: [1986, 2020]
  sma: [1986, 2020]
  vci: [2000, null]
min_base_years: 20
export:
  period_start: "2001-01"
  period_end: null
paths:
  app_root: "app"
  raw: "raw"
  processed: "processed"
  boundaries: null
  registry: null
downloads:
  chirps: {{dir: "chirps"}}
  era5land: {{dir: "era5land", dataset: "x", product_type: "x", variables: []}}
  modis: {{dir: "modis", product: "x", base_url: "x", tiles: []}}
  appeears: {{dir: "appeears"}}
variables:
  precip: {{dir: "precip", units: "mm/month", valid_range: [0.0, 4000.0]}}
  pet:    {{dir: "pet",    units: "mm/month", valid_range: [0.0, 700.0]}}
  soil:   {{dir: "soil",   units: "pct", valid_range: [0.0, 60.0]}}
  ndvi:   {{dir: "ndvi",   units: "fraction", valid_range: [-0.2, 1.0]}}
zonal:
  area_weighted: true
  all_touched_fallback: true
indicators:
  - {{id: "spi_1",   kind: spi,  scale: 1}}
  - {{id: "spi_3",   kind: spi,  scale: 3}}
  - {{id: "spi_6",   kind: spi,  scale: 6}}
  - {{id: "spi_12",  kind: spi,  scale: 12}}
  - {{id: "spei_1",  kind: spei, scale: 1}}
  - {{id: "spei_3",  kind: spei, scale: 3}}
  - {{id: "spei_6",  kind: spei, scale: 6}}
  - {{id: "spei_12", kind: spei, scale: 12}}
  - {{id: "sma",     kind: sma,  statistic: "percent_mean"}}
  - {{id: "vci",     kind: vci}}
app_metadata:
  data_mode: "static-research"
  methodology_version: "research-selftest-1.0"
  data_provenance: "self-test synthetic world"
  disclaimer: "self-test"
  sources:
    - id: "selftest"
      name: "Self-test generator"
      role: "fixture"
      description: "synthetic world for offline testing"
      url: "https://example.invalid"
qa:
  completeness_warn: 90.0
  completeness_fail: 70.0
  spi_abs_mean_warn: 0.35
  spi_sd_range: [0.70, 1.40]
  value_limits:
    zscore: [-4.0, 4.0]
    sma_pct: [-100.0, 100.0]
    vci_pct: [0.0, 100.0]
"""


def write_config(base: str) -> str:
    w, s, e, n = BBOX
    path = os.path.join(base, "config_selftest.yaml")
    with open(path, "w") as fh:
        fh.write(SELFTEST_CONFIG.format(bw=w, bs=s, be=e, bn=n))
    return path


def synthetic_world(cfg: dict, rng) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    months = common.month_range("1986-01", HIST_END)
    w, s, e, n = BBOX
    nx = int(round((e - w) / RES))
    ny = int(round((n - s) / RES))
    transform = from_bounds(w, s, e, n, nx, ny)
    xc = np.arange(nx) / nx                       # 0..1 west->east
    yc = np.arange(ny) / ny

    # smooth spatial noise fields (fixed in time)
    field = rng.normal(size=(ny, nx))
    field = np.add.outer(np.zeros(ny), np.convolve(field[0], np.ones(3) / 3, mode="same")) * 0 + field
    field = field + np.outer(np.sin(yc * 3.1), np.cos(xc * 2.7))

    a_t = np.zeros(len(months))                   # national anomaly factor
    for t in range(1, len(months)):
        a_t[t] = 0.55 * a_t[t - 1] + rng.normal(0, 0.7)
    for t, (y, m) in enumerate(months):
        if y == DROUGHT_YEAR and 6 <= m <= 9:
            a_t[t] -= 2.2
        if y == WET_YEAR and 6 <= m <= 9:
            a_t[t] += 1.6

    soil = np.full((ny, nx), 25.0)
    prev_precip_anom = 0.0
    dirs = {v: common.processed_dir(cfg, "rasters",
                                    cfg["variables"][v]["dir"])
            for v in ("precip", "pet", "soil", "ndvi")}

    def write(var, yms, arr):
        with rasterio.open(os.path.join(dirs[var], f"{yms}.tif"), "w",
                           driver="GTiff", height=ny, width=nx, count=1,
                           dtype="float32", crs="EPSG:4326", transform=transform,
                           nodata=np.nan, compress="deflate") as dst:
            dst.write(arr.astype(np.float32), 1)

    for t, (y, m) in enumerate(months):
        yms = common.ym((y, m))
        anom = a_t[t] + 0.35 * field
        precip = PRECIP_CLIM[m - 1] * np.exp(0.30 * anom)
        precip *= (1.0 + 0.15 * xc)[None, :]      # east slightly wetter
        write("precip", yms, precip)
        write("pet", yms, PET_CLIM[m - 1] * (1 + 0.0025 * (y - 1986))
              + 6.0 * field + rng.normal(0, 4, size=(ny, nx)))

        soil = 0.70 * soil + 0.30 * (25.0 + 0.045 * (precip - PRECIP_CLIM[m - 1])) \
            + rng.normal(0, 1.2, size=(ny, nx))
        soil = np.clip(soil, 3.0, 45.0)
        if yms != SOIL_GAP:
            write("soil", yms, soil)

        if (y, m) >= (2000, 2):
            anom_lag = 0.6 * prev_precip_anom + 0.4 * (precip.mean() - PRECIP_CLIM[m - 1])
            ndvi = NDVI_CLIM[m - 1] + 0.00035 * anom_lag + 0.02 * field \
                + rng.normal(0, 0.02, size=(ny, nx)) + 0.002 * (y - 2000)
            ndvi = np.clip(ndvi, 0.05, 0.92)
            clouds = rng.random((ny, nx)) < (0.10 if m in (6, 7, 8, 9) else 0.03)
            ndvi = np.where(clouds, np.nan, ndvi)
            write("ndvi", yms, ndvi)
            prev_precip_anom = precip.mean() - PRECIP_CLIM[m - 1]


# ---------------------------------------------------------------------------#
# assertions
# ---------------------------------------------------------------------------#

class Checks:
    def __init__(self):
        self.failed = []

    def check(self, cond, label, detail=""):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
        if not cond:
            self.failed.append(label)
        return cond


def verify(cfg, checks: Checks) -> None:
    from die_pipeline import export_app as _ea  # noqa: F401  (already ran)

    districts, states = common.load_registry(cfg)
    data = os.path.join(common.app_root(cfg), "data")
    with open(os.path.join(data, "metadata.json")) as fh:
        meta = json.load(fh)

    checks.check(meta["data_mode"] == "static-research", "metadata.data_mode switched")
    checks.check(meta["period"]["start"] == "2001-01" and meta["period"]["end"] == HIST_END,
                 "metadata.period = exported window",
                 f"{meta['period']['start']}..{meta['period']['end']}")
    checks.check(len(meta["indicators"]) == 10, "10 indicators in metadata")

    mats = {}
    for ind in meta["indicators"]:
        ids, date_cols, mat = common.read_wide_csv(
            os.path.join(common.app_root(cfg), ind["file"]))
        mats[ind["id"]] = mat
        checks.check(ids == [d["district_id"] for d in districts],
                     f"{ind['id']}: row order matches registry")
        checks.check(len(date_cols) == meta["period"]["n_months"],
                     f"{ind['id']}: month-column count matches period",
                     f"{len(date_cols)}")

    # SPI marginals over the whole export window (stationary precipitation)
    for iid in ("spi_1", "spi_3", "spi_6", "spi_12"):
        v = mats[iid][np.isfinite(mats[iid])]
        checks.check(abs(v.mean()) < 0.35, f"{iid}: pooled mean ~ 0", f"{v.mean():+.3f}")
        checks.check(0.70 <= v.std() <= 1.40, f"{iid}: pooled sd ~ 1", f"{v.std():.3f}")

    # Rolling-window warm-up months arrive as NaN.  The transform must keep
    # them missing instead of mapping them to the CLIP_P floor (-3.72), which
    # would look like a record drought in every early month.
    from die_pipeline import indicators as _ind
    _rng = np.random.default_rng(7)
    _fixtures = {
        "SPI": (_ind._gamma_spi, np.linspace(1.0, 120.0, 80)),
        "SPEI": (_ind._loglogistic_spei, _rng.gamma(2.0, 20.0, 300) - 40),
    }
    for name, (maker, base_sample) in _fixtures.items():
        fn = maker(base_sample)
        checks.check(fn is not None, f"{name} transform: fixture fits")
        z = fn(np.array([np.nan, -1.0, 20.0, 80.0]))
        checks.check(np.isnan(z[0]), f"{name} transform: NaN stays missing", str(z))
        checks.check(np.isfinite(z[1]) and np.isfinite(z[2]) and np.isfinite(z[3]),
                     f"{name} transform: valid inputs stay finite", str(z))

    # SPEI: calibrated on the base-period portion; the synthetic PET warming
    # trend must push post-base values lower (demand-side drought signal)
    cols = _date_cols(cfg, mats["spi_3"])
    base_j = [j for j, c in enumerate(cols) if int(c[:4]) <= 2020]
    post_j = [j for j, c in enumerate(cols) if int(c[:4]) > 2020]
    for iid in ("spei_1", "spei_3", "spei_6", "spei_12"):
        vb = mats[iid][:, base_j][np.isfinite(mats[iid][:, base_j])]
        vp = mats[iid][:, post_j][np.isfinite(mats[iid][:, post_j])]
        checks.check(abs(vb.mean()) < 0.35, f"{iid}: base-period mean ~ 0", f"{vb.mean():+.3f}")
        checks.check(0.70 <= vb.std() <= 1.40, f"{iid}: base-period sd ~ 1", f"{vb.std():.3f}")
        checks.check(vp.mean() < vb.mean(),
                     f"{iid}: warming PET trend lowers post-base SPEI",
                     f"post {vp.mean():+.3f} < base {vb.mean():+.3f}")

    # injected drought visible
    jja = [j for j, c in enumerate(cols) if c[5:7] in ("06", "07", "08", "09")]
    dr = [j for j in jja if cols[j][:4] == str(DROUGHT_YEAR)]
    nm = [j for j in jja if cols[j][:4]
          in ("2005", "2010", "2021", "2023", "2024")]
    d_mean = np.nanmean(mats["spi_3"][:, dr])
    n_mean = np.nanmean(mats["spi_3"][:, nm])
    checks.check(d_mean < n_mean - 0.8,
                 f"{DROUGHT_YEAR} monsoon drought visible in SPI-3",
                 f"drought {d_mean:+.2f} vs normal {n_mean:+.2f}")

    # VCI / SMA bounds + classification coverage
    vci = mats["vci"][np.isfinite(mats["vci"])]
    checks.check(vci.size > 0 and vci.min() >= 0 and vci.max() <= 100,
                 "VCI within [0, 100]", f"{vci.min():.1f}..{vci.max():.1f}")
    vci_2015 = np.nanmean(mats["vci"][:, dr])
    checks.check(vci_2015 < 45, "VCI depressed in the drought monsoon",
                 f"{vci_2015:.1f}")
    sma = mats["sma"][np.isfinite(mats["sma"])]
    checks.check(np.percentile(np.abs(sma), 99) <= 100,
                 "SMA within ±100 (99th pct)", f"{np.percentile(np.abs(sma), 99):.1f}")

    for ind in meta["indicators"]:
        vals = mats[ind["id"]][np.isfinite(mats[ind["id"]])]
        sample = vals[:: max(1, vals.size // 5000)]
        noclass = sum(1 for v in sample if common.classify(float(v), ind["classes"]) is None)
        checks.check(noclass == 0, f"{ind['id']}: every value classifies")

    # soil gap propagates as missing (never imputed)
    gap_j = [j for j, c in enumerate(_date_cols(cfg, mats["sma"])) if c == SOIL_GAP]
    if gap_j:
        col = mats["sma"][:, gap_j[0]]
        checks.check(np.isfinite(col).sum() == 0,
                     "missing source month -> all-missing SMA column (no imputation)")

    # summaries + manifest
    checks.check(os.path.exists(os.path.join(data, "summaries", "drought_events_spi_06.csv")),
                 "drought_events summary written")
    checks.check(os.path.exists(os.path.join(data, "summaries", "state_statistics_spi_06.csv")),
                 "state_statistics summary written")
    checks.check(os.path.exists(os.path.join(data, "pipeline_manifest.json")),
                 "pipeline_manifest.json written")
    import csv as _csv
    with open(os.path.join(data, "summaries", "drought_events_spi_06.csv")) as fh:
        ev = list(_csv.DictReader(fh))
    checks.check(any(int(e["event_start"][:4]) == DROUGHT_YEAR for e in ev),
                 f"at least one {DROUGHT_YEAR} drought event in the summary",
                 f"{len(ev)} events total")

    # validate step must return zero errors
    from die_pipeline import validate as _val
    rc = _val.validate(cfg)
    checks.check(rc == 0, "validate.py reports zero errors")


def verify_gee_parsing(cfg, checks: "Checks") -> None:
    """Offline checks for the GEE extraction -> series contract (no EE calls)."""
    import pandas as pd

    from die_pipeline import gee_export

    months = ["2025-01", "2025-02"]
    fields = {"id": "district_id", "name": "district_name", "state": "state_name"}

    def feature(did, name, state, jan, feb, suffix=""):
        props = {"district_id": did, "district_name": name, "state_name": state}
        for tag, (v, w, n, t) in (("m202501", jan), ("m202502", feb)):
            props[f"{tag}_v{suffix}"] = v
            props[f"{tag}_w{suffix}"] = w
            props[f"{tag}_n{suffix}"] = n
            props[f"{tag}_t{suffix}"] = t
        return {"type": "Feature", "properties": props, "geometry": None}

    info = {"features": [
        feature("d1", "District One", "State A",
                (300.0, 100.0, 40, 50), (0.0, 0.0, 0, 50)),
        feature("d2", "District Two", "State B",
                (120.0, 100.0, 20, 25), (0.0, 0.0, 0, 25)),
    ]}
    rows = gee_export._parse_features(info, months, fields)
    checks.check(len(rows) == 4, "GEE parse: one row per district-month")
    checks.check(abs(rows[0]["mean"] - 3.0) < 1e-9,
                 "GEE parse: weighted mean is v / w (no _sum suffix)")
    checks.check(rows[0]["valid_pixel_count"] == 40
                 and rows[0]["total_pixel_count"] == 50,
                 "GEE parse: valid/total pixel counts")
    checks.check(rows[1]["mean"] is None,
                 "GEE parse: fully masked month becomes a null mean")
    legacy = gee_export._parse_features(
        {"features": [feature("d3", "District Three", "State C",
                              (300.0, 100.0, 40, 50), (0.0, 0.0, 0, 50),
                              suffix="_sum")]},
        months, fields)
    checks.check(abs(legacy[0]["mean"] - 3.0) < 1e-9,
                 "GEE parse: legacy _sum-suffixed properties still parse")

    # Audit F2: the month gate must drop partially published months for
    # daily (summed) collections instead of compositing a false drought,
    # while monthly-aggregate collections still need only one image.
    months_all = ["2026-01", "2026-02", "2026-03"]
    gate_counts = {"2026-01": 31, "2026-02": 13, "2026-03": 0}
    ok_m, short_m, miss_m = gee_export._gate_months(months_all, gate_counts,
                                                    day_gate=True)
    checks.check(ok_m == ["2026-01"],
                 "GEE gate: fully published month is extractable")
    checks.check(short_m == ["2026-02"],
                 "GEE gate: partially published month is dropped (no false drought)")
    checks.check(miss_m == ["2026-03"],
                 "GEE gate: absent month is reported missing")
    ok_m2, short_m2, _miss2 = gee_export._gate_months(months_all, gate_counts,
                                                      day_gate=False)
    checks.check(ok_m2 == ["2026-01", "2026-02"] and short_m2 == [],
                 "GEE gate: monthly-aggregate collections need one image only")

    chunk_dir = common.processed_dir(cfg, "gee_chunks", "gee_selftest")
    os.makedirs(chunk_dir, exist_ok=True)
    gee_export._write_rows(os.path.join(chunk_dir, "2025-01__2025-01.csv"),
                           [rows[0], rows[2]])
    gee_export._write_rows(os.path.join(chunk_dir, "2025-02__2025-02.csv"),
                           [rows[1], rows[3]])
    out = gee_export._assemble(cfg, "gee_selftest", chunk_dir, months)
    df = pd.read_csv(out)
    checks.check(len(df) == 4, "GEE assemble: two chunks merge into 4 rows")
    checks.check(int(df["mean"].isna().sum()) == 2,
                 "GEE assemble: null means survive the CSV round trip")
    checks.check(str(df["valid_pixel_count"].dtype).startswith("int"),
                 "GEE assemble: pixel counts are integers")

    # Older chunks used ``Jan-25`` date labels; they must still land in the
    # assembled series instead of being filtered out.
    legacy_dir = common.processed_dir(cfg, "gee_chunks", "gee_selftest_legacy")
    os.makedirs(legacy_dir, exist_ok=True)
    legacy_rows = [dict(rows[0]), dict(rows[2])]
    for row in legacy_rows:
        row["date"] = "Jan-25"
    gee_export._write_rows(os.path.join(legacy_dir, "2025-01__2025-01.csv"),
                           legacy_rows)
    lout = gee_export._assemble(cfg, "gee_selftest_legacy", legacy_dir,
                                ["2025-01"])
    ldf = pd.read_csv(lout)
    checks.check(len(ldf) == 2 and set(ldf["date"]) == {"2025-01"},
                 "GEE assemble: legacy Mon-YY chunk dates are normalised")

    os.remove(out)
    shutil.rmtree(chunk_dir, ignore_errors=True)
    os.remove(lout)
    shutil.rmtree(legacy_dir, ignore_errors=True)


def _date_cols(cfg, mat):
    districts, _ = common.load_registry(cfg)
    months = common.month_range("2001-01", HIST_END)
    return [common.ym(t) for t in months]


# ---------------------------------------------------------------------------#

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="offline pipeline self-test")
    ap.add_argument("--keep", action="store_true", help="keep the .selftest workspace")
    args = ap.parse_args(argv or [])

    if os.path.exists(SELFTEST_DIR):
        shutil.rmtree(SELFTEST_DIR)
    os.makedirs(SELFTEST_DIR)
    base = SELFTEST_DIR

    write_fixture_app(base)
    cfg = common.load_config(write_config(base))

    common.banner("SELF-TEST 1/4 — synthetic world (raster generation)")
    synthetic_world(cfg, np.random.default_rng(7))
    n_ras = sum(len(os.listdir(common.processed_dir(cfg, "rasters", d)))
                for d in ("precip", "pet", "soil", "ndvi"))
    print(f"  wrote {n_ras} monthly GeoTIFFs")

    common.banner("SELF-TEST 2/4 — zonal statistics")
    from die_pipeline import zonal_stats
    districts, _ = common.load_registry(cfg)
    for var in ("precip", "pet", "soil", "ndvi"):
        zonal_stats.run_var(cfg, var, districts)

    common.banner("SELF-TEST 3/4 — indicators + export")
    from die_pipeline import indicators, export_app
    indicators.compute(cfg)
    export_app.run(cfg)

    common.banner("SELF-TEST 4/4 — assertions")
    checks = Checks()
    verify(cfg, checks)
    verify_gee_parsing(cfg, checks)

    common.hr()
    if checks.failed:
        print(f"SELF-TEST FAILED — {len(checks.failed)} check(s):")
        for f in checks.failed:
            print("   - " + f)
        rc = 1
    else:
        print("SELF-TEST PASSED — the pipeline produces a valid, scientifically "
              "consistent application dataset end-to-end.")
        rc = 0
    if not args.keep:
        shutil.rmtree(SELFTEST_DIR, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
