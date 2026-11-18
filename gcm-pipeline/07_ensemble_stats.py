#!/usr/bin/env python3
"""DIE v2.0 - gcm-pipeline step 07: ensemble statistics (task M2.10,
docs/v2/03 section 3.7).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9).
Resumable + idempotent (manifest work/ensemble_manifest.json).

Inputs : work/aggregate/<model>/<tag>/<iid>_districts_<period>.nc
         (step 06 output; one file per model per indicator)
Output : work/ensemble/<tag>/<iid>_ensemble_<period>.nc with, per
         (district, month):

  median / p25 / p75   quantiles over the n AVAILABLE models (numpy
                       quantile_method from config/ensemble.yaml; n recorded,
                       never assumed 24 - X3 honest ensemble)
  agreement_moderate   fraction of available models with value <= -1.0
  agreement_severe     fraction of available models with value <= -1.5
  n_models             contributing model count per district-month
  (ssp mode adds:) dir_agreement_drier - fraction of models whose
  effective-window mean is drier (lower z) than their own base mean;
  not applicable in historical-corrected mode (no future window) -> absent.
  dir_agreement_n      - count of models with a finite base AND window mean
  (the exact denominator; never inferred from n_models).

  The configured future window (config/ensemble.yaml) is a nominal target:
  the EFFECTIVE window is its overlap with the record when that overlap holds
  at least dir_agreement_min_window_years years, otherwise the latest that
  many years available (an explicit record-end truncation). The effective
  window is recorded verbatim in the NC attributes and the manifest, and is
  never silently shortened. The statistic is window-constant per district, so
  it is repeated across the months inside the effective window and absent
  elsewhere.

Definitions are fixed in code, printed into the manifest verbatim, and must
be rendered as UI tooltips (docs/v2/04 section 4.2). Per-model series stay in
work/aggregate/ so individual models remain inspectable - never hide
disagreement behind the ensemble (C5).

Self-tests (--selftest, deterministic seed 20261103, synthetic only; wired
into selftest_gcm.py at M2.13):
  T1 quantiles exact on a 5-model synthetic ensemble,
  T2 agreement fractions exact incl. NaN models (denominator = available n),
  T3 n_models honesty (a model missing a month drops out of everything),
  T4 dir_agreement_drier exact on a synthetic 2-window world + exact
     denominator (a NaN window mean must leave BOTH numerator and n),
  T5 single-model degenerate ensemble (median == the value, fractions 0/1),
  T6 effective-window rule (overlap when long enough, else the latest
     minimum years; short record -> honest null),
  T7 AS6 seam rule accept/reject (historical ends Dec -> ssp starts Jan).

Usage:
  python 07_ensemble_stats.py --selftest
  python 07_ensemble_stats.py --mode historical-corrected
  python 07_ensemble_stats.py --mode ssp --experiments ssp245,ssp585
"""
from __future__ import annotations

import argparse
import hashlib
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
IIDS = ("spi_01", "spi_03", "spi_06", "spi_12",
        "spei_01", "spei_03", "spei_06", "spei_12")


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------- selftest ----
def selftest() -> int:
    hr("SELFTEST - ensemble statistics on synthetic worlds (seed 20261103)")
    rng = np.random.default_rng(SEED)
    fails = []
    cfg = load_yaml(CONFIG_DIR / "ensemble.yaml")["ensemble"]
    qm = cfg["quantile_method"]
    t_mod = float(cfg["agreement_moderate_threshold"])
    t_sev = float(cfg["agreement_severe_threshold"])

    def stats(stack: np.ndarray) -> dict:
        fin = np.isfinite(stack)
        n = fin.sum(axis=0)
        with np.errstate(invalid="ignore"):
            med = np.nanquantile(stack, 0.5, axis=0, method=qm)
            p25 = np.nanquantile(stack, 0.25, axis=0, method=qm)
            p75 = np.nanquantile(stack, 0.75, axis=0, method=qm)
            v = np.where(fin, stack, np.inf)     # NaN models never agree
            agree_m = np.sum(v <= t_mod, axis=0) / np.maximum(n, 1)
            agree_s = np.sum(v <= t_sev, axis=0) / np.maximum(n, 1)
        return {"median": med, "p25": p25, "p75": p75,
                "agreement_moderate": agree_m, "agreement_severe": agree_s,
                "n_models": n}

    # ---- T1 quantiles exact: 5 models, 1 district, known values -----------
    stack = np.array([[[1.0]], [[2.0]], [[3.0]], [[4.0]], [[5.0]]])
    # (models, time, districts)
    s = stats(stack)
    ok = (s["median"][0, 0] == 3.0 and s["p25"][0, 0] == 2.0 and
          s["p75"][0, 0] == 4.0)
    print(f"T1 quantiles: median={s['median'][0, 0]} p25={s['p25'][0, 0]} "
          f"p75={s['p75'][0, 0]} (expect 3/2/4): {ok}")
    if not ok:
        fails.append("T1 quantiles inexact")

    # ---- T2 agreement fractions with a NaN model --------------------------
    # 4 models: -2.0 (moderate+severe), -1.2 (moderate only), 0.5, NaN
    stack = np.array([[[-2.0]], [[-1.2]], [[0.5]], [[np.nan]]])
    s = stats(stack)
    ok = (s["n_models"][0, 0] == 3 and
          abs(s["agreement_moderate"][0, 0] - 2 / 3) < 1e-12 and
          abs(s["agreement_severe"][0, 0] - 1 / 3) < 1e-12)
    print(f"T2 agreement: n={s['n_models'][0, 0]} mod={s['agreement_moderate'][0, 0]:.4f} "
          f"sev={s['agreement_severe'][0, 0]:.4f} (expect n=3, 2/3, 1/3): {ok}")
    if not ok:
        fails.append("T2 agreement fractions wrong")

    # ---- T3 NaN-model month drops out of quantiles too --------------------
    stack = np.array([[[1.0], [np.nan]], [[3.0], [np.nan]],
                      [[np.nan], [2.0]]])
    s = stats(stack)
    ok = (s["n_models"][0, 0] == 2 and s["median"][0, 0] == 2.0 and
          s["n_models"][1, 0] == 1 and s["median"][1, 0] == 2.0)
    print(f"T3 dropout: month1 n={s['n_models'][0, 0]} median={s['median'][0, 0]}; "
          f"month2 n={s['n_models'][1, 0]} median={s['median'][1, 0]} "
          f"(expect 2/2.0, 1/2.0): {ok}")
    if not ok:
        fails.append("T3 NaN-model dropout broken")

    # ---- T4 dir_agreement_drier exact + exact denominator ------------------
    # base mean per model vs window mean; the shift sign decides drying.
    # Model 6 has an all-NaN window: it must leave BOTH numerator and n.
    rng2 = np.random.default_rng(SEED)
    n_mod, n_t = 6, 20
    base = rng2.normal(0, 1, (n_mod, n_t))
    shift = np.array([0.5, 0.2, -0.3, 0.8, -0.8, 0.0])[:, None]
    win = base - shift            # positive shift -> lower window z -> drier
    win[5, :] = np.nan            # model 6: no window record
    frac, n_ok = dir_agreement(base[:, :, None], win[:, :, None], cfg)
    expect = 3 / 5                # models 1, 2, 4 drier; model 6 excluded
    ok = (abs(frac[0] - expect) < 1e-12 and int(n_ok[0]) == 5)
    print(f"T4 dir_agreement_drier: {frac[0]:.3f} of n={n_ok[0]} "
          f"(expect {expect:.3f} of 5): {ok}")
    if not ok:
        fails.append("T4 dir_agreement broken")

    # ---- T5 single-model degenerate ensemble ------------------------------
    stack = np.array([[[-1.7]]])
    s = stats(stack)
    ok = (s["n_models"][0, 0] == 1 and s["median"][0, 0] == -1.7 and
          s["agreement_moderate"][0, 0] == 1.0 and
          s["agreement_severe"][0, 0] == 1.0)
    print(f"T5 single-model: median={s['median'][0, 0]} agree={s['agreement_moderate'][0, 0]}"
          f"/{s['agreement_severe'][0, 0]} (expect -1.7, 1, 1): {ok}")
    if not ok:
        fails.append("T5 degenerate ensemble broken")

    # ---- T6 effective-window rule: overlap else latest available decade ----
    w_short, why_short = effective_window(range(2015, 2051), cfg)
    w_full, why_full = effective_window(range(2015, 2101), cfg)
    w_part, why_part = effective_window(range(2015, 2086), cfg)  # 5-yr overlap
    w_tiny, why_tiny = effective_window(range(2015, 2020), cfg)
    ok = (w_short == (2041, 2050) and w_full == (2081, 2100)
          and w_part == (2076, 2085) and w_tiny is None
          and "latest 10 years" in why_short and "overlap" in why_full
          and "minimum" in why_tiny)
    print(f"T6 dir window: short={w_short}, full={w_full}, "
          f"partial={w_part}, tiny={w_tiny}: {ok}")
    if not ok:
        fails.append("T6 dir window rule broken")

    # ---- T7 AS6 seam rule: accept Dec->Jan, reject Nov / gap ---------------
    hist_ok = [(y, mo) for y in range(1981, 2015) for mo in range(1, 13)]
    ssp_ok = [(2015, mo) for mo in range(1, 13)]
    ok_a, why_a = validate_seam(hist_ok, ssp_ok)
    ok_b, why_b = validate_seam(hist_ok[:-1], ssp_ok)      # ends Nov 2014
    ok_c, why_c = validate_seam(hist_ok, [(2017, 1)])      # 2016 gap
    ok = (ok_a and not ok_b and not ok_c
          and "Dec" in why_b and "gap" in why_c)
    print(f"T7 AS6 seam: accept={ok_a}, reject Nov={not ok_b}, "
          f"reject gap={not ok_c}: {ok}")
    if not ok:
        fails.append("T7 AS6 seam rule broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4, T5, T6, T7)")
    return 0


# ---------------------------------------------------------------- compute -----
def ensemble_stats(stack: np.ndarray, cfg: dict) -> dict:
    """stack: (n_models, n_time, n_districts) with NaN for absent."""
    fin = np.isfinite(stack)
    n = fin.sum(axis=0)
    qm = cfg["quantile_method"]
    t_mod = float(cfg["agreement_moderate_threshold"])
    t_sev = float(cfg["agreement_severe_threshold"])
    with np.errstate(invalid="ignore"):
        med = np.nanquantile(stack, 0.5, axis=0, method=qm)
        p25 = np.nanquantile(stack, 0.25, axis=0, method=qm)
        p75 = np.nanquantile(stack, 0.75, axis=0, method=qm)
        v = np.where(fin, stack, np.inf)
        agree_m = np.sum(v <= t_mod, axis=0) / np.maximum(n, 1)
        agree_s = np.sum(v <= t_sev, axis=0) / np.maximum(n, 1)
    agree_m = np.where(n > 0, agree_m, np.nan)
    agree_s = np.where(n > 0, agree_s, np.nan)
    return {"median": med, "p25": p25, "p75": p75,
            "agreement_moderate": agree_m, "agreement_severe": agree_s,
            "n_models": n}


def effective_window(years, cfg: dict):
    """Derive the EFFECTIVE direction window from the config and the record.

    Declared rule (config/ensemble.yaml, printed verbatim downstream):
      1. the overlap of dir_agreement_window with the record, when it holds at
         least dir_agreement_min_window_years distinct years;
      2. otherwise the LATEST dir_agreement_min_window_years years in the
         record - an explicit, labelled record-end truncation.
    Returns ((lo, hi), note) or (None, reason). Never silently shortens and
    never invents a window; a record shorter than the minimum yields None.
    """
    w0, w1 = (int(x) for x in cfg["dir_agreement_window"])
    mn = int(cfg["dir_agreement_min_window_years"])
    ys = sorted({int(y) for y in years})
    if not ys:
        return None, "empty record"
    lo, hi = max(w0, ys[0]), min(w1, ys[-1])
    n_in = sum(1 for y in ys if lo <= y <= hi) if lo <= hi else 0
    if n_in >= mn:
        return (lo, hi), (f"overlap of the configured window {w0}-{w1} with "
                          f"the record {ys[0]}-{ys[-1]}")
    if len(ys) < mn:
        return None, (f"record {ys[0]}-{ys[-1]} holds {len(ys)} years < "
                      f"declared minimum {mn} "
                      f"(dir_agreement_min_window_years)")
    tail = ys[-mn:]
    return (tail[0], tail[-1]), (
        f"configured window {w0}-{w1} is not in the record "
        f"({ys[0]}-{ys[-1]}); using the latest {mn} years available "
        f"{tail[0]}-{tail[-1]} (explicit record-end truncation, not the "
        f"configured window)")


def validate_seam(hist_keys, ssp_keys):
    """AS6 seam rule, identical to 05 stitch_hist_ssp: the historical-corrected
    record ends in December and the ssp record starts the next January.
    Anything else is a fabric defect, never a silently stitched record."""
    if not hist_keys or not ssp_keys:
        return False, "empty record"
    hy, hm = hist_keys[-1]
    sy, sm = ssp_keys[0]
    if hm != 12 or sm != 1:
        return False, (f"seam expects historical ending Dec and ssp starting "
                      f"Jan (got hist {hy}-{hm:02d}, ssp {sy}-{sm:02d})")
    if sy != hy + 1:
        return False, (f"gap/overlap at the AS6 seam: historical ends "
                       f"{hy}-{hm:02d}, ssp starts {sy}-{sm:02d}")
    return True, f"historical ends Dec {hy}, ssp starts Jan {sy}"


def _window_mean(stack: np.ndarray) -> np.ndarray:
    """(models, time, districts) -> (models, districts) nanmean, no warnings."""
    fin = np.isfinite(stack)
    n = fin.sum(axis=1)
    s = np.where(fin, stack, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore"):
        m = s / np.maximum(n, 1)
    return np.where(n > 0, m, np.nan)


def dir_agreement(stack_base: np.ndarray, stack_window: np.ndarray,
                  cfg: dict):
    """Fraction of models whose window mean is drier (lower z) than their own
    base mean, per district. Returns (fraction, n_models_counted).

    Months are collapsed inside each window. A model with a NaN base or window
    mean leaves BOTH the numerator and the denominator: an absent record is
    never counted as "not drier" (R10) and the denominator is reported so the
    UI can state "N of M" exactly. cfg is unused today; kept so the threshold
    vocabulary of the other statistics stays parallel."""
    b = _window_mean(stack_base)               # (models, districts)
    w = _window_mean(stack_window)
    ok = np.isfinite(b) & np.isfinite(w)
    n = ok.sum(axis=0)
    with np.errstate(invalid="ignore"):
        frac = np.where(ok, w < b, False).sum(axis=0) / np.maximum(n, 1)
    return np.where(n > 0, frac, np.nan), n


def run_tag(work_root: Path, tag_dir_name: str, models: list,
            cfg: dict, iids, manifest: dict,
            mode: str = "historical-corrected") -> int:
    """Ensemble over work/aggregate/<model>/<tag_dir_name>/ for one mode.

    ssp mode additionally stitches each model's historical-corrected record
    (AS6 seam, the same rule as 05) so the configured base window
    (ensemble.yaml dir_agreement_base, [1981, 2014] - register D6) is
    reachable, derives the EFFECTIVE future window, and emits the
    window-constant dir_agreement_drier / dir_agreement_n panels."""
    import netCDF4 as nc
    import pandas as pd
    import xarray as xr
    n_done = 0
    base_cfg = [int(x) for x in cfg["dir_agreement_base"]]
    win_cfg = [int(x) for x in cfg["dir_agreement_window"]]
    min_win = int(cfg["dir_agreement_min_window_years"])
    for iid in iids:
        stacks, dids_ref, dates_ref = [], None, None
        fulls, keys_full = [], None        # ssp mode: stitched per-model arrays
        for m in models:
            model_dir = work_root / "aggregate" / m / tag_dir_name
            g = sorted(model_dir.glob(f"{iid}_districts_*.nc"))
            if not g:
                print(f"  SKIP {iid}: {m} missing")
                continue
            d = nc.Dataset(g[0])
            var = d.variables[iid]
            arr = np.asarray(np.ma.filled(var[:], np.nan), float)  # (dist, t)
            t = d.variables["time"]
            dates = nc.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
            dids = [str(x) for x in d.variables["district"][:]]
            d.close()
            if dids_ref is None:
                dids_ref, dates_ref = dids, dates
            elif dids != dids_ref or len(dates) != len(dates_ref):
                print(f"  FATAL {iid}: {m} fabric/time mismatch")
                return 1
            stacks.append(arr)                 # (districts, time)
            if mode == "ssp":
                hp = sorted((work_root / "aggregate" / m
                             / "historical-corrected").glob(
                                 f"{iid}_districts_*.nc"))
                if not hp:
                    print(f"  FATAL {iid}: {m} has no historical-corrected "
                          f"aggregate for the {base_cfg[0]}-{base_cfg[1]} "
                          f"base - run 06 in historical-corrected mode first")
                    return 1
                hd = nc.Dataset(hp[0])
                try:
                    harr = np.asarray(
                        np.ma.filled(hd.variables[iid][:], np.nan), float)
                    ht = hd.variables["time"]
                    hdates = nc.num2date(
                        ht[:], ht.units, getattr(ht, "calendar", "standard"))
                    hdids = [str(x) for x in hd.variables["district"][:]]
                finally:
                    hd.close()
                if hdids != dids:
                    print(f"  FATAL {iid}: {m} historical district fabric "
                          f"differs from the ssp fabric")
                    return 1
                hkeys = [(x.year, x.month) for x in hdates]
                okeys = [(x.year, x.month) for x in dates]
                ok_seam, why = validate_seam(hkeys, okeys)
                if not ok_seam:
                    print(f"  FATAL {iid}: {m} AS6 seam rejected: {why}")
                    return 1
                kf = hkeys + okeys
                if keys_full is None:
                    keys_full = kf
                elif kf != keys_full:
                    print(f"  FATAL {iid}: {m} stitched time fabric differs "
                          f"from the other models - refusing a mixed base")
                    return 1
                fulls.append(np.concatenate([harr, arr], axis=1))
        if len(stacks) < 2:
            print(f"  SKIP {iid}: < 2 models with data")
            continue
        # stacks: (models, districts, time) -> want (models, time, districts)
        stack = np.stack(stacks).transpose(0, 2, 1)
        s = ensemble_stats(stack, cfg)

        dir_panel = dir_n = None
        dir_rec = None
        if mode == "ssp":
            base_idx = [i for i, (y, _m) in enumerate(keys_full)
                        if base_cfg[0] <= y <= base_cfg[1]]
            base_years = len({keys_full[i][0] for i in base_idx})
            if not base_idx:
                print(f"  FATAL {iid}: no months inside the base window "
                      f"{base_cfg[0]}-{base_cfg[1]}")
                return 1
            win, win_note = effective_window(
                sorted({x.year for x in dates_ref}), cfg)
            if win is None:
                print(f"  NOTE {iid}: dir_agreement not emitted - {win_note}")
                frac = np.full(len(dids_ref), np.nan)
                n_ok = np.zeros(len(dids_ref), dtype=int)
            else:
                win_idx = [i for i, (y, _m) in enumerate(keys_full)
                           if win[0] <= y <= win[1]]
                bs = np.stack([f[:, base_idx] for f in fulls]
                              ).transpose(0, 2, 1)
                ws = np.stack([f[:, win_idx] for f in fulls]
                              ).transpose(0, 2, 1)
                frac, n_ok = dir_agreement(bs, ws, cfg)
            in_win = np.zeros(len(dates_ref), dtype=bool)
            if win is not None:
                in_win = np.array([win[0] <= x.year <= win[1]
                                   for x in dates_ref])
            dir_panel = np.full((len(dids_ref), len(dates_ref)), np.nan,
                                dtype=np.float32)
            dir_n = np.full((len(dids_ref), len(dates_ref)), -999,
                            dtype=np.int16)
            if in_win.any():
                dir_panel[:, in_win] = frac[:, None].astype(np.float32)
                dir_n[:, in_win] = n_ok[:, None].astype(np.int16)
            dir_rec = {
                "base": f"{base_cfg[0]}-{base_cfg[1]}",
                "base_years": int(base_years),
                "window_configured": f"{win_cfg[0]}-{win_cfg[1]}",
                "window_effective": f"{win[0]}-{win[1]}" if win else None,
                "note": win_note,
                "min_window_years": min_win,
                "n_models_counted_min": int(n_ok.min()) if win else None,
                "n_models_counted_max": int(n_ok.max()) if win else None,
            }

        out_dir = work_root / "ensemble" / tag_dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{iid}_ensemble_{dates_ref[0].year}-" \
            f"{dates_ref[-1].year}.nc"
        tstamp = pd.to_datetime(
            [f"{x.year:04d}-{x.month:02d}-01" for x in dates_ref])
        data_vars = {
            "median": (("district", "time"), s["median"].T.astype(np.float32)),
            "p25": (("district", "time"), s["p25"].T.astype(np.float32)),
            "p75": (("district", "time"), s["p75"].T.astype(np.float32)),
            "agreement_moderate": (("district", "time"),
                                   s["agreement_moderate"].T.astype(np.float32)),
            "agreement_severe": (("district", "time"),
                                 s["agreement_severe"].T.astype(np.float32)),
            "n_models": (("district", "time"), s["n_models"].T.astype(np.int16)),
        }
        enc = {k: {"dtype": "float32", "zlib": True, "complevel": 4,
                   "_FillValue": np.float32(9.96921e36)}
               for k in ("median", "p25", "p75", "agreement_moderate",
                         "agreement_severe")}
        enc["n_models"] = {"dtype": "int16", "zlib": True, "complevel": 4,
                           "_FillValue": -999}
        defs = {
            "median_p25_p75":
                "quantiles over the n available models "
                "(numpy method: linear); n recorded, never "
                "assumed 24",
            "agreement_moderate":
                "fraction of available models with value "
                "<= -1.0 that month",
            "agreement_severe":
                "fraction of available models with value "
                "<= -1.5 that month",
            "dir_agreement_drier":
                "fraction of models whose effective-window mean is "
                "drier (lower z) than their own base mean; "
                "window-constant per district (ssp mode only)",
            "dir_agreement_n":
                "number of models with a finite base AND window mean "
                "(the exact denominator of dir_agreement_drier)",
            "n_models": "contributing model count",
        }
        attrs = {"definitions_verbatim": json.dumps(defs),
                 "quantile_method": cfg["quantile_method"],
                 "n_models_input": len(stacks),
                 "pipeline": "DIE v2.0 gcm-pipeline "
                             "07_ensemble_stats.py"}
        if mode == "ssp":
            data_vars["dir_agreement_drier"] = (("district", "time"), dir_panel)
            data_vars["dir_agreement_n"] = (("district", "time"), dir_n)
            enc["dir_agreement_drier"] = {
                "dtype": "float32", "zlib": True, "complevel": 4,
                "_FillValue": np.float32(9.96921e36)}
            enc["dir_agreement_n"] = {
                "dtype": "int16", "zlib": True, "complevel": 4,
                "_FillValue": -999}
            attrs.update({
                "dir_agreement_base": dir_rec["base"],
                "dir_agreement_base_years": dir_rec["base_years"],
                "dir_agreement_window_configured":
                    dir_rec["window_configured"],
                "dir_agreement_window_effective":
                    dir_rec["window_effective"] or "none",
                "dir_agreement_window_note": dir_rec["note"],
                "dir_agreement_min_window_years": min_win,
            })
        else:
            attrs["dir_agreement_window_effective"] = \
                "not applicable (historical-corrected mode)"
        ds = xr.Dataset(data_vars,
                        coords={"time": tstamp,
                                "district": np.array(dids_ref, dtype=object)},
                        attrs=attrs)
        ds.to_netcdf(out_path, encoding=enc)
        n_done += 1
        rec = {"iid": iid, "out": str(out_path.relative_to(work_root)),
               "n_models": len(stacks),
               "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
        if mode == "ssp":
            rec["dir_agreement"] = dir_rec
            manifest.setdefault("dir_agreement", {})[tag_dir_name] = dir_rec
        manifest["files"][f"{tag_dir_name}/{iid}"] = rec
        extra = ""
        if mode == "ssp":
            extra = (f", dir window {dir_rec['window_effective'] or 'none'}"
                     f" (n {dir_rec['n_models_counted_min']}-"
                     f"{dir_rec['n_models_counted_max']})")
        print(f"  OK {tag_dir_name:22s} {iid:8s} {len(stacks)} models, "
              f"{len(dates_ref)} months -> {out_path.name}{extra}")
    return n_done


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensemble statistics (M2.10)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--models", help="comma list (default: era-C ensemble)")
    ap.add_argument("--experiments", default=None,
                    help="ssp mode: comma list (default ssp245,ssp585)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    cfgm = load_yaml(CONFIG_DIR / "models.yaml")
    cfg = load_yaml(CONFIG_DIR / "ensemble.yaml")["ensemble"]
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    man_path = work_root / "ensemble_manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else \
        {"schema": 1, "files": {}}
    models = args.models.split(",") if args.models else \
        [r["source_id"] for r in cfgm["models"] if r.get("era_c_ensemble", True)]

    hr(f"ENSEMBLE mode={args.mode} models={len(models)}")
    if args.mode == "historical-corrected":
        n = run_tag(work_root, "historical-corrected", models, cfg, IIDS,
                    manifest, mode="historical-corrected")
    else:
        experiments = (args.experiments.split(",") if args.experiments
                       else ["ssp245", "ssp585"])
        n = 0
        for exp in experiments:
            n += run_tag(work_root, exp, models, cfg, IIDS, manifest,
                         mode="ssp")
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"ENSEMBLE DONE: {n} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
