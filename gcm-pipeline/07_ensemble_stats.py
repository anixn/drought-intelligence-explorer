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
  <window> mean is drier (lower z) than their <base> mean; not
  applicable in historical-corrected mode (no future window) -> null.

Definitions are fixed in code, printed into the manifest verbatim, and must
be rendered as UI tooltips (docs/v2/04 section 4.2). Per-model series stay in
work/aggregate/ so individual models remain inspectable - never hide
disagreement behind the ensemble (C5).

Self-tests (--selftest, deterministic seed 20261103, synthetic only; wired
into selftest_gcm.py at M2.13):
  T1 quantiles exact on a 5-model synthetic ensemble,
  T2 agreement fractions exact incl. NaN models (denominator = available n),
  T3 n_models honesty (a model missing a month drops out of everything),
  T4 dir_agreement_drier exact on a synthetic 2-window world,
  T5 single-model degenerate ensemble (median == the value, fractions 0/1).

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

    # ---- T4 dir_agreement_drier on a synthetic 2-window world -------------
    # base mean per model from 1981-1990, window mean 2081-2100;
    # models drying get counted
    rng2 = np.random.default_rng(SEED)
    n_mod, n_t = 6, 40
    base = rng2.normal(0, 1, (n_mod, 20))
    fut = base[:, :20] - np.array([-0.5, -0.2, 0.0, 0.3, 0.8, 1.5])[:, None]
    drier = fut.mean(axis=1) < base.mean(axis=1)
    frac = float(drier.mean())
    expect = float((fut.mean(axis=1) - base.mean(axis=1) < 0).mean())
    ok = frac == expect and frac == 3 / 6
    print(f"T4 dir_agreement_drier: {frac:.3f} (expect {expect:.3f} = 0.500): {ok}")
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

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4, T5)")
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


def dir_agreement(stack_base: np.ndarray, stack_window: np.ndarray,
                  cfg: dict) -> np.ndarray:
    """Fraction of models whose window mean is drier (lower z) than their
    base mean. Per district; months are collapsed inside each window."""
    b = np.nanmean(stack_base, axis=1)         # (models, districts)
    w = np.nanmean(stack_window, axis=1)
    return (w < b).sum(axis=0) / np.maximum(np.isfinite(w).sum(axis=0)
                                            & np.isfinite(b).sum(axis=0)
                                            > 0, 1)


def run_tag(work_root: Path, tag_dir_name: str, models: list,
            cfg: dict, iids, manifest: dict) -> int:
    """Ensemble over work/aggregate/<model>/<tag_dir_name>/ for one mode."""
    import netCDF4 as nc
    import pandas as pd
    import xarray as xr
    n_done = 0
    for iid in iids:
        stacks, dids_ref, dates_ref = [], None, None
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
        if len(stacks) < 2:
            print(f"  SKIP {iid}: < 2 models with data")
            continue
        # stacks: (models, districts, time) -> want (models, time, districts)
        stack = np.stack(stacks).transpose(0, 2, 1)
        s = ensemble_stats(stack, cfg)
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
        ds = xr.Dataset(data_vars,
                        coords={"time": tstamp,
                                "district": np.array(dids_ref, dtype=object)},
                        attrs={"definitions_verbatim": json.dumps({
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
                                "fraction of models whose window mean is "
                                "drier than their base mean (per window; "
                                "ssp mode only)",
                            "n_models": "contributing model count"}),
                               "quantile_method": cfg["quantile_method"],
                               "n_models_input": len(stacks),
                               "pipeline": "DIE v2.0 gcm-pipeline "
                                           "07_ensemble_stats.py"})
        ds.to_netcdf(out_path, encoding=enc)
        n_done += 1
        rec = {"iid": iid, "out": str(out_path.relative_to(work_root)),
               "n_models": len(stacks),
               "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
        manifest["files"][f"{tag_dir_name}/{iid}"] = rec
        print(f"  OK {tag_dir_name:22s} {iid:8s} {len(stacks)} models, "
              f"{len(dates_ref)} months -> {out_path.name}")
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
                    manifest)
    else:
        experiments = (args.experiments.split(",") if args.experiments
                       else ["ssp245", "ssp585"])
        n = 0
        for exp in experiments:
            n += run_tag(work_root, exp, models, cfg, IIDS, manifest)
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"ENSEMBLE DONE: {n} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
