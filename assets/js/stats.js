/* ===========================================================================
 * stats.js — inferential statistics (no DOM access)
 * ---------------------------------------------------------------------------
 *  - Lag-k autocorrelation and effective sample size.
 *  - Mann-Kendall trend test with tie-corrected variance and the Hamed-Rao
 *    (1998) variance correction for serial autocorrelation (applied only
 *    when significant autocorrelation exists; the plain result is always
 *    reported alongside).
 *  - Sen's slope with the rank-based (N - z*sqrt(VarS))/2 confidence bounds.
 *  - Moving-block bootstrap percentile confidence intervals for any
 *    statistic over paired series (deterministic, documented seed).
 *  - Lagged cross-correlation sweeps between two monthly series with
 *    pairwise (matched-month) deletion.
 * Deterministic: the bootstrap uses a fixed-seed PRNG so every export and
 * every reload reproduces the same intervals. Documented in methodology.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});

  /* ------------------------------------------------------------- helpers -- */
  function mean(a) { return a.length ? a.reduce((s, v) => s + v, 0) / a.length : NaN; }

  /** Lag-k autocorrelation (k >= 1) of a complete series. */
  function autocorr(x, k) {
    const n = x.length;
    if (k < 1 || k >= n) return 0;
    const m = mean(x);
    let num = 0, den = 0;
    for (let i = 0; i < n; i++) {
      const d = x[i] - m;
      den += d * d;
      if (i + k < n) num += d * (x[i + k] - m);
    }
    return den > 0 ? num / den : 0;
  }

  /**
   * Hamed-Rao effective-sample-size factor: sum of (n-k)/n * r_k over the
   * *significant* autocorrelations of the detrended series (|r_k| above the
   * 1.96/sqrt(n) white-noise bound), capped at `maxLag`.
   * Returns { rFun (sum term), nSig, lags: [r_k...] , significantLags }.
   */
  function hrCorrection(x, senSlope, maxLag) {
    const n = x.length;
    const cap = Math.min(maxLag || 12, Math.floor(n / 3) || 1);
    // detrend with the Sen slope (Hamed & Rao 1998, §3)
    const det = x.map((v, i) => v - senSlope * i);
    const bound = 1.96 / Math.sqrt(n);
    let sum = 0;
    const significant = [];
    const all = [];
    for (let k = 1; k <= cap; k++) {
      const r = autocorr(det, k);
      all.push(r);
      if (Math.abs(r) > bound) {
        significant.push({ k, r });
        sum += ((n - k) / n) * r;
      }
    }
    return { sum, significant, all, bound, nCap: cap };
  }

  /* --------------------------------------------------- Mann-Kendall test -- */
  /**
   * Mann-Kendall trend test on a complete series x (chronological).
   * Ties are variance-corrected. When significant autocorrelation exists,
   * also applies the Hamed-Rao corrected variance (n_s* effective size).
   * Returns { S, varS, Z, p, n, ties, hr: {applied, nEff, nSig} }.
   */
  function mannKendall(x, senSlope) {
    const n = x.length;
    if (n < 4) return { S: NaN, varS: NaN, Z: NaN, p: NaN, n, ties: 0, hr: { applied: false } };

    let S = 0;
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 1; j < n; j++) S += Math.sign(x[j] - x[i]);
    }
    // tie groups
    const counts = new Map();
    x.forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
    let tieTerm = 0, tieGroups = 0;
    counts.forEach((t) => { if (t > 1) { tieTerm += t * (t - 1) * (2 * t + 5); tieGroups++; } });

    let varS = (n * (n - 1) * (2 * n + 5) - tieTerm) / 18;
    if (varS <= 0) return { S, varS: NaN, Z: NaN, p: NaN, n, ties: tieGroups, hr: { applied: false } };

    const hr = { applied: false, nEff: n, nSig: 0, significantLags: [] };
    if (senSlope !== undefined && Number.isFinite(senSlope)) {
      const c = hrCorrection(x, senSlope, 12);
      if (c.significant.length) {
        const ns = n / (1 + 2 * c.sum);
        if (Number.isFinite(ns) && ns > 0 && ns < n * 2) {
          varS = varS * (n / ns);
          hr.applied = true;
          hr.nEff = ns;
          hr.nSig = c.significant.length;
          hr.significantLags = c.significant;
        }
      }
    }

    const Z = S > 0 ? (S - 1) / Math.sqrt(varS)
      : S < 0 ? (S + 1) / Math.sqrt(varS) : 0;
    // two-sided normal p
    const p = 2 * (1 - stdNormalCdf(Math.abs(Z)));
    return { S, varS, Z, p, n, ties: tieGroups, hr };
  }

  /** Normal CDF via Abramowitz-Stegun 7.1.26 (|erf| error < 1.5e-7). */
  function stdNormalCdf(z) {
    const t = 1 / (1 + 0.2316419 * z);
    const poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return 1 - (Math.exp(-z * z / 2) / Math.sqrt(2 * Math.PI)) * poly;
  }

  /* -------------------------------------------------------- Sen's slope -- */
  /**
   * Sen's slope (median of pairwise slopes) with rank-based confidence
   * interval from the MK variance (Gilbert 1987, §17.3). alpha = 0.10.
   * Returns { slope, ci: [lo, hi], nSlopes, interceptAtFirst }.
   */
  function senSlope(x, alpha) {
    const n = x.length;
    if (n < 4) return { slope: NaN, ci: [NaN, NaN], nSlopes: 0 };
    const slopes = [];
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 1; j < n; j++) slopes.push((x[j] - x[i]) / (j - i));
    }
    slopes.sort((a, b) => a - b);
    const slope = medianSorted(slopes);

    // CI ranks from MK variance (recomputed without HR for stability of the
    // classic Gilbert construction)
    let S = 0;
    for (let i = 0; i < n - 1; i++) for (let j = i + 1; j < n; j++) S += Math.sign(x[j] - x[i]);
    const counts = new Map();
    x.forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
    let tieTerm = 0;
    counts.forEach((t) => { if (t > 1) tieTerm += t * (t - 1) * (2 * t + 5); });
    const varS = Math.max(1e-12, (n * (n - 1) * (2 * n + 5) - tieTerm) / 18);
    const z = normQuantile(1 - (alpha || 0.10) / 2);
    const C = z * Math.sqrt(varS);
    const N = slopes.length;
    const m1 = Math.max(0, Math.round((N - C) / 2));
    const m2 = Math.min(N - 1, Math.round((N + C) / 2));
    return {
      slope,
      ci: [slopes[m1], slopes[m2]],
      nSlopes: N
    };
  }

  function medianSorted(s) {
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /** Normal quantile (inverse CDF), Acklam's rational approximation. */
  function normQuantile(p) {
    if (p <= 0) return -Infinity;
    if (p >= 1) return Infinity;
    const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01];
    const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
    const pl = 0.02425;
    let q, r;
    if (p < pl) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > 1 - pl) {
      q = Math.sqrt(-2 * Math.log(1 - p));
      return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    q = p - 0.5;
    r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  /* -------------------------------------------- moving-block bootstrap -- */
  /** Deterministic PRNG (mulberry32) — fixed seed for reproducibility. */
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /**
   * Moving-block bootstrap CI for a statistic computed on paired series.
   * Blocks are drawn jointly from (x, y) so both autocorrelation and the
   * cross-relationship are preserved. Block length = clamp(n^(1/3), 4, 24).
   * `statistic` receives (xs, ys) and returns a number.
   * Returns { ci: [lo, hi], reps, blockLength, seed }.
   */
  function blockBootstrapCI(x, y, statistic, opts) {
    opts = opts || {};
    const n = x.length;
    const reps = opts.reps || 1000;
    const seed = opts.seed || 20261103;
    if (n < 12) return { ci: [NaN, NaN], reps: 0, blockLength: 0, seed };
    const L = Math.max(4, Math.min(24, Math.round(Math.pow(n, 1 / 3))));
    const nBlocks = Math.ceil(n / L);
    const rnd = mulberry32(seed);
    const stats = [];
    for (let b = 0; b < reps; b++) {
      const xs = [], ys = [];
      for (let k = 0; k < nBlocks; k++) {
        const start = Math.floor(rnd() * (n - L + 1));
        for (let j = 0; j < L && xs.length < n; j++) {
          xs.push(x[start + j]);
          ys.push(y[start + j]);
        }
      }
      const s = statistic(xs, ys);
      if (Number.isFinite(s)) stats.push(s);
    }
    if (!stats.length) return { ci: [NaN, NaN], reps: 0, blockLength: L, seed };
    stats.sort((a, b) => a - b);
    const lo = stats[Math.floor(0.025 * stats.length)];
    const hi = stats[Math.min(stats.length - 1, Math.ceil(0.975 * stats.length))];
    return { ci: [lo, hi], reps: stats.length, blockLength: L, seed };
  }

  /* ----------------------------------------------- lagged cross-correl. -- */
  function pearson(x, y) {
    const n = Math.min(x.length, y.length);
    if (n < 3) return NaN;
    const mx = mean(x.slice(0, n)), my = mean(y.slice(0, n));
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      const dx = x[i] - mx, dy = y[i] - my;
      sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
    }
    return (sxx > 0 && syy > 0) ? sxy / Math.sqrt(sxx * syy) : NaN;
  }

  /**
   * Lagged correlation of two monthly series given as arrays of
   * { ym: 'YYYY-MM', v: number|null }.
   * Lag h pairs A[t] with B[t+h]; h = +2 therefore means "B lags A by two
   * months" (B[t+2] responds to A[t]). Verified against synthetic series.
   * Matched months only; returns per-lag r, n, t and two-sided p.
   */
  function laggedCrossCorrelation(ptsA, ptsB, maxLag) {
    maxLag = maxLag || 12;
    const mapB = new Map();
    ptsB.forEach((p) => { if (p.v !== null && p.v !== undefined) mapB.set(p.ym, p.v); });
    const out = [];
    for (let h = -maxLag; h <= maxLag; h++) {
      const xs = [], ys = [];
      ptsA.forEach((p) => {
        if (p.v === null || p.v === undefined) return;
        // partner month for A at time t is B at t+h
        const partner = shiftYm(p.ym, h);
        const bv = mapB.get(partner);
        if (bv !== undefined) { xs.push(p.v); ys.push(bv); }
      });
      const r = pearson(xs, ys);
      const n = xs.length;
      const t = Number.isFinite(r) && n > 3
        ? r * Math.sqrt((n - 2) / Math.max(1e-12, 1 - r * r)) : NaN;
      const p = Number.isFinite(t) ? 2 * (1 - stdNormalCdf(Math.abs(t))) : NaN;
      out.push({ lag: h, r, n, t, p });
    }
    return out;
  }

  function shiftYm(ym, months) {
    const [y, m] = ym.split('-').map(Number);
    const total = y * 12 + (m - 1) + months;
    const ny = Math.floor(total / 12);
    const nm = (total % 12 + 12) % 12 + 1;
    return ny + '-' + String(nm).padStart(2, '0');
  }

  /** Optimal lag: argmax |r| with n >= minN. Returns {lag, r, n} or null. */
  function optimalLag(lagArr, minN) {
    let best = null;
    lagArr.forEach((d) => {
      if (!Number.isFinite(d.r) || d.n < (minN || 30)) return;
      if (!best || Math.abs(d.r) > Math.abs(best.r)) best = d;
    });
    return best;
  }

  /* -------------------------------------------------------------- public -- */
  DIE.Stats = {
    mean, autocorr, mannKendall, senSlope, stdNormalCdf, normQuantile,
    blockBootstrapCI, pearson, laggedCrossCorrelation, optimalLag, shiftYm,
    mulberry32
  };
})();
