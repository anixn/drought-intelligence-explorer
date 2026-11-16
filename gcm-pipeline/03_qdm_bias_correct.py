#!/usr/bin/env python3
"""DIE v2.0 — gcm-pipeline step 03: QDM bias correction (task M2.6, docs/v2/03 §3.5).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9
convention). Resumable + idempotent (manifest work/qdm_manifest.json, SHA-256).

Method — Quantile Delta Mapping (Cannon et al. 2015), per grid cell, per
calendar month, on MONTHLY values (docs/v2/03 §3.5; decisions C1/C2/C3):
  - calibration (fixed 1981–2020, C2):
      reference  : IMD monthly on the 0.25° target grid (--prepare-reference),
      model hist : regridded model historical 1981–2014 COMBINED with the
                   2015–2020 scenario slice (one consistent model baseline),
  - for each model value x in the projection period:
      τ          = non-exceedance probability of x within the model's own
                   projected-period distribution (Gringorten plotting
                   position — continuity with v1.0),
      Δ          = x / Q_model,hist(τ)   (pr — multiplicative)
                 | x − Q_model,hist(τ)  (tas — additive),
      corrected  = Q_ref(τ) · Δ          (pr)
                 | Q_ref(τ) + Δ         (tas).
  - guards: pr zero-guard (Q_ref(τ) = 0 ⇒ corrected 0; Δ undefined when
    Q_model,hist(τ) = 0 and x ≠ 0 ⇒ Δ := 1, counted); physical range pr
    0–4,000 mm/month, tas −60…+60 °C (clips counted).
  - fit gate: ≥ 20 finite base years for BOTH the reference and the model
    calibration series per cell-month (v1.0 discipline); failing cells stay
    NaN (absent, never imputed).
  - era-C SPI/SPEI bounds [−5, +5] are applied later at step 05.

Modes:
  --prepare-reference          IMD daily NetCDFs -> monthly reference on the
                               target grid: work/reference/imd_<var>_<y0>-<y1>.nc
  --mode historical-corrected  corrected model HISTORICAL (projection sample =
                               the historical sample itself; no change
                               signal) — the X5/E17 product. Needs NO SSP data.
  --mode ssp                   full era C: needs model ssp 2015–2020 regridded
                               months for the calibration baseline — hard-fails
                               honestly if absent (phase-2 downloads).

Mandatory implementation tests (--selftest, deterministic seed 20261103,
synthetic only — §3.5; wired into selftest_gcm.py at M2.13):
  T1 identity (model = reference ⇒ output = reference; multiplicative + additive),
  T2 trend preservation (synthetic warming/drying signals survive correction),
  T3 quantile inversion (no change signal ⇒ corrected ≈ Qref at the same
     plotting positions),
  T4 pr zero-guard, T5 range guard.

Output: work/qdm/<model>/<tag>/<variable>_<period>.nc   (one file per variable)
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
SEED = 20261103
PR_RANGE = (0.0, 4000.0)          # mm/month physical guard (v1.0 rule)
TAS_RANGE = (-60.0, 60.0)         # degC sanity guard
CAL_WINDOW = (1981, 2020)         # C2, fixed
MIN_BASE_YEARS = 20               # fit gate (v1.0 discipline)


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def gringorten(n: int) -> np.ndarray:
    """Gringorten plotting positions (r-0.375)/(n+0.25) for ranks 1..n."""
    return (np.arange(1, n + 1) - 0.375) / (n + 0.25)


# ------------------------------------------------------------------ QDM core ---
def qdm_apply(ref_hist: np.ndarray, model_hist: np.ndarray, model_proj: np.ndarray,
              multiplicative: bool) -> tuple:
    """QDM for ONE (cell, calendar month): 1-D float arrays.

    ref_hist    reference values, calibration window
    model_hist  model values, calibration window
    model_proj  model values, projection period

    Returns (corrected, diag); diag = {"clipped": n, "undefined_delta": n}.
    Pure function — no IO. Used by selftests and production alike.
    """
    ranks = np.argsort(np.argsort(model_proj, kind="stable")) + 1
    tau = gringorten(len(model_proj))[ranks - 1]
    q_mh = np.quantile(model_hist, tau, method="linear")
    q_ref = np.quantile(ref_hist, tau, method="linear")
    diag = {"clipped": 0, "undefined_delta": 0}
    if multiplicative:
        with np.errstate(divide="ignore", invalid="ignore"):
            delta = np.where(model_proj != 0.0, model_proj / q_mh, 1.0)
        bad = (q_mh <= 0.0) & (model_proj != 0.0)      # x > 0 over a zero quantile
        if np.any(bad):
            diag["undefined_delta"] += int(bad.sum())
            delta = np.where(bad, 1.0, delta)           # honest fallback: Δ := 1
        out = q_ref * delta
        out = np.where(q_ref <= 0.0, 0.0, out)          # dry reference quantile
    else:
        delta = model_proj - q_mh
        out = q_ref + delta
    clip_lo, clip_hi = PR_RANGE if multiplicative else TAS_RANGE
    diag["clipped"] = int(np.sum((out < clip_lo) | (out > clip_hi)))
    out = np.clip(out, clip_lo, clip_hi)
    return out, diag


# ------------------------------------------------------------------ selftest ---
def selftest() -> int:
    hr("SELFTEST — QDM on synthetic worlds (deterministic seed 20261103)")
    rng = np.random.default_rng(SEED)
    fails = []

    # ---- T1 identity: model data = reference data => output = reference ----
    n = 200
    for name, mult in (("T1a multiplicative", True), ("T1b additive", False)):
        if mult:
            s = np.abs(rng.normal(50.0, 20.0, n))       # pr-like mm/month > 0
            out, _ = qdm_apply(s, s, s, multiplicative=True)
            err = float(np.max(np.abs(out - s) / np.maximum(s, 1e-9)))
        else:
            s = rng.normal(20.0, 2.0, n)                # degC-like
            out, _ = qdm_apply(s, s, s, multiplicative=False)
            err = float(np.max(np.abs(out - s)))
        print(f"{name}: max err = {err:.3e}")
        if err > 1e-9:
            fails.append(f"{name} identity broken")

    # ---- T2 trend preservation: synthetic signals survive correction ------
    n_h, n_p = 300, 300
    years = np.arange(n_p) - n_p / 2.0
    A = np.stack([np.ones(n_p), years], axis=1)
    ref_h = rng.normal(20.0, 2.0, n_h)
    model_h = rng.normal(18.0, 2.0, n_h)                # model biased −2 degC
    slope = 0.05
    proj = rng.normal(18.0, 2.0, n_p) + slope * years
    out, _ = qdm_apply(ref_h, model_h, proj, multiplicative=False)
    coef, *_ = np.linalg.lstsq(A, out, rcond=None)
    slope_out = float(coef[1])
    rel = abs(slope_out - slope) / slope
    print(f"T2a additive warming : slope in = {slope:.4f}, out = {slope_out:.4f}, "
          f"rel diff = {rel:.3f}")
    if rel > 0.15:                                      # rank-noise tolerance
        fails.append("T2a trend not preserved (additive)")

    ref_pr = rng.gamma(2.0, 25.0, n_h)
    model_prh = rng.gamma(2.0, 20.0, n_h)               # biased dry
    trend = -0.004
    proj_pr = rng.gamma(2.0, 20.0, n_p) * (1.0 + trend * years)
    out_pr, _ = qdm_apply(ref_pr, model_prh, proj_pr, multiplicative=True)
    coef, *_ = np.linalg.lstsq(A, np.log(out_pr), rcond=None)
    slope_out_m = float(coef[1])
    rel_m = abs(slope_out_m - trend) / abs(trend)
    print(f"T2b multiplicative drying: slope in = {trend:.4f}, out = "
          f"{slope_out_m:.4f}, rel diff = {rel_m:.3f}")
    if rel_m > 0.25:
        fails.append("T2b trend not preserved (multiplicative)")

    # ---- T3 quantile inversion: no change signal -> corrected = Qref -----
    # Construction: the projection sample IS the model's own quantiles at the
    # Gringorten positions, so Δ = x/Qmh(τ) = 1 EXACTLY by construction and
    # the corrected values must equal Qref(τ) to float precision.
    n = 400
    tau_g = gringorten(n)
    ref_q = np.sort(rng.gamma(2.0, 25.0, n))
    model_q = np.sort(ref_q * 0.8)                       # biased dry, same shape
    proj_q = np.quantile(model_q, tau_g, method="linear")
    out_q, _ = qdm_apply(ref_q, model_q, proj_q, multiplicative=True)
    expect = np.quantile(ref_q, tau_g, method="linear")
    rel_err = float(np.max(np.abs(out_q - expect) / np.maximum(np.abs(expect), 1e-9)))
    print(f"T3 quantile inversion: max rel err vs Qref(Gringorten) = {rel_err:.3e}")
    if rel_err > 1e-9:
        fails.append("T3 quantile inversion beyond tolerance")

    # ---- T4 pr zero-guard -------------------------------------------------
    ref_dry = np.concatenate([np.zeros(100), rng.gamma(2.0, 25.0, 200)])
    model_dry = rng.gamma(2.0, 20.0, 300)
    proj_dry = rng.gamma(2.0, 20.0, 300)
    out_dry, _ = qdm_apply(ref_dry, model_dry, proj_dry, multiplicative=True)
    n_zero_ref = int(np.sum(np.quantile(ref_dry, gringorten(300),
                                        method="linear") <= 0.0))
    n_zero_out = int(np.sum(out_dry <= 0.0))
    print(f"T4 zero-guard: dry reference quantiles = {n_zero_ref}, "
          f"corrected zeros = {n_zero_out}")
    if n_zero_ref == 0 or n_zero_out < n_zero_ref:
        fails.append("T4 zero-guard not enforced")

    # ---- T5 range guard ----------------------------------------------------
    ref_r = rng.gamma(2.0, 25.0, 300)
    model_r = rng.gamma(2.0, 25.0, 300)
    proj_r = np.array([5000.0, -10.0] + list(rng.gamma(2.0, 25.0, 298)))
    out_r, diag = qdm_apply(ref_r, model_r, proj_r, multiplicative=True)
    print(f"T5 range guard: clipped = {diag['clipped']} (expect 2), "
          f"min = {float(out_r.min()):.2f}, max = {float(out_r.max()):.2f}")
    if diag["clipped"] != 2 or out_r.min() < PR_RANGE[0] or out_r.max() > PR_RANGE[1]:
        fails.append("T5 range guard broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1a, T1b, T2a, T2b, T3, T4, T5)")
    return 0


# --------------------------------------------------------- reference prep ------
def read_imd_year(path: Path, var: str):
    """IMD daily year file -> (lat, lon, {(y, m): monthly field}, {(y, m): days}).
    IMD units: pr = mm/day (kept as monthly mean RATE — the same intensive
    quantity step 02 regrids), tas = degC (monthly mean). Missing -> NaN."""
    import cftime
    import netCDF4 as nc
    d = nc.Dataset(path)
    try:
        name = {"pr": "rain", "tasmax": "tmax", "tasmin": "tmin"}[var]
        v = d.variables[name]
        raw = np.ma.filled(np.ma.asarray(v[:]), np.nan).astype(np.float64)
        lat_name = "lat" if "lat" in d.variables else "latitude"
        lon_name = "lon" if "lon" in d.variables else "longitude"
        dims = v.dimensions
        t_ax, lat_ax, lon_ax = dims.index("time"), dims.index(lat_name), dims.index(lon_name)
        if (t_ax, lat_ax, lon_ax) != (0, 1, 2):
            raw = np.transpose(raw, (t_ax, lat_ax, lon_ax))
        lat = np.asarray(d.variables[lat_name][:], float)
        lon = np.asarray(d.variables[lon_name][:], float)
        tv = d.variables["time"]
        dates = cftime.num2date(tv[:], units=tv.units,
                                calendar=getattr(tv, "calendar", "standard"))
        groups = {}
        for i, t in enumerate(dates):
            groups.setdefault((t.year, t.month), []).append(i)
        monthly, days = {}, {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            for (y, m), idx in groups.items():
                with np.errstate(invalid="ignore"):
                    monthly[(y, m)] = np.nanmean(raw[idx], axis=0)
                days[(y, m)] = len(idx)
        return lat, lon, monthly, days
    finally:
        d.close()


def _load_r02():
    spec = importlib.util.spec_from_file_location(
        "regrid025", HERE / "02_regrid_025.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prepare_reference(work_root: Path, tgt: dict, variables, years) -> list:
    """IMD daily -> monthly on the target grid; pr totals reconstructed with
    days_in_month AFTER the conservative remap (identical rule to step 02 —
    one shared method for the model/reference water balance, C3)."""
    ref_cfg = load_yaml(HERE / "config" / "reference.yaml")
    pr_root = Path(ref_cfg["reference"]["precipitation"]["primary"]["path"]).parent
    r02 = _load_r02()
    import pandas as pd
    import xarray as xr
    out_dir = work_root / "reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for var in variables:
        sub = pr_root / ("pr" if var == "pr" else "tmax" if var == "tasmax" else "tmin")
        months_out, labels, days_map = [], [], {}
        t0 = time.time()
        for y in years:
            f = sub / f"IMD_rain_{y}.nc" if var == "pr" else \
                sub / f"IMD_{ 'tmax' if var == 'tasmax' else 'tmin'}_{y}.nc"
            if not f.exists():
                print(f"  MISSING IMD {var} {y}: {f}")
                continue
            lat, lon, monthly, days = read_imd_year(f, var)
            r02._assert_ascending(lat, lon, f"IMD-{var}")
            if var == "pr":
                A, rs = r02.conservative_weights(lat, lon, tgt)
            for (y2, m) in sorted(monthly):
                field = monthly[(y2, m)]
                if var == "pr":
                    remapped, row_eff, _rel = r02.conservative_apply(
                        A, rs, field, (tgt["n_lat"], tgt["n_lon"]))
                    total = remapped * days[(y2, m)]
                    total[np.isnan(remapped)] = np.nan
                    months_out.append(total)
                else:
                    remapped, _n_ext, _n_nan, _n_ren = r02.bilinear_masked(lat, lon, field, tgt)
                    months_out.append(remapped)
                labels.append((y2, m))
                days_map[(y2, m)] = days[(y2, m)]
        if not labels:
            records.append({"var": var, "status": "no-input"})
            continue
        period = f"{labels[0][0]}-{labels[-1][0]}"
        out_path = out_dir / f"imd_{var}_{period}.nc"
        tstamp = pd.to_datetime([f"{y:04d}-{m:02d}-01" for (y, m) in labels])
        data = np.stack(months_out).astype(np.float32)
        ds = xr.Dataset({var: (("time", "lat", "lon"), data)},
                        coords={"time": tstamp, "lat": tgt["lat_centres"],
                                "lon": tgt["lon_centres"]},
                        attrs={"source": "IMD 0.25° gridded (Pai et al. 2014 lineage)",
                               "variable": var,
                               "pr_units_note": "mm/month (rate remapped conservatively, "
                                                "total reconstructed)" if var == "pr"
                               else "degC monthly means",
                               "pipeline": "DIE v2.0 gcm-pipeline 03_qdm_bias_correct.py"
                                           " (prepare-reference)"})
        ds.to_netcdf(out_path, encoding={var: {"dtype": "float32", "zlib": True,
                                               "complevel": 4}})
        rec = {"var": var, "status": "ok", "out": str(out_path.relative_to(work_root)),
               "n_months": len(months_out), "period": period,
               "seconds": round(time.time() - t0, 1),
               "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
        records.append(rec)
        print(f"  OK IMD {var}: {rec['n_months']} months {period} "
              f"({rec['seconds']}s) -> {out_path.name}")
    return records


# ----------------------------------------------------------------- QDM run ------
def load_monthly_nc(path: Path, var: str):
    import netCDF4 as nc
    d = nc.Dataset(path)
    try:
        raw = np.ma.filled(np.ma.asarray(d.variables[var][:]), np.nan).astype(np.float32)
        t = d.variables["time"]
        dates = nc.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
        lat = np.asarray(d.variables["lat"][:], float)
        lon = np.asarray(d.variables["lon"][:], float)
        return raw, dates, lat, lon
    finally:
        d.close()


def regrid_file_for(work_root: Path, model: str, exp: str, var: str) -> Path | None:
    d = work_root / "regrid" / model / exp
    if not d.exists():
        return None
    fs = sorted(d.glob(f"{var}_*.nc"))
    return fs[0] if fs else None


def run_qdm(model: str, mode: str, experiments: list, variables: list,
            work_root: Path) -> list:
    """Production QDM per (model, experiment, variable). One output file per
    variable. Calibration model baseline: historical 1981–2014 + ssp 2015–2020
    combined (ssp mode) or historical only (historical-corrected mode)."""
    records = []
    for var in variables:
        fh = regrid_file_for(work_root, model, "historical", var)
        if fh is None:
            print(f"  SKIP {model}/{var}: no regridded historical (run 02 first)")
            continue
        arr_h, dates_h, lat_o, lon_o = load_monthly_nc(fh, var)
        ref_path = work_root / "reference" / f"imd_{var}_1981-2020.nc"
        if not ref_path.exists():
            sys.exit(f"FATAL: reference missing for {var} ({ref_path}) — "
                     "run --prepare-reference first")
        ref_arr, ref_dates, _, _ = load_monthly_nc(ref_path, var)

        if mode == "historical-corrected":
            arr_cal, dates_cal = arr_h, dates_h          # baseline = hist only
            arr_proj, dates_proj = arr_h, dates_h        # proj sample = hist itself
            tag = "historical-corrected"
        else:
            fs = regrid_file_for(work_root, model, exp, var) \
                if (exp := experiments[0]) else None
            # (one experiment per call — main() loops experiments)
            if fs is None:
                print(f"  SKIP {model}/{var}/{experiments[0]}: ssp regrid output "
                      f"absent (phase-2 downloads pending — reported honestly)")
                continue
            arr_s, dates_s, _, _ = load_monthly_nc(fs, var)
            arr_cal = np.concatenate([arr_h, arr_s], axis=0)
            dates_cal = list(dates_h) + list(dates_s)
            arr_proj, dates_proj = arr_s, dates_s
            tag = experiments[0]

        yrs_c = np.array([d.year for d in dates_cal])
        mos_c = np.array([d.month for d in dates_cal])
        yrs_r = np.array([d.year for d in ref_dates])
        mos_r = np.array([d.month for d in ref_dates])
        yrs_p = np.array([d.year for d in dates_proj])
        mos_p = np.array([d.month for d in dates_proj])

        ref_cal = ref_arr[(yrs_r >= CAL_WINDOW[0]) & (yrs_r <= CAL_WINDOW[1])]
        cal_mask = yrs_c <= 2014
        if mode != "historical-corrected":
            n_hist = int(np.sum(yrs_c <= 2014))
            cal_mask[:n_hist] = True                     # hist part
            cal_mask[n_hist:] = (yrs_c[n_hist:] >= 2015) & (yrs_c[n_hist:] <= 2020)
        mh = arr_cal[cal_mask]
        mos_mh = mos_c[cal_mask]

        multiplicative = (var == "pr")
        n_time, n_lat, n_lon = arr_proj.shape
        corrected = np.full((n_time, n_lat, n_lon), np.nan, dtype=np.float32)
        diag_totals = {"clipped": 0, "undefined_delta": 0, "gate_fail_cells": 0}
        t0 = time.time()
        for mo in range(1, 13):
            ref_s = ref_cal[mos_r == mo]                 # (n_ref, lat, lon)
            mh_s = mh[mos_mh == mo]
            p_idx = np.where(mos_p == mo)[0]
            p_s = arr_proj[p_idx]
            for a in range(n_lat):
                for b in range(n_lon):
                    r_c = ref_s[:, a, b].astype(np.float64)
                    m_c = mh_s[:, a, b].astype(np.float64)
                    p_c = p_s[:, a, b].astype(np.float64)
                    r_ok, m_ok, p_ok = np.isfinite(r_c), np.isfinite(m_c), np.isfinite(p_c)
                    if r_ok.sum() < MIN_BASE_YEARS or m_ok.sum() < MIN_BASE_YEARS:
                        diag_totals["gate_fail_cells"] += 1
                        continue                          # cell-month stays NaN
                    if not p_ok.any():
                        continue
                    o_c, diag = qdm_apply(r_c[r_ok], m_c[m_ok], p_c[p_ok],
                                          multiplicative=multiplicative)
                    corrected[p_idx[p_ok], a, b] = o_c
                    diag_totals["clipped"] += diag["clipped"]
                    diag_totals["undefined_delta"] += diag["undefined_delta"]
        # write
        import pandas as pd
        import xarray as xr
        out_dir = work_root / "qdm" / model / tag
        out_dir.mkdir(parents=True, exist_ok=True)
        period = f"{dates_proj[0].year}-{dates_proj[-1].year}"
        out_path = out_dir / f"{var}_{period}.nc"
        tstamp = pd.to_datetime([f"{d.year:04d}-{d.month:02d}-01" for d in dates_proj])
        ds = xr.Dataset({var: (("time", "lat", "lon"), corrected)},
                        coords={"time": tstamp, "lat": lat_o, "lon": lon_o},
                        attrs={"source_id": model, "mode": tag,
                               "calibration_window": f"{CAL_WINDOW[0]}-{CAL_WINDOW[1]}",
                               "method": "QDM (Cannon et al. 2015); "
                                         + ("multiplicative pr, zero-guard"
                                            if multiplicative else "additive tas")
                                         + "; Gringorten plotting positions",
                               "reference": "IMD 0.25° (Pai et al. 2014 lineage)",
                               "fit_gate": f">= {MIN_BASE_YEARS} finite base years "
                                           "per cell-month; failing cells NaN",
                               "guards": json.dumps(diag_totals),
                               "pipeline": "DIE v2.0 gcm-pipeline 03_qdm_bias_correct.py"})
        ds.to_netcdf(out_path, encoding={var: {"dtype": "float32", "zlib": True,
                                               "complevel": 4}})
        rec = {"model": model, "mode": tag, "var": var, "status": "ok",
               "out": str(out_path.relative_to(work_root)), "period": period,
               "n_time": n_time, "guards": diag_totals,
               "seconds": round(time.time() - t0, 1),
               "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
        records.append(rec)
        print(f"  OK {model:18s} {tag:22s} {var:7s} {n_time:4d} months {period} "
              f"clip={diag_totals['clipped']} undefDelta={diag_totals['undefined_delta']} "
              f"gateFail={diag_totals['gate_fail_cells']} ({rec['seconds']}s)")
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="QDM bias correction (M2.6)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--prepare-reference", action="store_true")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--models", help="comma list (default: all config models)")
    ap.add_argument("--variables", default="pr,tasmax,tasmin")
    ap.add_argument("--experiments", default=None,
                    help="ssp mode: comma list (default ssp245,ssp585)")
    ap.add_argument("--ref-years", default="1981-2020")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    paths = load_yaml(HERE / "config" / "paths.yaml")
    ref = load_yaml(HERE / "config" / "reference.yaml")
    cfg = load_yaml(HERE / "config" / "models.yaml")
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    r02 = _load_r02()
    tgt = r02.target_grid(ref)
    variables = args.variables.split(",")
    man_path = work_root / "qdm_manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else \
        {"schema": 1, "files": {}}

    if args.prepare_reference:
        a, b = (int(x) for x in args.ref_years.split("-"))
        recs = prepare_reference(work_root, tgt, variables, range(a, b + 1))
        for r in recs:
            if r.get("status") == "ok":
                manifest["files"][f"reference/{r['var']}"] = r
        man_path.write_text(json.dumps(manifest, indent=2))
        return 0

    models = args.models.split(",") if args.models else \
        [r["source_id"] for r in cfg["models"]]
    experiments = (args.experiments.split(",") if args.experiments else
                   (["historical"] if args.mode == "historical-corrected"
                    else ["ssp245", "ssp585"]))
    hr(f"QDM — mode={args.mode} models={len(models)} vars={','.join(variables)}")
    all_recs = []
    for model in models:
        exps = experiments if args.mode == "ssp" else [None]
        for exp in exps:
            exps_eff = [exp] if exp else ["historical"]
            recs = run_qdm(model, args.mode, exps_eff, variables, work_root)
            all_recs.extend(recs)
    for r in all_recs:
        manifest["files"][f"{r['model']}/{r['mode']}/{r['var']}"] = r
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"QDM DONE: {len(all_recs)} output(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
