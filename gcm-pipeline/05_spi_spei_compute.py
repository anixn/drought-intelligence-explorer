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
# Config-dir override (M2.13 phase 2): selftest_gcm.py points every step
# at a test config dir via DIE_CONFIG_DIR; default = the real config dir
# so production behaviour is untouched (documented in docs/v2/03 s3.11).
import os as _os
CONFIG_DIR = Path(_os.environ.get("DIE_CONFIG_DIR",
                                        str(HERE / "config")))

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

    # ---- T7 ssp stitch: baseline fitting on hist+ssp (F1 regression) ------
    # Production shape: historical-corrected 1981-2014 + ssp 2015-2100.
    # Review finding F1: fitting the ssp record alone passes (1981, 2014)
    # as the base window - zero base values per calendar month - so the
    # >= 20-value gate fails for EVERY calendar month and all-NaN index
    # files would exit 0. The committed seam (AS6) is to stitch and fit on
    # the model baseline 1981-2020.
    months_h7 = [(y, m) for y in range(1981, 2015) for m in range(1, 13)]
    months_s7 = [(y, m) for y in range(2015, 2101) for m in range(1, 13)]
    n_h7, n_s7 = len(months_h7), len(months_s7)
    rng7 = np.random.default_rng(SEED + 7)
    # 3-D grid layout (time, lat, lon) as produced by load_pr_pet
    pr_h7 = rng7.gamma(1.2, 40.0, (n_h7, 2, 4))
    pr_s7 = rng7.gamma(1.2, 40.0, (n_s7, 2, 4))
    pet_h7 = np.full((n_h7, 2, 4), 80.0) + rng7.normal(0, 5, (n_h7, 2, 4))
    pet_s7 = np.full((n_s7, 2, 4), 80.0) + rng7.normal(0, 5, (n_s7, 2, 4))
    # a) seam validation catches defects loudly
    seam_errors = 0
    for bad in ("gap", "month"):
        try:
            if bad == "gap":
                stitch_hist_ssp(pr_h7, pet_h7, months_h7[:-1],
                                pr_s7, pet_s7, months_s7)
            else:
                stitch_hist_ssp(pr_h7, pet_h7, months_h7,
                                pr_s7, pet_s7, months_s7[1:])
        except SystemExit:
            seam_errors += 1
    # b) the stitched fit produces finite ssp-segment values, base ~ N(0,1)
    pr7, pet7, months7 = stitch_hist_ssp(pr_h7, pet_h7, months_h7,
                                         pr_s7, pet_s7, months_s7)
    res7 = compute_indices(pr7, pet7, months7, (1981, 2020), (-5.0, 5.0))
    ssp_mask7 = np.array([y >= 2015 for (y, _m) in months7])
    spi7 = res7["spi_03"][0][ssp_mask7]
    finite_frac = float(np.isfinite(spi7).mean())
    base7 = res7["spi_03"][0][~ssp_mask7]
    mean_b, sd_b = float(np.nanmean(base7)), float(np.nanstd(base7))
    # c) document the old failure mode: ssp-only series + base (1981, 2014)
    # leaves zero base values per calendar month -> all-NaN output
    rep_only = {}
    pr_only = pr7[-n_s7:].transpose(1, 2, 0).reshape(8, n_s7)
    only = indicators._apply_per_calendar(
        indicators.rolling_sum(pr_only, 3), months_s7,
        indicators._base_cols(months_s7, (1981, 2014)),
        indicators._gamma_spi, 20, "spi_ssp_only", rep_only)
    n_finite_only = int(np.isfinite(only).sum())
    insuff = sum(1 for s in rep_only.get("insufficient_base_months", [])
                 if "spi_ssp_only" in s)
    ok7 = (seam_errors == 2 and finite_frac > 0.95 and n_finite_only == 0
           and insuff == 12 and abs(mean_b) <= 0.2 and 0.7 <= sd_b <= 1.4)
    print(f"T7 ssp stitch: seam rejections={seam_errors}/2, ssp finite "
          f"frac={finite_frac:.3f}, base mean={mean_b:+.3f} sd={sd_b:.3f}; "
          f"ssp-only fit (F1 failure mode) finite={n_finite_only} "
          f"(must be 0), insufficient-month notes={insuff}/12")
    if not ok7:
        fails.append("T7 ssp stitch baseline broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4, T5, T6, T7)")
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


def stitch_hist_ssp(pr_h, pet_h, months_h, pr_s, pet_s, months_s):
    """Seam-validated stitch of the historical-corrected record (1981-2014)
    and an ssp record (2015-2100) into ONE continuous (pr, pet, months)
    series, so indices can be fitted on the model baseline 1981-2020
    (C2 + AS6: reference.yaml scenario_combo_note - "model baseline
    1981-2020 = historical 1981-2014 combined with ssp 2015-2020").

    WHY THIS EXISTS (review finding F1, 2026-11-17): fitting the ssp record
    alone leaves ZERO base values per calendar month (the baseline years
    live in the historical file, not the ssp file) - every calendar month
    then fails the >= 20-value fit gate in indicators._apply_per_calendar
    and step 05 emitted all-NaN index files with exit 0. Stitching also
    gives the ssp SPI-12/SPEI-12 columns complete rolling windows instead
    of warm-up NaNs. Fails loudly (SystemExit) on any seam defect."""
    if not months_h or not months_s:
        sys.exit("FATAL: stitch called with an empty record")
    if (months_h[-1][1], months_s[0][1]) != (12, 1):
        sys.exit(f"FATAL: stitch seam expects historical ending Dec and ssp "
                 f"starting Jan (got hist {months_h[-1]}, ssp {months_s[0]})")
    if months_s[0][0] != months_h[-1][0] + 1:
        sys.exit(f"FATAL: stitch gap/overlap: hist ends {months_h[-1]}, "
                 f"ssp starts {months_s[0]}")
    pr = np.concatenate([pr_h, pr_s], axis=0)
    pet = np.concatenate([pet_h, pet_s], axis=0)
    return pr, pet, months_h + months_s


def run_target_ssp(work_root: Path, model: str, exp: str,
                   base: tuple, bounds: tuple, label: str) -> list:
    """ssp-mode indices per (model, experiment): load the QDM-corrected
    historical (1981-2014) and ssp (2015-2100) files, STITCH them (AS6),
    fit on the fixed model baseline 1981-2020 (C2), and write ONLY the ssp
    segment (period label = the ssp record's own year range)."""
    import pandas as pd
    import xarray as xr
    qdm_h_all = sorted((work_root / "qdm" / model
                        / "historical-corrected").glob("pr_*.nc"))
    pet_h_all = sorted((work_root / "pet" / model
                        / "historical-corrected").glob("pet_*.nc"))
    qdm_s_all = sorted((work_root / "qdm" / model / exp).glob("pr_*.nc"))
    pet_s_all = sorted((work_root / "pet" / model / exp).glob("pet_*.nc"))
    # one corrected record per tag by construction; anything else is a
    # fabric problem -> refuse loudly. Periods are derived from the data
    # (e.g. ssp 2015-2050 while the download is partial) — never assumed.
    if len(qdm_h_all) != 1 or len(pet_h_all) != 1 or \
            len(qdm_s_all) != 1 or len(pet_s_all) != 1:
        print(f"  SKIP {label}: missing or ambiguous stitched-fit inputs "
              f"({len(qdm_h_all)}/{len(pet_h_all)}/{len(qdm_s_all)}/"
              f"{len(pet_s_all)} files) - run 03/04 in both modes first")
        return []
    qdm_h, pet_h = qdm_h_all[0], pet_h_all[0]
    qdm_s, pet_s = qdm_s_all[0], pet_s_all[0]
    pr_h, pet_h2, months_h, lat, lon = load_pr_pet(qdm_h, pet_h)
    pr_s, pet_s2, months_s, _, _ = load_pr_pet(qdm_s, pet_s)
    pr, pet, months = stitch_hist_ssp(pr_h, pet_h2, months_h,
                                      pr_s, pet_s2, months_s)
    period = f"{months_s[0][0]}-{months_s[-1][0]}"
    hr(f"INDICES {label} (ssp, stitched) — {len(months)} months "
       f"{months[0][0]}-{months[-1][0]}, base {base[0]}-{base[1]} (C2+AS6)")
    results = compute_indices(pr, pet, months, base, bounds)
    ssp_from = months_s[0][0]
    ssp_mask = np.array([y >= ssp_from for (y, _m) in months])
    months_out = [mm for mm, keep in zip(months, ssp_mask) if keep]
    meta_base = {
        "label": label,
        "base_period": f"{base[0]}-{base[1]} (stitched model baseline: "
                       "historical 1981-2014 + "
                       f"{exp} {ssp_from}-{base[1]}; C2+AS6)",
        "era_c_bounds": f"[{bounds[0]}, {bounds[1]}]",
        "spi_method": "gamma MLE (loc=0) + mixed zeros (McKee 1993 convention)",
        "spei_method": "log-logistic L-moments (Vicente-Serrano 2010); "
                       "Gringorten empirical fallback",
        "fit_gate": ">= 20 base values per cell-calendar-month",
        "source_note": "IMD 0.25deg reference / QDM-corrected model "
                       "(step 03) + Hargreaves PET (step 04); ssp segment "
                       "of a continuous stitched series",
    }
    out_dir = work_root / "indices" / model / exp
    records = []
    for iid, (mat, rep) in results.items():
        meta = {**meta_base, "fit_report": json.dumps(rep)}
        rec = write_indices(out_dir, iid, period, mat[ssp_mask], months_out,
                            lat, lon, meta)
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

    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    ref_cfg = load_yaml(CONFIG_DIR / "reference.yaml")
    cfg = load_yaml(CONFIG_DIR / "models.yaml")
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
        if args.mode == "historical-corrected":
            for model in models:
                pr_path = (work_root / "qdm" / model
                           / "historical-corrected" / "pr_1981-2014.nc")
                pet_path = (work_root / "pet" / model
                            / "historical-corrected" / "pet_1981-2014.nc")
                if not pr_path.exists() or not pet_path.exists():
                    print(f"  SKIP {model}: pr/pet inputs missing")
                    continue
                recs = run_target(pr_path, pet_path,
                                  work_root / "indices" / model
                                  / "historical-corrected",
                                  (1981, 2014), bounds,
                                  f"{model}/historical-corrected")
                all_recs.extend(recs)
        else:
            # ssp mode: fit on the STITCHED model baseline 1981-2020
            # (C2 + AS6) - never on the ssp record alone (finding F1:
            # that leaves zero base values per calendar month, the fit
            # gate fails silently, and all-NaN indices exit 0).
            base = tuple(ref_cfg.get("calibration_window", [1981, 2020]))
            for model in models:
                for exp in experiments:
                    all_recs.extend(
                        run_target_ssp(work_root, model, exp, base,
                                       bounds, f"{model}/{exp}"))

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
