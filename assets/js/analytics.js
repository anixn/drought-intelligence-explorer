/* ===========================================================================
 * analytics.js — client-side scientific computations
 * ---------------------------------------------------------------------------
 *  - Areal (area-weighted) regional statistics and KPI inputs.
 *  - Severity distribution bins (area km², %, district counts).
 *  - District and regional monthly series with valid-observation counts.
 *  - Drought events by runs analysis (Yevjevich, 1967): threshold = upper
 *    bound of the moderate-drought class of each indicator (−1.0 for
 *    SPI/SPEI z-scores; −15% SMA; 30% VCI), minimum duration 3 months.
 *  - Historical aggregates (frequency, duration, severity).
 *  - Regional comparison rows (states or districts).
 *  - Multi-indicator agreement statistics (pairwise-complete).
 *  - CSV export builders (long-format schema, district summaries, table).
 * All functions take plain dataset objects from data-loader and registry
 * lookups — no DOM access, fully unit-testable from the console.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});

  /* --------------------------------------------------------- statistics -- */
  function mean(a) { return a.length ? a.reduce((s, v) => s + v, 0) / a.length : NaN; }
  function median(a) {
    if (!a.length) return NaN;
    const s = [...a].sort((x, y) => x - y);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /* ------------------------------------------------------------ memo cache --
   * Heavy aggregates (724 districts × 540 months) are recomputed several
   * times by different panels with identical inputs. Memoise per dataset
   * object; keys describe the region, period and options. The cache clears
   * when it grows, so switching indicators cannot leak memory. */
  function memoize(fn, keyFn) {
    const cache = new WeakMap();
    return function () {
      const first = arguments[0];
      let map = cache.get(first);
      if (!map) { map = new Map(); cache.set(first, map); }
      const key = keyFn.apply(null, arguments);
      if (map.has(key)) return map.get(key);
      const value = fn.apply(null, arguments);
      if (map.size >= 64) map.clear();
      map.set(key, value);
      return value;
    };
  }
  function idsKey(ids) {
    if (!ids || !ids.length) return '0';
    return ids.length + ':' + ids[0] + ':' + ids[ids.length - 1];
  }
  function periodKey(period, season) {
    return (period ? period.from : '') + '-' + (period ? period.to : '') + '-' + (season || 'all');
  }
  /** Stable key for districtStats-style options (threshold/duration/season). */
  function optsKey(opts) {
    opts = opts || {};
    return (opts.threshold !== undefined ? opts.threshold : 'd') + '|' +
      (opts.minDuration !== undefined ? opts.minDuration : 'd') + '|' +
      (opts.season || 'all') + '|' + (opts.granularity || 'd');
  }
  function pearson(x, y) {
    const n = x.length;
    if (n < 3) return NaN;
    const mx = mean(x), my = mean(y);
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      const dx = x[i] - mx, dy = y[i] - my;
      sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
    }
    return (sxx > 0 && syy > 0) ? sxy / Math.sqrt(sxx * syy) : NaN;
  }
  function ols(x, y) {
    const n = x.length;
    if (n < 2) return null;
    const mx = mean(x), my = mean(y);
    let sxy = 0, sxx = 0;
    for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; }
    if (sxx === 0) return null;
    const slope = sxy / sxx;
    return { slope, intercept: my - slope * mx, n };
  }

  /** Drought threshold: upper bound of the moderate-drought class. */
  function droughtThreshold(indicator) {
    const c = indicator.classes.find((c) => c.key === 'moderate_drought');
    return c ? c.max : -1.0;
  }

  /* -------------------------------------------------- region statistics -- */
  /**
   * Snapshot statistics for a set of districts at one date index.
   * Returns areas in equal-area km², area-weighted mean, class counts and
   * the change relative to the previous available observation.
   */
  function regionStats(ds, dateIdx, ids) {
    const ind = ds.indicator;
    const out = {
      dateIdx, totalArea: 0, withDataArea: 0, affectedArea: 0, severeArea: 0,
      mean: NaN, n: 0, nDrought: 0, nSevere: 0, nNoData: 0,
      districtsTotal: ids.length, prev: null
    };
    let wsum = 0, wval = 0;
    ids.forEach((id) => {
      const d = DIE.registry.districts.get(id);
      if (!d) return;
      const i = ds.districtIndex.get(id);
      const v = (i === undefined) ? NaN : ds.values[i][dateIdx];
      out.totalArea += d.area;
      if (!Number.isFinite(v)) { out.nNoData++; return; }
      out.n++;
      out.withDataArea += d.area;
      wval += v * d.area; wsum += d.area;
      const c = DIE.classify(v, ind);
      if (DIE.isDroughtClass(c)) { out.affectedArea += d.area; out.nDrought++; }
      if (DIE.isSevereClass(c)) { out.severeArea += d.area; out.nSevere++; }
    });
    out.mean = wsum > 0 ? wval / wsum : NaN;
    out.meanClass = DIE.classify(out.mean, ind);
    out.affectedPct = out.totalArea > 0 ? out.affectedArea / out.totalArea * 100 : NaN;
    out.severePct = out.totalArea > 0 ? out.severeArea / out.totalArea * 100 : NaN;

    if (dateIdx > 0) {
      out.prev = regionStatsCached(ds, dateIdx - 1, ids);
      out.prevDateIdx = dateIdx - 1;
    }
    return out;
  }
  const regionStatsCached = memoize(regionStats, (ds, dateIdx, ids) =>
    ds.id + '|' + dateIdx + '|' + idsKey(ids));

  /* --------------------------------------------- severity distribution -- */
  function severityDistribution(ds, dateIdx, ids) {
    const ind = ds.indicator;
    const bins = {};
    DIE.Charts.DIST_BINS.forEach((b) => { bins[b.key] = { area: 0, pct: 0, districts: 0 }; });
    let regionArea = 0, anyData = false, noDataArea = 0;
    ids.forEach((id) => {
      const d = DIE.registry.districts.get(id);
      if (!d) return;
      regionArea += d.area;
      const i = ds.districtIndex.get(id);
      const v = (i === undefined) ? NaN : ds.values[i][dateIdx];
      if (!Number.isFinite(v)) { noDataArea += d.area; return; }
      anyData = true;
      const c = DIE.classify(v, ind);
      const bin = DIE.Charts.DIST_BINS.find((b) => b.match(c));
      if (bin) { bins[bin.key].area += d.area; bins[bin.key].districts++; }
    });
    Object.values(bins).forEach((b) => { b.pct = regionArea > 0 ? b.area / regionArea * 100 : 0; });
    return { bins, regionArea, anyData, noDataArea };
  }
  const severityDistributionCached = memoize(severityDistribution, (ds, dateIdx, ids) =>
    dateIdx + '|' + idsKey(ids));

  /* -------------------------------------------------------- time series -- */
  function districtSeries(ds, id) {
    const i = ds.districtIndex.get(id);
    const pts = [];
    if (i !== undefined) {
      for (let j = 0; j < ds.dates.length; j++) {
        const v = ds.values[i][j];
        pts.push({ ym: ds.dates[j], v: Number.isFinite(v) ? v : null });
      }
    }
    return { pts, totalMonths: ds.dates.length };
  }
  const districtSeriesCached = memoize(districtSeries, (ds, id) => id);

  /** Area-weighted regional mean per month (valid districts only). */
  function regionSeries(ds, ids) {
    const pts = [];
    let any = false;
    for (let j = 0; j < ds.dates.length; j++) {
      let wval = 0, wsum = 0;
      ids.forEach((id) => {
        const d = DIE.registry.districts.get(id);
        const i = ds.districtIndex.get(id);
        if (!d || i === undefined) return;
        const v = ds.values[i][j];
        if (Number.isFinite(v)) { wval += v * d.area; wsum += d.area; }
      });
      const v = wsum > 0 ? wval / wsum : null;
      if (v !== null) any = true;
      pts.push({ ym: ds.dates[j], v });
    }
    return { pts, totalMonths: ds.dates.length, anyValid: any };
  }
  const regionSeriesCached = memoize(regionSeries, (ds, ids) => idsKey(ids));

  /* ------------------------------------------------------ event analysis -- */
  /**
   * Runs analysis: maximal runs of consecutive months with value <= threshold
   * and length >= minDuration. NaN months break runs (no interpolation).
   */
  function findEvents(values, dates, threshold, minDuration) {
    const events = [];
    let start = -1;
    for (let j = 0; j <= values.length; j++) {
      const v = j < values.length ? values[j] : NaN;
      const inRun = Number.isFinite(v) && v <= threshold;
      if (inRun && start < 0) start = j;
      if (!inRun && start >= 0) {
        const dur = j - start;
        if (dur >= minDuration) {
          const seg = values.slice(start, j);
          let deficit = 0;
          seg.forEach((x) => { deficit += (threshold - x); });
          events.push({
            startIdx: start, endIdx: j - 1,
            startDate: dates[start], endDate: dates[j - 1],
            duration: dur,
            severity: deficit,
            meanIntensity: deficit / dur,
            minValue: Math.min(...seg)
          });
        }
        start = -1;
      }
    }
    return events;
  }

  /** Series of monthly values (with nulls) -> compacted valid list. */
  function compact(pts) { return pts.filter((p) => p.v !== null); }

  /* ------------------------------------------------ historical summary -- */
  function historicalSummary(ds, ids, period, season) {
    const ind = ds.indicator;
    const threshold = droughtThreshold(ind);
    const months = DIE.meta.seasons[season] || DIE.meta.seasons.all;
    const from = period.from, to = period.to;

    const series = regionSeriesCached(ds, ids);
    const scopeIdx = [];
    const continuousIdx = [];
    for (let j = 0; j < ds.dates.length; j++) {
      const [y, m] = ds.dates[j].split('-').map(Number);
      if (y >= from && y <= to) {
        continuousIdx.push(j);
        if (months.includes(m)) scopeIdx.push(j);
      }
    }

    // frequency (season-filtered)
    let droughtMonths = 0, validScopeMonths = 0;
    const perYear = new Map();
    scopeIdx.forEach((j) => {
      const v = series.pts[j].v;
      if (v === null) return;
      validScopeMonths++;
      const y = +ds.dates[j].slice(0, 4);
      if (v <= threshold) {
        droughtMonths++;
        perYear.set(y, (perYear.get(y) || 0) + 1);
      }
    });
    const years = Array.from({ length: to - from + 1 }, (_, k) => from + k);
    const counts = years.map((y) => perYear.get(y) || 0);

    // events on the continuous monthly series within the period
    const contValues = continuousIdx.map((j) => series.pts[j].v === null ? NaN : series.pts[j].v);
    const contDates = continuousIdx.map((j) => ds.dates[j]);
    const events = findEvents(contValues, contDates, threshold, 3);

    const durations = events.map((e) => e.duration);
    const totalSeverity = events.reduce((s, e) => s + e.severity, 0);
    const meanIntensity = events.length ? mean(events.map((e) => e.meanIntensity)) : NaN;
    const regionMean = validScopeMonths
      ? mean(scopeIdx.map((j) => series.pts[j].v).filter((v) => v !== null))
      : NaN;

    return {
      threshold, droughtMonths, validScopeMonths, years, counts,
      events, regionMean,
      duration: { mean: mean(durations), median: median(durations), max: durations.length ? Math.max(...durations) : 0 },
      severity: { total: totalSeverity, meanIntensity, worst: events.length ? events.reduce((a, b) => a.severity > b.severity ? a : b) : null },
      nEvents: events.length
    };
  }
  const historicalSummaryCached = memoize(historicalSummary, (ds, ids, period, season) =>
    idsKey(ids) + '|' + periodKey(period, season));

  /* ------------------------------------------ per-district statistics -- */
  /**
   * District-level drought statistics over the analysis period, on the
   * continuous monthly series (runs analysis; season filter applies to the
   * frequency column only, consistent with historicalSummary).
   * Events that touch the record or period edges are flagged censored
   * (left/right) and excluded from duration/severity ranking but reported.
   * `recoveryMonths` = months from event end to the first value >= 0
   * (null when the record ends first or no recovery within the window).
   */
  function districtStats(ds, ids, period, opts) {
    opts = opts || {};
    const ind = ds.indicator;
    const threshold = opts.threshold !== undefined ? opts.threshold : droughtThreshold(ind);
    const minDuration = opts.minDuration !== undefined ? opts.minDuration : 3;
    const seasons = DIE.meta.seasons;
    const scopeMonths = seasons[opts.season] || seasons.all;

    const periodIdx = [];
    for (let j = 0; j < ds.dates.length; j++) {
      const y = +ds.dates[j].slice(0, 4);
      if (y >= period.from && y <= period.to) periodIdx.push(j);
    }
    // Hoist per-slice work out of the district loop: dates and the
    // season-scope mask are identical for every district.
    const periodDates = periodIdx.map((j) => ds.dates[j]);
    const scopeMask = periodIdx.map((j) => scopeMonths.includes(+ds.dates[j].slice(5, 7)));
    const nPeriod = periodIdx.length;

    const rows = [];
    ids.forEach((id) => {
      const d = DIE.registry.districts.get(id);
      const i = ds.districtIndex.get(id);
      if (!d || i === undefined) return;
      const row = ds.values[i];

      let valid = 0, scopeValid = 0, scopeDrought = 0, sum = 0;
      const vals = new Array(nPeriod);
      for (let k = 0; k < nPeriod; k++) {
        const v = row[periodIdx[k]];
        vals[k] = v;
        if (Number.isFinite(v)) {
          valid++; sum += v;
          if (scopeMask[k]) {
            scopeValid++;
            if (v <= threshold) scopeDrought++;
          }
        }
      }

      const events = findEvents(vals, periodDates, threshold, minDuration)
        .map((e) => {
          const eFirst = e.startIdx, eLast = e.endIdx; // indices within period slice
          const censored = (eFirst === 0) ? 'left' : (eLast === vals.length - 1) ? 'right' : null;
          // recovery: first month after event end with value >= 0
          let recovery = null;
          for (let k = eLast + 1; k < vals.length; k++) {
            const v = vals[k];
            if (Number.isFinite(v)) { if (v >= 0) recovery = k - eLast - 1; break; }
          }
          return { ...e, censoring: censored, recoveryMonths: recovery };
        });

      const complete = events.filter((e) => !e.censoring);
      const durations = complete.map((e) => e.duration);
      const severities = complete.map((e) => e.severity);
      const maxIdx = vals.reduce((b, v, k) => (Number.isFinite(v) && (b === -1 || v < vals[b]) ? k : b), -1);

      rows.push({
        id, name: d.name, state: d.state, area: d.area,
        validMonths: valid, expectedMonths: nPeriod,
        completeness: nPeriod ? valid / nPeriod : 0,
        mean: valid ? sum / valid : NaN,
        minValue: maxIdx >= 0 ? vals[maxIdx] : NaN,
        minDate: maxIdx >= 0 ? ds.dates[periodIdx[maxIdx]] : null,
        droughtMonths: scopeDrought,
        droughtPct: scopeValid ? scopeDrought / scopeValid * 100 : NaN,
        nEvents: complete.length,
        nEventsCensored: events.length - complete.length,
        meanDuration: durations.length ? mean(durations) : NaN,
        maxDuration: durations.length ? Math.max(...durations) : 0,
        meanSeverity: severities.length ? mean(severities) : NaN,
        maxSeverity: severities.length ? Math.max(...severities) : NaN,
        cumulativeSeverity: severities.reduce((s, v) => s + v, 0),
        worstEvent: complete.length ? complete.reduce((a, b) => a.severity > b.severity ? a : b) : null,
        events
      });
    });
    return rows;
  }
  const districtStatsCached = memoize(districtStats, (ds, ids, period, opts) =>
    idsKey(ids) + '|' + periodKey(period, opts && opts.season) + '|' + optsKey(opts));

  /**
   * Event catalogue rows (one per event) for the region and period.
   * Columns follow §3.A of the five-tab specification.
   */
  function eventCatalogue(ds, ids, period, opts) {
    const stats = districtStatsCached(ds, ids, period, opts);
    const out = [];
    stats.forEach((s) => {
      s.events.forEach((e) => {
        out.push({
          districtId: s.id, district: s.name, state: s.state, area: s.area,
          start: e.startDate, end: e.endDate,
          duration: e.duration,
          maxIntensity: e.minValue,
          severity: e.severity,
          meanIntensity: e.meanIntensity,
          censoring: e.censoring,
          recoveryMonths: e.recoveryMonths,
          startIdx: e.startIdx, endIdx: e.endIdx
        });
      });
    });
    out.sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : b.severity - a.severity));
    return { rows: out, nDistricts: stats.length };
  }
  const eventCatalogueCached = memoize(eventCatalogue, (ds, ids, period, opts) =>
    idsKey(ids) + '|' + periodKey(period, opts && opts.season) + '|' + optsKey(opts));

  /**
   * Sensitivity scenario: re-run the catalogue with a custom threshold /
   * min duration. The default (metadata) configuration is always what the
   * main catalogue shows; scenarios are labelled separately in the UI.
   */
  function eventSensitivity(ds, ids, period, threshold, minDuration) {
    return eventCatalogueCached(ds, ids, period, { threshold, minDuration });
  }

  /* ----------------------------------------------- trend input series -- */
  /**
   * Regional annual series (area-weighted means of valid months per year)
   * and the monthly region series restricted to the analysis period.
   * Used by the Mann-Kendall / Sen analysis in the Historical tab.
   */
  function trendSeries(ds, ids, period, opts) {
    opts = opts || {};
    const granularity = opts.granularity || 'annual';
    const months = DIE.meta.seasons[opts.season] || DIE.meta.seasons.all;
    const series = regionSeriesCached(ds, ids);

    const buckets = new Map(); // key -> {sum, w, nMonths}
    for (let j = 0; j < ds.dates.length; j++) {
      const [y, m] = ds.dates[j].split('-').map(Number);
      if (y < period.from || y > period.to || !months.includes(m)) continue;
      const v = series.pts[j].v;
      if (v === null) continue;
      const key = granularity === 'annual' ? String(y) : y + '-' + String(m).padStart(2, '0');
      if (!buckets.has(key)) buckets.set(key, { sum: 0, w: 0, n: 0 });
      const b = buckets.get(key);
      b.sum += v * 12; b.w += 12; b.n += 1; // monthly region means are equally weighted within a year
    }
    const keys = Array.from(buckets.keys()).sort();
    const values = keys.map((k) => {
      const b = buckets.get(k);
      return b.w ? b.sum / b.w : NaN;
    });
    return {
      keys, values,
      valid: keys.filter((_, i) => Number.isFinite(values[i])).length,
      granularity
    };
  }
  const trendSeriesCached = memoize(trendSeries, (ds, ids, period, opts) =>
    idsKey(ids) + '|' + periodKey(period, opts && opts.season) + '|' + optsKey(opts));

  /* ---------------------------------------------- inter-event recurrence -- */
  /**
   * Empirical recurrence statistics from event start dates on the regional
   * series: mean/median inter-arrival time and empirical return periods of
   * severity exceedance (non-parametric; no fitted distribution — the
   * assumption-free estimate is n_years / n_events_exceeding).
   */
  function recurrenceStats(events, period) {
    if (!events.length) {
      return { nEvents: 0, meanInterArrival: NaN, medianInterArrival: NaN, returnPeriods: [] };
    }
    const starts = events.map((e) => e.startIdx).sort((a, b) => a - b);
    const gaps = [];
    for (let i = 1; i < starts.length; i++) gaps.push(starts[i] - starts[i - 1]);
    const nYears = period.to - period.from + 1;
    const severities = events.map((e) => e.severity).sort((a, b) => a - b);
    const qs = [0.5, 0.75, 0.9];
    const returnPeriods = qs.map((q) => {
      // empirical quantile of severities (type-7)
      const pos = (severities.length - 1) * q;
      const lo = Math.floor(pos), hi = Math.ceil(pos);
      const thr = severities[lo] + (severities[hi] - severities[lo]) * (pos - lo);
      const nExc = severities.filter((s) => s >= thr).length;
      return {
        quantile: q, threshold: thr, nExceeding: nExc,
        returnPeriod: nExc ? nYears / nExc : Infinity
      };
    });
    return {
      nEvents: events.length,
      meanInterArrival: gaps.length ? mean(gaps) : NaN,
      medianInterArrival: gaps.length ? median(gaps) : NaN,
      returnPeriods
    };
  }

  /* ------------------------------------------------ regional comparison -- */
  function comparisonRows(ds, level, period, season, scopeIds) {
    const ind = ds.indicator;
    const threshold = droughtThreshold(ind);
    const months = DIE.meta.seasons[season] || DIE.meta.seasons.all;
    const from = period.from, to = period.to;

    // date indexes in the historical scope
    const scopeIdx = [];
    for (let j = 0; j < ds.dates.length; j++) {
      const [y, m] = ds.dates[j].split('-').map(Number);
      if (y >= from && y <= to && months.includes(m)) scopeIdx.push(j);
    }

    const ids = scopeIds || Array.from(DIE.registry.districts.keys());
    const groups = new Map(); // groupId -> {label, ids, type}
    if (level === 'state') {
      ids.forEach((id) => {
        const d = DIE.registry.districts.get(id);
        if (!d) return;
        if (!groups.has(d.sid)) groups.set(d.sid, { id: d.sid, label: d.state, ids: [], type: 'state' });
        groups.get(d.sid).ids.push(id);
      });
    } else {
      ids.forEach((id) => {
        const d = DIE.registry.districts.get(id);
        if (d) groups.set(id, { id, label: d.name + ' · ' + d.state, ids: [id], type: 'district' });
      });
    }

    const rows = [];
    groups.forEach((g) => {
      // Resolve the group's districts and total area once instead of on every
      // month iteration (this was the hottest loop in the comparison table).
      const members = [];
      let area = 0;
      g.ids.forEach((id) => {
        const d = DIE.registry.districts.get(id);
        if (!d) return;
        area += d.area;
        const i = ds.districtIndex.get(id);
        if (i !== undefined) members.push({ area: d.area, row: ds.values[i] });
      });

      let wval = 0, wsum = 0, valid = 0, expected = 0;
      let affectedAreaSum = 0, severeAreaSum = 0, monthsConsidered = 0;
      let droughtMonths = 0;
      scopeIdx.forEach((j) => {
        let monthWVal = 0, monthWSum = 0;
        let monthAffected = 0, monthSevere = 0;
        for (let m = 0; m < members.length; m++) {
          const mem = members[m];
          expected++;
          const v = mem.row[j];
          if (!Number.isFinite(v)) continue;
          valid++;
          monthWVal += v * mem.area; monthWSum += mem.area;
          const c = DIE.classify(v, ind);
          if (DIE.isDroughtClass(c)) monthAffected += mem.area;
          if (DIE.isSevereClass(c)) monthSevere += mem.area;
        }
        wval += monthWVal; wsum += monthWSum;
        if (monthWSum > 0) {
          monthsConsidered++;
          if (g.type === 'state') {
            affectedAreaSum += monthAffected / area;
            severeAreaSum += monthSevere / area;
          } else {
            // single district: temporal incidence
            const v = monthWVal / monthWSum;
            const c = DIE.classify(v, ind);
            affectedAreaSum += DIE.isDroughtClass(c) ? 1 : 0;
            severeAreaSum += DIE.isSevereClass(c) ? 1 : 0;
          }
          const monthMean = monthWVal / monthWSum;
          if (monthMean <= threshold) droughtMonths++;
        }
      });
      const meanV = wsum > 0 ? wval / wsum : NaN;
      const completeness = expected ? valid / expected * 100 : 0;
      rows.push({
        id: g.id, label: g.label, type: g.type, nUnits: g.ids.length,
        mean: Number.isFinite(meanV) ? meanV : NaN,
        affected: monthsConsidered ? affectedAreaSum / monthsConsidered * 100 : NaN,
        severe: monthsConsidered ? severeAreaSum / monthsConsidered * 100 : NaN,
        months: droughtMonths,
        monthsConsidered,
        completeness,
        area
      });
    });
    return rows;
  }
  const comparisonRowsCached = memoize(comparisonRows, (ds, level, period, season, scopeIds) =>
    level + '|' + periodKey(period, season) + '|' + idsKey(scopeIds || []));

  /* -------------------------------------------- multi-indicator stats --- */
  function comparisonStats(dsA, dsB, dateIdx) {
    const pairs = [];
    dsA.districtIds.forEach((id) => {
      const iA = dsA.districtIndex.get(id);
      const iB = dsB.districtIndex.get(id);
      if (iB === undefined) return;
      const a = dsA.values[iA][dateIdx];
      const b = dsB.values[iB][dateIdx];
      if (Number.isFinite(a) && Number.isFinite(b)) {
        const d = DIE.registry.districts.get(id);
        pairs.push({ id, name: d ? d.name : id, a, b });
      }
    });
    if (!pairs.length) return { pairs, n: 0 };
    const xs = pairs.map((p) => p.a), ys = pairs.map((p) => p.b);
    const r = pearson(xs, ys);
    const fit = ols(xs, ys);
    const rmse = Math.sqrt(mean(pairs.map((p) => (p.b - p.a) ** 2)));
    const bias = mean(pairs.map((p) => p.b - p.a));
    // fit line endpoints across observed x-range
    let line = null;
    if (fit) {
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      line = { x: [x0, x1], y: [fit.intercept + fit.slope * x0, fit.intercept + fit.slope * x1] };
    }
    const missing = dsA.districtIds.length - pairs.length;
    return { pairs, n: pairs.length, r, r2: r * r, fit, line, rmse, bias, missing,
      nA: dsA.districtIds.length, date: dsA.dates[dateIdx] };
  }
  const comparisonStatsCached = memoize(comparisonStats, (dsA, dsB, dateIdx) =>
    dsB.id + '|' + dateIdx);

  /* ---------------------------------------------- evolution series ------ */
  /** % of region area in drought (mild or worse) per date. */
  function droughtAreaPctSeries(ds, ids) {
    const ind = ds.indicator;
    const pct = new Array(ds.dates.length).fill(null);
    let totalArea = 0;
    ids.forEach((id) => { const d = DIE.registry.districts.get(id); if (d) totalArea += d.area; });
    if (!totalArea) return { dates: ds.dates, pct };
    for (let j = 0; j < ds.dates.length; j++) {
      let affected = 0, any = false;
      ids.forEach((id) => {
        const i = ds.districtIndex.get(id);
        if (i === undefined) return;
        const v = ds.values[i][j];
        if (!Number.isFinite(v)) return;
        any = true;
        if (DIE.isDroughtClass(DIE.classify(v, ind))) affected += DIE.registry.districts.get(id).area;
      });
      pct[j] = any ? affected / totalArea * 100 : null;
    }
    return { dates: ds.dates, pct };
  }
  const droughtAreaPctSeriesCached = memoize(droughtAreaPctSeries, (ds, ids) => idsKey(ids));

  /* ---------------------------------------------------------- CSV export -- */
  function csvEscape(v) {
    const s = (v === null || v === undefined) ? '' : String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function toCSV(filename, rows) {
    const blob = new Blob([rows.map((r) => r.map(csvEscape).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' });
    downloadBlob(filename, blob);
  }
  function toText(filename, text, mime) {
    downloadBlob(filename, new Blob([text], { type: mime || 'text/plain;charset=utf-8' }));
  }
  function downloadBlob(filename, blob) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
    // Every export in the application funnels through here — the single
    // highest-value behavioural signal, so it is tracked with its type.
    try {
      if (DIE.Telemetry) {
        DIE.Telemetry.track('export_data', {
          file_name: filename,
          file_type: /\.csv$/i.test(filename) ? 'csv'
            : /\.json$/i.test(filename) ? 'json'
            : /\.png$/i.test(filename) ? 'png'
            : /\.md$/i.test(filename) ? 'markdown' : 'file'
        });
      }
    } catch (e) { /* telemetry must never break exports */ }
  }

  /* ------------------------------------------ reproducibility metadata -- */
  /**
   * Build the `#`-comment metadata block prepended to every exported CSV
   * (§5.E of the specification). Tabular schema rows are appended by the
   * caller; this returns the header lines only.
   */
  function exportMetaLines(extra) {
    const st = DIE.state;
    const m = DIE.meta;
    const ds = DIE.datasets.get(st.indicator);
    const lines = [
      '# Drought Intelligence Explorer — research export',
      '# exported (UTC): ' + new Date().toISOString(),
      '# indicator: ' + (ds ? ds.indicator.label + ' (' + ds.indicator.id + ', ' + ds.indicator.units + ')' : st.indicator),
      '# geography: ' + DIE.Filters.regionLabel() + ' (extent: ' + st.extent + ')',
      '# observation period (dataset): ' + (ds ? (ds.availableFrom || m.period.start) + ' to ' + (ds.availableTo || m.period.end) : m.period.start + ' to ' + m.period.end),
      '# analysis period: ' + st.period.from + ' to ' + st.period.to +
        (st.period.season === 'all' ? '' : ' · season: ' + st.period.season),
      '# reference period: ' + m.reference_period,
      '# methodology version: ' + m.methodology_version +
        ' · data mode: ' + m.data_mode +
        (m.random_seed !== null && m.random_seed !== undefined ? ' (random seed ' + m.random_seed + ')' : ''),
      '# data source: ' + (m.sources && m.sources[0] ? m.sources[0].name : m.data_provenance),
      '# threshold / event settings: truncation ' + droughtThreshold(ds ? ds.indicator : { classes: [] }) +
        ' · minimum duration 3 months (runs analysis, Yevjevich 1967)'
    ];
    (extra || []).forEach((l) => lines.push('# ' + l));
    lines.push('');
    return lines;
  }

  /** Long-format extract (the documented interchange schema). */
  function longExportCSV(ds, ids, opts) {
    opts = opts || {};
    const ind = ds.indicator;
    const rows = [[
      'district_id', 'district_name', 'state_name', 'date', 'indicator',
      'indicator_value', 'severity_class', 'area_km2', 'data_provenance'
    ]];
    const from = opts.fromYm || ds.dates[0];
    const to = opts.toYm || ds.dates[ds.dates.length - 1];
    ids.forEach((id) => {
      const d = DIE.registry.districts.get(id);
      const i = ds.districtIndex.get(id);
      if (!d || i === undefined) return;
      for (let j = 0; j < ds.dates.length; j++) {
        const ym = ds.dates[j];
        if (ym < from || ym > to) continue;
        const v = ds.values[i][j];
        const c = DIE.classify(v, ind);
        rows.push([
          id, d.name, d.state, ym, ind.id,
          Number.isFinite(v) ? v : '',
          c ? c.label : '',
          d.area, (DIE.meta && DIE.meta.data_mode) || ''
        ]);
      }
    });
    toCSV('die-' + ind.id + '-' + (DIE.Filters.regionLabel() || 'region').toLowerCase().replace(/\W+/g, '-') + '-long.csv', rows);
    return rows.length - 1;
  }

  /** Long-format extract with reproducibility metadata header. */
  function longExportCSVMeta(ds, ids) {
    const ind = ds.indicator;
    const rows = [[
      'district_id', 'district_name', 'state_name', 'date', 'indicator',
      'indicator_value', 'severity_class', 'area_km2', 'data_provenance'
    ]];
    ids.forEach((id) => {
      const d = DIE.registry.districts.get(id);
      const i = ds.districtIndex.get(id);
      if (!d || i === undefined) return;
      for (let j = 0; j < ds.dates.length; j++) {
        const ym = ds.dates[j];
        const v = ds.values[i][j];
        const c = DIE.classify(v, ind);
        rows.push([
          id, d.name, d.state, ym, ind.id,
          Number.isFinite(v) ? v : '',
          c ? c.label : '',
          d.area, (DIE.meta && DIE.meta.data_mode) || ''
        ]);
      }
    });
    const text = exportMetaLines(['records: ' + (rows.length - 1)])
      .concat(rows.map((r) => r.map(csvEscape).join(','))).join('\n');
    downloadBlob('die-' + ind.id + '-region-long.csv', new Blob([text], { type: 'text/csv;charset=utf-8' }));
    return rows.length - 1;
  }

  /** District statistics export with metadata header. */
  function districtStatsCSVMeta(ds, ids, period, season) {
    const stats = districtStatsCached(ds, ids, period, { season });
    const rows = [[
      'district_id', 'district_name', 'state_name', 'indicator',
      'valid_months', 'expected_months', 'completeness_pct',
      'mean', 'min', 'min_date', 'drought_months', 'drought_months_pct',
      'events', 'events_censored', 'mean_duration_months', 'max_duration_months',
      'mean_event_severity', 'max_event_severity', 'cumulative_severity',
      'worst_event_start', 'worst_event_end'
    ]];
    stats.forEach((s) => {
      rows.push([
        s.id, s.name, s.state, ds.indicator.id,
        s.validMonths, s.expectedMonths, (s.completeness * 100).toFixed(1),
        Number.isFinite(s.mean) ? s.mean.toFixed(3) : '',
        Number.isFinite(s.minValue) ? s.minValue.toFixed(2) : '',
        s.minDate || '',
        s.droughtMonths, Number.isFinite(s.droughtPct) ? s.droughtPct.toFixed(2) : '',
        s.nEvents, s.nEventsCensored,
        Number.isFinite(s.meanDuration) ? s.meanDuration.toFixed(2) : '',
        s.maxDuration || 0,
        Number.isFinite(s.meanSeverity) ? s.meanSeverity.toFixed(2) : '',
        Number.isFinite(s.maxSeverity) ? s.maxSeverity.toFixed(2) : '',
        s.cumulativeSeverity.toFixed(2),
        s.worstEvent ? s.worstEvent.startDate : '',
        s.worstEvent ? s.worstEvent.endDate : ''
      ]);
    });
    const text = exportMetaLines(['records: ' + (rows.length - 1), 'note: censored events touch the record/period edge and are excluded from duration/severity columns'])
      .concat(rows.map((r) => r.map(csvEscape).join(','))).join('\n');
    downloadBlob('die-' + ds.indicator.id + '-district-statistics-' + period.from + '-' + period.to + '.csv',
      new Blob([text], { type: 'text/csv;charset=utf-8' }));
    return rows.length - 1;
  }

  /** Event catalogue export with metadata header. */
  function eventCatalogueCSVMeta(ds, ids, period, season) {
    const cat = eventCatalogueCached(ds, ids, period, { season });
    const rows = [[
      'district_id', 'district_name', 'state_name', 'indicator',
      'event_start', 'event_end', 'duration_months', 'max_intensity',
      'cumulative_severity', 'mean_intensity', 'censoring',
      'recovery_months'
    ]];
    cat.rows.forEach((e) => {
      rows.push([
        e.districtId, e.district, e.state, ds.indicator.id,
        e.start, e.end, e.duration,
        Number.isFinite(e.maxIntensity) ? e.maxIntensity.toFixed(2) : '',
        e.severity.toFixed(2), e.meanIntensity.toFixed(2),
        e.censoring || '',
        e.recoveryMonths === null ? '' : e.recoveryMonths
      ]);
    });
    const text = exportMetaLines([
      'records: ' + (rows.length - 1),
      'note: events are runs of >= 3 consecutive months <= truncation; censored events touch the record/period edge',
      'recovery_months: months from event end to first value >= 0 (blank = record ends first)'
    ]).concat(rows.map((r) => r.map(csvEscape).join(','))).join('\n');
    downloadBlob('die-' + ds.indicator.id + '-event-catalogue-' + period.from + '-' + period.to + '.csv',
      new Blob([text], { type: 'text/csv;charset=utf-8' }));
    return rows.length - 1;
  }

  /** Reproducibility metadata export (JSON). */
  function analysisMetadataJSON() {
    const st = DIE.state;
    const m = DIE.meta;
    const ds = DIE.datasets.get(st.indicator);
    return JSON.stringify({
      application: m.application,
      exported_at_utc: new Date().toISOString(),
      state: {
        indicator: st.indicator,
        extent: st.extent,
        stateId: st.stateId,
        districtId: st.districtId,
        region: DIE.Filters.regionLabel(),
        dateIdx: st.dateIdx,
        period: st.period
      },
      dataset: {
        data_mode: m.data_mode,
        methodology_version: m.methodology_version,
        random_seed: m.random_seed ?? null,
        period: m.period,
        reference_period: m.reference_period,
        indicator_available_from: ds ? ds.availableFrom : null,
        indicator_available_to: ds ? ds.availableTo : null,
        provenance: m.data_provenance,
        citation: m.citation
      },
      methods: {
        classification: 'SPI/SPEI McKee (1993) / Vicente-Serrano (2010) convention; indicator-specific thresholds in metadata.json',
        events: m.events,
        aggregation: m.aggregation,
        area_method: m.area_method,
        trend: 'Mann-Kendall with Hamed-Rao variance correction when significant autocorrelation; Sen slope with 90% rank CI',
        correlation: 'Pearson on matched months; moving-block bootstrap 95% CI (block = n^(1/3), 1000 resamples, fixed seed)'
      }
    }, null, 2);
  }

  function districtSummaryCSV(ds, ids, period) {
    const ind = ds.indicator;
    const threshold = droughtThreshold(ind);
    const periodIdx = [];
    for (let j = 0; j < ds.dates.length; j++) {
      const y = +ds.dates[j].slice(0, 4);
      if (y >= period.from && y <= period.to) periodIdx.push(j);
    }
    const rows = [[
      'district_id', 'district_name', 'state_name', 'indicator', 'valid_months',
      'mean', 'min', 'max', 'drought_months', 'drought_events',
      'max_event_duration_months', 'cumulative_severity', 'completeness_pct'
    ]];
    ids.forEach((id) => {
      const d = DIE.registry.districts.get(id);
      const i = ds.districtIndex.get(id);
      if (!d || i === undefined) return;
      const valsByDate = new Array(ds.dates.length).fill(NaN);
      const vals = [];
      periodIdx.forEach((j) => {
        const v = ds.values[i][j];
        valsByDate[j] = v;
        if (Number.isFinite(v)) vals.push(v);
      });
      const events = findEvents(valsByDate, ds.dates, threshold, 3)
        .filter((e) => +e.startDate.slice(0, 4) >= period.from && +e.startDate.slice(0, 4) <= period.to);
      const droughtMonths = valsByDate.filter((v) => Number.isFinite(v) && v <= threshold).length;
      const completeness = periodIdx.length ? vals.length / periodIdx.length * 100 : 0;
      rows.push([
        id, d.name, d.state, ind.id, vals.length,
        vals.length ? mean(vals).toFixed(3) : '',
        vals.length ? Math.min(...vals).toFixed(2) : '',
        vals.length ? Math.max(...vals).toFixed(2) : '',
        droughtMonths, events.length,
        events.length ? Math.max(...events.map((e) => e.duration)) : 0,
        events.reduce((s, e) => s + e.severity, 0).toFixed(2),
        completeness.toFixed(1)
      ]);
    });
    toCSV('die-' + ind.id + '-district-summary-' + period.from + '-' + period.to + '.csv', rows);
    return rows.length - 1;
  }

  /* -------------------------------------------------------------- public -- */
  DIE.Analytics = {
    mean, median, pearson, ols, droughtThreshold,
    regionStats: regionStatsCached,
    severityDistribution: severityDistributionCached,
    districtSeries: districtSeriesCached,
    regionSeries: regionSeriesCached,
    findEvents, compact,
    historicalSummary: historicalSummaryCached,
    comparisonRows: comparisonRowsCached,
    comparisonStats: comparisonStatsCached,
    droughtAreaPctSeries: droughtAreaPctSeriesCached,
    districtStats: districtStatsCached,
    eventCatalogue: eventCatalogueCached,
    eventSensitivity, trendSeries: trendSeriesCached,
    recurrenceStats, exportMetaLines,
    toCSV, toText, downloadBlob, csvEscape,
    longExportCSV, districtSummaryCSV,
    longExportCSVMeta, districtStatsCSVMeta, eventCatalogueCSVMeta,
    analysisMetadataJSON
  };
})();
