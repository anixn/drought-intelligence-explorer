#!/usr/bin/env python3
"""DIE v2.0 - gcm-pipeline step 08: validation gate (task M2.11,
docs/v2/03 section 3.8 + amendment M2.11 tail checks).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9):
  work/validation/validation_report.json   full audit (gates, Q-Q, counts)
  work/validation/best_subset.yaml         ranked best subset (8-12 models)
  work/validation/ranking.csv              per-model metrics (UI panel)
  work/validation_manifest.json            checksums of the above
Step 09 copies the report + best_subset + ranking into out/ when exporting.

Non-zero exit blocks release (gate failure). Gate-failure fallback if the
gate fails after two documented remediation rounds: publish observed-only
v2.0 and ship projections next cycle (docs/v2/03 section 3.8) - every
attempt recorded in PROGRESS.md.

Checks (all tolerances/weights declared in config/validation.yaml and
printed verbatim into the report; gate basis = POOLED MULTI-MODEL
distribution - see the remediation note in the config):
  1. Consistency: pooled corrected-model z vs reference z (mean diff, sd
     ratio) per (region, season, indicator); national breach FAILS. The
     ensemble-MEDIAN comparison is computed and reported (concentrated by
     construction) but not gated.
  2. Drought statistics: v1.0 event machinery (runs analysis, verbatim
     rules) - complete events pooled across all models vs reference:
     frequency / mean duration / mean severity per region; national breach
     FAILS. Ensemble-median events reported (a median rarely crosses the
     truncation level), not gated.
  3. Per-model ranking: 8 metrics (pearson_r, abs_bias, rmsd,
     class_agreement, freq_ratio, duration_ratio, severity_ratio,
     spatial_r) -> weighted composite (documented weights, no
     single-metric ranking) -> committed SUBSET CRITERION (largest-gap
     core extended to the registered floor by reweighting-stability
     order; NOT a fixed count) -> best_subset.yaml.
     Free-running decorrelation caveat: temporal-synchrony metrics carry
     mostly noise (measured r ~ 0, M2.8) and are weighted accordingly.
  4. SPI-SPEI divergence quantified (national + regional, per season) -
     reported, never gated (the warming fingerprint the UI presents).
  5. Dry tails (amendment M2.11): Q-Q pairs + p10/p05 drought-tail ratios
     per (region, season); national tail breach FAILS.
  6. Clip counts, missing-model months, calendar anomalies - all reported.

Regions = states/UTs of the 724-district registry + "national". Districts
with an entirely-NaN reference series (IMD ocean mask islands) are excluded
from pools and reported (R10 honesty). Reference (base 1981-2020, C2) is
sliced to the shared 1981-2014 window by calendar month.

Self-tests (--selftest, seed 20261103, synthetic only; wired into
selftest_gcm.py at M2.13) exercise the REAL gate functions:
  T1 runs-analysis events exact (durations, severity, censoring, NaN break)
  T2 consistency gate: identical pass; shifted/heavier world flagged
  T3 tail gate: same-tail pass; heavy-tail world flagged
  T4 ranking: closeness transform + min-max + composite ordering exact;
     subset = registered floor when candidates below it
  T5 SPI-SPEI divergence exact
  T6 all-NaN district excluded from a region pool and counted
  T7 subset criterion: largest-gap core detected; floor extension by
     stability order exact

Usage:
  python 08_validate_gcm.py --selftest
  python 08_validate_gcm.py --mode historical-corrected
  python 08_validate_gcm.py --mode ssp          # hard-fails until SSP data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
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
IIDS = ("spi_01", "spi_03", "spi_06", "spi_12",
        "spei_01", "spei_03", "spei_06", "spei_12")

# McKee 9-class z bins (v1.0 classification, indicators/config):
# (-inf,-2) extreme dry, [-2,-1.5) severe, [-1.5,-1) moderate,
# [-1,-0.5) abnormally dry, [-0.5,0.5) near normal, then mirrored wet side.
MCKEE_EDGES = np.array([-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0])


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def r6(x):
    """Round for the report (JSON size)."""
    if isinstance(x, (float, np.floating)):
        return round(float(x), 6)
    return x


# ------------------------------------------------------------- gate pieces ----
def find_events_matrix(mat: np.ndarray, tau: float, min_dur: int) -> dict:
    """v1.0 runs analysis, vectorised over rows of `mat` (series, T).

    A run = consecutive finite months with value <= tau (a NaN month breaks
    the run - R10); runs shorter than min_dur are discarded; a run touching
    the record edge is censored (excluded from duration/severity statistics,
    counted). severity = sum(tau - x) over the run (positive deficit).
    Returns per-row aggregate: n_complete, n_censored_complete,
    mean_duration, mean_severity, drought_months, finite_months.
    """
    n, T = mat.shape
    dry = np.where(np.isfinite(mat), mat <= tau, False)
    dry_pad = np.zeros((n, T + 2), dtype=bool)
    dry_pad[:, 1:-1] = dry
    starts = dry & ~np.roll(dry_pad, 1, axis=1)[:, 1:-1]  # first month of run
    ends = dry & ~np.roll(dry_pad, -1, axis=1)[:, 1:-1]   # last month of run
    s_idx = np.argwhere(starts)          # (row, col)
    e_idx = np.argwhere(ends)
    n_complete = np.zeros(n, dtype=np.int64)
    n_cens = np.zeros(n, dtype=np.int64)
    dur_sum = np.zeros(n, dtype=np.float64)
    sev_sum = np.zeros(n, dtype=np.float64)
    if len(s_idx):
        # runs pair in order within each row (starts and ends interleave)
        for (i, s), (j, e) in zip(s_idx, e_idx):
            assert i == j and e >= s, "run pairing corrupted"
            dur = e - s + 1
            censored = (s == 0) or (e == T - 1)
            if dur >= min_dur:
                seg = mat[i, s:e + 1]
                sev = float(np.sum(tau - seg))
                if censored:
                    n_cens[i] += 1
                else:
                    n_complete[i] += 1
                    dur_sum[i] += dur
                    sev_sum[i] += sev
    finite = np.isfinite(mat).sum(axis=1)
    drought = (np.where(np.isfinite(mat), mat <= tau, False)).sum(axis=1)
    mean_dur = np.where(n_complete > 0, dur_sum / np.maximum(n_complete, 1),
                        np.nan)
    mean_sev = np.where(n_complete > 0, sev_sum / np.maximum(n_complete, 1),
                        np.nan)
    return {"n_complete": n_complete, "n_censored_complete": n_cens,
            "mean_duration": mean_dur, "mean_severity": mean_sev,
            "dur_sum": dur_sum, "sev_sum": sev_sum,
            "drought_months": drought, "finite_months": finite}


def pooled_z(a: np.ndarray, b: np.ndarray) -> tuple:
    """Pooled paired-finite z arrays of ens (a) and ref (b)."""
    m = np.isfinite(a) & np.isfinite(b)
    return a[m], b[m], int(m.sum())


def pooled_models_cell(pool: np.ndarray, ref_region: np.ndarray,
                       n_models: int, cell_fn, cfg: dict) -> dict:
    """Gate cell on the POOLED MULTI-MODEL distribution: pool (models,
    districts, months_masked) flattened over (models x districts), paired
    against the reference region tiled model-times. `cell_fn` is
    consistency_cell or tail_cell (same tolerance semantics)."""
    M, d, t = pool.shape
    b_tiled = np.repeat(ref_region[None], M, axis=0).reshape(M * d, t)
    a_flat = pool.reshape(M * d, t)
    return cell_fn(a_flat, b_tiled, cfg)


def consistency_cell(a: np.ndarray, b: np.ndarray, cfg: dict) -> dict:
    """One (region, season, iid) consistency cell from paired z pools."""
    x, y, n = pooled_z(a, b)
    if n == 0:
        return {"n_pairs": 0, "mean_ens": None, "mean_ref": None,
                "sd_ens": None, "sd_ref": None, "breach": None}
    mean_a, mean_b = float(x.mean()), float(y.mean())
    sd_a, sd_b = float(x.std()), float(y.std())
    mean_diff = mean_a - mean_b
    sd_ratio = (sd_a / sd_b) if sd_b > 1e-12 else None
    tol = cfg["consistency"]
    breach = (abs(mean_diff) > tol["mean_abs_tol"]) or \
        (sd_ratio is None or not
         (tol["sd_ratio_range"][0] <= sd_ratio <= tol["sd_ratio_range"][1]))
    return {"n_pairs": n, "mean_ens": r6(mean_a), "mean_ref": r6(mean_b),
            "sd_ens": r6(sd_a), "sd_ref": r6(sd_b),
            "mean_diff": r6(mean_diff), "sd_ratio": r6(sd_ratio),
            "breach": bool(breach)}


def drought_stats_region(ev_mod: dict, ev_ref: dict, region_idx: np.ndarray,
                         n_series_used: int, n_years: float) -> dict:
    """Pooled region-level drought statistics from per-series event
    aggregates (complete events only). `ev_mod` may be a single model's or a
    POOLED multi-model aggregate (n_complete/dur_sum/sev_sum summed across
    models; n_series_used then counts model-district pairs). Series excluded
    when either side has no finite months (reported honestly)."""
    n_comp = ev_mod["n_complete"][region_idx]
    use = (ev_mod["finite_months"][region_idx] > 0) & \
        (ev_ref["finite_months"][region_idx] > 0)
    out = {"n_districts_total": int(region_idx.size),
           "n_series_used": int(n_series_used)}
    if use.sum() == 0 or n_series_used <= 0:
        return {**out, "freq_ens": None, "freq_ref": None,
                "mean_dur_ens": None, "mean_dur_ref": None,
                "mean_sev_ens": None, "mean_sev_ref": None,
                "freq_ratio": None, "duration_ratio": None,
                "severity_ratio": None, "breach": None}
    # frequency = pooled complete events per contributing series-year
    f_ens = float(n_comp[use].sum() / (n_series_used * n_years))
    f_ref = float(ev_ref["n_complete"][region_idx][use].sum() /
                  (int(use.sum()) * n_years))
    n_ev = float(n_comp[use].sum())
    n_ev_r = float(ev_ref["n_complete"][region_idx][use].sum())
    d_ens = (float(ev_mod["dur_sum"][region_idx][use].sum() / n_ev)
             if n_ev > 0 else None)
    d_ref = (float(ev_ref["dur_sum"][region_idx][use].sum() / n_ev_r)
             if n_ev_r > 0 else None)
    s_ens = (float(ev_mod["sev_sum"][region_idx][use].sum() / n_ev)
             if n_ev > 0 else None)
    s_ref = (float(ev_ref["sev_sum"][region_idx][use].sum() / n_ev_r)
             if n_ev_r > 0 else None)
    fr = (f_ens / f_ref) if f_ref and f_ref > 0 else None
    dr = (d_ens / d_ref) if (d_ens and d_ref) else None
    sr = (s_ens / s_ref) if (s_ens and s_ref) else None

    def in_range(v, key):
        if v is None:
            return False
        lo, hi = EV_CFG[key]
        return lo <= v <= hi

    breach = not (in_range(fr, "freq_ratio_range") and
                  in_range(dr, "duration_ratio_range") and
                  in_range(sr, "severity_ratio_range"))
    return {**out, "freq_ens": r6(f_ens), "freq_ref": r6(f_ref),
            "mean_dur_ens": r6(d_ens), "mean_dur_ref": r6(d_ref),
            "mean_sev_ens": r6(s_ens), "mean_sev_ref": r6(s_ref),
            "n_events_mod": int(n_ev), "n_events_ref": int(n_ev_r),
            "freq_ratio": r6(fr), "duration_ratio": r6(dr),
            "severity_ratio": r6(sr), "breach": bool(breach)}


EV_CFG = {}  # set by run(); the events gate block of validation.yaml


def tail_cell(a: np.ndarray, b: np.ndarray, cfg: dict) -> dict:
    """Dry-tail cell: lower-tail z quantiles of ens vs ref + breach."""
    x, y, n = pooled_z(a, b)
    if n == 0:
        return {"n_pairs": 0, "tails": {}, "breach": None}
    lo, hi = cfg["ratio_range"]
    tails, breach = {}, False
    for p in cfg["quantiles"]:
        qa, qb = float(np.quantile(x, p)), float(np.quantile(y, p))
        ratio = (abs(qa) / abs(qb)) if abs(qb) > 1e-9 else None
        tails[f"p{int(round(p * 100))}"] = {"q_ens": r6(qa), "q_ref": r6(qb),
                                            "ratio": r6(ratio)}
        if ratio is None or not (lo <= ratio <= hi):
            breach = True
    return {"n_pairs": n, "tails": tails, "breach": bool(breach)}


def qq_pairs(a: np.ndarray, b: np.ndarray, levels: list) -> list:
    """Stored Q-Q pairs (ref quantile, ens quantile) on the paired pool."""
    x, y, n = pooled_z(a, b)
    if n == 0:
        return []
    return [{"level": lv, "q_ref": r6(float(np.quantile(y, lv))),
             "q_ens": r6(float(np.quantile(x, lv)))} for lv in levels]


def spi_spei_divergence(spi: np.ndarray, spei: np.ndarray) -> dict:
    """mean(SPI z) - mean(SPEI z) over the paired-finite pool (ens and ref
    computed on their OWN pools - honest when availability differs)."""
    m = np.isfinite(spi)
    msp = float(np.nanmean(spi[m])) if m.any() else None
    m2 = np.isfinite(spei)
    msp2 = float(np.nanmean(spei[m2])) if m2.any() else None
    d = None if (msp is None or msp2 is None) else msp - msp2
    return {"mean_spi": r6(msp), "mean_spei": r6(msp2), "divergence": r6(d),
            "n_spi": int(m.sum()), "n_spei": int(m2.sum())}


def closeness(ratio, cap: float) -> float:
    """Map a model/ref ratio to [0, 1] goodness (1 = ratio 1)."""
    if ratio is None or ratio <= 0:
        return 0.0
    return float(max(0.0, 1.0 - abs(np.log(ratio)) / np.log(cap)))


def mckee_classes(z: np.ndarray) -> np.ndarray:
    """McKee 9-class bin index 0..8 for finite z (NaN -> -1)."""
    safe = np.where(np.isfinite(z), z, -10.0)
    out = np.searchsorted(MCKEE_EDGES, safe, side="right")
    return np.where(np.isfinite(z), out, -1)


def select_subset(goodness: dict, models: list, rank_cfg: dict,
                  iids) -> dict:
    """Committed subset criterion (config/validation.yaml ranking.
    subset_criterion): core = models above the largest inter-rank composite
    gap; extended to the registered floor by reweighting-stability order
    (Dirichlet weight perturbations, deterministic seed); capped at the
    registered ceiling and the candidate count. Returns the subset plus the
    full audit (gaps, inclusion frequencies) for the report."""
    weights = rank_cfg["metrics"]
    metric_names = list(weights.keys())
    w0 = np.array([weights[k] for k in metric_names])
    crit = rank_cfg["subset_criterion"]
    lo, hi = (int(x) for x in crit["size_range"])
    have = [m for m in models if any(m in goodness.get(iid, {})
                                     for iid in iids)]

    def composite(w: np.ndarray) -> dict:
        out = {}
        for m in have:
            cs = [sum(w[j] * goodness[iid][m][metric_names[j]]
                      for j in range(len(metric_names)))
                  for iid in iids if m in goodness[iid]]
            out[m] = float(np.mean(cs)) if cs else -9e9
        return out

    base = composite(w0)
    order = sorted(have, key=lambda m: (-base[m], m))
    gaps = [base[order[i]] - base[order[i + 1]]
            for i in range(len(order) - 1)]
    core = 1
    if gaps:
        g_max = max(gaps)
        core = gaps.index(g_max) + 1          # earliest boundary on ties
    freq = {}
    if core < lo:
        rng = np.random.default_rng(int(crit["stability_seed"]))
        draws = int(crit["stability_draws"])
        conc = float(crit["dirichlet_concentration"])
        for _ in range(draws):
            c = composite(rng.dirichlet(w0 * conc))
            for m in sorted(have, key=lambda x: (-c[x], x))[:lo]:
                freq[m] = freq.get(m, 0) + 1
        freq = {m: f / draws for m, f in freq.items()}
        candidates = [m for m in order[core:] if m in freq]
        candidates.sort(key=lambda m: (-freq.get(m, 0.0), -base[m], m))
        subset = order[:core] + candidates[:lo - core]
    else:
        subset = order[:core]
    if len(subset) > hi:
        subset = subset[:hi]
    return {"subset": subset, "core": core,
            "core_gap": r6(g_max) if gaps else None,
            "size_range": [lo, hi],
            "inclusion_freq_at_floor": {m: r6(freq.get(m, 1.0 if m in subset
                                                   else 0.0)) for m in have},
            "base_composites": {m: r6(base[m]) for m in order},
            "rule": "core = largest inter-rank composite gap; extend to "
                    "size_range[0] by reweighting-stability order "
                    "(Dirichlet weight perturbations); cap at "
                    "size_range[1] and candidate count (see "
                    "config/validation.yaml ranking.subset_criterion)"}


def rank_models(models_z: dict, ref_z: dict, iids, ev_cfg: dict,
                rank_cfg: dict, years: float) -> tuple:
    """Per-model metrics per iid -> composite (documented weights,
    min-max normalised across models) -> ranking. Returns (rows, per_iid,
    goodness) - subset selection is select_subset's job."""
    names = list(models_z.keys())
    per_iid = {}
    for iid in iids:
        ref = ref_z[iid]
        ev_ref = find_events_matrix(ref, ev_cfg["truncation"],
                                    ev_cfg["min_duration"])
        ref_dry_frac = (ev_ref["drought_months"] /
                        np.maximum(ev_ref["finite_months"], 1))
        mets = {}
        for m in names:
            z = models_z[m][iid]
            ev_m = find_events_matrix(z, ev_cfg["truncation"],
                                      ev_cfg["min_duration"])
            x, y, n = pooled_z(z, ref)
            if n == 0:
                mets[m] = None
                continue
            r = float(np.corrcoef(x, y)[0, 1]) if n > 2 and \
                x.std() > 1e-12 and y.std() > 1e-12 else None
            bias = float(x.mean() - y.mean())
            rmsd = float(np.sqrt(((x - y) ** 2).mean()))
            xcls, ycls = mckee_classes(x), mckee_classes(y)
            # paired-finite denominator (F7): months where the reference is
            # undefined must not count as disagreements
            pair = (xcls >= 0) & (ycls >= 0)
            cls = (xcls == ycls) & pair
            ca = float(cls.sum() / pair.sum()) if pair.any() else None
            fr = (ev_m["n_complete"].sum() / max(ev_ref["n_complete"].sum(), 1)
                  ) if ev_ref["n_complete"].sum() > 0 else None
            dur_m = float(np.nanmean(ev_m["mean_duration"])) \
                if np.isfinite(ev_m["mean_duration"]).any() else None
            dur_r = float(np.nanmean(ev_ref["mean_duration"])) \
                if np.isfinite(ev_ref["mean_duration"]).any() else None
            sev_m = float(np.nanmean(ev_m["mean_severity"])) \
                if np.isfinite(ev_m["mean_severity"]).any() else None
            sev_r = float(np.nanmean(ev_ref["mean_severity"])) \
                if np.isfinite(ev_ref["mean_severity"]).any() else None
            dry_m = ev_m["drought_months"] / np.maximum(ev_m["finite_months"], 1)
            ok = (ev_m["finite_months"] > 0) & (ev_ref["finite_months"] > 0)
            with np.errstate(invalid="ignore", divide="ignore"):
                sr = None
                if ok.sum() > 2 and dry_m[ok].std() > 1e-12 and \
                        ref_dry_frac[ok].std() > 1e-12:
                    sr = float(np.corrcoef(dry_m[ok],
                                           ref_dry_frac[ok])[0, 1])
                    sr = sr if np.isfinite(sr) else None
            mets[m] = {
                "pearson_r": r, "abs_bias": abs(bias), "rmsd": rmsd,
                "class_agreement": ca,
                "freq_ratio": fr,
                "duration_ratio": (dur_m / dur_r) if (dur_m and dur_r) else None,
                "severity_ratio": (sev_m / sev_r) if (sev_m and sev_r) else None,
                "spatial_r": sr,
                "n_pairs": n,
                "raw_bias": r6(bias),
                "mean_duration_model": r6(dur_m), "mean_duration_ref": r6(dur_r),
                "mean_severity_model": r6(sev_m), "mean_severity_ref": r6(sev_r),
                "drought_freq_model_per_dy": r6(
                    ev_m["n_complete"].sum() /
                    max(ev_m["finite_months"].sum() / 12.0, 1e-9)),
                "drought_freq_ref_per_dy": r6(
                    ev_ref["n_complete"].sum() /
                    max(ev_ref["finite_months"].sum() / 12.0, 1e-9)),
            }
        per_iid[iid] = mets

    # composite: min-max normalise each metric across models per iid
    weights = rank_cfg["metrics"]
    cap = float(rank_cfg["closeness_cap_ratio"])
    goodness = {}
    for iid in iids:
        mets = {m: v for m, v in per_iid[iid].items() if v is not None}
        if len(mets) < 2:
            continue
        scores = {m: {} for m in mets}
        for metric in weights:
            vals = {}
            for m, v in mets.items():
                x = v.get(metric)
                if metric.endswith("_ratio"):
                    x = closeness(x, cap)
                elif metric == "abs_bias" or metric == "rmsd":
                    x = None if x is None else -x      # lower is better
                if x is not None and not np.isfinite(x):
                    x = None                            # NaN poisons min/max
                vals[m] = x
            finite_vals = {m: v for m, v in vals.items() if v is not None}
            if len(finite_vals) < 2:
                for m in mets:
                    scores[m][metric] = 0.5
                continue
            lo, hi = min(finite_vals.values()), max(finite_vals.values())
            for m in mets:
                if vals[m] is None:
                    scores[m][metric] = 0.5
                elif hi - lo < 1e-12:
                    scores[m][metric] = 0.5
                else:
                    scores[m][metric] = (vals[m] - lo) / (hi - lo)
        goodness[iid] = scores
    rows = []
    for m in names:
        comps = []
        detail = {}
        for iid in iids:
            if iid not in goodness or m not in goodness[iid]:
                continue
            sc = goodness[iid][m]
            comp = sum(weights[k] * sc.get(k, 0.5) for k in weights)
            comps.append(comp)
            detail[iid] = {k: r6(v) for k, v in sc.items()}
        rows.append({"model": m,
                     "composite": r6(float(np.mean(comps))) if comps else None,
                     "per_iid_scores": detail})
    rows.sort(key=lambda rw: (rw["composite"] is None,
                              -(rw["composite"] or -9e9)))
    for i, rw in enumerate(rows):
        rw["rank"] = i + 1
    return rows, per_iid, goodness


# ------------------------------------------------------------------ selftest --
def selftest() -> int:
    global EV_CFG
    hr("SELFTEST - validation gate on synthetic worlds (seed 20261103)")
    rng = np.random.default_rng(SEED)
    fails = []
    cfg = load_yaml(CONFIG_DIR / "validation.yaml")["validation"]
    EV_CFG = cfg["events"]
    T = 408
    years = 34.0

    # ---- T1 runs analysis exactness ---------------------------------------
    row = np.array([np.nan, -0.2, -1.2, -1.5, np.nan, -0.5, -1.1, -1.3,
                    -1.2, 0.2, -1.1, -1.0, np.nan])
    ev = find_events_matrix(row[None, :], -1.0, 3)
    ok = (ev["n_complete"][0] == 1 and ev["n_censored_complete"][0] == 0 and
          abs(ev["mean_duration"][0] - 3) < 1e-12 and
          abs(ev["mean_severity"][0] - 0.6) < 1e-12 and
          ev["drought_months"][0] == 7)
    # censoring: run touching the end edge -> censored, excluded from the
    # duration/severity statistics (v1.0 rule), counted separately
    row2 = np.array([0.5, -1.2, -1.4, -1.1])
    ev2 = find_events_matrix(row2[None, :], -1.0, 3)
    ok2 = (ev2["n_censored_complete"][0] == 1 and
           ev2["n_complete"][0] == 0 and
           not np.isfinite(ev2["mean_severity"][0]))
    print(f"T1 events: complete={ev['n_complete'][0]} dur={ev['mean_duration'][0]} "
          f"sev={ev['mean_severity'][0]} (expect 1, 3, 0.6): {ok}; "
          f"censored edge event counted: {ok2}")
    if not (ok and ok2):
        fails.append("T1 runs analysis inexact")

    # ---- T2 consistency gate ----------------------------------------------
    ref = rng.normal(0, 1, (5, T))
    same = consistency_cell(ref.copy(), ref, cfg)
    shifted = consistency_cell(ref + 0.5, ref, cfg)
    scaled = consistency_cell(ref * 2.0, ref, cfg)
    ok = (same["breach"] is False and shifted["breach"] is True and
          scaled["breach"] is True and same["n_pairs"] == 5 * T)
    print(f"T2 consistency: identical pass={same['breach'] is False}, "
          f"+0.5 shift flagged={shifted['breach']}, x2 spread flagged="
          f"{scaled['breach']}: {ok}")
    if not ok:
        fails.append("T2 consistency gate wrong")

    # ---- T3 tail gate ------------------------------------------------------
    same = tail_cell(ref.copy(), ref, cfg["tails"])
    heavy = tail_cell(ref * 3.0, ref, cfg["tails"])
    ok = (same["breach"] is False and heavy["breach"] is True and
          abs(same["tails"]["p10"]["ratio"] - 1.0) < 1e-9)
    print(f"T3 tails: identical pass={same['breach'] is False}, "
          f"x3 heavy tail flagged={heavy['breach']}: {ok}")
    if not ok:
        fails.append("T3 tail gate wrong")

    # ---- T4 ranking --------------------------------------------------------
    world = {"mA": 0.0, "mB": 1.0, "mC": 2.0, "mD": 4.0}   # |bias| ladder
    models_z = {m: {iid: ref + b for iid in IIDS[:2]} for m, b in world.items()}
    ref_z = {iid: ref for iid in IIDS[:2]}
    rows, _, goodness = rank_models(models_z, ref_z, IIDS[:2], EV_CFG,
                                    cfg["ranking"], years)
    sub = select_subset(goodness, list(world), cfg["ranking"], IIDS[:2])
    order = [rw["model"] for rw in rows]
    ok = order[0] == "mA" and order[-1] == "mD" and \
        len(sub["subset"]) == min(len(world),
                                  cfg["ranking"]["subset_criterion"]
                                  ["size_range"][0])
    cl = closeness(1.0, 3.0)
    ok2 = abs(cl - 1.0) < 1e-12 and closeness(3.0, 3.0) == 0.0
    print(f"T4 ranking: order={order} (mA best, mD worst), "
          f"subset={len(sub['subset'])}: {ok}; closeness(1)=1, "
          f"closeness(3)=0: {ok2}")
    if not (ok and ok2):
        fails.append("T4 ranking broken")

    # ---- T5 SPI-SPEI divergence -------------------------------------------
    d = spi_spei_divergence(np.array([[0.5, 1.0]]), np.array([[0.2, 0.4]]))
    ok = abs(d["divergence"] - 0.45) < 1e-12 and d["n_spi"] == 2
    print(f"T5 divergence: {d['divergence']} (expect 0.45): {ok}")
    if not ok:
        fails.append("T5 divergence wrong")

    # ---- T6 all-NaN district excluded from region pool ---------------------
    a = np.vstack([rng.normal(0, 1, (2, T)), np.full((1, T), np.nan)])
    b = a.copy()
    ev_a = find_events_matrix(a, -1.0, 3)
    ev_b = find_events_matrix(b, -1.0, 3)
    st = drought_stats_region(ev_a, ev_b, np.array([0, 1, 2]), 2, years)
    ok = st["n_districts_total"] == 3 and st["n_series_used"] == 2
    print(f"T6 region pool: total={st['n_districts_total']} "
          f"used={st['n_series_used']} (expect 3, 2): {ok}")
    if not ok:
        fails.append("T6 region exclusion broken")

    # ---- T7 subset criterion (largest-gap core + stability extension) ------
    mnames = [f"m{k:02d}" for k in range(1, 13)]

    def mk_goodness(top_n):
        g = {}
        for iid in IIDS[:2]:
            g[iid] = {m: {k: (1.0 if int(m[1:]) <= top_n else 0.0)
                          for k in cfg["ranking"]["metrics"]} for m in mnames}
        return g

    sub_a = select_subset(mk_goodness(9), mnames, cfg["ranking"], IIDS[:2])
    ok = sub_a["core"] == 9 and sub_a["subset"] == mnames[:9]
    sub_b = select_subset(mk_goodness(6), mnames, cfg["ranking"], IIDS[:2])
    ok2 = sub_b["core"] == 6 and len(sub_b["subset"]) == \
        cfg["ranking"]["subset_criterion"]["size_range"][0] and \
        sub_b["subset"][:6] == mnames[:6]
    print(f"T7 subset: gap-core 9 -> {sub_a['core']}/"
          f"{len(sub_a['subset'])} (expect 9/9): {ok}; core 6 below floor "
          f"-> extended to {len(sub_b['subset'])} = {sub_b['subset']} "
          f"(expect 8, m01..m06 + most-stable plateau): {ok2}")
    if not (ok and ok2):
        fails.append("T7 subset criterion broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4, T5, T6, T7)")
    return 0


# ---------------------------------------------------------------------- run ----
def load_district_nc(path: Path, var_name: str, y_lo: int, y_hi: int):
    """(values, year-month key list) sliced to the window.

    Step-06/07 NC files store (district, time); robust to a (time, district)
    legacy layout by explicit shape check against the coordinates.
    """
    import netCDF4 as nc
    d = nc.Dataset(path)
    var = d.variables[var_name]
    arr = np.asarray(np.ma.filled(var[:], np.nan), float)
    t = d.variables["time"]
    dates = nc.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
    dids = [str(x) for x in d.variables["district"][:]]
    d.close()
    keys = [(x.year, x.month) for x in dates]
    if arr.shape[1] == len(keys) and arr.shape[0] == len(dids):
        pass                                    # (district, time) as written
    elif arr.shape[0] == len(keys) and arr.shape[1] == len(dids):
        arr = arr.T                             # legacy (time, district)
    else:
        raise ValueError(f"{path}: shape {arr.shape} does not match "
                         f"({len(dids)} districts, {len(keys)} months)")
    keep = np.array([y_lo <= y <= y_hi for (y, _m) in keys])
    return arr[:, keep], [k for k, m in zip(keys, keep) if m], dids


def check_calendar(keys: list) -> int:
    """0 = contiguous monthly sequence; 1 = anomaly."""
    for k in range(1, len(keys)):
        y, m = keys[k - 1]
        y2, m2 = keys[k]
        if not (y2 == y + (m == 12) and m2 == (1 if m == 12 else m + 1)):
            return k
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validation gate (M2.11)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--models", help="comma list (default: era-C ensemble)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    global EV_CFG
    cfg = load_yaml(CONFIG_DIR / "validation.yaml")["validation"]
    EV_CFG = cfg["events"]
    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    cfgm = load_yaml(CONFIG_DIR / "models.yaml")
    work_root = (HERE / paths.get("work_root", "work")).resolve()

    if args.mode == "ssp":
        print("HARD FAIL: ssp-mode validation requires the phase-2 SSP "
              "downloads for the ranked subset (gated BY this step in "
              "historical mode). Nothing to validate yet - run "
              "--mode historical-corrected first (R3: no synthetic data "
              "passed off as projections).")
        return 2

    y_lo, y_hi = cfg["window"]
    models = args.models.split(",") if args.models else \
        [r["source_id"] for r in cfgm["models"] if r.get("era_c_ensemble", True)]
    seasons = cfg["seasons"]
    qq_levels = cfg["tails"]["qq_levels"]

    hr(f"VALIDATION GATE mode={args.mode} window={y_lo}-{y_hi} "
       f"models={len(models)}")

    # registry: district -> state region
    import csv as csvmod
    state_of = {}
    with open(REPO / "data" / "districts.csv", encoding="utf-8") as fh:
        for row in csvmod.DictReader(fh):
            state_of[row["district_id"]] = row["state_name"]

    # ---------------- load reference + ensemble + models ----------------
    ref_z, ens_z, models_z = {}, {}, {m: {} for m in models}
    cal_anomalies = []
    n_ref_districts = None
    for iid in IIDS:
        # reference files were written as 1981-2020, directly under
        # work/aggregate/reference/ (step 06 layout); slice to the window
        rp = work_root / "aggregate" / "reference" / \
            f"{iid}_districts_1981-2020.nc"
        if not rp.exists():
            print(f"FATAL: missing reference aggregate {rp}")
            return 1
        ref, rkeys, rids = load_district_nc(rp, iid, y_lo, y_hi)
        k = check_calendar(rkeys)
        if k:
            cal_anomalies.append(f"reference/{iid}@{rkeys[k]}")
        ep = work_root / "ensemble" / "historical-corrected" / \
            f"{iid}_ensemble_{y_lo}-{y_hi}.nc"
        if not ep.exists():
            print(f"FATAL: missing ensemble file {ep} (run 07 first)")
            return 1
        ens, ekeys, eids = load_district_nc(ep, "median", y_lo, y_hi)
        if ekeys != rkeys or eids != rids:
            print(f"FATAL: {iid} ensemble/reference fabric mismatch")
            return 1
        ref_z[iid], ens_z[iid] = ref, ens
        for m in models:
            mp = work_root / "aggregate" / m / "historical-corrected" / \
                f"{iid}_districts_{y_lo}-{y_hi}.nc"
            if not mp.exists():
                print(f"FATAL: missing model aggregate {mp}")
                return 1
            marr, mkeys, mids = load_district_nc(mp, iid, y_lo, y_hi)
            if mkeys != rkeys or mids != rids:
                print(f"FATAL: {iid}/{m} fabric mismatch")
                return 1
            models_z[m][iid] = marr
        n_ref_districts = len(rids)

    T = ref_z[IIDS[0]].shape[1]
    years = (y_hi - y_lo + 1)
    dids = rids
    regions = {"national": np.arange(len(dids))}
    for s in sorted(set(state_of.get(d) for d in dids)):
        if s:
            regions[s] = np.array([i for i, d in enumerate(dids)
                                   if state_of.get(d) == s])

    # districts with an entirely-NaN reference (IMD ocean mask) - excluded
    excluded = [dids[i] for i in range(len(dids))
                if not np.isfinite(ref_z["spi_03"][i]).any()]
    print(f"reference districts={n_ref_districts}, months={T}, "
          f"regions={len(regions)}, excluded(no ref data)={len(excluded)}")

    report = {"schema": "die-gcm-validation/1.0", "seed": SEED,
              "mode": args.mode, "window": [y_lo, y_hi],
              "n_models": len(models), "models": models,
              "n_months": T, "n_districts": len(dids),
              "districts_excluded_no_reference": excluded,
              "config_verbatim": cfg, "calendar_anomalies": cal_anomalies}
    gates = {}

    # ------------- gate 1: consistency (pooled models vs reference) ------
    # Gate basis: pooled multi-model distribution (config gate_basis);
    # ensemble-median cells still computed and reported (concentrated by
    # construction - median-of-n, documented in M2.10).
    print(f"[1/5] consistency gate (basis={cfg['gate_basis']})")
    cells, med_cells, n_reg_breach, n_reg_total = {}, {}, 0, 0
    national_breach = False
    for iid in IIDS:
        pool = np.stack([models_z[m][iid] for m in models])  # (M, dist, T)
        for sname, months in seasons.items():
            mask = np.array([m in months for (_y, m) in rkeys])
            for rname, ridx in regions.items():
                b = ref_z[iid][ridx][:, mask]
                c = pooled_models_cell(pool[:, ridx][:, :, mask], b,
                                       len(models), consistency_cell,
                                       cfg)
                if c["breach"] is None:
                    continue
                cells[f"{iid}/{sname}/{rname}"] = c
                if rname == "national":
                    if c["breach"]:
                        national_breach = True
                        print(f"  NATIONAL BREACH {iid}/{sname}: "
                              f"mean_diff={c['mean_diff']} "
                              f"sd_ratio={c['sd_ratio']}")
                    med_cells[f"{iid}/{sname}"] = consistency_cell(
                        ens_z[iid][:, mask], ref_z[iid][:, mask], cfg)
                else:
                    n_reg_total += 1
                    n_reg_breach += bool(c["breach"])
        del pool
    frac = n_reg_breach / max(n_reg_total, 1)
    g1 = (not (national_breach and cfg["consistency"]["national_breach_fails"])
          and frac <= cfg["consistency"]["region_breach_frac_fail"])
    gates["consistency"] = {
        "pass": bool(g1), "basis": cfg["gate_basis"],
        "national_breach": bool(national_breach),
        "region_cells": n_reg_total, "region_breaches": n_reg_breach,
        "region_breach_frac": r6(frac), "cells": cells,
        "ensemble_median_reported": {
            "note": "ensemble MEDIAN vs reference - concentrated by "
                    "construction (median-of-n sd ~ 1.25/sqrt(n)); reported "
                    "for transparency, NOT gated",
            "cells": med_cells}}
    print(f"  national_breach={national_breach}, regional breaches "
          f"{n_reg_breach}/{n_reg_total} ({frac:.1%}) -> "
          f"{'PASS' if g1 else 'FAIL'}")

    # ------------- gate 2: drought statistics (event machinery) ----------
    # Gate basis: events pooled across ALL models per region vs reference
    # events (ensemble-median national stats reported alongside - the
    # median rarely crosses -1.0 by construction).
    print(f"[2/5] drought-statistics gate (basis={cfg['gate_basis']})")
    ev_ref_all = {iid: find_events_matrix(ref_z[iid], EV_CFG["truncation"],
                                          EV_CFG["min_duration"])
                  for iid in IIDS}
    ev_med_all = {iid: find_events_matrix(ens_z[iid], EV_CFG["truncation"],
                                          EV_CFG["min_duration"])
                  for iid in IIDS}
    ev_models_all = {m: {iid: find_events_matrix(models_z[m][iid],
                                                 EV_CFG["truncation"],
                                                 EV_CFG["min_duration"])
                         for iid in IIDS} for m in models}
    all_idx = np.arange(len(dids))
    dstats, med_stats, nb2, tot2 = {}, {}, 0, 0
    for iid in IIDS:
        pooled = {k: np.sum([ev_models_all[m][iid][k] for m in models],
                            axis=0)
                  for k in ("n_complete", "n_censored_complete", "dur_sum",
                            "sev_sum", "drought_months", "finite_months")}
        for rname, ridx in regions.items():
            n_used = int(sum(int(((ev_models_all[m][iid]["finite_months"][ridx] > 0)
                                  & (ev_ref_all[iid]["finite_months"][ridx] > 0)
                                  ).sum()) for m in models))
            st = drought_stats_region(pooled, ev_ref_all[iid], ridx,
                                      n_used, float(years))
            dstats[f"{iid}/{rname}"] = st
            if st["breach"] is None:
                continue
            if rname == "national":
                if st["breach"]:
                    print(f"  NATIONAL BREACH {iid}: freq_ratio="
                          f"{st['freq_ratio']} dur_ratio="
                          f"{st['duration_ratio']} sev_ratio="
                          f"{st['severity_ratio']}")
                n_used_med = int(((ev_med_all[iid]["finite_months"] > 0) &
                                  (ev_ref_all[iid]["finite_months"] > 0)).sum())
                med_stats[iid] = drought_stats_region(
                    ev_med_all[iid], ev_ref_all[iid], all_idx, n_used_med,
                    float(years))
            else:
                tot2 += 1
                nb2 += bool(st["breach"])
    frac2 = nb2 / max(tot2, 1)
    g2 = (not (any(dstats[f"{iid}/national"]["breach"] for iid in IIDS
                   if dstats[f"{iid}/national"]["breach"] is not None)
               and cfg["events"]["national_breach_fails"])
          and frac2 <= cfg["events"]["region_breach_frac_fail"])
    gates["drought_statistics"] = {
        "pass": bool(g2), "basis": cfg["gate_basis"],
        "region_cells": tot2, "region_breaches": nb2,
        "region_breach_frac": r6(frac2), "stats": dstats,
        "ensemble_median_reported": {
            "note": "ensemble MEDIAN events vs reference - a median of "
                    "standardised models rarely crosses the truncation "
                    "level; reported for transparency, NOT gated",
            "national": med_stats}}
    print(f"  regional breaches {nb2}/{tot2} ({frac2:.1%}) -> "
          f"{'PASS' if g2 else 'FAIL'}")

    # ------------- gate 3: per-model ranking ------------------------------
    print("[3/5] per-model ranking (composite, documented weights)")
    rows, per_iid, goodness = rank_models(models_z, ref_z, IIDS, EV_CFG,
                                          cfg["ranking"], float(years))
    sub = select_subset(goodness, models, cfg["ranking"], IIDS)
    subset = sub["subset"]
    # seasonal detail for detail_seasons
    detail = {}
    for sname in cfg["ranking"]["detail_seasons"]:
        months = seasons[sname]
        mask = np.array([m in months for (_y, m) in
                         [(k[0], k[1]) for k in rkeys]])
        for iid in IIDS:
            ref = ref_z[iid][:, mask]
            for m in models:
                x, y, n = pooled_z(models_z[m][iid][:, mask], ref)
                if n == 0:
                    continue
                r = float(np.corrcoef(x, y)[0, 1]) if x.std() > 1e-12 and \
                    y.std() > 1e-12 else None
                detail[f"{m}/{iid}/{sname}"] = {
                    "pearson_r": r6(r), "abs_bias": r6(abs(x.mean() - y.mean())),
                    "rmsd": r6(float(np.sqrt(((x - y) ** 2).mean()))),
                    "n_pairs": n}
    gates["ranking"] = {"pass": True, "rows": rows, "seasonal_detail": detail,
                        "subset": sub}

    # ------------- gate 4: SPI-SPEI divergence (reported, no gate) --------
    print("[4/5] SPI-SPEI divergence (reported, no gate)")
    div = {}
    for sname, months in seasons.items():
        mask = np.array([m in months for (_y, m) in
                         [(k[0], k[1]) for k in rkeys]])
        for rname, ridx in regions.items():
            de = spi_spei_divergence(ens_z["spi_03"][ridx][:, mask],
                                     ens_z["spei_03"][ridx][:, mask])
            dr = spi_spei_divergence(ref_z["spi_03"][ridx][:, mask],
                                     ref_z["spei_03"][ridx][:, mask])
            div[f"{sname}/{rname}"] = {"ensemble": de, "reference": dr}
    gates["divergence"] = {"reported_only": True, "spi_03_vs_spei_03": div}

    # ------------- gate 5: dry tails (amendment M2.11) --------------------
    # Gate basis: pooled multi-model distribution vs reference tails.
    print(f"[5/5] dry-tail gate (basis={cfg['gate_basis']}, Q-Q stored)")
    tcells, med_tcells, nb5, tot5 = {}, {}, 0, 0
    national_breach5 = False
    for iid in IIDS:
        pool = np.stack([models_z[m][iid] for m in models])
        for sname, months in seasons.items():
            mask = np.array([m in months for (_y, m) in rkeys])
            for rname, ridx in regions.items():
                b = ref_z[iid][ridx][:, mask]
                c = pooled_models_cell(pool[:, ridx][:, :, mask], b,
                                       len(models), tail_cell, cfg["tails"])
                if c["breach"] is None:
                    continue
                key = f"{iid}/{sname}/{rname}"
                if rname == "national":
                    b_tiled = np.repeat(b[None], len(models), axis=0)
                    c["qq_pairs"] = qq_pairs(
                        pool[:, ridx][:, :, mask].reshape(-1, mask.sum()),
                        b_tiled.reshape(-1, b.shape[1]), qq_levels)
                    tcells[key] = c
                    if c["breach"]:
                        national_breach5 = True
                        print(f"  NATIONAL TAIL BREACH {iid}/{sname}: "
                              f"{c['tails']}")
                    med_tcells[key] = tail_cell(ens_z[iid][:, mask],
                                                ref_z[iid][:, mask],
                                                cfg["tails"])
                else:
                    tcells[key] = c
                    tot5 += 1
                    nb5 += bool(c["breach"])
        del pool
    frac5 = nb5 / max(tot5, 1)
    g5 = (not (national_breach5 and cfg["tails"]["national_breach_fails"])
          and frac5 <= cfg["tails"]["region_breach_frac_fail"])
    gates["tails"] = {
        "pass": bool(g5), "basis": cfg["gate_basis"],
        "national_breach": bool(national_breach5),
        "region_cells": tot5, "region_breaches": nb5,
        "region_breach_frac": r6(frac5), "cells": tcells,
        "ensemble_median_reported": {
            "note": "ensemble MEDIAN tails - concentrated by construction; "
                    "reported for transparency, NOT gated",
            "national": med_tcells}}
    print(f"  national_breach={national_breach5}, regional breaches "
          f"{nb5}/{tot5} ({frac5:.1%}) -> {'PASS' if g5 else 'FAIL'}")

    # ------------- reporting: clips, missing months, sub-pixel ------------
    fit_reports = {}
    man_p = work_root / "indices_manifest.json"
    if man_p.exists() and cfg["report"]["include_fit_reports"]:
        man = json.loads(man_p.read_text(encoding="utf-8"))
        for k, v in man.get("files", {}).items():
            fr = v.get("fit_report")
            if fr:
                fit_reports[k] = fr
    missing = {m: {iid: int(np.isnan(models_z[m][iid]).sum())
                   for iid in IIDS} for m in models}
    subpixel = []
    sp = work_root / "aggregate" / "sub_pixel_flags.csv"
    if sp.exists():
        with open(sp, encoding="utf-8") as fh:
            subpixel = list(csvmod.DictReader(fh))
    report["gates"] = gates
    report["fit_reports"] = fit_reports
    report["missing_district_months"] = missing
    report["sub_pixel_districts"] = [r.get("district_id") for r in subpixel]

    # ------------- write outputs (work/validation/, X9) -------------------
    out_dir = work_root / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    rep_path = out_dir / "validation_report.json"
    rep_path.write_text(json.dumps(report, indent=2, default=str,
                                   ensure_ascii=False), encoding="utf-8")

    best = {"schema": "die-best-subset/1.1", "seed": SEED,
            "window": [y_lo, y_hi], "n_candidates": len(models),
            "criterion": cfg["ranking"]["subset_criterion"],
            "criterion_rule": sub["rule"],
            "core_size": sub["core"], "core_gap": sub["core_gap"],
            "inclusion_freq_at_floor": sub["inclusion_freq_at_floor"],
            "weights_verbatim": cfg["ranking"]["metrics"],
            "closeness_cap_ratio": cfg["ranking"]["closeness_cap_ratio"],
            "method": "composite rank (8 metrics, min-max normalised across "
                      "models per indicator, mean over indicators); "
                      "free-running decorrelation caveat documented in "
                      "config/validation.yaml; subset size = committed "
                      "stability criterion (largest-gap core extended to "
                      "the registered floor), NOT a fixed count",
            "subset": subset,
            "ranking": [{"rank": rw["rank"], "model": rw["model"],
                         "composite": rw["composite"]} for rw in rows]}
    (out_dir / "best_subset.yaml").write_text(
        yaml.safe_dump(best, sort_keys=False, allow_unicode=True),
        encoding="utf-8")

    import csv as csvmod2
    with open(out_dir / "ranking.csv", "w", newline="", encoding="utf-8") as fh:
        w = csvmod2.writer(fh)
        w.writerow(["rank", "model", "composite"] +
                   [f"{m}" for m in cfg["ranking"]["metrics"]] +
                   ["n_pairs_spi_03"])
        for rw in rows:
            agg = {}
            for k in cfg["ranking"]["metrics"]:
                vals = [rw["per_iid_scores"].get(iid, {}).get(k)
                        for iid in IIDS if iid in rw["per_iid_scores"]]
                vals = [v for v in vals if v is not None]
                agg[k] = r6(float(np.mean(vals))) if vals else ""
            n_pairs = next((rw["per_iid_scores"].get(iid, {}).get("n_pairs")
                            for iid in IIDS if iid in rw["per_iid_scores"]), "")
            w.writerow([rw["rank"], rw["model"], rw["composite"]] +
                       [agg[k] for k in cfg["ranking"]["metrics"]] + [n_pairs])

    man_out = {"schema": 1, "files": {}}
    manp = work_root / "validation_manifest.json"
    if manp.exists():
        man_out = json.loads(manp.read_text(encoding="utf-8"))
    for p in (rep_path, out_dir / "best_subset.yaml", out_dir / "ranking.csv"):
        man_out["files"][p.name] = {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size}
    manp.write_text(json.dumps(man_out, indent=2), encoding="utf-8")

    failed = [k for k, g in gates.items() if g.get("pass") is False]
    print(f"\nGATES: " + ", ".join(
        f"{k}={'PASS' if g.get('pass') else 'FAIL'}"
        for k, g in gates.items() if isinstance(g, dict) and "pass" in g))
    if failed:
        print(f"VALIDATION GATE: FAIL ({failed}) - see {rep_path}")
        print("Gate-failure fallback (committed): two documented remediation "
              "rounds, else publish observed-only v2.0 first "
              "(docs/v2/03 section 3.8). Record attempts in PROGRESS.md.")
        return 1
    print(f"VALIDATION GATE: PASS -> {rep_path}")
    print(f"BEST SUBSET ({len(subset)}): {', '.join(subset)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
