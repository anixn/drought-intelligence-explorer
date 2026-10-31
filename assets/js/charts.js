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

  function state(el, code, message) {
    clearState(el);
    const div = document.createElement('div');
    div.className = 'chart-state';
    div.innerHTML = (code ? '<span class="code">' + code + '</span>' : '') + '<span>' + message + '</span>';
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
      dragmode: 'pan'
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
    if (!available()) { state(el, 'CHART LIBRARY UNAVAILABLE', 'Plotly failed to load. All other analyses remain functional.'); return; }
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
    if (!available()) { state(el, 'CHART LIBRARY UNAVAILABLE', 'Plotly failed to load.'); return; }
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
    if (!available()) { state(el, 'CHART LIBRARY UNAVAILABLE', 'Plotly failed to load.'); return; }
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
    if (!available()) { state(el, 'CHART LIBRARY UNAVAILABLE', 'Plotly failed to load.'); return; }
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
    if (!available()) { state(el, 'CHART LIBRARY UNAVAILABLE', 'Plotly failed to load.'); return; }
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

  /* -------------------------------------------------------------- public -- */
  DIE.Charts = {
    available, state, clearState, timeSeries, severityBars, frequencyByYear,
    scatterCompare, areaTimeline, DIST_BINS, dryThresholds
  };
})();
