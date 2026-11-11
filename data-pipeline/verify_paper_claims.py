#!/usr/bin/env python3
"""Reproduce the quantified methodological evidence quoted in the manuscript.

Every number in the paper's Methods and Technical Validation sections that
refers to a statistical experiment is produced by this script, so a reviewer
can check each claim with one command:

    python verify_paper_claims.py          # all six experiments
    python verify_paper_claims.py v2 v6    # any subset

Experiments (labels match the manuscript's Code availability section):

    v1   L-moment parameter recovery of the log-logistic fit at n = 50,000
    v2   small-sample MLE wet bias of the log-logistic SPEI fit at n = 40
         (300 synthetic replications, L-moments as the control)
    v3   tie handling of the Gringorten empirical transform (all-tied,
         tie-free and dry-end tie-block base samples)
    v4   classification continuity: the metadata class tables form a
         contiguous partition, and every finite released value falls in
         exactly one class
    v5   area-weighting accuracy: state means recomputed from the released
         district matrices against the published summary file, area-weighted
         versus unweighted
    v6   Benjamini-Hochberg false-discovery-rate demonstration on the
         released SPI-3 trend map (annual Mann-Kendall, 724 districts)

The log-logistic simulation truth (v1, v2) is the median L-moment fit over
all district-month water-balance base samples of the released build where the
family applies (6,493 fits; loc = -420.5, scale = 248.4, c = 8.381, i.e.
L-skew tau3 = 0.119), measured from data_processed/series. The random seed
is the release seed 20261103, so every number below is deterministic.

Exits 0 when all requested experiments pass, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from die_pipeline import common                     # noqa: E402
from die_pipeline.indicators import _empirical_transform, _loglogistic_lmoments  # noqa: E402

SEED = 20261103                       # the release seed quoted in the paper
N_SIM = 300                           # replications for the n = 40 experiment
N_RECOVER = 50_000                    # sample size for the recovery experiment
# Median L-moment fit over the released water-balance base samples:
TRUTH = {"loc": -420.5274, "scale": 248.4026, "c": 8.3814}


def _lm_fit(sample: np.ndarray):
    """Closed-form L-moment log-logistic fit -> (c, loc, scale) or None."""
    row = np.asarray(sample, dtype=float)
    if row.size < 8 or np.allclose(row, row[0]):
        return None
    l1, l2, l3 = _loglogistic_lmoments(row)
    if not np.isfinite([l1, l2, l3]).all() or l2 <= 0:
        return None
    a = l3 / l2
    if not (0.02 < a < 0.98):
        return None
    scale = l2 * np.sin(np.pi * a) / (np.pi * a * a)
    loc = l1 - l2 / a
    if not (np.isfinite(loc) and np.isfinite(scale) and scale > 0):
        return None
    return 1.0 / a, loc, scale


def _transform(x: np.ndarray, c: float, loc: float, scale: float) -> np.ndarray:
    """Fit-CDF / inverse-normal transform (the pipeline's SPEI step)."""
    F = stats.fisk.cdf(np.asarray(x, dtype=float), c, loc, scale)
    return stats.norm.ppf(np.clip(F, 1e-4, 1.0 - 1e-4))


def v1_lmoment_recovery() -> bool:
    """L-moments recover known log-logistic parameters at n = 50,000."""
    rng = np.random.default_rng(SEED)
    x = stats.fisk.rvs(TRUTH["c"], TRUTH["loc"], TRUTH["scale"],
                       size=N_RECOVER, random_state=rng)
    fit = _lm_fit(x)
    ok = fit is not None
    if ok:
        c, loc, scale = fit
        err = (abs(loc - TRUTH["loc"]) / abs(TRUTH["loc"]),
               abs(scale - TRUTH["scale"]) / TRUTH["scale"],
               abs(c - TRUTH["c"]) / TRUTH["c"])
        ok = max(err) < 0.02
        print(f"    recovered loc {loc:9.2f} (truth {TRUTH['loc']:9.2f}), "
              f"scale {scale:8.3f} (truth {TRUTH['scale']:8.3f}), "
              f"c {c:7.4f} (truth {TRUTH['c']:7.4f})")
        print(f"    max relative error {max(err) * 100:.2f}% at n = {N_RECOVER:,}"
              "  (paper: about 1%)")
    else:
        print("    fit failed")
    print(f"  [{'PASS' if ok else 'FAIL'}] v1: L-moment parameter recovery")
    return ok


def v2_mle_wet_bias() -> bool:
    """At the operational n = 40, MLE biases transformed SPEI wet; L-moments do not."""
    rng = np.random.default_rng(SEED + 1)
    mle_means, lm_means, mle_failed = [], [], 0
    loc_on_min, scales = 0, []
    for _ in range(N_SIM):
        x = stats.fisk.rvs(TRUTH["c"], TRUTH["loc"], TRUTH["scale"],
                           size=40, random_state=rng)
        fit = _lm_fit(x)
        if fit is not None:
            lm_means.append(float(np.mean(_transform(x, *fit))))
        try:
            c, loc, scale = stats.fisk.fit(x)
            z = _transform(x, c, loc, scale)
            mle_means.append(float(np.mean(z)))
            scales.append(scale)
            if loc <= x.min() + 1e-6 * max(1.0, abs(x.min())):
                loc_on_min += 1
        except Exception:                              # noqa: BLE001
            mle_failed += 1
    mle, lm = float(np.mean(mle_means)), float(np.mean(lm_means))
    ok = mle > 0.3 and abs(lm) < 0.1
    print(f"    {N_SIM} replications at n = 40, truth "
          f"(loc {TRUTH['loc']}, scale {TRUTH['scale']}, c {TRUTH['c']}):")
    print(f"    mean transformed base value: MLE {mle:+.2f} z vs "
          f"L-moments {lm:+.2f} z  (paper: +0.68 vs +0.02)")
    print(f"    MLE drove the location onto the sample minimum in "
          f"{loc_on_min}/{N_SIM - mle_failed} usable fits "
          f"(median fitted scale {np.median(scales):.3g} vs truth "
          f"{TRUTH['scale']:.3g}); {mle_failed} fits failed outright")
    print(f"  [{'PASS' if ok else 'FAIL'}] v2: small-sample MLE wet bias")
    return ok


def v3_gringorten_ties() -> bool:
    """Tie-aware Gringorten transform: ties never fabricate extreme wetness."""
    rng = np.random.default_rng(SEED + 2)
    ok = True

    z_all = _empirical_transform(np.zeros(40))(np.zeros(40))
    ok &= bool(np.all(np.abs(z_all) < 0.1))
    print(f"    all-tied base sample (40 zeros): z in "
          f"[{z_all.min():+.3f}, {z_all.max():+.3f}] "
          "(a plain transform would give the wettest rank, about +2.2)")

    x = stats.norm.rvs(size=40, random_state=rng)
    zb = _empirical_transform(x)(x)
    ok &= bool(abs(zb.mean()) < 0.1 and 0.9 < zb.std() < 1.05)
    print(f"    tie-free base sample: base z mean {zb.mean():+.3f}, "
          f"sd {zb.std():.3f}")

    pos = stats.gamma.rvs(2.0, scale=25.0, size=35, random_state=rng)
    base = np.sort(np.concatenate([np.zeros(5), pos]))   # dry-end tie block
    z0 = float(_empirical_transform(base)(np.zeros(1))[0])
    ok &= bool(z0 < 0)
    print(f"    dry-end tie block (5 zero months in 40): zero month maps to "
          f"z = {z0:+.3f} (below zero, never the wettest rank)")
    print(f"  [{'PASS' if ok else 'FAIL'}] v3: Gringorten tie handling")
    return ok


def v4_classification_continuity() -> bool:
    """Metadata classes form a contiguous partition of each indicator's range."""
    cfg = common.load_config()
    meta_path = os.path.join(common.app_data_dir(cfg), "metadata.json")
    import json
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    ok = True
    for ind in meta["indicators"]:
        classes = ind["classes"]
        # (lower, upper, lower_closed, upper_closed) intervals in class order
        intervals = [(c["min"], c["max"],
                      bool(c["minClosed"]), bool(c["maxClosed"]))
                     for c in classes]
        if ind["id"] == "vci":
            # the VCI table is deliberately closed at both ends (0 and 100)
            ok &= intervals[0][0] == 0.0 and intervals[-1][1] == 100.0
        else:
            # z and SMA tables are open below the first and above the last class
            ok &= (intervals[0][0] is None or intervals[0][1] is None) and \
                  (intervals[-1][0] is None or intervals[-1][1] is None)
        contiguous = True
        for a, b in zip(intervals, intervals[1:]):
            if a[1] is None or b[0] is None or a[1] != b[0]:
                contiguous = False
            if a[0] is not None and b[0] is not None and b[0] < a[0]:
                contiguous = False            # order must be monotone
        ok &= contiguous
    print(f"    {len(meta['indicators'])} indicator class tables checked: "
          "ordered, contiguous, one open end (VCI closed at 0 and 100)")

    # value coverage on three released matrices (one per family)
    import csv as _csv
    for fname, scale in (("spi_03.csv", "z"), ("soil_moisture.csv", "%"),
                         ("vci.csv", "%")):
        path = os.path.join(common.app_data_dir(cfg), "drought", fname)
        ind = next(i for i in meta["indicators"]
                   if i["file"].endswith(fname))
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(_csv.reader(fh))
        vals = np.array([
            float(cell) for r in rows[1:] if r
            for cell in r[3:] if cell.strip() != ""], dtype=float)
        in_exactly_one = np.zeros(vals.shape[0], dtype=int)
        for c in ind["classes"]:
            lo, hi = c["min"], c["max"]
            m = np.ones(vals.shape[0], dtype=bool)
            if lo is not None:
                m &= vals > lo if not c["minClosed"] else vals >= lo
            if hi is not None:
                m &= vals < hi if not c["maxClosed"] else vals <= hi
            in_exactly_one += m
        covered = float(np.mean(in_exactly_one == 1))
        ok &= covered == 1.0
        print(f"    {fname}: {len(vals):,} values, {covered * 100:.4f}% in "
              "exactly one class")
    print(f"  [{'PASS' if ok else 'FAIL'}] v4: classification continuity")
    return ok


def v5_area_weighting() -> bool:
    """Published state means are the area-weighted rule, not unweighted means."""
    cfg = common.load_config()
    import csv as _csv
    with open(os.path.join(common.app_data_dir(cfg), "districts.csv"),
              encoding="utf-8") as fh:
        districts = list(_csv.DictReader(fh))
    area = {d["district_id"]: float(d["area_km2"]) for d in districts}
    state_of = {d["district_id"]: d["state_id"] for d in districts}
    with open(os.path.join(common.app_data_dir(cfg), "drought", "spi_06.csv"),
              newline="", encoding="utf-8") as fh:
        rows = list(_csv.reader(fh))
    header = rows[0]
    ids = [r[0] for r in rows[1:] if r]
    j = {d: k for k, d in enumerate(ids)}
    months = header[3:]
    w = np.array([area[i] for i in ids])
    with open(os.path.join(common.app_data_dir(cfg), "summaries",
                           "state_statistics_spi_06.csv"),
              newline="", encoding="utf-8") as fh:
        summary = list(_csv.DictReader(fh))
    d_weighted, d_unweighted = [], []
    for row in summary:
        sid, published = row["state_id"], row["mean"]
        if published == "":
            continue
        members = [k for d, k in j.items() if state_of[d] == sid]
        if not members:
            continue
        vals = np.array([
            float(np.mean([float(rows[1 + k][3 + jj])
                           for jj in range(len(months))
                           if rows[1 + k][3 + jj].strip() != ""]))
            for k in members])
        wv = w[members]
        finite = np.isfinite(vals)
        weighted = np.nansum(np.where(finite, vals, 0) * np.where(finite, wv, 0)) \
            / np.sum(np.where(finite, wv, 0))
        unweighted = np.nanmean(vals)
        d_weighted.append(abs(weighted - float(published)))
        d_unweighted.append(abs(unweighted - float(published)))
    wm, um = float(np.mean(d_weighted)), float(np.mean(d_unweighted))
    print(f"    recomputed each State/UT mean from the released SPI-6 matrix "
          f"({len(d_weighted)} States and UTs):")
    print(f"    average absolute difference vs the published mean column: "
          f"area-weighted {wm:.4f}, unweighted {um:.4f}  "
          "(paper: 0.0002 vs 0.0043)")
    ok = wm < 0.001 and wm < um
    print(f"  [{'PASS' if ok else 'FAIL'}] v5: area-weighting accuracy")
    return ok


def _mk_test(y: np.ndarray) -> float:
    """Tie-corrected Mann-Kendall two-sided p-value for one series."""
    y = y[np.isfinite(y)]
    n = y.size
    if n < 4:
        return np.nan
    s = 0
    for k in range(n - 1):
        s += int(np.sum(y[k + 1:] > y[k])) - int(np.sum(y[k + 1:] < y[k]))
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5)
           - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    if var <= 0 or s == 0:
        return 1.0
    z = (s - 1) / np.sqrt(var) if s > 0 else (s + 1) / np.sqrt(var)
    return float(2.0 * stats.norm.sf(abs(z)))


def v6_bh_demonstration() -> bool:
    """Benjamini-Hochberg FDR demonstration on the released SPI-3 trend map."""
    cfg = common.load_config()
    ids, date_cols, mat = common.read_wide_csv(os.path.join(
        common.app_data_dir(cfg), "drought", "spi_03.csv"))
    years = sorted({int(c[:4]) for c in date_cols})
    annual = np.full((len(ids), len(years)), np.nan)
    for k, yr in enumerate(years):
        cols = [jj for jj, c in enumerate(date_cols) if int(c[:4]) == yr]
        block = mat[:, cols]
        valid = np.isfinite(block).sum(axis=1)
        with np.errstate(invalid="ignore"):
            ann = np.where(valid >= 9, np.nanmean(block, axis=1), np.nan)
        annual[:, k] = ann
    p = np.array([_mk_test(annual[i]) for i in range(len(ids))])
    alpha, q = 0.05, 0.05
    tested = np.isfinite(p)
    sig_uncorrected = int(np.sum(tested & (p < alpha)))
    order = np.argsort(p[tested])
    m = int(tested.sum())
    ranked = p[tested][order]
    below = np.where(ranked <= q * (np.arange(1, m + 1) / m))[0]
    # 0-based index -> step-up rank count; equal p-values are one tie block
    # and all fall inside the same block
    sig_bh = int(below.max()) + 1 if below.size else 0
    # direction of the uncorrected significant districts: first-to-last
    sig_idx = np.where(tested & (p < alpha))[0]
    first, last = annual[:, 0], annual[:, len(years) - 1]
    wetting = int(np.sum(last[sig_idx] > first[sig_idx]))
    drying = int(np.sum(last[sig_idx] < first[sig_idx]))
    print(f"    annual SPI-3 means ({years[0]}-{years[-1]}, at least 9 valid "
          f"months per year), tie-corrected Mann-Kendall, {len(ids)} districts:")
    print(f"    significant at alpha = 0.05 uncorrected: {sig_uncorrected} "
          f"({sig_uncorrected / len(ids) * 100:.1f}%)  (paper: 382, 52.8%)")
    print(f"    significant after Benjamini-Hochberg at q = 0.05: {sig_bh} "
          f"({sig_bh / len(ids) * 100:.1f}%)  (paper: 324, 44.8%)")
    print(f"    direction of the uncorrected significant districts "
          f"(first-to-last): {wetting} wetting vs {drying} drying  "
          "(paper: 370 vs 12)")
    ok = (sig_uncorrected == 382 and sig_bh == 324
          and wetting == 370 and drying == 12)
    print(f"  [{'PASS' if ok else 'FAIL'}] v6: Benjamini-Hochberg trend demonstration")
    return ok


EXPERIMENTS = {
    "v1": ("L-moment parameter recovery", v1_lmoment_recovery),
    "v2": ("small-sample MLE wet bias (n = 40)", v2_mle_wet_bias),
    "v3": ("Gringorten tie handling", v3_gringorten_ties),
    "v4": ("classification continuity", v4_classification_continuity),
    "v5": ("area-weighting accuracy", v5_area_weighting),
    "v6": ("Benjamini-Hochberg trend demonstration", v6_bh_demonstration),
}


def main(argv=None) -> int:
    wanted = [a.lower() for a in (argv or sys.argv[1:]) if not a.startswith("-")]
    keys = [k for k in EXPERIMENTS if not wanted or k in wanted]
    print("Drought Intelligence Explorer - paper-claim verification")
    print(f"seed {SEED} (release seed); experiments: {', '.join(keys)}\n")
    results = {}
    for k in keys:
        label, fn = EXPERIMENTS[k]
        print(f"  {k.upper()} - {label}")
        t0 = time.time()
        try:
            results[k] = fn()
        except Exception as exc:                       # noqa: BLE001
            print(f"    ERROR: {type(exc).__name__}: {exc}")
            results[k] = False
        print(f"    ({time.time() - t0:.1f} s)\n")
    n_ok = sum(results.values())
    for k, ok in results.items():
        print(f"  [{('PASS' if ok else 'FAIL')}] {k.upper()}: "
              f"{EXPERIMENTS[k][0]}")
    print(f"\nresult: {n_ok}/{len(results)} experiment(s) reproduced the "
          "quoted evidence")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
