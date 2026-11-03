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
      out.prev = regionStats(ds, dateIdx - 1, ids);
      out.prevDateIdx = dateIdx - 1;
    }
    return out;
  }

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

    const series = regionSeries(ds, ids);
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
      let wval = 0, wsum = 0, valid = 0, expected = 0;
      let affectedAreaSum = 0, severeAreaSum = 0, monthsConsidered = 0;
      let droughtMonths = 0;
      scopeIdx.forEach((j) => {
        let monthWVal = 0, monthWSum = 0;
        let monthAffected = 0, monthSevere = 0;
        g.ids.forEach((id) => {
          const d = DIE.registry.districts.get(id);
          const i = ds.districtIndex.get(id);
          if (!d || i === undefined) return;
          expected++;
          const v = ds.values[i][j];
          if (!Number.isFinite(v)) return;
          valid++;
          monthWVal += v * d.area; monthWSum += d.area;
          const c = DIE.classify(v, ind);
          if (DIE.isDroughtClass(c)) monthAffected += d.area;
          if (DIE.isSevereClass(c)) monthSevere += d.area;
        });
        wval += monthWVal; wsum += monthWSum;
        if (monthWSum > 0) {
          monthsConsidered++;
          if (g.type === 'state') {
            const stateArea = g.ids.reduce((s, id) => s + (DIE.registry.districts.get(id)?.area || 0), 0);
            affectedAreaSum += monthAffected / stateArea;
            severeAreaSum += monthSevere / stateArea;
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
      const area = g.ids.reduce((s, id) => s + (DIE.registry.districts.get(id)?.area || 0), 0);
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
    regionStats, severityDistribution, districtSeries, regionSeries,
    findEvents, compact, historicalSummary, comparisonRows, comparisonStats,
    droughtAreaPctSeries,
    toCSV, toText, downloadBlob, csvEscape, longExportCSV, districtSummaryCSV
  };
})();
