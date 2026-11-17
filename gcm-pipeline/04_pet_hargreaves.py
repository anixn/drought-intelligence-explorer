#!/usr/bin/env python3
"""DIE v2.0 — gcm-pipeline step 04: Hargreaves PET (task M2.7, docs/v2/03 §3).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9
convention, docs/v2/06 §5). Resumable + idempotent (manifest work/pet_manifest.json,
SHA-256).

Method — Hargreaves–Samani (1985), committed decision C3 and applied
IDENTICALLY to reference and model data (register resolution E):

    PET_mm_day = Ch * Ra * (Tmean + To) * sqrt(max(Tmax - Tmin, 0))

  Ra      : extraterrestrial daily radiation (FAO-56 eqs 21-25) evaluated at
            the mid-month day (day = round(days_in_month/2)) on the
            proleptic-Gregorian axis, per grid-cell latitude,
  Tmean   : (monthly mean Tmax + monthly mean Tmin) / 2,
  Ch, To  : 0.0023, 17.8 degC            (config/reference.yaml `pet:` block)
  monthly : PET_mm_month = PET_mm_day * days_in_month (standard calendar of
            the output time axis).

Inputs (produced by steps 02/03):
  model   : work/qdm/<model>/<mode>/tasmax_<period>.nc + tasmin_<period>.nc
  reference: work/reference/imd_tasmax_1981-2020.nc + imd_tasmin_1981-2020.nc
             (--reference -> work/reference/imd_pet_1981-2020.nc)

Guards (counts recorded in the output attributes):
  Tmax < Tmin  -> PET NaN for that cell-month (physically invalid; R10).
  PET < 0      -> clipped at 0, counted (possible only if Tmean < -17.8 degC).
  Missing tas  -> NaN (absent, never imputed).

Mandatory self-tests (--selftest, deterministic seed 20261103, synthetic only;
wired into selftest_gcm.py at M2.13):
  T1 Ra formula: equator/equinox vs the theoretical top-of-atmosphere value
     (1367 W m-2 * 86400 s / pi), and 45N mid-July vs an independent hand
     computation of the FAO-56 equations.
  T2 Hargreaves arithmetic: hand-computed PET for fixed inputs reproduced
     exactly; monotone in (Tmean + To) and in sqrt(dT).
  T3 invalid guard: Tmax < Tmin -> NaN + counted.
  T4 seasonal sanity: synthetic Indian-plateau temperatures give peak PET in
     the pre-monsoon month (May), not at the June solstice.
  T5 units: monthly PET = daily * days_in_month.

Usage:
  python 04_pet_hargreaves.py --selftest
  python 04_pet_hargreaves.py --reference                 # IMD PET (1981-2020)
  python 04_pet_hargreaves.py --mode historical-corrected --models ACCESS-CM2
  python 04_pet_hargreaves.py --mode ssp --models ...     # after phase-2 downloads
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
# Config-dir override (M2.13 phase 2): selftest_gcm.py points every step
# at a test config dir via DIE_CONFIG_DIR; default = the real config dir
# so production behaviour is untouched (documented in docs/v2/03 s3.11).
import os as _os
CONFIG_DIR = Path(_os.environ.get("DIE_CONFIG_DIR",
                                        str(HERE / "config")))

SEED = 20261103


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_r02():
    spec = importlib.util.spec_from_file_location(
        "regrid025", HERE / "02_regrid_025.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_r03():
    spec = importlib.util.spec_from_file_location(
        "qdm03", HERE / "03_qdm_bias_correct.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------- Ra ---------
def extraterrestrial_ra(lat_deg: np.ndarray, j: int, gsc: float) -> np.ndarray:
    """FAO-56 eqs 21-25: daily extraterrestrial radiation (MJ m-2 day-1) at
    latitude(s) lat_deg for day-of-year j."""
    phi = np.deg2rad(np.asarray(lat_deg, float))
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)
    delta = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)
    x = -np.tan(phi) * np.tan(delta)
    ws = np.arccos(np.clip(x, -1.0, 1.0))
    ra = ((24.0 * 60.0) / np.pi) * gsc * dr * (
        ws * np.sin(phi) * np.sin(delta)
        + np.cos(phi) * np.cos(delta) * np.sin(ws))
    return ra


# ---------------------------------------------------------------- PET core ------
def hargreaves_pet(tasmax: np.ndarray, tasmin: np.ndarray, lat_deg: np.ndarray,
                   year: int, month: int, pet_cfg: dict) -> tuple:
    """Monthly PET (mm) for ONE month over a (time-free) 2-D field.
    tasmax/tasmin: monthly-mean fields (degC), shape (n_lat, n_lon).
    Returns (pet_mm, diag) with diag = {"invalid_dt": n, "clipped_neg": n}."""
    ch = float(pet_cfg["coefficient_ch"])
    to = float(pet_cfg["coefficient_temp_offset"])
    gsc = float(pet_cfg["solar_constant_mj_m2_min"])
    lh = float(pet_cfg["latent_heat_mj_per_kg"])
    n_days = calendar.monthrange(year, month)[1]
    mid_day = int(round(n_days / 2.0))
    j = sum(calendar.monthrange(year, m)[1] for m in range(1, month)) + mid_day
    ra = extraterrestrial_ra(lat_deg, j, gsc)             # (n_lat,) MJ m-2 d-1
    ra_mm = ra / lh                                       # mm/day equivalent
    d_t = tasmax - tasmin
    invalid = d_t < 0
    diag = {"invalid_dt": int(invalid.sum()), "clipped_neg": 0}
    tmean = 0.5 * (tasmax + tasmin)
    with np.errstate(invalid="ignore", divide="ignore"):
        pet_day = ch * ra_mm[:, None] * (tmean + to) * np.sqrt(np.maximum(d_t, 0.0))
    neg = np.isfinite(pet_day) & (pet_day < 0)
    diag["clipped_neg"] = int(neg.sum())
    pet_day = np.where(neg, 0.0, pet_day)
    pet_day = np.where(invalid, np.nan, pet_day)
    return pet_day * n_days, diag


# ---------------------------------------------------------------- selftest ------
def selftest() -> int:
    hr("SELFTEST — Hargreaves PET on synthetic worlds (seed 20261103)")
    pet_cfg = load_yaml(CONFIG_DIR / "reference.yaml")["pet"]
    gsc = float(pet_cfg["solar_constant_mj_m2_min"])
    fails = []

    # T1a — equator/equinox vs top-of-atmosphere theory
    ra_eq = float(extraterrestrial_ra(np.array([0.0]), 81, gsc)[0])
    theory = 1367.0 * 86400.0 / 1e6 / np.pi                # MJ m-2 d-1
    rel = abs(ra_eq - theory) / theory
    print(f"T1a Ra equator/equinox: {ra_eq:.3f} vs theory {theory:.3f} "
          f"MJ m-2 d-1 (rel {rel:.3e})")
    if rel > 0.01:
        fails.append("T1a Ra equator beyond 1% of theory")

    # T1b — 45N, 15 July vs independent hand computation of FAO-56 equations
    ra_45 = float(extraterrestrial_ra(np.array([45.0]), 196, gsc)[0])
    dr = 1 + 0.033 * np.cos(2 * np.pi * 196 / 365)
    delta = 0.409 * np.sin(2 * np.pi * 196 / 365 - 1.39)
    ws = np.arccos(-np.tan(np.deg2rad(45)) * np.tan(delta))
    hand = (1440 / np.pi) * gsc * dr * (
        ws * np.sin(np.deg2rad(45)) * np.sin(delta)
        + np.cos(np.deg2rad(45)) * np.cos(delta) * np.sin(ws))
    diff = abs(ra_45 - hand)
    print(f"T1b Ra 45N/15-July: {ra_45:.3f} vs hand {hand:.3f} (diff {diff:.2e})")
    if diff > 1e-9:
        fails.append("T1b Ra 45N disagrees with hand computation")

    # T2 — arithmetic: fixed Ra, hand-computed PET
    lat = np.array([22.5])
    tx = np.full((1, 1), 35.0)
    tn = np.full((1, 1), 20.0)
    pet, diag = hargreaves_pet(tx, tn, lat, 2002, 7, pet_cfg)
    # independent hand value: Ra(22.5N, J mid-July 2002 = 197) = ?
    ra_hand = extraterrestrial_ra(np.array([22.5]), 197, gsc)[0]
    expected = 0.0023 * (ra_hand / 2.45) * (27.5 + 17.8) * np.sqrt(15.0) * 31
    diff = abs(pet[0, 0] - expected)
    print(f"T2 arithmetic: PET={pet[0, 0]:.3f} vs hand {float(expected):.3f} "
          f"(diff {diff:.2e}), invalid_dt={diag['invalid_dt']}")
    if diff > 1e-9:
        fails.append("T2 Hargreaves arithmetic mismatch")
    # monotonicity in sqrt(dT) and (Tmean + To)
    pet_small_d, _ = hargreaves_pet(np.full((1, 1), 30.0), np.full((1, 1), 20.0),
                                    lat, 2002, 7, pet_cfg)
    if not pet[0, 0] > pet_small_d[0, 0]:
        fails.append("T2 monotonicity in dT broken")

    # T3 — invalid guard: Tmax < Tmin
    pet_bad, diag_bad = hargreaves_pet(np.full((1, 1), 10.0), np.full((1, 1), 20.0),
                                       lat, 2002, 1, pet_cfg)
    ok = bool(np.isnan(pet_bad[0, 0])) and diag_bad["invalid_dt"] == 1
    print(f"T3 invalid dT: PET is NaN: {ok}, counted: {diag_bad['invalid_dt']}")
    if not ok:
        fails.append("T3 invalid-dT guard broken")

    # T4 — seasonal sanity: synthetic Indian-plateau temperatures peak PET in
    # the pre-monsoon month (May), not at the June solstice
    months = np.arange(1, 13)
    tmax_m = np.array([28, 31, 35, 38, 39, 35, 30, 30, 31, 32, 30, 28], float)
    tmin_m = np.array([14, 17, 21, 25, 27, 25, 24, 24, 23, 20, 17, 14], float)
    pets = [hargreaves_pet(tmax_m[m - 1][None, None], tmin_m[m - 1][None, None],
                           lat, 2002, int(m), pet_cfg)[0][0, 0] for m in months]
    peak = int(months[int(np.argmax(pets))])
    print(f"T4 seasonal: PET by month = "
          + " ".join(f"{m}:{p:.0f}" for m, p in zip(months, pets))
          + f"; peak month = {peak} (expect 5 = pre-monsoon)")
    if peak != 5:
        fails.append("T4 pre-monsoon PET peak not reproduced")

    # T5 — units: February (28 days, low Ra) vs March (31 days, higher Ra) at
    # equal temperature inputs: monthly ratio = (Ra_feb/Ra_mar) * 28/31.
    pet_feb, _ = hargreaves_pet(tx, tn, lat, 2002, 2, pet_cfg)
    pet_mar, _ = hargreaves_pet(tx, tn, lat, 2002, 3, pet_cfg)
    ra_feb = float(extraterrestrial_ra(lat, 31 + 14, gsc)[0])   # mid-Feb DOY 45
    ra_mar = float(extraterrestrial_ra(lat, 59 + 16, gsc)[0])   # mid-Mar DOY 75
    expected_ratio = (ra_feb / ra_mar) * (28.0 / 31.0)
    ratio = pet_feb[0, 0] / pet_mar[0, 0]
    print(f"T5 units: PET(Feb)/PET(Mar) = {ratio:.4f} vs expected "
          f"(Ra_feb/Ra_mar)*28/31 = {expected_ratio:.4f}")
    if abs(ratio - expected_ratio) > 0.01 * expected_ratio:
        fails.append("T5 monthly scaling mismatch")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1a, T1b, T2, T3, T4, T5)")
    return 0


# --------------------------------------------------------------------- run ------
def compute_pet_stack(tasmax: np.ndarray, tasmin: np.ndarray, dates,
                      lat_deg: np.ndarray, pet_cfg: dict) -> tuple:
    """PET (mm/month) for a (time, lat, lon) stack + guard totals."""
    pet = np.full(tasmax.shape, np.nan, dtype=np.float32)
    totals = {"invalid_dt": 0, "clipped_neg": 0}
    for k, d in enumerate(dates):
        p, diag = hargreaves_pet(tasmax[k].astype(np.float64),
                                 tasmin[k].astype(np.float64),
                                 lat_deg, int(d.year), int(d.month), pet_cfg)
        pet[k] = p
        totals["invalid_dt"] += diag["invalid_dt"]
        totals["clipped_neg"] += diag["clipped_neg"]
    return pet, totals


def run_reference(work_root: Path) -> list:
    """IMD reference tmax/tmin -> IMD PET on the target grid."""
    ref_cfg = load_yaml(CONFIG_DIR / "reference.yaml")
    pet_cfg = ref_cfg["pet"]
    r03 = _load_r03()
    import pandas as pd
    import xarray as xr
    tx_path = work_root / "reference" / "imd_tasmax_1981-2020.nc"
    tn_path = work_root / "reference" / "imd_tasmin_1981-2020.nc"
    for p in (tx_path, tn_path):
        if not p.exists():
            sys.exit(f"FATAL: {p} missing — run 03 --prepare-reference first")
    tx, dates, lat, lon = r03.load_monthly_nc(tx_path, "tasmax")
    tn, dates2, _, _ = r03.load_monthly_nc(tn_path, "tasmin")
    if len(dates) != len(dates2) or any(a.year != b.year or a.month != b.month
                                        for a, b in zip(dates, dates2)):
        sys.exit("FATAL: reference tasmax/tasmin time axes disagree")
    t0 = time.time()
    pet, totals = compute_pet_stack(tx, tn, dates, lat, pet_cfg)
    out_dir = work_root / "reference"
    out_path = out_dir / "imd_pet_1981-2020.nc"
    tstamp = pd.to_datetime([f"{d.year:04d}-{d.month:02d}-01" for d in dates])
    ds = xr.Dataset({"pet": (("time", "lat", "lon"), pet)},
                    coords={"time": tstamp, "lat": lat, "lon": lon},
                    attrs={"method": pet_cfg["method"],
                           "equation": pet_cfg["equation"],
                           "source": "IMD 0.25deg tmax/tmin (Srivastava et al. 2009)",
                           "guards": json.dumps(totals),
                           "pipeline": "DIE v2.0 gcm-pipeline 04_pet_hargreaves.py"})
    ds.to_netcdf(out_path, encoding={"pet": {"dtype": "float32", "zlib": True,
                                             "complevel": 4}})
    rec = {"var": "pet", "status": "ok", "source": "reference",
           "out": str(out_path.relative_to(work_root)), "n_time": len(dates),
           "guards": totals, "seconds": round(time.time() - t0, 1),
           "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
    print(f"  OK reference PET: {rec['n_time']} months 1981-2020 "
          f"invalidDt={totals['invalid_dt']} clipNeg={totals['clipped_neg']} "
          f"({rec['seconds']}s) -> {out_path.name}")
    return [rec]


def run_model(model: str, mode: str, variables_unused, work_root: Path,
              experiments: list) -> list:
    """Model corrected tmax/tmin -> PET (one file per experiment tag)."""
    ref_cfg = load_yaml(CONFIG_DIR / "reference.yaml")
    pet_cfg = ref_cfg["pet"]
    r03 = _load_r03()
    import pandas as pd
    import xarray as xr
    records = []
    for exp in experiments:
        tag = ("historical-corrected" if mode == "historical-corrected" else exp)
        tx_path = work_root / "qdm" / model / tag / "tasmax_1981-2014.nc"
        tn_path = work_root / "qdm" / model / tag / "tasmin_1981-2014.nc"
        if not tx_path.exists() or not tn_path.exists():
            print(f"  SKIP {model}/{tag}: corrected tasmax/tasmin missing "
                  f"(run 03 first)")
            continue
        tx, dates, lat, lon = r03.load_monthly_nc(tx_path, "tasmax")
        tn, dates2, _, _ = r03.load_monthly_nc(tn_path, "tasmin")
        if len(dates) != len(dates2) or any(a.year != b.year or a.month != b.month
                                            for a, b in zip(dates, dates2)):
            sys.exit(f"FATAL: {model}/{tag} tasmax/tasmin time axes disagree")
        t0 = time.time()
        pet, totals = compute_pet_stack(tx, tn, dates, lat, pet_cfg)
        out_dir = work_root / "pet" / model / tag
        out_dir.mkdir(parents=True, exist_ok=True)
        period = f"{dates[0].year}-{dates[-1].year}"
        out_path = out_dir / f"pet_{period}.nc"
        tstamp = pd.to_datetime([f"{d.year:04d}-{d.month:02d}-01" for d in dates])
        ds = xr.Dataset({"pet": (("time", "lat", "lon"), pet)},
                        coords={"time": tstamp, "lat": lat, "lon": lon},
                        attrs={"source_id": model, "mode": tag,
                               "method": pet_cfg["method"],
                               "equation": pet_cfg["equation"],
                               "identical_application_note":
                                   "C3/E: same Hargreaves equations applied to "
                                   "reference and model temperature",
                               "guards": json.dumps(totals),
                               "pipeline": "DIE v2.0 gcm-pipeline "
                                           "04_pet_hargreaves.py"})
        ds.to_netcdf(out_path, encoding={"pet": {"dtype": "float32", "zlib": True,
                                                 "complevel": 4}})
        rec = {"model": model, "mode": tag, "var": "pet", "status": "ok",
               "out": str(out_path.relative_to(work_root)), "period": period,
               "n_time": len(dates), "guards": totals,
               "seconds": round(time.time() - t0, 1),
               "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
        records.append(rec)
        print(f"  OK {model:18s} {tag:22s} pet    {rec['n_time']:4d} months "
              f"{period} invalidDt={totals['invalid_dt']} "
              f"clipNeg={totals['clipped_neg']} ({rec['seconds']}s)")
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="Hargreaves PET (M2.7)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reference", action="store_true",
                    help="compute IMD reference PET (1981-2020)")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--models", help="comma list (default: all config models)")
    ap.add_argument("--experiments", default=None,
                    help="ssp mode: comma list (default ssp245,ssp585)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    cfg = load_yaml(CONFIG_DIR / "models.yaml")
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    man_path = work_root / "pet_manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else \
        {"schema": 1, "files": {}}

    all_recs = []
    if args.reference:
        all_recs.extend(run_reference(work_root))
    models = args.models.split(",") if args.models else \
        [r["source_id"] for r in cfg["models"]]
    experiments = (args.experiments.split(",") if args.experiments else
                   (["historical"] if args.mode == "historical-corrected"
                    else ["ssp245", "ssp585"]))
    if not args.reference:
        hr(f"PET — mode={args.mode} models={len(models)}")
        for model in models:
            all_recs.extend(run_model(model, args.mode, None, work_root,
                                      experiments))
    for r in all_recs:
        key = f"reference/pet" if r.get("source") == "reference" \
            else f"{r['model']}/{r['mode']}"
        manifest["files"][key] = r
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"PET DONE: {len(all_recs)} output(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
