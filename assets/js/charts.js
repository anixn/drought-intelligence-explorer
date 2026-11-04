/* ===========================================================================
 * charts.js — Plotly scientific chart builders
 * ---------------------------------------------------------------------------
 *  - Time series with zero reference, drought-threshold lines, range
 *    selector/slider and optional OLS trend (only when n >= 120).
 *  - Severity distribution (horizontal bars, % and km²).
 *  - Frequency-by-year bars, comparison scatter, evolution timeline.
 *  - Consistent scientific styling; graceful "Plotly unavailable" states.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});

  const FONT = { family: 'Inter, IBM Plex Sans, sans-serif', size: 11, color: '#1F2937' };
  const MONO = { family: 'IBM Plex Mono, monospace', size: 10, color: '#687588' };

  function available() { return !!window.Plotly; }
  function engineFailed() {
    return !!((window.DIE_LIBS && window.DIE_LIBS.failed && window.DIE_LIBS.failed.Plotly) ||
      (window.DIE_DIAG && (window.DIE_DIAG.vendorMissing || []).indexOf('Plotly') !== -1));
  }
  /**
   * True when the caller should stop: the chart area is filled either with a
   * "failed" message or a transient "engine still loading" placeholder.
   */
  function unavailable(el) {
    if (available()) return false;
    if (engineFailed()) {
      state(el, 'CHART LIBRARY UNAVAILABLE', 'Plotly failed to load. Maps, statistics and tables remain fully functional.');
    } else {
      state(el, 'LOADING CHART ENGINE', 'The chart engine is still loading — this chart redraws automatically when it is ready.');
    }
    return true;
  }
  function loading(el, message) {
    state(el, 'LOADING', message || 'Preparing this chart…');
  }

  function state(el, code, message) {
    clearState(el);
    const div = document.createElement('div');
    div.className = 'chart-state';
    div.innerHTML = (code ? '<span class="code' +
      (/^LOADING/.test(code) ? ' is-loading' : '') + '">' + code + '</span>' : '') +
      '<span>' + message + '</span>';
    el.appendChild(div);
  }
  function clearState(el) {
    el.querySelectorAll('.chart-state').forEach((n) => n.remove());
  }

  function baseLayout(extra) {
    const layout = {
      font: FONT,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: '#FFFFFF',
      margin: { l: 52, r: 16, t: 14, b: 34 },
      xaxis: { gridcolor: '#E2E7EE', zerolinecolor: '#CBD5E1', linecolor: '#CBD5E1' },
      yaxis: { gridcolor: '#E2E7EE', zerolinecolor: '#CBD5E1', linecolor: '#CBD5E1' },
      hovermode: 'closest',
      showlegend: false,
      dragmode: 'pan',
      // Preserve user zoom/pan when data are updated on the same element.
      uirevision: 'die-chart'
    };
    Object.assign(layout, extra || {});
    return layout;
  }

  function config(filename) {
    return {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
      toImageButtonOptions: { filename: filename || 'drought-intelligence-chart', scale: 2, format: 'png' }
    };
  }

  /** Drought-side threshold values for an indicator (dry class boundaries). */
  function dryThresholds(indicator) {
    const out = [];
    indicator.classes.forEach((c) => {
      if (/drought/.test(c.key) && c.min !== null && c.min !== undefined) out.push({ v: c.min, label: c.label });
    });
    return out.sort((a, b) => b.v - a.v);
  }

  /* --------------------------------------------------- A · time series --- */
  function timeSeries(el, opts) {
    if (unavailable(el)) return;
    clearState(el);

    const { series, indicator, regionLabel, trend } = opts;
    const valid = series.pts.filter((p) => p.v !== null && p.v !== undefined);
    if (!valid.length) { state(el, 'NO VALID OBSERVATIONS', 'This selection has no valid observations for the current indicator.'); return; }

    const x = series.pts.map((p) => DIE.dates.toUTC(p.ym));
    const y = series.pts.map((p) => (p.v === null || p.v === undefined || !Number.isFinite(p.v) ? null : p.v));
    const [lo, hi] = indicator.scale;

    const traces = [{
      type: 'scatter', mode: 'lines', name: indicator.label,
      x, y,
      line: { color: '#203B59', width: 1.7 },
      connectgaps: false,
      hovertemplate: '<b>%{x|%b %Y}</b><br>' + indicator.label + ': %{y:' +
        (indicator.family === 'land' ? '.0f' : '.2f') + '} ' + indicator.units +
        '<extra>' + regionLabel + '</extra>'
    }];

    const shapes = [{
      type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0,
      line: { color: '#9AA7B5', width: 1 }
    }];
    dryThresholds(indicator).forEach((t) => {
      shapes.push({
        type: 'line', xref: 'paper', x0: 0, x1: 1, y0: t.v, y1: t.v,
        line: { color: 'rgba(185,71,71,0.55)', width: 1, dash: 'dot' }
      });
    });

    if (trend && trend.n >= 120) {
      const x0 = Math.min(...valid.map((p) => DIE.dates.toUTC(p.ym).getTime()));
      const x1 = Math.max(...valid.map((p) => DIE.dates.toUTC(p.ym).getTime()));
      traces.push({
        type: 'scatter', mode: 'lines', name: 'OLS trend',
        x: [new Date(x0), new Date(x1)],
        y: [trend.intercept, trend.intercept + trend.slope * (x1 - x0)],
        line: { color: '#B94747', width: 1.6, dash: 'dash' },
        hoverinfo: 'skip'
      });
    }

    const annotations = valid.length && series.totalMonths
      ? [{
          x: 0.995, xref: 'paper', y: 1.06, yref: 'paper', xanchor: 'right',
          showarrow: false,
          text: 'n = ' + valid.length + '/' + series.totalMonths + ' valid months',
          font: MONO
        }]
      : [];

    Plotly.react(el, traces, baseLayout({
      shapes, annotations,
      margin: { l: 46, r: 16, t: 26, b: 20 },
      yaxis: {
        gridcolor: '#E2E7EE', zeroline: true, zerolinecolor: '#9AA7B5',
        range: [Math.max(lo, -3.4), Math.min(hi, 3.4)],
        linecolor: '#CBD5E1',
        title: { text: indicator.label + ' (' + indicator.units + ')', font: { size: 10.5, color: '#687588' } }
      },
      xaxis: {
        type: 'date', gridcolor: '#F0F3F7', linecolor: '#CBD5E1',
        rangeslider: { bgcolor: '#F5F7FA', thickness: 0.085, bordercolor: '#E2E7EE' },
        rangeselector: {
          buttons: [
            { count: 5, step: 'year', stepmode: 'backward', label: '5y' },
            { count: 10, step: 'year', stepmode: 'backward', label: '10y' },
            { step: 'all', label: 'All' }
          ],
          font: FONT, bgcolor: '#FFFFFF', activecolor: '#203B59',
          bordercolor: '#CBD5E1', borderwidth: 1
        }
      }
    }), config('timeseries-' + indicator.id + '-' + regionLabel.replace(/\W+/g, '-').toLowerCase()));
  }

  /* --------------------------------------------- B · severity bars ------ */
  const DIST_BINS = [
    { key: 'extreme', label: 'Extreme drought', color: '#8F252F', match: (c) => c && c.key === 'extreme_drought' },
    { key: 'severe', label: 'Severe drought', color: '#B94747', match: (c) => c && c.key === 'severe_drought' },
    { key: 'moderate', label: 'Moderate drought', color: '#D97745', match: (c) => c && c.key === 'moderate_drought' },
    { key: 'mild', label: 'Mild drought', color: '#E9BE54', match: (c) => c && c.key === 'mild_drought' },
    { key: 'normal', label: 'Near normal', color: '#72A982', match: (c) => c && c.key === 'near_normal' },
    { key: 'wet', label: 'Wet conditions', color: '#4F91B8', match: (c) => c && (c.key === 'wet' || /wet/.test(c.key)) }
  ];

  function severityBars(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    const indicator = data.indicator;
    const rows = DIST_BINS.map((b) => ({ ...b, ...(data.bins[b.key] || { area: 0, pct: 0, districts: 0 }) }));
    const totalArea = rows.reduce((s, r) => s + r.area, 0);
    if (!totalArea && !data.anyData) {
      state(el, 'NO VALID OBSERVATIONS', 'No valid observations in the selected region for this date.');
      return;
    }
    const noDataArea = Math.max(0, (data.regionArea || 0) - totalArea);

    Plotly.react(el, [{
      type: 'bar', orientation: 'h',
      x: rows.map((r) => +r.pct.toFixed(2)),
      y: rows.map((r) => r.label),
      marker: { color: rows.map((r) => r.color) },
      text: rows.map((r) => r.pct >= 0.05
        ? '<b>' + DIE.fmt.pct(r.pct) + '</b>'
        : '<span style="color:#9AA7B5">0%</span>'),
      textposition: 'outside',
      textfont: { size: 10.5, color: '#1F2937' },
      cliponaxis: false,
      hovertemplate: '<b>%{y}</b><br>Area: ' + '%{customdata}<extra></extra>',
      customdata: rows.map((r) => DIE.fmt.area(r.area) + ' · ' + r.districts + ' districts')
    }], baseLayout({
      margin: { l: 118, r: 64, t: 8, b: 26 },
      xaxis: {
        range: [0, Math.max(20, Math.ceil(Math.max(...rows.map((r) => r.pct)) / 10) * 10 + 6)],
        title: { text: 'Share of region area (%)', font: { size: 10.5, color: '#687588' } },
        gridcolor: '#E2E7EE', linecolor: '#CBD5E1', zeroline: false
      },
      yaxis: { automargin: true, gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 11 } },
      annotations: noDataArea > 0.5 ? [{
        x: 0.99, xref: 'paper', y: -0.18, yref: 'paper', xanchor: 'right', showarrow: false,
        text: 'no data: ' + DIE.fmt.pct((noDataArea / (data.regionArea || 1)) * 100) +
          ' of region area (' + DIE.fmt.int.format(Math.round(noDataArea)) + ' km²)',
        font: MONO
      }] : []
    }), config('severity-distribution-' + indicator.id));
  }

  /* -------------------------------------------- frequency by year bars -- */
  function frequencyByYear(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.years.length) { state(el, 'NO DROUGHT MONTHS', 'No months below the −1.0 threshold in the selected period.'); return; }
    Plotly.react(el, [{
      type: 'bar',
      x: data.years.map(String),
      y: data.counts,
      marker: { color: '#B94747' },
      hovertemplate: '<b>%{x}</b><br>%{y} drought months<extra></extra>'
    }], baseLayout({
      margin: { l: 34, r: 12, t: 8, b: 22 },
      xaxis: { gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9.5 } },
      yaxis: {
        gridcolor: '#E2E7EE', linecolor: '#CBD5E1', dtick: 2,
        title: { text: 'months ≤ −1.0', font: { size: 9.5, color: '#687588' } }
      }
    }), config('drought-frequency'));
  }

  /* ------------------------------------------------- comparison scatter -- */
  function scatterCompare(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.pairs || data.pairs.length < 3) {
      state(el, 'INSUFFICIENT MATCHED PAIRS', 'Fewer than 3 districts have valid values for both indicators at this date.');
      return;
    }
    const traces = [{
      type: 'scatter', mode: 'markers',
      x: data.pairs.map((p) => p.a),
      y: data.pairs.map((p) => p.b),
      text: data.pairs.map((p) => p.name),
      marker: { size: 7, color: '#203B59', opacity: 0.55, line: { color: '#FFFFFF', width: 0.5 } },
      hovertemplate: '<b>%{text}</b><br>' + data.labelA + ': %{x:.2f}<br>' + data.labelB + ': %{y:.2f}<extra></extra>'
    }];
    if (data.fit) {
      traces.push({
        type: 'scatter', mode: 'lines', name: 'OLS fit',
        x: data.fit.x, y: data.fit.y,
        line: { color: '#B94747', width: 1.6, dash: 'dash' },
        hoverinfo: 'skip'
      });
    }
    const axisTitle = (ind) => ind.label + ' (' + ind.units + ')';
    Plotly.react(el, traces, baseLayout({
      showlegend: false,
      margin: { l: 52, r: 16, t: 18, b: 46 },
      xaxis: {
        title: { text: axisTitle(data.indA), font: { size: 10.5, color: '#687588' } },
        gridcolor: '#E2E7EE', zeroline: true, zerolinecolor: '#9AA7B5', linecolor: '#CBD5E1'
      },
      yaxis: {
        title: { text: axisTitle(data.indB), font: { size: 10.5, color: '#687588' } },
        gridcolor: '#E2E7EE', zeroline: true, zerolinecolor: '#9AA7B5', linecolor: '#CBD5E1'
      },
      annotations: data.statsAnnotation ? [data.statsAnnotation] : []
    }), config('indicator-comparison'));
  }

  /* ---------------------------------------------- evolution timeline ---- */
  function areaTimeline(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    const x = data.dates.map((ym) => DIE.dates.toUTC(ym));
    const traces = [{
      type: 'scatter', mode: 'lines',
      x, y: data.pct,
      line: { color: '#B94747', width: 1.6 },
      fill: 'tozeroy', fillcolor: 'rgba(185,71,71,0.16)',
      hovertemplate: '<b>%{x|%b %Y}</b><br>%{y:.1f}% of area in drought<extra></extra>',
      name: 'Area in drought'
    }];
    if (data.frameIdx !== null && data.frameIdx !== undefined) {
      traces.push({
        type: 'scatter', mode: 'markers',
        x: [x[data.frameIdx]], y: [data.pct[data.frameIdx]],
        marker: { size: 9, color: '#14263D', line: { color: '#FFFFFF', width: 1.5 } },
        hoverinfo: 'skip', name: 'Current frame'
      });
    }
    Plotly.react(el, traces, baseLayout({
      margin: { l: 36, r: 10, t: 8, b: 20 },
      showlegend: false,
      xaxis: { type: 'date', gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9 } },
      yaxis: {
        range: [0, 100], gridcolor: '#E2E7EE', linecolor: '#CBD5E1',
        title: { text: '% area in drought', font: { size: 9.5, color: '#687588' } }
      }
    }), config('drought-area-timeline'));
  }

  /* ------------------------------------------------ ranking bar chart -- */
  function rankingBars(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.rows || !data.rows.length) {
      state(el, 'NO VALID OBSERVATIONS', 'No districts with valid values for this region and date.');
      return;
    }
    const rows = data.rows;
    const byArea = data.byArea;
    const xs = rows.map((r) => byArea ? r.area : r.value);
    const fmt = byArea
      ? (v) => DIE.fmt.int.format(Math.round(v)) + ' km²'
      : (v) => v.toFixed(2);
    Plotly.react(el, [{
      type: 'bar', orientation: 'h',
      x: xs,
      y: rows.map((r, i) => (i + 1) + '. ' + r.name),
      marker: { color: rows.map((r) => r.color) },
      customdata: rows.map((r) => r.classLabel),
      hovertemplate: '<b>%{y}</b><br>' +
        (byArea ? 'Area: %{x:,.0f} km²' : data.indicator.label + ': %{x:.2f} ' + data.indicator.units) +
        '<br>Class: %{customdata}<extra></extra>',
      text: xs.map((v) => fmt(v)),
      textposition: 'outside',
      textfont: { size: 10, color: '#1F2937' },
      cliponaxis: false
    }], baseLayout({
      margin: { l: 140, r: 60, t: 8, b: 24 },
      xaxis: {
        title: { text: byArea ? 'District area (km², equal-area)' : data.indicator.label + ' (' + data.indicator.units + ')', font: { size: 10.5, color: '#687588' } },
        gridcolor: '#E2E7EE', linecolor: '#CBD5E1'
      },
      yaxis: { automargin: true, gridcolor: '#F0F3F7', tickfont: { size: 10.5 }, autorange: 'reversed' }
    }), config('district-ranking-' + data.indicator.id));
  }

  /* ------------------------------------------- district stats choropleth legend -- */
  /** Diverging continuous colour ramp for statistical maps (freq %, duration). */
  function statRamp(v, lo, hi, invert) {
    if (!Number.isFinite(v)) return '#D7DEE7';
    let t = (v - lo) / (hi - lo);
    t = Math.min(1, Math.max(0, t));
    if (invert) t = 1 - t;
    // single-hue sequential ramp: near-white -> navy-2 (colourblind-safe lightness ramp)
    const a = [243, 246, 249], b = [32, 59, 89];
    return 'rgb(' + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',') + ')';
  }

  /**
   * Warm multi-hue sequential ramp reusing the drought-class palette tokens
   * (pale amber -> mild -> moderate -> severe -> extreme). Used by the
   * Historical duration/severity maps so "more drought" reads consistently
   * with the classification colours used everywhere else in the app.
   */
  const WARM_STOPS = [[255, 249, 230], [233, 190, 84], [217, 119, 69], [185, 71, 71], [143, 37, 47]];
  function statRampWarm(v, lo, hi) {
    if (!Number.isFinite(v)) return '#D7DEE7';
    let t = (v - lo) / (hi - lo);
    if (!Number.isFinite(t)) t = 0;
    t = Math.min(1, Math.max(0, t));
    const f = t * (WARM_STOPS.length - 1);
    const seg = Math.min(WARM_STOPS.length - 2, Math.floor(f));
    const u = f - seg;
    const a = WARM_STOPS[seg], b = WARM_STOPS[seg + 1];
    return 'rgb(' + a.map((x, i) => Math.round(x + (b[i] - x) * u)).join(',') + ')';
  }

  function statLegendHtml(label, unit, lo, hi, ramp) {
    const f = ramp || statRamp;
    const stops = [];
    for (let k = 0; k <= 6; k++) stops.push(f(lo + (hi - lo) * k / 6, lo, hi) + ' ' + (k / 6 * 100) + '%');
    return '<div class="legend-head">' + label + '</div>' +
      '<div class="legend-grad" style="background:linear-gradient(90deg,' + stops.join(',') + ')"></div>' +
      '<div class="legend-grad-labels"><span>' + (Math.round(lo * 10) / 10) + unit + '</span><span>' +
      (Math.round((lo + hi) / 2 * 10) / 10) + '</span><span>' + (Math.round(hi * 10) / 10) + unit + '</span></div>';
  }

  /* --------------------------------------------- trend chart (MK/Sen) -- */
  function trendChart(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    const valid = data.values.filter((v) => Number.isFinite(v)).length;
    if (valid < 4) {
      state(el, 'INSUFFICIENT DATA', 'Fewer than 4 valid ' + (data.granularity === 'annual' ? 'years' : 'months') + ' — trend tests require at least 4 observations.');
      return;
    }
    const xs = data.keys.map((k) => data.granularity === 'annual'
      ? new Date(Date.UTC(+k, 6, 15))
      : DIE.dates.toUTC(k));
    const traces = [{
      type: 'scatter', mode: 'lines+markers', name: data.label,
      x: xs, y: data.values,
      line: { color: '#203B59', width: 1.4 },
      marker: { size: 4.5, color: '#203B59' },
      hovertemplate: '<b>%{x|%b %Y}</b><br>' + data.indicator.label + ': %{y:.2f}<extra></extra>'
    }];
    if (data.sen) {
      const x0 = xs[0].getTime(), x1 = xs[xs.length - 1].getTime();
      const slopePerDay = data.sen.slope / (30.44 * 24 * 3600 * 1000) *
        (data.granularity === 'annual' ? 365.25 : 1) / (data.granularity === 'annual' ? 365.25 / 30.44 : 1);
      // simpler: compute in index space over the same x range
      const n = data.values.length;
      traces.push({
        type: 'scatter', mode: 'lines', name: "Sen's slope",
        x: [xs[0], xs[xs.length - 1]],
        y: [data.sen.intercept, data.sen.intercept + data.sen.slope * (n - 1)],
        line: { color: '#B94747', width: 1.8, dash: 'dash' },
        hoverinfo: 'skip'
      });
    }
    Plotly.react(el, traces, baseLayout({
      margin: { l: 46, r: 14, t: 10, b: 26 },
      showlegend: true,
      legend: { orientation: 'h', y: 1.08, font: { size: 10.5 } },
      xaxis: { gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9.5 } },
      yaxis: {
        gridcolor: '#E2E7EE', zeroline: true, zerolinecolor: '#9AA7B5', linecolor: '#CBD5E1',
        title: { text: data.indicator.label + ' (' + data.indicator.units + ')', font: { size: 10, color: '#687588' } }
      }
    }), config('trend-' + data.indicator.id));
  }

  /* ---------------------------------------------- event timeline (Gantt) -- */
  function eventTimeline(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.events || !data.events.length) {
      state(el, 'NO EVENTS', 'No drought events identified for this selection (runs ≥ ' + data.minDuration + ' months below the truncation level).');
      return;
    }
    // aggregate: events per start month (region-wide)
    const byMonth = new Map();
    data.events.forEach((e) => {
      const key = e.start.slice(0, 7);
      if (!byMonth.has(key)) byMonth.set(key, { n: 0, sev: 0 });
      const b = byMonth.get(key);
      b.n++; b.sev += e.severity;
    });
    const keys = Array.from(byMonth.keys()).sort();
    const x = keys.map((k) => DIE.dates.toUTC(k));
    const counts = keys.map((k) => byMonth.get(k).n);
    const traces = [{
      type: 'bar', name: 'Event onsets',
      x, y: counts,
      marker: { color: '#B94747' },
      hovertemplate: '<b>%{x|%b %Y}</b><br>%{y} districts entered drought<extra></extra>'
    }];
    Plotly.react(el, traces, baseLayout({
      margin: { l: 34, r: 12, t: 8, b: 22 },
      bargap: 0.2,
      xaxis: { type: 'date', gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9 } },
      yaxis: {
        gridcolor: '#E2E7EE', linecolor: '#CBD5E1', dtick: 25,
        title: { text: 'districts entering drought', font: { size: 9.5, color: '#687588' } }
      }
    }), config('event-onset-timeline'));
  }

  /* ------------------------------------- event duration / severity dist -- */
  function eventDistribution(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.events || !data.events.length) {
      state(el, 'NO EVENTS', 'No complete events for this selection.');
      return;
    }
    const durations = data.events.map((e) => e.duration);
    const maxDur = Math.max(...durations);
    const bins = [];
    for (let d = 3; d <= maxDur; d++) bins.push(d);
    const counts = bins.map((d) => durations.filter((x) => x === d).length);
    // aggregate tail >= 12
    const nTail = durations.filter((x) => x >= 12).length;
    const showBins = bins.filter((d) => d < 12);
    const showCounts = showBins.map((d) => counts[bins.indexOf(d)]);
    const xs = showBins.map(String).concat(['≥12']);
    const ys = showCounts.concat(nTail);
    Plotly.react(el, [{
      type: 'bar',
      x: xs, y: ys,
      marker: { color: '#203B59' },
      hovertemplate: '<b>%{x} months</b><br>%{y} events<extra></extra>'
    }], baseLayout({
      margin: { l: 34, r: 12, t: 8, b: 24 },
      xaxis: { title: { text: 'event duration (months)', font: { size: 10, color: '#687588' } }, gridcolor: '#F0F3F7', linecolor: '#CBD5E1' },
      yaxis: { gridcolor: '#E2E7EE', linecolor: '#CBD5E1', title: { text: 'events', font: { size: 9.5, color: '#687588' } } }
    }), config('event-duration-dist'));
  }

  /* --------------------------------------------- event detail series -- */
  function eventDetailSeries(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    const { series, event, indicator } = data;
    const x = series.pts.map((p) => DIE.dates.toUTC(p.ym));
    const y = series.pts.map((p) => p.v);
    const t0 = DIE.dates.toUTC(event.startDate);
    const t1 = DIE.dates.toUTC(event.endDate);
    const m0 = Math.max(0, event.startIdx - 18);
    const m1 = Math.min(series.pts.length - 1, event.endIdx + 24);
    const traces = [{
      type: 'scatter', mode: 'lines', name: indicator.label,
      x: x.slice(m0, m1 + 1), y: y.slice(m0, m1 + 1),
      line: { color: '#203B59', width: 1.7 }, connectgaps: false,
      hovertemplate: '<b>%{x|%b %Y}</b><br>' + indicator.label + ': %{y:.2f}<extra></extra>'
    }];
    Plotly.react(el, traces, baseLayout({
      margin: { l: 46, r: 12, t: 10, b: 24 },
      shapes: [
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: '#9AA7B5', width: 1 } },
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: data.threshold, y1: data.threshold, line: { color: 'rgba(185,71,71,0.6)', width: 1, dash: 'dot' } },
        { type: 'rect', xref: 'x', x0: t0, x1: t1, yref: 'paper', y0: 0, y1: 1, fillcolor: 'rgba(185,71,71,0.10)', line: { width: 0 } }
      ],
      annotations: [{
        x: t0, xref: 'x', y: 1.05, yref: 'paper', showarrow: false,
        text: 'event window', font: { size: 10, color: '#B94747' }, xanchor: 'left'
      }],
      xaxis: { type: 'date', gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9 } },
      yaxis: {
        gridcolor: '#E2E7EE', zeroline: true, zerolinecolor: '#9AA7B5', linecolor: '#CBD5E1',
        title: { text: indicator.label + ' (' + indicator.units + ')', font: { size: 10, color: '#687588' } }
      }
    }), config('event-detail'));
  }

  /* --------------------------------------------- sensitivity chart -- */
  function sensitivityChart(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.points || !data.points.length) {
      state(el, 'NO DATA', 'Sensitivity requires a non-empty event catalogue.');
      return;
    }
    Plotly.react(el, [{
      type: 'scatter', mode: 'lines+markers',
      x: data.points.map((p) => p.x),
      y: data.points.map((p) => p.nEvents),
      line: { color: '#203B59', width: 1.8 },
      marker: { size: 7, color: '#203B59' },
      hovertemplate: '<b>' + data.xLabel + ': %{x}</b><br>%{y} events<extra></extra>',
      text: data.points.map((p) => p.note || ''),
      hovertext: data.points.map((p) => p.note || '')
    }], baseLayout({
      margin: { l: 40, r: 14, t: 8, b: 26 },
      xaxis: {
        title: { text: data.xLabel, font: { size: 10.5, color: '#687588' } },
        gridcolor: '#E2E7EE', linecolor: '#CBD5E1'
      },
      yaxis: {
        gridcolor: '#E2E7EE', linecolor: '#CBD5E1', rangemode: 'tozero',
        title: { text: 'identified events', font: { size: 10, color: '#687588' } }
      },
      annotations: data.defaultX !== undefined ? [{
        x: data.defaultX, xref: 'x', y: data.defaultY, yref: 'y',
        showarrow: true, arrowcolor: '#B94747', arrowwidth: 1.4,
        text: 'default', font: { size: 10, color: '#B94747' },
        ax: 0, ay: -32
      }] : []
    }), config('event-sensitivity'));
  }

  /* ------------------------------------------------ lag correlation -- */
  function lagCorrelationChart(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    if (!data.lags || !data.lags.length) {
      state(el, 'NO MATCHED MONTHS', 'The two indicators have no overlapping valid months for this selection.');
      return;
    }
    const valid = data.lags.filter((d) => Number.isFinite(d.r));
    if (!valid.length) {
      state(el, 'INSUFFICIENT PAIRS', 'Fewer than 3 matched months at every lag.');
      return;
    }
    const traces = [
      {
        type: 'scatter', mode: 'lines+markers', name: 'r (lag −12…+12)',
        x: data.lags.map((d) => d.lag), y: data.lags.map((d) => Number.isFinite(d.r) ? d.r : null),
        line: { color: '#203B59', width: 1.7 },
        marker: { size: 5, color: '#203B59' },
        connectgaps: false,
        customdata: data.lags.map((d) => d.n),
        hovertemplate: '<b>lag %{x} months</b><br>r = %{y:.3f}<br>n = %{customdata} pairs<extra></extra>'
      },
      {
        type: 'scatter', mode: 'markers', name: '95% CI (block bootstrap)',
        x: [], y: [],
        error_y: { type: 'data', symmetric: false, array: [], arrayminus: [], color: '#B94747', thickness: 1.2, width: 5 },
        hoverinfo: 'skip'
      }
    ];
    if (data.ci && Number.isFinite(data.ci.ci[0])) {
      const r = data.ci.r;
      traces[1].x = [data.ci.lag];
      traces[1].y = [r];
      traces[1].error_y.array = [Math.max(0, data.ci.ci[1] - r)];
      traces[1].error_y.arrayminus = [Math.max(0, r - data.ci.ci[0])];
    }
    if (data.optimal) {
      traces.push({
        type: 'scatter', mode: 'markers', name: 'optimal lag',
        x: [data.optimal.lag], y: [data.optimal.r],
        marker: { size: 11, color: '#B94747', line: { color: '#FFFFFF', width: 1.6 }, symbol: 'diamond' },
        hovertemplate: '<b>optimal lag %{x} months</b><br>r = %{y:.3f}<extra></extra>'
      });
    }
    Plotly.react(el, traces, baseLayout({
      margin: { l: 44, r: 12, t: 24, b: 26 },
      showlegend: true,
      legend: { orientation: 'h', y: 1.12, font: { size: 10 } },
      xaxis: {
        title: { text: 'lag (months) — positive: B responds after A', font: { size: 10, color: '#687588' } },
        dtick: 3, gridcolor: '#E2E7EE', linecolor: '#CBD5E1', zeroline: true, zerolinecolor: '#9AA7B5'
      },
      yaxis: {
        range: [-1.05, 1.05], gridcolor: '#E2E7EE', linecolor: '#CBD5E1',
        zeroline: true, zerolinecolor: '#9AA7B5',
        title: { text: 'Pearson r', font: { size: 10, color: '#687588' } }
      }
    }), config('lag-correlation'));
  }

  /* -------------------------------------------- dual indicator series -- */
  function dualSeriesChart(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    const a = data.seriesA.pts.filter((p) => p.v !== null);
    const b = data.seriesB.pts.filter((p) => p.v !== null);
    if (!a.length || !b.length) {
      state(el, 'NO VALID OBSERVATIONS', 'One of the indicators has no valid months in the analysis period.');
      return;
    }
    const traces = [
      {
        type: 'scatter', mode: 'lines', name: data.indA.label,
        x: a.map((p) => DIE.dates.toUTC(p.ym)), y: a.map((p) => p.v),
        line: { color: '#203B59', width: 1.5 },
        hovertemplate: '<b>%{x|%b %Y}</b><br>' + data.indA.label + ': %{y:.2f}<extra></extra>'
      },
      {
        type: 'scatter', mode: 'lines', name: data.indB.label,
        x: b.map((p) => DIE.dates.toUTC(p.ym)), y: b.map((p) => p.v),
        line: { color: '#D97745', width: 1.5 },
        hovertemplate: '<b>%{x|%b %Y}</b><br>' + data.indB.label + ': %{y:.2f}<extra></extra>'
      }
    ];
    Plotly.react(el, traces, baseLayout({
      margin: { l: 46, r: 14, t: 8, b: 22 },
      showlegend: true,
      legend: { orientation: 'h', y: 1.1, font: { size: 10.5 } },
      xaxis: { type: 'date', gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9 } },
      yaxis: {
        gridcolor: '#E2E7EE', zeroline: true, zerolinecolor: '#9AA7B5', linecolor: '#CBD5E1',
        title: { text: 'z-score / %', font: { size: 10, color: '#687588' } }
      }
    }), config('indicator-comparison-series'));
  }

  /* ------------------------------------------------------ heatmap -- */
  function correlationHeatmap(el, data) {
    if (unavailable(el)) return;
    clearState(el);
    const labels = data.labels;
    const z = data.z;
    if (!labels.length) { state(el, 'NO DATA', 'No indicators loaded.'); return; }
    // colour scale: white at 0 -> navy at 1 (single-hue, colourblind-safe)
    const colorscale = [[0, '#FFFFFF'], [0.5, '#A3C1CC'], [1, '#203B59']];
    Plotly.react(el, [{
      type: 'heatmap',
      x: labels, y: labels, z,
      colorscale, zmin: 0, zmax: 1,
      colorbar: { title: { text: 'r', font: { size: 10 } }, thickness: 12, len: 0.9, tickfont: { size: 9 } },
      hovertemplate: '<b>%{y} vs %{x}</b><br>r = %{z:.3f}<extra></extra>',
      xgap: 1.5, ygap: 1.5
    }], baseLayout({
      margin: { l: 96, r: 10, t: 10, b: 96 },
      xaxis: { tickfont: { size: 10 }, gridcolor: '#FFFFFF', linecolor: '#CBD5E1', tickangle: -45 },
      yaxis: { tickfont: { size: 10 }, gridcolor: '#FFFFFF', linecolor: '#CBD5E1' },
      plot_bgcolor: '#FAFBFC'
    }), config('correlation-heatmap'));
  }

  /* -------------------------------------------------------------- public -- */
  DIE.Charts = {
    available, unavailable, loading, state, clearState, timeSeries, severityBars, frequencyByYear,
    scatterCompare, areaTimeline, DIST_BINS, dryThresholds,
    rankingBars, statRamp, statRampWarm, statLegendHtml, trendChart, eventTimeline,
    eventDistribution, eventDetailSeries, sensitivityChart,
    lagCorrelationChart, dualSeriesChart, correlationHeatmap
  };
})();
