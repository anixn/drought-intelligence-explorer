"""Step 4 — compute drought indicators from the district-month series.

Reads <processed>/series/{precip,pet,soil,ndvi}.csv and writes
<processed>/indicators/<indicator_id>.csv (long format:
district_id, date, value).

Scientific formulation
----------------------
SPI (McKee et al., 1993)
    k-month rolling precipitation totals (complete windows only) are
    standardised per district and calendar month. A two-parameter gamma
    distribution (loc=0) is fitted by maximum likelihood to the base-period
    totals; dry-month zeros are handled with the standard mixed distribution
    H(x) = q + (1 - q) G(x), q = P(x = 0), before the inverse-normal
    transform. This is the NCAR/`climate_indices` convention.

SPEI (Vicente-Serrano et al., 2010)
    The monthly climatic water balance D = P - PET is accumulated over k
    months and standardised per district and calendar month with a
    three-parameter log-logistic distribution. Parameters are estimated with
    the L-moment (probability-weighted-moment) closed form used by the
    reference R `SPEI` package and Singh et al. (1993):

        a = tau3 = l3/l2,  c = 1/a,
        scale = l2 * sin(pi*a) / (pi*a^2),
        loc   = l1 - l2/a

    Small-sample maximum likelihood of the log-logistic location is
    degenerate (loc collapses onto the sample minimum with a near-zero
    scale, biasing every SPEI value wet by ~+0.8); the L-moment estimator
    is unbiased in simulation and recovers known parameters almost exactly.
    Fits with an incompatible sample skew (tau3 <= 0, or a outside
    (0.02, 0.98)) fall back to the empirical transform below, as does any
    fit failing its self-calibration check (|mean(z)| <= 0.2,
    0.75 <= sd(z) <= 1.3 on the base sample).

Empirical fallback (both SPI and SPEI)
    Distribution-free Gringorten plotting-position transform computed on
    average (mid) ranks, the standard treatment of tied values in
    empirical-CDF transforms. Months at or below the dry endpoint of the
    base sample (including exact zeros) map to the tie block's
    mid-percentile; an all-zero base month therefore maps every year to
    z ~ 0 ("identical to climatology") instead of the +2.2 "extremely wet"
    artifact plain np.interp over duplicated values produced, and partial
    ties no longer inherit the largest rank's wet z.

SMA (soil-moisture anomaly, percent of mean)
    100 * (x - mu_m) / mu_m with mu_m the per-calendar-month base-period
    mean of the district-mean volumetric soil water (%). Negative values
    are deficits; thresholds in metadata.json (-5/-15/-30/-50) match this
    statistic. A z-score variant is available via config
    (indicators.sma.statistic: zscore) — if you switch, change the classes
    in metadata.json accordingly.

VCI (Kogan, 1995)
    100 * (x - min_m) / (max_m - min_m) with min_m/max_m the per-calendar-
    month extrema of district-mean NDVI over the (open-ended) MODIS base
    period.

Fitting uses only base-period values; the transform is then applied to the
full record, so indicators are comparable across the whole archive.

Usage
-----
    python -m die_pipeline.indicators
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from . import common

MIN_SAMPLE = 8          # hard floor of base values per district-month fit
CLIP_P = 1e-4           # CDF clip before the inverse-normal transform
TAU3_MIN, TAU3_MAX = 0.02, 0.98   # valid log-logistic L-skew range (a = tau3)


# ---------------------------------------------------------------------------#
# series -> matrices
# ---------------------------------------------------------------------------#

def load_matrix(cfg: dict, var: str, ids: list[str], months) -> np.ndarray:
    """district x month matrix (NaN = missing) for one physical variable."""
    path = common.processed_file(cfg, "series", f"{var}.csv")
    if not os.path.exists(path):
        print(f"  WARNING: no {var} series on disk — indicators depending on "
              f"{var} will be entirely missing until its source is downloaded")
        return np.full((len(ids), len(months)), np.nan)
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str)
    id_pos = {d: i for i, d in enumerate(ids)}
    ym_pos = {common.ym(t): j for j, t in enumerate(months)}
    mat = np.full((len(ids), len(months)), np.nan)
    sub = df[df["mean"].notna()]
    for r in sub.itertuples(index=False):
        i, j = id_pos.get(r.district_id), ym_pos.get(r.date)
        if i is not None and j is not None:
            mat[i, j] = float(r.mean)
    return mat


def rolling_sum(mat: np.ndarray, k: int) -> np.ndarray:
    """k-month rolling totals; windows containing NaN yield NaN."""
    if k == 1:
        return mat.copy()
    out = np.full_like(mat, np.nan)
    T = mat.shape[1]
    for j in range(k - 1, T):
        win = mat[:, j - k + 1:j + 1]
        out[:, j] = np.where(np.isfinite(win).all(axis=1), win.sum(axis=1), np.nan)
    return out


# ---------------------------------------------------------------------------#
# per-calendar-month transforms
# ---------------------------------------------------------------------------#

def _base_cols(months, base_years) -> np.ndarray:
    """Boolean mask of month columns inside the base period."""
    if base_years[1] is None:
        return np.array([y >= base_years[0] for (y, _m) in months])
    return np.array([base_years[0] <= y <= base_years[1] for (y, _m) in months])


def _apply_per_calendar(values: np.ndarray, months, base_mask: np.ndarray,
                        fitter, min_years: int, label: str,
                        report: dict) -> np.ndarray:
    """Fit fitter(base_row) per district & calendar month, transform all years."""
    out = np.full(values.shape, np.nan)
    fitted = calibration_fallbacks = empirical = 0
    cal = np.array([m for (_y, m) in months])
    for m in range(1, 13):
        cols = np.where(cal == m)[0]
        bcols = cols[base_mask[cols]]
        if len(bcols) < min_years:
            report.setdefault("insufficient_base_months", []).append(
                f"{label} month {m}: {len(bcols)} base years < {min_years}")
            continue
        base = values[:, bcols]
        for i in range(values.shape[0]):
            row = base[i][np.isfinite(base[i])]
            if row.size < MIN_SAMPLE:
                continue
            fn = fitter(row)
            ok = False
            if fn is not None:
                zb = fn(row)
                ok = (abs(float(np.mean(zb))) <= 0.2
                      and 0.75 <= float(np.std(zb)) <= 1.3)
            if fn is not None and ok:
                fitted += 1
            else:
                if fn is not None:
                    calibration_fallbacks += 1
                fn = _empirical_transform(row)
                empirical += 1
            out[i, cols] = fn(values[i, cols])
    rep = report.setdefault("per_indicator", {}).setdefault(label, {})
    rep["fits"] = rep.get("fits", 0) + fitted
    rep["calibration_fallbacks"] = rep.get("calibration_fallbacks", 0) + calibration_fallbacks
    rep["empirical_transforms"] = rep.get("empirical_transforms", 0) + empirical
    report["fits"] = report.get("fits", 0) + fitted
    report["calibration_fallbacks"] = report.get("calibration_fallbacks", 0) + calibration_fallbacks
    report["empirical_transforms"] = report.get("empirical_transforms", 0) + empirical
    return out


def _empirical_transform(base_row):
    """Tie-aware Gringorten plotting-position transform over the base sample.

    Distinct base values receive Gringorten positions p_i = (r_i - 0.44) /
    (n + 0.12) computed on AVERAGE (mid) ranks, the standard treatment of
    ties in empirical-CDF transforms.  Consequences:

    * no ties -> plain Gringorten transform (base z has mean ~ 0, sd ~ 1);
    * a tie block at the dry end maps to the block's mid-percentile, so a
      zero-rainfall month is never assigned the wettest rank;
    * a fully tied base month (e.g. an all-zero arid sample) maps every
      year to z ~ 0 ("identical to climatology") instead of the +2.2
      "extremely wet" artifact plain np.interp over duplicated x values
      produced (np.interp returns the value at the LAST duplicate);
    * values beyond the base extremes are clamped to the end z values (a
      conservative choice for monitoring).
    """
    xs = np.sort(np.asarray(base_row, dtype=float))
    n = xs.size
    xd, zd = [], []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        mid = (i + j + 2) / 2.0            # average of 1-based ranks i+1..j+1
        p = (mid - 0.44) / (n + 0.12)
        xd.append(xs[i])
        zd.append(stats.norm.ppf(min(max(p, 1e-4), 1.0 - 1e-4)))
        i = j + 1
    xd = np.asarray(xd, dtype=float)
    zd = np.asarray(zd, dtype=float)

    def fn(x):
        x = np.asarray(x, dtype=float)
        z = np.full_like(x, np.nan)
        finite = np.isfinite(x)
        if finite.any():
            # np.interp clamps beyond the endpoints, which is the intended
            # conservative behaviour outside the base range.
            z[finite] = np.interp(x[finite], xd, zd)
        return z
    return fn


def _gamma_spi(base_row):
    """Mixed gamma / inverse-normal transform factory (SPI convention)."""
    q = float(np.mean(base_row <= 0))
    pos = base_row[base_row > 0]
    if pos.size < MIN_SAMPLE or np.all(pos == pos[0]):
        return None
    try:
        a, _loc, scale = stats.gamma.fit(pos, floc=0.0)
    except Exception:                                     # noqa: BLE001
        return None
    if not (np.isfinite(a) and np.isfinite(scale) and a > 0 and scale > 0):
        return None

    def fn(x):
        x = np.asarray(x, dtype=float)
        # Missing inputs (e.g. warm-up months whose rolling window is
        # incomplete) must stay missing.  A plain ``np.where`` would send NaN
        # down the ``<= 0`` branch and encode it as the CLIP_P floor
        # (-3.72), which is indistinguishable from a record drought.
        finite = np.isfinite(x)
        cdf = np.zeros_like(x)
        positive = finite & (x > 0)
        if positive.any():
            cdf[positive] = stats.gamma.cdf(x[positive], a, 0.0, scale)
        H = q + (1.0 - q) * cdf
        z = stats.norm.ppf(np.clip(H, CLIP_P, 1.0 - CLIP_P))
        z[~finite] = np.nan
        return z
    return fn


def _loglogistic_lmoments(base_row):
    """L-moments l1, l2, l3 (unbiased PWM estimators)."""
    xs = np.sort(np.asarray(base_row, dtype=float))
    n = xs.size
    i = np.arange(1, n + 1)
    b0 = float(xs.mean())
    b1 = float(np.sum((i - 1) * xs) / (n * (n - 1)))
    b2 = float(np.sum((i - 1) * (i - 2) * xs) / (n * (n - 1) * (n - 2)))
    l1 = b0
    l2 = 2.0 * b1 - b0
    l3 = 6.0 * b2 - 6.0 * b1 + b0
    return l1, l2, l3


def _loglogistic_spei(base_row):
    """Three-parameter log-logistic transform, L-moment fitted.

    The closed-form L-moment estimators (Vicente-Serrano et al., 2010 /
    Singh et al., 1993 — the method used by the R SPEI package) are:

        a     = l3 / l2                (L-skewness, tau3)
        c     = 1 / a                  (scipy fisk shape)
        scale = l2 * sin(pi*a) / (pi*a^2)
        loc   = l1 - l2 / a

    Maximum likelihood is deliberately NOT used here: on n ~ 30-40 base
    years the MLE drives loc onto min(sample) with a vanishing scale, which
    compresses the whole CDF into a fraction of the unit interval and bias
    every transformed SPEI wet by roughly +0.8 z.  The L-moment fit is
    unbiased on simulated water balances and recovers known parameters to
    ~1% at n = 50k, and stays calibrated at the operational n = 30-40.
    """
    row = np.asarray(base_row, dtype=float)
    if row.size < MIN_SAMPLE or np.allclose(row, row[0]):
        return None
    l1, l2, l3 = _loglogistic_lmoments(row)
    if not np.isfinite([l1, l2, l3]).all() or l2 <= 0:
        return None
    a = l3 / l2
    if not (TAU3_MIN < a < TAU3_MAX):
        return None
    c = 1.0 / a
    scale = l2 * np.sin(np.pi * a) / (np.pi * a * a)
    loc = l1 - l2 / a
    if not (np.isfinite(c) and np.isfinite(loc) and np.isfinite(scale)
            and c > 0 and scale > 0):
        return None

    def fn(x):
        x = np.asarray(x, dtype=float)
        finite = np.isfinite(x)
        F = np.full_like(x, np.nan)
        if finite.any():
            F[finite] = stats.fisk.cdf(x[finite], c, loc, scale)
        return stats.norm.ppf(np.clip(F, CLIP_P, 1.0 - CLIP_P))
    return fn


# ---------------------------------------------------------------------------#
# indicator drivers
# ---------------------------------------------------------------------------#

def compute(cfg: dict) -> dict:
    districts, _states = common.load_registry(cfg)
    ids = [d["district_id"] for d in districts]

    # full month axis = union of what the series files actually contain
    dates = set()
    for var in ("precip", "pet", "soil", "ndvi"):
        p = common.processed_file(cfg, "series", f"{var}.csv")
        if os.path.exists(p):
            try:
                d = pd.read_csv(p, usecols=["date"])
                if len(d):
                    dates.update(d["date"].astype(str))
            except Exception:
                pass
    if not dates:
        common.die("no series files found — run zonal_stats first")
    end = cfg["history"]["end"] or max(dates)
    months = common.month_range(cfg["history"]["start"], end)
    date_cols = [common.ym(t) for t in months]

    base_mask = _base_cols(months, cfg["base_period"]["spi_spei"])
    min_years = int(cfg.get("min_base_years", 20))
    vci_base = cfg["base_period"]["vci"]

    precip = load_matrix(cfg, "precip", ids, months)
    pet = load_matrix(cfg, "pet", ids, months)
    soil = load_matrix(cfg, "soil", ids, months)
    ndvi = load_matrix(cfg, "ndvi", ids, months)

    report: dict = {"months": len(months), "period": [date_cols[0], date_cols[-1]],
                    "districts": len(ids), "min_base_years": min_years}

    out_dir = common.processed_dir(cfg, "indicators")

    for spec in cfg["indicators"]:
        iid, kind = spec["id"], spec["kind"]
        print(f"  {iid:8s} ({kind})", end="  ")
        if kind == "spi":
            mat = _apply_per_calendar(rolling_sum(precip, spec["scale"]), months,
                                      base_mask, _gamma_spi, min_years, iid, report)
        elif kind == "spei":
            wb = np.where(np.isfinite(precip) & np.isfinite(pet),
                          precip - pet, np.nan)
            mat = _apply_per_calendar(rolling_sum(wb, spec["scale"]), months,
                                      base_mask, _loglogistic_spei, min_years, iid, report)
        elif kind == "sma":
            mat = _sma(soil, months, base_mask, spec.get("statistic", "percent_mean"))
        elif kind == "vci":
            mat = _vci(ndvi, months, _base_cols(months, vci_base))
        else:
            raise ValueError(f"unknown indicator kind: {kind}")

        rows = [{"district_id": ids[i], "date": date_cols[j],
                 "value": mat[i, j]}
                for i in range(mat.shape[0])
                for j in range(mat.shape[1])
                if np.isfinite(mat[i, j])]
        df = pd.DataFrame(rows, columns=["district_id", "date", "value"])
        df.to_csv(common.processed_file(cfg, "indicators", f"{iid}.csv"), index=False)
        finite = mat[np.isfinite(mat)]
        print(f"values={finite.size} ({finite.size / mat.size * 100:.1f}% of grid) "
              f"mean={finite.mean():+.2f} sd={finite.std():.2f}")

    with open(common.processed_file(cfg, "indicators", "_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return report


def _sma(soil: np.ndarray, months, base_mask: np.ndarray, statistic: str) -> np.ndarray:
    out = np.full(soil.shape, np.nan)
    cal = np.array([m for (_y, m) in months])
    for m in range(1, 13):
        cols = np.where(cal == m)[0]
        bcols = cols[base_mask[cols]]
        base = soil[:, bcols]
        if base.shape[1] == 0:
            continue
        if statistic == "zscore":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                mu = np.nanmean(base, axis=1)
                sd = np.nanstd(base, axis=1)
            ok = np.isfinite(mu) & np.isfinite(sd) & (sd > 0)
            for i in np.where(ok)[0]:
                out[i, cols] = (soil[i, cols] - mu[i]) / sd[i]
        else:  # percent_mean
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                mu = np.nanmean(base, axis=1)
            ok = np.isfinite(mu) & (np.abs(mu) > 1e-6)
            for i in np.where(ok)[0]:
                out[i, cols] = 100.0 * (soil[i, cols] - mu[i]) / mu[i]
    return out


def _vci(ndvi: np.ndarray, months, base_mask: np.ndarray) -> np.ndarray:
    out = np.full(ndvi.shape, np.nan)
    cal = np.array([m for (_y, m) in months])
    for m in range(1, 13):
        cols = np.where(cal == m)[0]
        bcols = cols[base_mask[cols]]
        if bcols.size == 0:
            continue
        base = ndvi[:, bcols]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            lo = np.nanmin(base, axis=1)
            hi = np.nanmax(base, axis=1)
        with np.errstate(invalid="ignore"):
            span_ok = np.isfinite(lo) & np.isfinite(hi) & ((hi - lo) > 1e-6)
        for i in np.where(span_ok)[0]:
            out[i, cols] = np.clip(100.0 * (ndvi[i, cols] - lo[i]) / (hi[i] - lo[i]),
                                   0.0, 100.0)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    cfg = common.load_config(args.config)
    common.banner("Compute indicators (SPI / SPEI / SMA / VCI)")
    rep = compute(cfg)
    common.hr()
    print(f"months {rep['period'][0]}..{rep['period'][1]}, "
          f"parametric fits kept: {rep.get('fits', 0)}, "
          f"parametric fits rejected (calibration): {rep.get('calibration_fallbacks', 0)}, "
          f"empirical transforms: {rep.get('empirical_transforms', 0)}")
    for iid, r in (rep.get("per_indicator") or {}).items():
        print(f"  {iid:8s} fits={r.get('fits', 0):6d} "
              f"calibration_fallbacks={r.get('calibration_fallbacks', 0):6d} "
              f"empirical={r.get('empirical_transforms', 0):6d}")
    if rep.get("insufficient_base_months"):
        print("WARNING: some calendar months had fewer base years than "
              "min_base_years and were left as missing:")
        for line in rep["insufficient_base_months"][:8]:
            print("   " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
