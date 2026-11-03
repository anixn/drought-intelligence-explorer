/* ===========================================================================
 * data-loader.js — data access layer
 * ---------------------------------------------------------------------------
 * Responsibilities
 *  - Resolve the deployment base path (GitHub Pages subdirectory, custom
 *    domain, or local server) so that every asset fetch is deployment-safe.
 *  - Load metadata.json, boundary GeoJSON files, district/state registries
 *    and indicator matrices (wide CSV via PapaParse) with sessionStorage
 *    caching keyed by methodology version.
 *  - Validate every dataset (missing values, duplicate district rows,
 *    invalid dates, invalid values, unknown district identifiers) and expose
 *    a structured report for the Data Sources dialog.
 *  - Provide classification (discrete classes from metadata) and continuous
 *    colour scales driven by the same metadata — a single source of truth.
 *  - Tiny pub/sub bus used across modules.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});
  DIE.datasets = new Map();
  DIE.bus = {
    _subs: {},
    on(evt, fn) { (this._subs[evt] = this._subs[evt] || []).push(fn); },
    emit(evt, payload) { (this._subs[evt] || []).forEach((fn) => { try { fn(payload); } catch (e) { console.error(e); } }); }
  };

  /* ---------------------------------------------------------- base path -- */
  function resolveBase() {
    const override = window.DIE_BASE_PATH_OVERRIDE;
    if (typeof override === 'string' && override) return override;
    const el = document.querySelector('script[src*="js/data-loader.js"]');
    if (el) {
      try {
        const url = new URL(el.getAttribute('src'), document.baseURI);
        const m = url.pathname.match(/^(.*)(?:assets\/js\/data-loader\.js)$/);
        if (m) return m[1] || '/';
      } catch (e) { /* fall through */ }
    }
    return './';
  }
  DIE.base = resolveBase();
  DIE.isLocalFile = location.protocol === 'file:';

  /* ------------------------------------------------------------- caches -- */
  function cacheKey(path) {
    return 'die:v' + (DIE.meta ? DIE.meta.methodology_version : '0') + ':' + path;
  }
  async function fetchText(path) {
    let hit = null;
    try { hit = sessionStorage.getItem(cacheKey(path)); } catch (e) { /* storage unavailable */ }
    if (hit !== null) return hit;
    const res = await fetch(DIE.base + path);
    if (!res.ok) throw new Error('HTTP ' + res.status + ' — ' + path);
    const text = await res.text();
    try { if (text.length < 3_000_000) sessionStorage.setItem(cacheKey(path), text); } catch (e) { /* quota */ }
    return text;
  }
  async function fetchJSON(path) { return JSON.parse(await fetchText(path)); }

  /* ------------------------------------------------------- date helpers -- */
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  DIE.dates = {
    monthsShort: MONTHS,
    label(ym) { const [y, m] = ym.split('-'); return MONTHS[+m - 1] + ' ' + y; },
    toUTC(ym) { const [y, m] = ym.split('-'); return new Date(Date.UTC(+y, +m - 1, 15)); },
    valid(ym) { return /^\d{4}-(0[1-9]|1[0-2])$/.test(ym); },
    compare(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  };

  /* ---------------------------------------------------- number formats -- */
  DIE.fmt = {
    int: new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }),
    dec: new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    dec2: new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    area(km2) { return this.int.format(Math.round(km2)) + ' km²'; },
    pct(x, dash) { return Number.isFinite(x) ? this.dec.format(x) + '%' : (dash || 'N/A'); },
    val(v, indicator) {
      if (!Number.isFinite(v)) return 'N/A';
      return (indicator && indicator.family === 'land')
        ? this.int.format(Math.round(v))
        : this.dec2.format(v);
    }
  };

  /* -------------------------------------------------------- colour util -- */
  function hexToRgb(h) {
    const n = parseInt(h.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function lerpRgb(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }
  function rgbToCss(c) {
    return 'rgb(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ')';
  }

  /**
   * Continuous colour ramp: anchors at the centre of every discrete class,
   * linear interpolation between them, clamped at the indicator scale.
   */
  function buildRamp(indicator) {
    const [lo, hi] = indicator.scale;
    const anchors = indicator.classes.map((c) => {
      const cLo = (c.min === null || c.min === undefined) ? lo : c.min;
      const cHi = (c.max === null || c.max === undefined) ? hi : c.max;
      const centre = (cLo + cHi) / 2;
      return { t: (centre - lo) / (hi - lo), rgb: hexToRgb(c.color) };
    }).sort((a, b) => a.t - b.t);
    return function (value) {
      if (!Number.isFinite(value)) return '#D7DEE7';
      const t = Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
      if (t <= anchors[0].t) return rgbToCss(anchors[0].rgb);
      if (t >= anchors[anchors.length - 1].t) return rgbToCss(anchors[anchors.length - 1].rgb);
      for (let i = 0; i < anchors.length - 1; i++) {
        const a = anchors[i], b = anchors[i + 1];
        if (t >= a.t && t <= b.t) return rgbToCss(lerpRgb(a.rgb, b.rgb, (t - a.t) / (b.t - a.t)));
      }
      return rgbToCss(anchors[anchors.length - 1].rgb);
    };
  }

  /* ----------------------------------------------------- classification -- */
  function classMatches(v, c) {
    const lo = (c.min === null || c.min === undefined) ? -Infinity : c.min;
    const hi = (c.max === null || c.max === undefined) ? Infinity : c.max;
    const loOk = v > lo || (c.minClosed === true && v === lo);
    const hiOk = v < hi || (c.maxClosed === true && v === hi);
    return loOk && hiOk;
  }
  function classify(value, indicator) {
    if (!Number.isFinite(value)) return null;
    for (const c of indicator.classes) if (classMatches(value, c)) return c;
    return null;
  }
  function isDroughtClass(c) { return !!c && /drought/.test(c.key); }
  function isSevereClass(c) { return !!c && (c.key === 'severe_drought' || c.key === 'extreme_drought'); }

  DIE.classify = classify;
  DIE.isDroughtClass = isDroughtClass;
  DIE.isSevereClass = isSevereClass;
  DIE.ramps = new Map();
  DIE.ramp = function (indicator) {
    if (!DIE.ramps.has(indicator.id)) DIE.ramps.set(indicator.id, buildRamp(indicator));
    return DIE.ramps.get(indicator.id);
  };
  /** Colour for a district value under the current display mode. */
  DIE.colorFor = function (value, indicator, mode) {
    if (!Number.isFinite(value)) return '#D7DEE7';
    if (mode === 'continuous') return DIE.ramp(indicator)(value);
    const c = classify(value, indicator);
    return c ? c.color : '#D7DEE7';
  };

  /* ------------------------------------------------------------ loaders -- */
  async function loadMetadata() {
    DIE.meta = await fetchJSON('data/metadata.json');
    DIE.indicatorById = new Map(DIE.meta.indicators.map((i) => [i.id, i]));
    return DIE.meta;
  }

  async function loadBoundaries() {
    const [districts, states, outline] = await Promise.all([
      fetchJSON('data/boundaries/india_districts.geojson'),
      fetchJSON('data/boundaries/india_states.geojson'),
      fetchJSON('data/boundaries/india_outline.geojson')
    ]);
    DIE.boundaries = { districts, states, outline };
    return DIE.boundaries;
  }

  async function loadRegistry() {
    const text = await fetchText('data/districts.csv');
    const parsed = window.Papa
      ? Papa.parse(text, { header: true, skipEmptyLines: true })
      : { data: [] };
    const districts = new Map();
    const byState = new Map();
    for (const r of parsed.data) {
      if (!r.district_id) continue;
      const d = {
        id: r.district_id, name: r.district_name, state: r.state_name, sid: r.state_id,
        area: parseFloat(r.area_km2), lon: parseFloat(r.centroid_lon), lat: parseFloat(r.centroid_lat)
      };
      districts.set(d.id, d);
      if (!byState.has(d.sid)) byState.set(d.sid, []);
      byState.get(d.sid).push(d);
    }
    for (const list of byState.values()) list.sort((a, b) => a.name.localeCompare(b.name));

    const sText = await fetchText('data/states.csv');
    const sParsed = window.Papa ? Papa.parse(sText, { header: true, skipEmptyLines: true }) : { data: [] };
    const states = new Map();
    for (const r of sParsed.data) {
      if (!r.state_id) continue;
      states.set(r.state_id, {
        id: r.state_id, name: r.state_name, area: parseFloat(r.area_km2),
        nDistricts: +r.n_districts, lon: parseFloat(r.centroid_lon), lat: parseFloat(r.centroid_lat)
      });
    }
    DIE.registry = { districts, states, byState };
    return DIE.registry;
  }

  /* ------------------------------------------------- indicator matrices -- */
  /**
   * Parse a wide-format indicator CSV:
   *   district_id, district_name, state_name, 2005-01, 2005-02, ...
   * Returns a dataset with values[i][j] (NaN = missing) plus a validation
   * report. Duplicate district rows are merged (last wins) and counted.
   */
  async function loadIndicator(indicatorId) {
    if (DIE.datasets.has(indicatorId)) return DIE.datasets.get(indicatorId);
    const indicator = DIE.indicatorById.get(indicatorId);
    if (!indicator) throw new Error('Unknown indicator: ' + indicatorId);

    const text = await fetchText(indicator.file);
    if (!window.Papa) throw new Error('PapaParse unavailable — cannot parse ' + indicator.file);
    const parsed = Papa.parse(text, { skipEmptyLines: 'greedy' });

    const report = {
      indicator: indicatorId,
      rowsParsed: 0, duplicates: 0, missingCells: 0, invalidValues: 0,
      invalidDates: 0, missingIds: 0, unknownDistricts: 0, unrepresentedDistricts: 0,
      issues: []
    };

    const rows = parsed.data;
    if (!rows.length) throw new Error('Empty dataset: ' + indicator.file);
    const header = rows[0];

    // --- validate date columns against the declared period ---
    const period = DIE.meta.period;
    const dates = [];
    const dateCols = [];
    for (let c = 3; c < header.length; c++) {
      const col = (header[c] || '').trim();
      if (DIE.dates.valid(col) && col >= period.start && col <= period.end) {
        dates.push(col); dateCols.push(c);
      } else {
        report.invalidDates++;
        if (report.issues.length < 12) report.issues.push('Invalid date column skipped: "' + col + '"');
      }
    }

    const districtIndex = new Map();
    const districtIds = [];
    const values = [];

    for (let r = 1; r < rows.length; r++) {
      const row = rows[r];
      if (!row || !row.length) continue;
      report.rowsParsed++;
      const id = (row[0] || '').trim();
      if (!id) { report.missingIds++; continue; }
      if (!DIE.registry.districts.has(id)) {
        report.unknownDistricts++;
        if (report.issues.length < 12) report.issues.push('District id not present in boundaries: "' + id + '"');
        continue;
      }
      if (districtIndex.has(id)) {
        report.duplicates++;
        if (report.issues.length < 12) report.issues.push('Duplicate district row merged (last kept): "' + id + '"');
      } else {
        districtIndex.set(id, districtIds.length);
        districtIds.push(id);
        // Empty CSV cells mean "missing", not zero. Float64Array is
        // zero-initialised, so fill with NaN before writing parsed values.
        const rowValues = new Float64Array(dates.length);
        rowValues.fill(NaN);
        values.push(rowValues);
      }
      const i = districtIndex.get(id);
      for (let j = 0; j < dates.length; j++) {
        const raw = (row[dateCols[j]] !== undefined ? String(row[dateCols[j]]).trim() : '');
        if (raw === '') { report.missingCells++; continue; }
        const v = parseFloat(raw);
        if (!Number.isFinite(v)) {
          report.invalidValues++;
          report.missingCells++;
        } else {
          values[i][j] = v;
        }
      }
    }

    const represented = new Set(districtIds);
    for (const id of DIE.registry.districts.keys()) {
      if (!represented.has(id)) report.unrepresentedDistricts++;
    }

    // ---- availability window -------------------------------------------
    // Some inputs start later than others (MODIS NDVI is only available from
    // 2000-02, so VCI cannot cover the full 1981+ record).  Compute the first
    // and last month that contain at least one finite value and measure
    // completeness inside that window, not across the whole declared period.
    let firstValid = dates.length;
    let lastValid = -1;
    for (let j = 0; j < dates.length; j++) {
      for (let i = 0; i < values.length; i++) {
        if (Number.isFinite(values[i][j])) {
          if (j < firstValid) firstValid = j;
          if (j > lastValid) lastValid = j;
          break;
        }
      }
    }
    const hasData = lastValid >= firstValid;
    const availableStart = hasData ? firstValid : 0;
    const availableEnd = hasData ? lastValid : -1;
    const availableMonths = hasData ? lastValid - firstValid + 1 : 0;

    let missingAvailable = 0;
    if (hasData) {
      for (let i = 0; i < values.length; i++) {
        for (let j = firstValid; j <= lastValid; j++) {
          if (!Number.isFinite(values[i][j])) missingAvailable++;
        }
      }
    }

    report.spanMonths = dates.length;
    report.availableFrom = hasData ? dates[firstValid] : null;
    report.availableTo = hasData ? dates[lastValid] : null;
    report.availableMonths = availableMonths;
    report.completeness = hasData && availableMonths
      ? 1 - missingAvailable / Math.max(1, districtIds.length * availableMonths)
      : 0;
    report.periodCompleteness = districtIds.length && dates.length
      ? 1 - report.missingCells / Math.max(1, districtIds.length * dates.length)
      : 0;
    report.validObservations = districtIds.length * availableMonths - missingAvailable;

    const dataset = {
      id: indicatorId, indicator, dates, values, districtIds, districtIndex,
      dateIndex: new Map(dates.map((d, j) => [d, j])),
      availableStartIndex: availableStart,
      availableEndIndex: availableEnd,
      availableFrom: report.availableFrom,
      availableTo: report.availableTo,
      report
    };
    DIE.datasets.set(indicatorId, dataset);
    DIE.bus.emit('dataset:loaded', dataset);
    console.info('[DIE] loaded ' + indicatorId + ': ' + districtIds.length + ' districts × ' +
      dates.length + ' months · completeness ' + (report.completeness * 100).toFixed(1) + '%', report);
    return dataset;
  }

  DIE.loader = {
    metadata: loadMetadata,
    boundaries: loadBoundaries,
    registry: loadRegistry,
    indicator: loadIndicator,
    fetchText,
    fetchJSON
  };
})();
