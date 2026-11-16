#!/usr/bin/env python3
"""DIE v2.0 — gcm-pipeline step 05: SPI/SPEI on corrected-model + reference
grids (task M2.8, docs/v2/03 §3).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9
convention). Resumable + idempotent (manifest work/indices_manifest.json).

SCIENCE IS REUSED VERBATIM from the audited v1.0 module
`data-pipeline/die_pipeline/indicators.py` (the module is imported, not
copied — a change there changes here):

  SPI  (McKee 1993): k-month rolling precipitation totals (complete windows
       only), two-parameter gamma MLE (loc=0) per cell & calendar month,
       mixed distribution H = q + (1-q)G(x) for dry zeros, inverse-normal
       transform.
  SPEI (Vicente-Serrano 2010): monthly water balance D = P - PET accumulated
       over k months, three-parameter log-logistic via L-moments (PWM) —
       MLE deliberately not used; tau3 gate (0.02, 0.98); fallback to the
       tie-aware Gringorten empirical transform when the fit fails its
       self-calibration check (|mean z| <= 0.2, 0.75 <= sd z <= 1.3).
  Fit gate: >= 20 base values per cell-month (config min_base_years = 20);
       failing cell-months stay NaN (absent, never imputed).
  Missing months break rolling windows (v1.0 rule; rolling_sum yields NaN).

Inputs (produced by steps 03/04):
  reference : work/reference/imd_pr_1981-2020.nc + imd_pet_1981-2020.nc
              base period = the full reference window (1981-2020, C2)
  model     : work/qdm/<model>/<tag>/pr_<period>.nc
              + work/pet/<model>/<tag>/pet_<period>.nc
              base period = the model's own corrected record (1981-2014 in
              historical-corrected mode). Note: C2's fixed 1981-2020 window
              is already honoured UPSTREAM by the QDM calibration (step 03);
              this step's base is the available corrected record.

Bounds: era C QA bounds [-5, +5] (config qa.bounds_era_c) applied AFTER the
transform, clip counts recorded in the output attributes. The released era B
record keeps its own +/-4 bounds — untouched (R1).

Outputs:
  work/indices/reference/{spi,spei}_{01,03,06,12}_<period>.nc
  work/indices/<model>/<tag>/{spi,spei}_{01,03,06,12}_<period>.nc
  + per-run fit report inside the file attributes (fits / calibration
    fallbacks / empirical transforms per indicator — the v1.0 gate report).

Self-tests (--selftest, deterministic seed 20261103, synthetic only; wired
into selftest_gcm.py at M2.13) — they call the REAL indicators functions:
  T1 SPI standardisation (seasonal gamma world -> mean~0 sd~1),
  T2 dry-zero handling (zero months never map wet),
  T3 SPEI standardisation (log-logistic world -> mean~0 sd~1),
  T4 fit-gate fallback (degenerate base -> empirical, all-tied -> z~0),
  T5 era-C bounds clip counted,
  T6 NaN-window honesty (missing month breaks the rolling window).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SEED = 20261103
SCALES = (1, 3, 6, 12)

sys.path.insert(0, str(REPO / "data-pipeline"))
indicators = importlib.import_module("die_pipeline.indicators")


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_r03():
    spec = importlib.util.spec_from_file_location(
        "qdm03", HERE / "03_qdm_bias_correct.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ selftest ---
def selftest() -> int:
    hr("SELFTEST — SPI/SPEI on synthetic worlds (real indicators.py functions)")
    rng = np.random.default_rng(SEED)
    fails = []
    # record 1981-2000 (240 months); base 1981-1998 -> 18 base values per
    # calendar month (>= MIN_SAMPLE 8, >= min_years 12 below)
    months = [(y, m) for y in range(1981, 2001) for m in range(1, 13)]
    base_mask = indicators._base_cols(months, (1981, 1998))
    min_years = 12

    # ---- T1 SPI: seasonal gamma world -----------------------------------
    n = len(months)
    cells = 40
    pr = np.full((cells, n), np.nan)
    season = {1: 0.4, 2: 0.5, 3: 0.8, 4: 1.2, 5: 1.6, 6: 3.0, 7: 5.0, 8: 4.5,
              9: 3.0, 10: 1.2, 11: 0.5, 12: 0.3}          # mm/day-ish mean
    for j, (_y, m) in enumerate(months):
        pr[:, j] = rng.gamma(1.2, season[m] * 15.0, cells)
    report = {}
    spi = indicators._apply_per_calendar(
        indicators.rolling_sum(pr, 3), months, base_mask,
        indicators._gamma_spi, min_years, "spi_03", report)
    z = spi[:, base_mask]
    mean, sd = float(np.nanmean(z)), float(np.nanstd(z))
    print(f"T1 SPI gamma world: base mean={mean:+.3f} sd={sd:.3f} "
          f"(report {report['per_indicator']['spi_03']})")
    if abs(mean) > 0.1 or not 0.75 <= sd <= 1.3:
        fails.append("T1 SPI base not standardised")

    # ---- T2 dry zeros never map wet (mixed distribution, q = 6/18) -------
    pr_z = pr.copy()
    zero_years = base_mask & (np.array([y for (y, _m) in months]) <= 1986)
    pr_z[:20, zero_years] = 0.0                 # 6 zeros + 12 positives in base
    spi_z = indicators._apply_per_calendar(
        indicators.rolling_sum(pr_z, 3), months, base_mask,
        indicators._gamma_spi, min_years, "spi_z", {})
    zw = indicators.rolling_sum(pr_z, 3)
    zero_windows = np.isfinite(zw[:20]) & (zw[:20] == 0.0) & base_mask[None, :]
    z_zero = spi_z[:20][zero_windows]
    ok = bool(np.nanmax(z_zero) <= 0.0)
    print(f"T2 dry zeros: n zero-window base months = {zero_windows.sum()}, "
          f"max z = {np.nanmax(z_zero):+.3f} (must be <= 0)")
    if not ok:
        fails.append("T2 zero months mapped wet")

    # ---- T3 SPEI: log-logistic water-balance world -----------------------
    pet = np.full((cells, n), 80.0) + rng.normal(0, 5, (cells, n))
    wb = np.where(np.isfinite(pr) & np.isfinite(pet), pr - pet, np.nan)
    spei = indicators._apply_per_calendar(
        indicators.rolling_sum(wb, 6), months, base_mask,
        indicators._loglogistic_spei, min_years, "spei_06", report)
    z = spei[:, base_mask]
    mean, sd = float(np.nanmean(z)), float(np.nanstd(z))
    print(f"T3 SPEI log-logistic world: base mean={mean:+.3f} sd={sd:.3f}")
    if abs(mean) > 0.15 or not 0.7 <= sd <= 1.4:
        fails.append("T3 SPEI base not standardised")

    # ---- T4 fit-gate fallback: degenerate (all-tied) base -> z ~ 0 -------
    wb_d = wb.copy()
    wb_d[:10] = 5.0                            # perfectly tied base months
    rep_d = {}
    spei_d = indicators._apply_per_calendar(
        indicators.rolling_sum(wb_d, 1), months, base_mask,
        indicators._loglogistic_spei, min_years, "spei_deg", rep_d)
    z_d = spei_d[:10][:, base_mask]
    emp = rep_d["per_indicator"]["spei_deg"]["empirical_transforms"]
    ok = float(np.nanstd(z_d)) < 0.05 and emp > 0
    print(f"T4 degenerate base: sd={float(np.nanstd(z_d)):.4f} (~0), "
          f"empirical fallbacks counted: {emp}")
    if not ok:
        fails.append("T4 fit-gate fallback broken")

    # ---- T5 era-C bounds clip counted ------------------------------------
    lo, hi = -5.0, 5.0
    z5 = np.array([[-6.2, 0.0, 7.1, np.nan]])
    finite5 = z5[np.isfinite(z5)]
    clipped = int(np.sum(finite5 < lo) + np.sum(finite5 > hi))
    z5c = np.clip(z5, lo, hi)
    ok = clipped == 2 and np.nanmax(z5c) == hi and np.isnan(z5c[0, 3])
    print(f"T5 bounds clip: clipped={clipped} (expect 2), NaN preserved: "
          f"{bool(np.isnan(z5c[0, 3]))}")
    if not ok:
        fails.append("T5 bounds/NaN handling broken")

    # ---- T6 NaN window honesty -------------------------------------------
    pr6 = pr.copy()
    pr6[:, 50] = np.nan                        # one missing month breaks windows
    rs = indicators.rolling_sum(pr6, 6)
    broken = rs[:, 50:56]                      # windows ending j=50..55
    ok = bool(np.all(np.isnan(broken)))
    print(f"T6 NaN window: 6-month windows crossing a missing month are all "
          f"NaN: {ok}")
    if not ok:
        fails.append("T6 NaN window honesty broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4, T5, T6)")
    return 0


# ---------------------------------------------------------------- compute ------
def load_pr_pet(pr_path: Path, pet_path: Path):
    r03 = _load_r03()
    pr, dates_p, lat, lon = r03.load_monthly_nc(pr_path, "pr")
    pet, dates_e, _, _ = r03.load_monthly_nc(pet_path, "pet")
    if len(dates_p) != len(dates_e) or any(a.year != b.year or a.month != b.month
                                           for a, b in zip(dates_p, dates_e)):
        sys.exit(f"FATAL: pr/pet time axes disagree ({pr_path.name})")
    months = [(d.year, d.month) for d in dates_p]
    return pr.astype(np.float64), pet.astype(np.float64), months, lat, lon


def compute_indices(pr: np.ndarray, pet: np.ndarray, months, base_years,
                    bounds: tuple) -> dict:
    """SPI/SPEI at scales 1/3/6/12 via the v1.0 indicators machinery.
    Returns {iid: (mat, fit_report_dict)} with mats clipped to bounds.

    The v1.0 drivers are 2-D (series x time); the grid is flattened to
    (lat*lon cells x months) and the results reshaped back — the district
    axis of v1.0 is simply replaced by the cell axis.
    """
    n_time, n_lat, n_lon = pr.shape
    cells = n_lat * n_lon
    pr_f = pr.transpose(1, 2, 0).reshape(cells, n_time)
    pet_f = pet.transpose(1, 2, 0).reshape(cells, n_time)
    base_mask = indicators._base_cols(months, base_years)
    wb_f = np.where(np.isfinite(pr_f) & np.isfinite(pet_f), pr_f - pet_f, np.nan)
    out = {}
    report = {}
    for kind in ("spi", "spei"):
        src = pr_f if kind == "spi" else wb_f
        fitter = (indicators._gamma_spi if kind == "spi"
                  else indicators._loglogistic_spei)
        for k in SCALES:
            iid = f"{kind}_{k:02d}"
            t0 = time.time()
            mat_f = indicators._apply_per_calendar(
                indicators.rolling_sum(src, k), months, base_mask,
                fitter, 20, iid, report)
            finite = np.isfinite(mat_f)
            n_clip = int(np.sum(finite & ((mat_f < bounds[0]) | (mat_f > bounds[1]))))
            mat_f = np.clip(mat_f, bounds[0], bounds[1])
            z = mat_f[finite]
            rep = report["per_indicator"][iid]
            rep["bounds_clipped"] = n_clip
            rep["finite_values"] = int(z.size)
            rep["mean"] = round(float(z.mean()), 4)
            rep["sd"] = round(float(z.std()), 4)
            mat = mat_f.reshape(n_lat, n_lon, n_time).transpose(2, 0, 1)
            out[iid] = (mat.astype(np.float32), rep)
            print(f"    {iid:8s} finite={z.size:8d} mean={z.mean():+.3f} "
                  f"sd={z.std():.3f} clip={n_clip} "
                  f"emp={rep['empirical_transforms']} "
                  f"({time.time() - t0:.0f}s)")
    return out


def write_indices(out_dir: Path, iid: str, period: str, mat: np.ndarray,
                  dates, lat, lon, meta: dict) -> dict:
    import pandas as pd
    import xarray as xr
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{iid}_{period}.nc"
    tstamp = pd.to_datetime([f"{y:04d}-{m:02d}-01" for (y, m) in dates])
    ds = xr.Dataset({iid: (("time", "lat", "lon"), mat)},
                    coords={"time": tstamp, "lat": lat, "lon": lon},
                    attrs={**meta, "pipeline":
                           "DIE v2.0 gcm-pipeline 05_spi_spei_compute.py "
                           "(indicators.py reused verbatim)"})
    ds.to_netcdf(out_path, encoding={iid: {"dtype": "float32", "zlib": True,
                                           "complevel": 4}})
    return {"iid": iid, "out": str(out_path.relative_to(out_dir.parent.parent)),
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}


def run_target(pr_path: Path, pet_path: Path, out_dir: Path,
               base_years: tuple, bounds: tuple, label: str) -> list:
    pr, pet, months, lat, lon = load_pr_pet(pr_path, pet_path)
    period = f"{months[0][0]}-{months[-1][0]}"
    meta_base = {
        "label": label,
        "base_period": f"{base_years[0]}-{base_years[1]}",
        "era_c_bounds": f"[{bounds[0]}, {bounds[1]}]",
        "spi_method": "gamma MLE (loc=0) + mixed zeros (McKee 1993 convention)",
        "spei_method": "log-logistic L-moments (Vicente-Serrano 2010); "
                       "Gringorten empirical fallback",
        "fit_gate": ">= 20 base values per cell-calendar-month",
        "source_note": "IMD 0.25deg reference / QDM-corrected model "
                       "(step 03) + Hargreaves PET (step 04)",
    }
    hr(f"INDICES {label} — {len(months)} months {period}, "
       f"base {base_years[0]}-{base_years[1]}")
    results = compute_indices(pr, pet, months, base_years, bounds)
    records = []
    for iid, (mat, rep) in results.items():
        meta = {**meta_base, "fit_report": json.dumps(rep)}
        rec = write_indices(out_dir, iid, period, mat, months, lat, lon, meta)
        rec.update({"label": label, "iid": iid, "period": period,
                    "fit_report": rep, "status": "ok"})
        records.append(rec)
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="SPI/SPEI on grids (M2.8)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reference", action="store_true",
                    help="compute IMD reference indices (1981-2020)")
    ap.add_argument("--models", help="comma list (default: era-C ensemble)")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--experiments", default=None,
                    help="ssp mode: comma list (default ssp245,ssp585)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    paths = load_yaml(HERE / "config" / "paths.yaml")
    ref_cfg = load_yaml(HERE / "config" / "reference.yaml")
    cfg = load_yaml(HERE / "config" / "models.yaml")
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    bounds = tuple(ref_cfg["qa"]["bounds_era_c"])
    man_path = work_root / "indices_manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else \
        {"schema": 1, "files": {}}
    all_recs = []

    if args.reference:
        all_recs.extend(run_target(
            work_root / "reference" / "imd_pr_1981-2020.nc",
            work_root / "reference" / "imd_pet_1981-2020.nc",
            work_root / "indices" / "reference", (1981, 2020), bounds,
            "reference IMD"))
    else:
        models = args.models.split(",") if args.models else \
            [r["source_id"] for r in cfg["models"]
             if r.get("era_c_ensemble", True)]
        experiments = (args.experiments.split(",") if args.experiments else
                       (["historical"] if args.mode == "historical-corrected"
                        else ["ssp245", "ssp585"]))
        hr(f"INDICES — mode={args.mode} models={len(models)} "
           f"bounds={bounds}")
        for model in models:
            tags = ["historical-corrected"] if args.mode == "historical-corrected" \
                else experiments
            for tag in tags:
                pr_path = work_root / "qdm" / model / tag / "pr_1981-2014.nc" \
                    if args.mode == "historical-corrected" else \
                    work_root / "qdm" / model / tag / f"pr_2015-2100.nc"
                pet_path = work_root / "pet" / model / tag / "pet_1981-2014.nc" \
                    if args.mode == "historical-corrected" else \
                    work_root / "pet" / model / tag / f"pet_2015-2100.nc"
                if not pr_path.exists() or not pet_path.exists():
                    print(f"  SKIP {model}/{tag}: pr/pet inputs missing")
                    continue
                recs = run_target(pr_path, pet_path,
                                  work_root / "indices" / model / tag,
                                  (1981, 2014), bounds, f"{model}/{tag}")
                all_recs.extend(recs)

    for r in all_recs:
        key = (f"reference/{r['iid']}" if r["label"] == "reference IMD"
               else f"{r['label']}/{r['iid']}")
        manifest["files"][key] = {
            "out": r["out"], "period": r["period"],
            "fit_report": r["fit_report"], "sha256": r["sha256"]}
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"INDICES DONE: {len(all_recs)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
