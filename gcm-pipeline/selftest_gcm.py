#!/usr/bin/env python3
"""DIE v2.0 - gcm-pipeline selftest_gcm.py (task M2.13, docs/v2/03 s3.11).

Deterministic orchestrator for the gcm-pipeline verification harness:
runs every step's --selftest suite (02-09) plus the frozen v1.0
data-pipeline harness, in fixed order, and fails loudly if any suite
fails. Nothing here runs production compute and nothing writes outside
work/test-output/ (the individual selftests own their scratch space).

Phase 1 (this file): wiring. Phase 2 (next session, same task ID): the
synthetic end-to-end mini world (3-model x 2-scenario, known biases +
injected drying trend) that exercises 02->09 compositionally - regrid
conservation, QDM identity + trend preservation, PET correctness,
SPI/SPEI calibration gates, ensemble exactness, partition sizes, catalog
integrity (docs/v2/03 s3.11).

Usage:
  python selftest_gcm.py              # run all suites
  python selftest_gcm.py --list       # list the suites
  python selftest_gcm.py --only 05,07 # run a subset (by prefix)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# (label, script path relative to `cwd`, cwd relative to repo root)
# Fixed order = pipeline order; the v1.0 harness first (frozen semantics
# must stay green before anything gcm-pipeline is trusted).
SUITES = [
    ("v1.0 data-pipeline harness (82 assertions)",
     "selftest.py", "data-pipeline"),
    ("02 regrid (T1a-T1e, T2, T3)", "02_regrid_025.py", "gcm-pipeline"),
    ("03 QDM (T1a-T5)", "03_qdm_bias_correct.py", "gcm-pipeline"),
    ("04 PET Hargreaves (T1a-T5)", "04_pet_hargreaves.py", "gcm-pipeline"),
    ("05 SPI/SPEI (T1-T7)", "05_spi_spei_compute.py", "gcm-pipeline"),
    ("06 district aggregation (T1-T6)", "06_district_aggregate.py",
     "gcm-pipeline"),
    ("07 ensemble statistics (T1-T5)", "07_ensemble_stats.py",
     "gcm-pipeline"),
    ("08 validation gate (T1-T8)", "08_validate_gcm.py", "gcm-pipeline"),
    ("09 export (T1-T9)", "09_export_parquet.py", "gcm-pipeline"),
]


def proj_env_fix(env: dict) -> dict:
    """Local-Windows workaround (PROGRESS M1.2 audit): PostGIS sets global
    PROJ_LIB/GDAL_DATA to unusable locations. Set them from the active env's
    rasterio bundle when those directories exist; a no-op elsewhere (the
    manylinux wheels used on CI bundle their own data)."""
    sp = Path(sys.prefix)
    for var, sub in (("PROJ_LIB", "Lib/site-packages/rasterio/proj_data"),
                     ("GDAL_DATA",
                      "Lib/site-packages/rasterio/gdal_data")):
        d = sp / sub
        if d.is_dir():
            env.setdefault(var, str(d))
    return env


def run_suite(label: str, script: str, cwd: str, python: str) -> tuple[bool, str]:
    """Run one --selftest suite; returns (ok, last-line summary)."""
    env = proj_env_fix(os.environ.copy())
    proc = subprocess.run([python, "-X", "utf8", script, "--selftest"],
                          cwd=REPO / cwd, env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1200)
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    tail = lines[-1] if lines else "(no output)"
    ok = proc.returncode == 0 and ("PASS" in out.upper())
    return ok, tail


def main() -> int:
    ap = argparse.ArgumentParser(description="gcm-pipeline selftest orchestrator (M2.13)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", metavar="PREFIX",
                    help="comma list of suite prefixes, e.g. '02,08,09' "
                         "(matches the leading number of the label)")
    ap.add_argument("--world", action="store_true",
                    help="M2.13 phase 2: build + run the synthetic "
                         "end-to-end mini world (02->09 chain, known "
                         "biases + injected drying trend)")
    args = ap.parse_args()

    suites = SUITES
    if args.only:
        keys = [k.strip() for k in args.only.split(",")]
        suites = [s for s in SUITES
                  if any(s[0].startswith(k) for k in keys)]
        if not suites:
            print(f"--only {args.only}: no suite matches")
            return 2

    if args.list:
        for label, script, _cwd in suites:
            print(f"  {label:<44} {script}")
        return 0

    if args.world:
        return world_selftest()

    print("=" * 78)
    print(f"GCM-PIPELINE SELFTEST ORCHESTRATOR - {len(suites)} suite(s)")
    print("=" * 78)
    python = sys.executable
    results = []
    for label, script, cwd in suites:
        print(f"[suite] {label:<44} {script}")
        try:
            ok, tail = run_suite(label, script, cwd, python)
        except subprocess.TimeoutExpired:
            ok, tail = False, "TIMEOUT (> 1200 s)"
        results.append((label, ok, tail))
        print(f"        -> {'PASS' if ok else 'FAIL'}   {tail[:110]}")

    n_fail = sum(1 for _l, ok, _t in results if not ok)
    print("=" * 78)
    for label, ok, tail in results:
        if not ok:
            print(f"  FAILED: {label}   ({tail})")
    print(f"RESULT: {len(results) - n_fail}/{len(results)} suites PASS"
          + ("" if n_fail == 0 else f" - {n_fail} FAILED"))
    print("=" * 78)
    return 1 if n_fail else 0


# ===========================================================================
# M2.13 phase 2 — synthetic end-to-end mini world (docs/v2/03 s3.11)
# ===========================================================================
# A 3-model world that mirrors the PRODUCTION record shape exactly
# (historical 1981-2014 + ssp245 2015-2050 — the real phase-2 download is
# 2015-2050, so the world exercises the same seam logic verbatim) and runs
# the whole chain 02->09 through subprocesses with DIE_CONFIG_DIR pointed
# at a test config dir. Everything lives under work/test-output/ (X9).
#
# World design (recorded in PROGRESS section 9):
#   source grid 0.5 deg (6x6, offset so every 0.25 target cell straddles
#   4 source cells — genuine conservative weighting); target grid 7x7
#   0.25 deg (world reference.yaml); wA truthful; wB = pr x0.7 + 1.5 K
#   temperature bias (QDM must remove it); wC = wA + ssp drying trend
#   (pr x1.0 -> x0.75 over 2015-2050) + +2 K warming (trend must SURVIVE
#   the correction). IMD reference = independent realisation with the
#   same climatology, pr missing 1981-01/02 like the real record.

import json as _json
import math as _math
import shutil as _shutil

import numpy as _np

WORLD_SEED = 20261103
WORLD_MODELS = ("wA", "wB", "wC")
WORLD_VARS = ("pr", "tasmax", "tasmin")
WORLD_HIST = (1981, 2014)
WORLD_SSP = (2015, 2050)                    # mirrors the real phase-2 record
WORLD_REF = (1981, 2020)
WORLD_VARIANT, WORLD_GRID = "r1i1p1f1", "gn"
WORLD_IIDS = tuple(f"{k}_{s:02d}" for k in ("spi", "spei") for s in (1, 3, 6, 12))

# 0.5-deg source grid, offset so target cell edges (.0/.25/.5/.75) always
# straddle source cell edges (.625/.125) -> 2x2 source overlap per cell
W_SRC_LON = 78.875 + 0.5 * _np.arange(6)    # 78.875 .. 81.375
W_SRC_LAT = 20.375 + 0.5 * _np.arange(6)    # 20.375 .. 22.875
# 0.25-deg target grid (world reference.yaml): 7x7 = 49 cells
W_TGT = {"res_deg": 0.25, "lon_min": 79.0, "lon_max": 80.75,
         "lat_min": 21.0, "lat_max": 22.75,
         "regrid_method": {"pr": "conservative", "tasmax": "bilinear",
                           "tasmin": "bilinear"}}

W_SEAS = _np.array([0.4, 0.5, 0.8, 1.2, 1.6, 3.0, 5.0, 4.5, 3.0, 1.2, 0.5, 0.3])
W_WETF = _np.array([0.2, 0.2, 0.3, 0.4, 0.5, 0.7, 0.8, 0.8, 0.7, 0.5, 0.3, 0.2])
W_TMAXC = _np.array([26.0, 28.0, 32.0, 35.0, 36.0, 32.0, 29.0, 29.0, 30.0,
                     30.0, 28.0, 26.0])
W_DRNG = _np.array([14.0, 13.0, 12.0, 11.0, 10.0, 8.0, 7.0, 7.0, 8.0, 9.0,
                    11.0, 13.0])
W_DRY_MONTHS = (12, 1, 2, 3)


def _w_days_in_month(y, m):
    return [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def _w_monthly_rates(rng, years, nlat, nlon, zero_atom=True):
    """Monthly mean pr rate fields (mm/day) with a seasonal cycle, an
    east-west wetness gradient and interannual noise. In dry-season months
    ~10% of cells are forced fully dry (the mixed-zeros atom the SPI fit
    must handle). Returns {(y, m): (nlat, nlon) array}."""
    cf = 1.0 + 0.5 * (_np.arange(nlon) / (nlon - 1))
    out = {}
    for y in years:
        yf = 1.0 + 0.05 * rng.standard_normal()
        for m in range(1, 13):
            e = _np.exp(0.15 * rng.standard_normal((nlat, nlon)))
            r = W_SEAS[m - 1] * cf[None, :] * yf * e
            if zero_atom and m in W_DRY_MONTHS and rng.random() < 0.5:
                r = _np.where(rng.random((nlat, nlon)) < 0.10, 0.0, r)
            out[(y, m)] = r
    return out


def _w_monthly_tas(rng, years, nlat, nlon, warming=None):
    """Monthly mean tasmax (deg C) fields: seasonal cycle + interannual
    noise + optional linear warming (deg C per year from the period start)."""
    latf = 0.15 * (_np.arange(nlat) - (nlat - 1) / 2)      # mild S->N cooling
    out = {}
    for y in years:
        for m in range(1, 13):
            base = W_TMAXC[m - 1] + latf[:, None]
            n = 0.4 * rng.standard_normal((nlat, nlon))
            if warming is not None:
                base = base + warming * (y - years[0] + 1)
            out[(y, m)] = base + n
    return out


def _w_daily_pr(rng, rate, y, m):
    """Monthly rate -> daily rate (n days) with a wet/dry atom; the monthly
    mean of the daily series EXACTLY equals `rate` (weights normalised over
    all days). Returns (n, nlat, nlon)."""
    n = _w_days_in_month(y, m)
    wet = rng.random(n) < W_WETF[m - 1]
    w = _np.where(wet, rng.gamma(1.5, 1.0, n) + 0.1, 0.0)
    nl, nlon = rate.shape
    daily = _np.zeros((n, nl, nlon))
    if w.mean() > 0:
        scale = w / w.mean()                    # (n,) — sums preserve mean
        daily = rate[None, :, :] * scale[:, None, None]
    return daily


def _w_daily_tas(rng, monthly, y, m, dmin=None):
    """Monthly mean (deg C) -> daily fields with zero-mean jitter so the
    monthly mean is preserved exactly. dmin = paired daily minima array."""
    n = _w_days_in_month(y, m)
    nl, nlon = monthly.shape
    eps = rng.standard_normal((n, nl, nlon))
    eps -= eps.mean(axis=0, keepdims=True)
    daily = monthly[None, :, :] + eps
    if dmin is not None:
        # diurnal range with jitter, kept > 2 degC
        dr = W_DRNG[m - 1] + rng.standard_normal((n, nl, nlon))
        dr -= dr.mean(axis=0, keepdims=True)
        dr = _np.clip(dr, 2.0, None)
        dmin = daily - dr
    return daily, dmin


def _w_write_daily_nc(path, var, lat, lon, days_offsets, data, units,
                      base_date):
    import netCDF4 as nc
    path.parent.mkdir(parents=True, exist_ok=True)
    with nc.Dataset(path, "w") as d:
        d.createDimension("time", len(days_offsets))
        d.createDimension("lat", len(lat))
        d.createDimension("lon", len(lon))
        v = d.createVariable(var, "f4", ("time", "lat", "lon"), zlib=True,
                             complevel=4, fill_value=_np.float32(9.96921e36))
        v[:] = data.astype(_np.float32)
        v.units = units
        t = d.createVariable("time", "f8", ("time",))
        t[:] = _np.asarray(days_offsets, _np.float64)
        t.units = f"days since {base_date} 00:00:00"
        t.calendar = "proleptic_gregorian"
        la = d.createVariable("lat", "f8", ("lat",))
        la[:] = lat
        la.units = "degrees_north"
        la.axis = "Y"
        lo = d.createVariable("lon", "f8", ("lon",))
        lo[:] = lon
        lo.units = "degrees_east"
        lo.axis = "X"


def _w_write_year(world, var, model, exp, y, daily_mm_or_k):
    """One raw year file in the production naming convention. pr arrives as
    mm/day and is stored in kg m-2 s-1 (x1/86400); tas in deg C -> K."""
    name = f"{var}_day_{model}_{exp}_{WORLD_VARIANT}_{WORLD_GRID}_{y}_v2.0.nc"
    path = world / "raw" / var / name
    if var == "pr":
        data = daily_mm_or_k / 86400.0
        units = "kg m-2 s-1"
        out = data
    else:
        data = daily_mm_or_k + 273.1
        units = "K"
        out = data
    base = f"{y}-01-01"
    offs = _np.arange(out.shape[0])
    _w_write_daily_nc(path, var, W_SRC_LAT, W_SRC_LON, offs, out, units, base)


def _w_geo_area_km2(ring):
    """Shoelace area of a lon/lat ring on the v1.0 LAEA projection."""
    from pyproj import Proj
    p = Proj("+proj=laea +lat_0=22.5 +lon_0=79.5 +x_0=0 +y_0=0 "
             "+datum=WGS84 +units=m +no_defs")
    xy = [p(lon, lat) for lon, lat in ring[:-1]]      # drop the closing node
    s = 0.0
    for k in range(len(xy)):
        x1, y1 = xy[k]
        x2, y2 = xy[(k + 1) % len(xy)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0 / 1e6


def build_world() -> tuple:
    """Create the whole synthetic world + test config dir. Idempotent
    (wipes the world dir first). Returns (world_dir, cfg_dir)."""
    import yaml
    import netCDF4 as nc
    world = HERE / "work" / "test-output" / "gcm-world"
    if world.exists():
        _shutil.rmtree(world)
    cfg = world / "config"
    cfg.mkdir(parents=True)
    rng = _np.random.default_rng(WORLD_SEED)
    nl_s, nlon_s = len(W_SRC_LAT), len(W_SRC_LON)
    hist_years = range(WORLD_HIST[0], WORLD_HIST[1] + 1)
    ssp_years = range(WORLD_SSP[0], WORLD_SSP[1] + 1)
    ref_years = range(WORLD_REF[0], WORLD_REF[1] + 1)

    # ---------------- source-grid monthly fields -------------------------
    truth_hist = _w_monthly_rates(rng, hist_years, nl_s, nlon_s)
    truth_ssp = _w_monthly_rates(rng, ssp_years, nl_s, nlon_s, zero_atom=False)
    tmax_hist = _w_monthly_tas(rng, hist_years, nl_s, nlon_s)
    tmax_ssp = _w_monthly_tas(rng, ssp_years, nl_s, nlon_s, warming=2.0 / 36.0)

    # ---------------- model raw year files -------------------------------
    def model_pr_rate(model, y, m):
        r = truth_hist[(y, m)] if y <= 2014 else truth_ssp[(y, m)]
        if model == "wB":
            r = 0.7 * r                       # the bias QDM must remove
        elif model == "wC" and y > 2014:
            r = r * (1.0 - 0.25 * (y - 2014) / 36.0)   # drying 1.0 -> 0.75
        return r

    def model_tmax(model, y, m):
        t = tmax_hist[(y, m)] if y <= 2014 else tmax_ssp[(y, m)]
        if model == "wB":
            t = t + 1.5                       # warm bias QDM must remove
        return t

    for model in WORLD_MODELS:
        for exp, years in (("historical", hist_years), ("ssp245", ssp_years)):
            for y in years:
                # accumulate the WHOLE year first, then write once —
                # _w_write_daily_nc replaces the file, so a per-month call
                # would leave only the last month's days (the bug that
                # produced one (y, 1) month group per year file)
                pr_parts, tx_parts, tn_parts = [], [], []
                for m in range(1, 13):
                    pr_parts.append(_w_daily_pr(
                        rng, model_pr_rate(model, y, m), y, m))
                    tx, tn = _w_daily_tas(rng, model_tmax(model, y, m), y, m,
                                          dmin=True)
                    tx_parts.append(tx)
                    tn_parts.append(tn)
                _w_write_year(world, "pr", model, exp, y,
                              _np.concatenate(pr_parts))
                _w_write_year(world, "tasmax", model, exp, y,
                              _np.concatenate(tx_parts))
                _w_write_year(world, "tasmin", model, exp, y,
                              _np.concatenate(tn_parts))

    # ---------------- IMD reference (target grid, 1981-2020) --------------
    # independent realisation of the same climate (free-running models are
    # never expected to match observed weather month-by-month); pr missing
    # 1981-01/02 like the real IMD record.
    from pyproj import Proj
    import scipy.sparse as sp
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("r02w", HERE / "02_regrid_025.py")
    r02 = _ilu.module_from_spec(spec)
    spec.loader.exec_module(r02)
    tgt = r02.target_grid({"target_grid": W_TGT})
    A, row_sums = r02.conservative_weights(W_SRC_LAT, W_SRC_LON, tgt)
    tgt_lat, tgt_lon = tgt["lat_centres"], tgt["lon_centres"]
    cell_noise = 1.0 + 0.05 * rng.standard_normal((len(tgt_lat), len(tgt_lon)))
    imd_rates = {}
    for y in ref_years:
        for m in range(1, 13):
            if y == 1981 and m in (1, 2):
                imd_rates[(y, m)] = None       # missing like the real record
                continue
            src = truth_hist[(y, m)] if y <= 2014 else truth_ssp[(y, m)]
            remap, _re, _cr = r02.conservative_apply(
                A, row_sums, src, (tgt["n_lat"], tgt["n_lon"]))
            imd_rates[(y, m)] = remap * cell_noise
    # accumulate each reference year across months, then write ONCE per
    # file (same overwrite hazard as the model writer above)
    for y in ref_years:
        pr_y, tx_y, tn_y = [], [], []
        for m in range(1, 13):
            n = _w_days_in_month(y, m)
            r = imd_rates[(y, m)]
            if r is None:
                pr_d = _np.full((n, len(tgt_lat), len(tgt_lon)), _np.nan)
            else:
                pr_d = _w_daily_pr(rng, r, y, m)
            t_ref = (_w_monthly_tas(rng, [y], len(tgt_lat), len(tgt_lon))
                     [(y, m)])
            tx, tn = _w_daily_tas(rng, t_ref, y, m, dmin=True)
            pr_y.append(pr_d)
            tx_y.append(tx)
            tn_y.append(tn)
        base = f"{y}-01-01"
        offs = _np.arange(sum(_w_days_in_month(y, m) for m in range(1, 13)))
        _w_write_daily_nc(world / "imd" / "pr" / f"IMD_rain_{y}.nc",
                          "rain", tgt_lat, tgt_lon, offs,
                          _np.concatenate(pr_y), "mm/day", base)
        _w_write_daily_nc(world / "imd" / "tmax" / f"IMD_tmax_{y}.nc",
                          "tmax", tgt_lat, tgt_lon, offs,
                          _np.concatenate(tx_y), "degC", base)
        _w_write_daily_nc(world / "imd" / "tmin" / f"IMD_tmin_{y}.nc",
                          "tmin", tgt_lat, tgt_lon, offs,
                          _np.concatenate(tn_y), "degC", base)

    # ---------------- 3-district geometry + registry ----------------------
    bands = [(79.0, 79.6), (79.6, 80.2), (80.2, 80.75)]
    feats = []
    reg_rows = []
    for i, (lo0, lo1) in enumerate(bands, start=1):
        ring = [[lo0, 21.0], [lo1, 21.0], [lo1, 22.75], [lo0, 22.75],
                [lo0, 21.0]]
        feats.append({"type": "Feature",
                      "properties": {"id": f"w{i}", "district": f"Test {i}",
                                     "state": "Test State", "sid": "TS"},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
        reg_rows.append({"district_id": f"w{i}", "district_name": f"Test {i}",
                         "state_name": "Test State", "state_id": "TS",
                         "area_km2": f"{_w_geo_area_km2(ring):.1f}",
                         "centroid_lon": f"{(lo0 + lo1) / 2:.4f}",
                         "centroid_lat": "21.8750"})
    (world / "boundaries").mkdir(parents=True, exist_ok=True)
    (world / "boundaries" / "test_districts.geojson").write_text(
        _json.dumps({"type": "FeatureCollection", "features": feats}),
        encoding="utf-8")
    with open(world / "boundaries" / "test_registry.csv", "w",
              encoding="utf-8", newline="") as fh:
        import csv as _csv
        wtr = _csv.DictWriter(fh, fieldnames=list(reg_rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(reg_rows)

    # ---------------- test config dir (DIE_CONFIG_DIR) --------------------
    def load(name):
        return yaml.safe_load((HERE / "config" / name).read_text(encoding="utf-8"))

    def dump(name, doc):
        yaml.safe_dump(doc, open(cfg / name, "w", encoding="utf-8"),
                       sort_keys=False, allow_unicode=True)

    wroot = "work/test-output/gcm-world/work"
    oroot = "work/test-output/gcm-world/out"
    paths = load("paths.yaml")
    paths["raw_root"] = str(world / "raw")
    paths["raw_root_ssp"] = str(world / "raw")
    paths["work_root"] = wroot
    paths["out_root"] = oroot
    dump("paths.yaml", paths)

    ref = load("reference.yaml")
    ref["target_grid"] = W_TGT
    ref["reference"]["precipitation"]["primary"]["path"] = \
        str(world / "imd" / "pr")
    ref["reference"]["temperature"]["primary"]["path"] = \
        str(world / "imd" / "tmax")
    ref["reference"]["temperature"]["primary"]["path_tmin"] = \
        str(world / "imd" / "tmin")
    dump("reference.yaml", ref)

    doc = load("models.yaml")
    doc["meta"] = {"status": "selftest-synthetic-world",
                   "list_source": "selftest_gcm.py world builder"}
    doc["genealogy"] = {}
    doc["models"] = [
        {"source_id": m, "variant": WORLD_VARIANT, "grid_label": WORLD_GRID,
         "historical": {"start": WORLD_HIST[0], "end": WORLD_HIST[1]},
         "ssp245": {"start": WORLD_SSP[0], "end": WORLD_SSP[1]},
         "era_c_ensemble": True}
        for m in WORLD_MODELS]
    dump("models.yaml", doc)

    agg = load("aggregate.yaml")
    agg["district_aggregation"]["boundaries_geojson"] = \
        str(world / "boundaries" / "test_districts.geojson")
    agg["district_aggregation"]["registry_csv"] = \
        str(world / "boundaries" / "test_registry.csv")
    dump("aggregate.yaml", agg)

    for name in ("ensemble.yaml", "validation.yaml"):
        dump(name, load(name))

    ex = load("export.yaml")
    # defense in depth: publish targets point INSIDE work/test-output even
    # though the X1 gate refuses before any publish copy happens (W8)
    pub = ex["export"]["publish"]["targets"]
    pub["parquet"] = "gcm-pipeline/work/test-output/gcm-world/publish/parquet"
    pub["catalog"] = "gcm-pipeline/work/test-output/gcm-world/publish/catalog.json"
    pub["pipeline_manifest"] = ("gcm-pipeline/work/test-output/gcm-world/"
                                "publish/pipeline_manifest.json")
    pub["metadata"] = "gcm-pipeline/work/test-output/gcm-world/publish/metadata.json"
    dump("export.yaml", ex)
    return world, cfg


def _w_run_step(label, script, args, cfg_dir, expect_rc=0):
    """Run one pipeline step in the world; returns (ok, output tail)."""
    env = proj_env_fix(os.environ.copy())
    env["DIE_CONFIG_DIR"] = str(cfg_dir)
    proc = subprocess.run([sys.executable, "-X", "utf8", script] + args,
                          cwd=HERE, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=3600)
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    tail = lines[-1] if lines else "(no output)"
    ok = proc.returncode == expect_rc
    if not ok:
        tail = f"rc={proc.returncode} (expected {expect_rc}): {tail}"
    print(f"[chain] {label:<46} {'OK' if ok else 'FAIL'}  {tail[:100]}")
    return ok, out


def _w_load_monthly(path, var):
    """(time, lat, lon) monthly field + [(y, m)] axis from an NC file."""
    import netCDF4 as nc
    d = nc.Dataset(path)
    arr = _np.asarray(_np.ma.filled(d.variables[var][:], _np.nan), float)
    t = d.variables["time"]
    import cftime
    dates = cftime.num2date(t[:], t.units,
                            getattr(t, "calendar", "standard"))
    d.close()
    return arr, [(x.year, x.month) for x in dates]


def world_selftest() -> int:
    """Build the world, run the 02->09 chain, assert W1-W8."""
    print("=" * 78)
    print("GCM-PIPELINE WORLD SELFTEST (M2.13 phase 2, seed "
          f"{WORLD_SEED})")
    print("=" * 78)
    world, cfg_dir = build_world()
    work = world / "work"
    out = world / "out"
    steps = [
        ("02 regrid both experiments",
         "02_regrid_025.py", ["--experiments", "historical,ssp245"], 0),
        ("03 prepare reference", "03_qdm_bias_correct.py",
         ["--prepare-reference"], 0),
        ("03 QDM historical-corrected", "03_qdm_bias_correct.py",
         ["--mode", "historical-corrected"], 0),
        ("03 QDM ssp245", "03_qdm_bias_correct.py",
         ["--mode", "ssp", "--experiments", "ssp245"], 0),
        ("04 PET reference", "04_pet_hargreaves.py", ["--reference"], 0),
        ("04 PET historical-corrected", "04_pet_hargreaves.py",
         ["--mode", "historical-corrected"], 0),
        ("04 PET ssp245", "04_pet_hargreaves.py",
         ["--mode", "ssp", "--experiments", "ssp245"], 0),
        ("05 indices reference", "05_spi_spei_compute.py",
         ["--reference"], 0),
        ("05 indices historical-corrected", "05_spi_spei_compute.py",
         ["--mode", "historical-corrected"], 0),
        ("05 indices ssp245 (stitched)", "05_spi_spei_compute.py",
         ["--mode", "ssp", "--experiments", "ssp245"], 0),
        ("06 aggregate reference", "06_district_aggregate.py",
         ["--reference"], 0),
        ("06 aggregate historical-corrected", "06_district_aggregate.py",
         ["--mode", "historical-corrected"], 0),
        ("06 aggregate ssp245", "06_district_aggregate.py",
         ["--mode", "ssp", "--experiments", "ssp245"], 0),
        ("07 ensemble historical-corrected", "07_ensemble_stats.py", [], 0),
        ("07 ensemble ssp245", "07_ensemble_stats.py",
         ["--mode", "ssp", "--experiments", "ssp245"], 0),
        ("08 validation historical-corrected", "08_validate_gcm.py",
         ["--mode", "historical-corrected"], 0),
        ("09 export historical-corrected", "09_export_parquet.py",
         ["--mode", "historical-corrected"], 0),
        ("09 export ssp245 (staging)", "09_export_parquet.py",
         ["--mode", "ssp"], 0),
        ("09 publish attempt (X1 refusal expected)", "09_export_parquet.py",
         ["--mode", "ssp", "--publish"], 3),
    ]
    fails = []
    for label, script, args, rc in steps:
        ok, outp = _w_run_step(label, script, args, cfg_dir, expect_rc=rc)
        if not ok:
            fails.append(f"{label}: {outp[-2000:]}")
            break
    if fails:
        print(f"WORLD FAIL at chain step: {fails[0]}")
        return 1

    # ------------------- assertions -------------------------------------
    import netCDF4 as nc
    import pyarrow.parquet as pq

    # W1: regrid manifest complete + conservation gate
    man = _json.loads((work / "regrid_manifest.json").read_text())
    recs = man["files"]
    ok = len(recs) == 18 and all(r.get("status") == "ok" for r in recs.values())
    cons_bad = [k for k, r in recs.items()
                if r.get("conservation_max_rel") is not None
                and r["conservation_max_rel"] > 1e-6]
    print(f"W1 regrid: {len(recs)} records (expect 18), status ok: {ok}, "
          f"conservation breaches: {cons_bad or 'none'}")
    if not ok or cons_bad:
        fails.append("W1 regrid manifest/conservation")

    # W2: QDM removes the wB bias (pr ratio + tas offset)
    imd_pr, imd_m = _w_load_monthly(work / "reference" / "imd_pr_1981-2020.nc",
                                    "pr")
    imd_tx, _ = _w_load_monthly(work / "reference" / "imd_tasmax_1981-2020.nc",
                                "tasmax")
    wb_c, wb_m = _w_load_monthly(
        work / "qdm" / "wB" / "historical-corrected" /
        sorted((work / "qdm" / "wB" / "historical-corrected")
               .glob("pr_*.nc"))[0].name, "pr")
    wa_c, _ = _w_load_monthly(
        work / "qdm" / "wA" / "historical-corrected" /
        sorted((work / "qdm" / "wA" / "historical-corrected")
               .glob("pr_*.nc"))[0].name, "pr")
    common = [i for i, mm in enumerate(wb_m)
              if mm in imd_m and not (mm[0] == 1981 and mm[1] in (1, 2))]
    imd_idx = {mm: k for k, mm in enumerate(imd_m)}
    pr_corr = _np.nanmean([wb_c[i] for i in common]) / \
        _np.nanmean([imd_pr[imd_idx[wb_m[i]]] for i in common])
    pr_raw = 0.7          # the injected wB factor
    wb_tx = _w_load_monthly(
        work / "qdm" / "wB" / "historical-corrected" /
        sorted((work / "qdm" / "wB" / "historical-corrected")
               .glob("tasmax_*.nc"))[0].name, "tasmax")[0]
    tx_corr = _np.nanmean([wb_tx[i] for i in common]) - _np.nanmean(
        [imd_tx[imd_idx[wb_m[i]]] for i in common])
    ok = 0.90 <= pr_corr <= 1.10 and abs(tx_corr) <= 0.5
    print(f"W2 QDM bias removal (wB): corrected pr mean ratio vs IMD = "
          f"{pr_corr:.3f} (raw 0.700), corrected tasmax offset = "
          f"{tx_corr:+.2f} K (raw +1.50 K): {ok}")
    if not ok:
        fails.append("W2 QDM bias removal")

    # W3: the wC drying trend SURVIVES correction; wA stays flat
    def window_mean(path, var, y0, y1):
        arr, months = _w_load_monthly(path, var)
        idx = [i for i, mm in enumerate(months) if y0 <= mm[0] <= y1]
        return float(_np.nanmean(arr[idx]))

    qdm_c = work / "qdm"
    for model, expect_dry in (("wC", True), ("wA", False)):
        pr_p = next((qdm_c / model / "ssp245").glob("pr_*.nc"))
        base = window_mean(pr_p, "pr", 2015, 2034)
        wind = window_mean(pr_p, "pr", 2041, 2050)
        spi_p = next((work / "indices" / model / "ssp245")
                     .glob("spi_03_*.nc"))
        sb = window_mean(spi_p, "spi_03", 2015, 2034)
        sw = window_mean(spi_p, "spi_03", 2041, 2050)
        if expect_dry:
            ok = wind < 0.90 * base and sw < sb - 0.15
        else:
            ok = abs(wind / base - 1.0) < 0.10 and abs(sw - sb) < 0.30
        print(f"W3 trend survival ({model}): pr window/base = "
              f"{wind / base:.3f} (raw wC 0.75-endpoint), spi_03 window-base "
              f"= {sw - sb:+.3f}: {'OK' if ok else 'FAIL'}")
        if not ok:
            fails.append(f"W3 trend survival {model}")

    # W4: reference SPI-3 is standardised
    ref_spi, ref_months = _w_load_monthly(
        work / "indices" / "reference" /
        sorted((work / "indices" / "reference").glob("spi_03_*.nc"))[0].name,
        "spi_03")
    z = ref_spi[_np.isfinite(ref_spi)]
    ok = abs(float(z.mean())) <= 0.15 and z.size > 0.9 * ref_spi.size
    print(f"W4 reference spi_03: mean={z.mean():+.3f} sd={z.std():.3f} "
          f"finite={z.size}/{ref_spi.size}: {ok}")
    if not ok:
        fails.append("W4 reference standardisation")

    # W5: ensemble exactness (n=3 recorded; median == member median)
    ens_path = work / "ensemble" / "ssp245" / \
        sorted((work / "ensemble" / "ssp245").glob("spi_03_ensemble_*.nc"))[0] \
        .name
    ens, ens_months = _w_load_monthly(ens_path, "median")
    nmod, _ = _w_load_monthly(ens_path, "n_models")
    members = []
    for m in WORLD_MODELS:
        a, mm = _w_load_monthly(
            work / "aggregate" / m / "ssp245" /
            sorted((work / "aggregate" / m / "ssp245")
                   .glob("spi_03_districts_*.nc"))[0].name, "spi_03")
        members.append(a)
    med = _np.nanmedian(_np.stack(members), axis=0)
    fin = _np.isfinite(ens)
    ok = bool(_np.all(nmod[fin] == 3)
              and _np.nanmax(_np.abs(ens[fin] - med[fin])) < 1e-4)
    print(f"W5 ensemble: n_models==3 on all finite cells, median vs member "
          f"median max|diff| = "
          f"{_np.nanmax(_np.abs(ens[fin] - med[fin])):.2e}: {ok}")
    if not ok:
        fails.append("W5 ensemble exactness")

    # W6: gate PASS recorded
    report = _json.loads((work / "validation" / "validation_report.json")
                         .read_text())
    gates = report.get("gates", {})
    enforcing = {k: g for k, g in gates.items() if not g.get("reported_only")}
    all_pass = all(g.get("pass") for g in enforcing.values()) if enforcing \
        else False
    print(f"W6 validation report: mode={report.get('mode')}, "
          f"{len(enforcing)} enforcing gates "
          f"(+{len(gates) - len(enforcing)} reported-only), all pass: "
          f"{all_pass}")
    if report.get("mode") != "historical-corrected" or not all_pass:
        fails.append("W6 validation gate")

    # W7: staging round-trip (12 random partitions vs source NCs)
    stag = out / "projections"
    parts = sorted(stag.rglob("*.parquet"))
    n_expected = (8 * 6 * 36) + (3 * 8 * 36)     # ensemble + members
    ok = len(parts) == n_expected
    print(f"W7 staging: {len(parts)} parquet partitions "
          f"(expect {n_expected}): {ok}")
    if ok:
        rng7 = _np.random.default_rng(WORLD_SEED + 77)
        for p in rng7.choice(parts, size=min(12, len(parts)), replace=False):
            p = Path(p)
            rel = p.relative_to(stag)
            # layout: scenario=../stat=../variable=../year=../part-0.parquet
            seg = dict(s.split("=", 1) for s in rel.parts[:-1])
            tbl = pq.read_table(p)
            vals = _np.asarray(tbl.column("value"))
            dids = _np.asarray(tbl.column("district_id")).astype(str)
            yr = int(seg["year"])
            src_path = None
            var = seg["variable"]
            if seg["stat"] == "members":
                src_path = next((work / "aggregate" / seg["model"]
                                 / "ssp245").glob(f"{var}_districts_*.nc"))
            else:
                src_path = next((work / "ensemble" / "ssp245")
                                .glob(f"{var}_ensemble_*.nc"))
            # districts files store the raw iid variable; ensemble files
            # store each stat under its own name (median, spread, ...)
            field = var if seg["stat"] == "members" else seg["stat"]
            src, months = _w_load_monthly(src_path, field)
            did_order = _w_dids_of(src_path)
            did_pos = {d: k for k, d in enumerate(did_order)}
            yidx = [i for i, mm in enumerate(months) if mm[0] == yr]
            bad = 0
            for k, (d, v) in enumerate(zip(dids, vals)):
                i = yidx[int(_np.asarray(
                    tbl.column("month"))[k]) - 1]
                j = did_pos[d]
                if _np.abs(float(v) - float(src[j, i])) > 1e-4:
                    bad += 1
            if bad:
                ok = False
                print(f"  W7 round-trip mismatch {rel}: {bad} rows")
                break
    print(f"W7 round-trip: {ok}")
    if not ok:
        fails.append("W7 staging round-trip")

    # W8 is enforced by the chain step above (publish expected exit 3)
    print("W8 X1 publish refusal: enforced by chain (exit 3 expected) - see "
          "[chain] line above")

    if fails:
        print(f"WORLD SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("WORLD SELFTEST PASS (W1-W8)")
    return 0


def _w_dids_of(path):
    import netCDF4 as nc
    d = nc.Dataset(path)
    dids = [str(x) for x in d.variables["district"][:]]
    d.close()
    return dids


if __name__ == "__main__":
    sys.exit(main())
