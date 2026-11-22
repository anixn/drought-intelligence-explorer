/* ---------------------------------------------------------------------------
 * DIE v2.0 - Engine-backed datasets (?engine=1, task M1.8; docs/v2/04 §3.4)
 *
 * When the URL carries ?engine=1, indicator datasets are built from the
 * Parquet store (DuckDB-WASM) instead of the wide CSVs. The produced dataset
 * object is structurally identical to the CSV path's (data-loader.js), so
 * every consumer - Historical first, then the other workspaces as they are
 * migrated - runs unchanged. The CSV loader stays the default and the
 * permanent fallback (any engine failure falls back to CSV with a toast).
 *
 * Parity rules implemented here (verified by the M1.8 gate):
 *  - dates[] is built from the DECLARED period (metadata.json), not from the
 *    parquet: the converter omits absent rows, so months with no data at all
 *    (e.g. VCI before 2000-02) must still appear as all-NaN columns, exactly
 *    like the empty CSV columns they came from.
 *  - values are Float64Array rows indexed by districtIndex/dateIndex; absent
 *    parquet rows stay NaN (missing = never imputed, R10).
 *  - Parquet values are float32 (documented contract, docs/v2/03 §8.2). CSV
 *    cells round-trip through float32 exactly: float32("1.60") re-reads as
 *    1.600000023841858, which is what the store holds. Spot checks therefore
 *    compare at source precision (Math.fround) AND at display precision
 *    (2 decimals / integers), both exact.
 *  - report fields carry the same semantics (missingCells counts every
 *    missing district-month cell inside the declared span, including the
 *    pre-availability months, like the CSV path does).
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});

  let failed = false;        // sticky: after one engine failure use CSV only
  let chipShown = false;

  function flagOn() {
    const p = new URLSearchParams(location.search);
    return p.get('engine') === '1';
  }

  /** Engine mode active: flag present, engine module loaded, no sticky failure. */
  function enabled() {
    return flagOn() && !failed && !!(DIE.Engine && DIE.Engine.query);
  }

  function markFailed() { failed = true; }
  function failedOnce() { return failed; }

  /* metadata indicator id -> catalog variable id (spi_3 -> spi_03; sma/vci pass) */
  function varIdFor(indicatorId) {
    const m = /^(spi|spei)_(\d{1,2})$/.exec(indicatorId);
    return m ? m[1] + '_' + ('0' + m[2]).slice(-2) : indicatorId;
  }

  /** One-time topbar chip: makes the engine-backed mode visible (R2 - the
   *  data source is always labelled). Renders nothing when the CSV path runs. */
  function ensureChip() {
    if (chipShown || !document.getElementById) return;
    const anchor = document.getElementById('chipUpdated');
    if (!anchor) return;
    const chip = document.createElement('span');
    chip.className = 'chip chip-engine';
    chip.id = 'chipEngine';
    chip.title = 'Data served from the Parquet store via DuckDB-WASM ' +
      '(?engine=1). Values are identical to the CSV path at source precision.';
    chip.setAttribute('aria-label', 'Engine data mode active');
    chip.textContent = 'Engine data · DuckDB';
    anchor.insertAdjacentElement('afterend', chip);
    chipShown = true;
  }

  /** Build the declared-period month list exactly like the CSV header scan:
   *  every valid YYYY-MM inside [period.start, period.end], in order. */
  function declaredDates(period) {
    const dates = [];
    let y = Number(period.start.slice(0, 4));
    let m = Number(period.start.slice(5, 7));
    const endY = Number(period.end.slice(0, 4));
    const endM = Number(period.end.slice(5, 7));
    while (y < endY || (y === endY && m <= endM)) {
      const col = y + '-' + (m < 10 ? '0' + m : m);
      if (DIE.dates.valid(col) && col >= period.start && col <= period.end) dates.push(col);
      m += 1; if (m > 12) { m = 1; y += 1; }
    }
    return dates;
  }

  async function buildDataset(indicator, indicatorId) {
    if (!DIE.Engine) throw new Error('engine module not loaded');
    const cat = await DIE.Engine.ensureCatalog();
    const varId = varIdFor(indicatorId);
    const v = (cat.variables || []).find((x) => x.id === varId);
    const files = v && v.files && v.files.observed;
    if (!files || !files.length) {
      throw new Error('no observed parquet file for ' + varId);
    }
    await DIE.Engine.ensureEngine();

    const report = {
      indicator: indicatorId,
      source: 'parquet (DuckDB-WASM) · ' + files[0],
      engine: true,
      rowsParsed: 0, duplicates: 0, missingCells: 0, invalidValues: 0,
      invalidDates: 0, missingIds: 0, unknownDistricts: 0, unrepresentedDistricts: 0,
      issues: []
    };

    // --- dates: declared period (parity with the CSV header scan) --------
    const period = DIE.meta.period;
    const dates = declaredDates(period);
    const dateIndex = new Map(dates.map((d, j) => [d, j]));

    // --- districts: distinct ids in file, filtered by the registry --------
    const fileUrl = DIE.Engine.absPath(files[0]);
    const idTable = await DIE.Engine.query(
      "SELECT DISTINCT district_id::VARCHAR AS district_id " +
      "FROM read_parquet(['" + fileUrl + "']) ORDER BY district_id");
    const districtIds = [];
    const districtIndex = new Map();
    for (const row of idTable.toArray()) {
      const id = row.district_id;
      if (!DIE.registry.districts.has(id)) {
        report.unknownDistricts++;
        if (report.issues.length < 12) report.issues.push('District id not present in boundaries: "' + id + '"');
        continue;
      }
      districtIndex.set(id, districtIds.length);
      districtIds.push(id);
    }

    // --- values: one Float64Array row per district, NaN-filled ------------
    const values = districtIds.map(() => {
      const a = new Float64Array(dates.length);
      a.fill(NaN);
      return a;
    });

    const t = await DIE.Engine.query(
      "SELECT district_id::VARCHAR AS district_id, year, month, value::DOUBLE AS value " +
      "FROM read_parquet(['" + fileUrl + "'])");
    const ids = t.getChild('district_id').toArray();
    const ys = t.getChild('year').toArray();
    const ms = t.getChild('month').toArray();
    const vs = t.getChild('value').toArray();
    const n = t.numRows;
    report.rowsParsed = n;

    let finiteWrites = 0;
    for (let k = 0; k < n; k++) {
      const di = districtIndex.get(ids[k]);
      if (di === undefined) continue;                    // already counted unknown
      const col = ys[k] + '-' + (ms[k] < 10 ? '0' + ms[k] : ms[k]);
      const j = dateIndex.get(col);
      if (j === undefined) {                             // outside declared period
        report.invalidDates++;
        if (report.issues.length < 12) report.issues.push('Row outside declared period: "' + col + '"');
        continue;
      }
      const val = vs[k];
      if (val === null || val === undefined || !Number.isFinite(val)) {
        continue;                     // stored NULL: counted by the total-finite audit below
      }
      values[di][j] = val;
      finiteWrites++;
    }

    // every district-month cell inside the declared span that holds no value
    // counts as missing - same semantics as empty CSV cells (includes the
    // pre-availability months, e.g. VCI before 2000-02)
    report.missingCells += districtIds.length * dates.length - finiteWrites;
    if (report.invalidDates) {
      report.issues.push('Rows outside declared period skipped: ' + report.invalidDates);
    }

    const represented = new Set(districtIds);
    for (const id of DIE.registry.districts.keys()) {
      if (!represented.has(id)) report.unrepresentedDistricts++;
    }

    // ---- availability window (identical scan to the CSV path) -----------
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

    ensureChip();
    return dataset;
  }

  DIE.EngineData = { enabled, buildDataset, markFailed, failedOnce, varIdFor };
})();
