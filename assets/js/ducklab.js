/* =========================================================================
 * DIE v2.0 — DuckDB-WASM data engine service (task M1.6, docs/v2/04 §3)
 * =========================================================================
 * In-browser analytical SQL over the Parquet store; zero backend. The v1.0
 * CSV loader stays the default/first-paint path; this engine activates per
 * tab behind ?engine=1 (M1.8) and must reproduce CSV-path values exactly.
 *
 * Spec compliance (docs/v2/04 §3.1–§3.3) — the seven measured pitfalls:
 *  P1 shared-load promise: ensureEngine() caches the PROMISE, not a boolean.
 *  P2 heuristic caching: server.py sends Cache-Control: no-cache for
 *     html/js/json; every catalog fetch uses cache:'no-store'.
 *  P3 byte counting happens in DuckDB's worker: the fetch/XHR interceptor is
 *     injected as the FIRST lines of the worker blob; HEADs are excluded
 *     (DuckDB HEADs file size then GETs ranges — counting both doubles).
 *  P4 httpfs needs absolute URLs: abs() on every read_parquet path.
 *  P5 ::VARCHAR in WHERE kills filter pushdown: cast only in projections.
 *  P6 Range support: served by server.py / GitHub Pages / R2, never
 *     python3 -m http.server.
 *  P7 no HTTP globbing: explicit file lists built from catalog.json.
 *
 * Settings (prototype-verified, docs/v2/04 §3.1): applied defensively — an
 * unknown setting logs a warning instead of failing init.
 *
 * Query safety: NO user free-text is concatenated. All ids are validated
 * against catalog.json keys / strict slugs (^[a-z0-9-]+$), years/months must
 * be integers. The general escape hatch query(sql) is for Engine Lab (M1.7)
 * and trusted builders only.
 * ========================================================================= */

(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});

  const DUCKDB_VERSION = '1.32.0';             // locked architecture (AGENTS §4)
  const DUCKDB_ESM_URL =
    'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@' + DUCKDB_VERSION + '/+esm';
  // Root-absolute: pages may live in any directory (e.g. scripts/ dev pages,
  // v1.0 tab views) - a page-relative URL would resolve against the page path.
  // When data/data-source.json names a remote snapshot (R2, M7.1) the catalog
  // travels with it; otherwise the same-origin copy is used.
  function catalogUrl() {
    const base = DIE.dataBase;
    if (base) return base + 'parquet/catalog.json';
    return new URL('/data/parquet/catalog.json', location.origin).href;
  }

  const DISTRICT_RE = /^[a-z0-9-]{1,64}$/;     // v1.0 registry slugs
  const VAR_RE = /^[a-z0-9_]{1,32}$/;
  const DATE_RE = /^(\d{4})-(0[1-9]|1[0-2])$/;

  /* ---- worker-side byte interceptor (P3) -------------------------------- */
  /* Injected verbatim as the first lines of the worker blob. Counts GET
   * response bytes only; HEADs are excluded. Deltas are posted on a dedicated
   * MessageChannel port handed over from the main thread — NOT on the shared
   * worker channel — so duckdb-wasm's own dispatcher never sees them (it logs
   * "unassociated response" for every foreign message type; measured
   * 2026-11-22, M7.3 polish). The main-side listener filters by type either
   * way; duckdb-wasm's handler is unaffected. */
  const WORKER_INTERCEPTOR = `
    (function () {
      self.__ducklab = { bytes: 0, requests: 0 };
      var __dlPort = null;
      function __dlPortMsg(e) {
        var d = e.data;
        if (!d || d.type !== 'ducklab-port') return;
        // transferable ports live on the event, never on the cloned data
        if (e.ports && e.ports[0]) __dlPort = e.ports[0];
        else if (d.ports && d.ports[0]) __dlPort = d.ports[0];
        // duckdb-wasm's own onmessage would answer this control message with an
        // ERROR on the shared channel; stop it here, we registered first.
        if (e.stopImmediatePropagation) e.stopImmediatePropagation();
        self.removeEventListener('message', __dlPortMsg);
      }
      self.addEventListener('message', __dlPortMsg);
      function track(url, method, contentLength) {
        if (String(method || 'GET').toUpperCase() === 'HEAD') return;
        var n = 0;
        if (contentLength != null) {
          n = parseInt(contentLength, 10);
          if (!isFinite(n) || n < 0) n = 0;
        }
        self.__ducklab.bytes += n;
        self.__ducklab.requests += 1;
        try {
          if (__dlPort) __dlPort.postMessage({ type: 'ducklab-bytes', delta: n });
          else self.postMessage({ type: 'ducklab-bytes', delta: n });
        } catch (e) {}
      }
      var __origFetch = self.fetch;
      if (__origFetch) {
        self.fetch = function (input, init) {
          var url = (typeof input === 'string') ? input : (input && input.url) || '';
          var method = (init && init.method) || (input && input.method) || 'GET';
          return __origFetch.apply(this, arguments).then(function (res) {
            try {
              var cloned = res.clone();
              var cl = cloned.headers ? cloned.headers.get('content-length') : null;
              if (cl == null) {
                // no content-length (rare on static hosts): drain a clone
                return cloned.arrayBuffer().then(function (buf) {
                  track(url, method, buf.byteLength);
                  return res;
                });
              }
              track(url, method, cl);
              return res;
            } catch (e) { return res; }
          });
        };
      }
      var __origOpen = XMLHttpRequest.prototype.open;
      var __origSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function (method, url) {
        this.__ducklabMethod = method; this.__ducklabUrl = url;
        return __origOpen.apply(this, arguments);
      };
      XMLHttpRequest.prototype.send = function () {
        var self2 = this;
        this.addEventListener('load', function () {
          track(self2.__ducklabUrl, self2.__ducklabMethod, self2.getResponseHeader('content-length'));
        });
        return __origSend.apply(this, arguments);
      };
    })();`;

  function newEngineError(kind, message, cause) {
    const e = new Error(message || kind);
    e.name = 'DIEEngineError';
    e.kind = kind;
    if (cause) e.cause = cause;
    return e;
  }

  function absPath(rel) {                       // P4: httpfs needs absolute
    if (!/^https?:/i.test(location.protocol)) {
      throw newEngineError('no-http',
        'Engine requires http(s) — serve the site with server.py (P6).');
    }
    // Remote snapshot (R2): catalog paths stay repo-relative ("data/…") so the
    // data contract never changes; only the origin moves.
    if (DIE.dataBase && /^data\//.test(rel)) {
      return DIE.dataBase + rel.slice('data/'.length);
    }
    return new URL(rel, location.origin + '/').href;
  }

  /* ---- service ---------------------------------------------------------- */

  const state = {
    initPromise: null,        // P1: the promise is the cache, never a flag
    catalogPromise: null,
    catalog: null,
    conn: null,
    db: null,
    queryCache: new Map(),    // sql string -> Promise<Arrow Table>
    lastMs: 0,
    lastSql: null,
    bytes: 0,                 // main-side mirror of the worker interceptor
    requests: 0,
    settingsApplied: [],
  };

  function onWorkerMessage(ev) {
    const d = ev && ev.data;
    if (d && d.type === 'ducklab-bytes') {
      state.bytes += d.delta | 0;
      state.requests += 1;
    }
    // everything else belongs to duckdb-wasm's own handler
  }

  async function initEngine() {
    let duckdb;
    try {
      duckdb = await import(/* webpackIgnore: true */ DUCKDB_ESM_URL);
    } catch (err) {
      throw newEngineError('cdn-unreachable',
        'DuckDB-WASM could not be loaded from jsDelivr. The CSV loader ' +
        'remains the fallback path (docs/v2/04 §3.4).', err);
    }

    const bundles = await duckdb.getJsDelivrBundles();
    const bundle = bundles.eh || bundles.mvp;   // eh preferred, mvp fallback
    if (!bundle || !bundle.mainWorker) {
      throw newEngineError('bundle-missing', 'No usable duckdb-wasm bundle.');
    }

    const workerBlob = new Blob(
      [WORKER_INTERCEPTOR, '\nimportScripts("' + bundle.mainWorker + '");\n'],
      { type: 'text/javascript' });
    const workerUrl = URL.createObjectURL(workerBlob);
    const worker = new Worker(workerUrl);
    worker.addEventListener('message', onWorkerMessage);
    URL.revokeObjectURL(workerUrl);   // worker already loaded the blob

    /* Dedicated byte-counter channel (M7.3 polish): the interceptor posts its
     * deltas on port2, and only this port feeds onWorkerMessage, so the
     * duckdb-wasm dispatcher on the shared channel never logs an
     * "unassociated response" warning per transferred byte. The shared-channel
     * listener stays as a fallback. */
    const byteChannel = new MessageChannel();
    byteChannel.port1.onmessage = onWorkerMessage;
    worker.postMessage({ type: 'ducklab-port' }, [byteChannel.port2]);

    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    state.db = db;
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    const conn = await db.connect();
    state.conn = conn;

    // Mandatory settings (spec §3.1). Applied defensively: an unrecognised
    // setting name warns instead of breaking init.
    const settings = [
      'SET disable_parquet_prefetching = true',  // P3-adjacent: no speculative row-group fetches
      'SET parquet_metadata_cache = true',
    ];
    for (const s of settings) {
      try { await conn.query(s); state.settingsApplied.push(s); }
      catch (err) { console.warn('[ducklab] setting rejected:', s, err && err.message); }
    }

    return { duckdb, db, conn };
  }

  function ensureEngine() {
    if (!state.initPromise) {
      state.initPromise = initEngine().catch((err) => {
        state.initPromise = null;   // allow retry after a transient failure
        throw err;
      });
    }
    return state.initPromise;
  }

  async function ensureCatalog() {
    if (!state.catalogPromise) {
      state.catalogPromise = fetch(catalogUrl(), { cache: 'no-store' })  // P2
        .then((r) => {
          if (!r.ok) throw newEngineError('catalog-http', 'catalog.json HTTP ' + r.status);
          return r.json();
        })
        .then((catalog) => { state.catalog = catalog; return catalog; })
        .catch((err) => {
          state.catalogPromise = null;
          throw (err && err.name === 'DIEEngineError') ? err
            : newEngineError('catalog-unreachable', 'catalog.json could not be fetched.', err);
        });
    }
    return state.catalogPromise;
  }

  /* ---- byte/timing accounting ------------------------------------------- */

  function bytes() {
    return { bytes: state.bytes, requests: state.requests,
             lastMs: state.lastMs, lastSql: state.lastSql };
  }
  function lastMs() { return state.lastMs; }

  /* ---- query core -------------------------------------------------------- */

  async function query(sql) {
    await ensureEngine();
    const cached = state.queryCache.get(sql);
    if (cached) {                                 // P1-adjacent: share per-SQL promise
      const t0 = performance.now();
      const out = await cached;
      state.lastMs = performance.now() - t0;      // await time of a repeat ≈ 0
      state.lastSql = sql;
      return out;
    }
    const t0 = performance.now();
    const bytesBefore = state.bytes;
    const promise = state.conn.query(sql).then((r) => r);
    state.queryCache.set(sql, promise);           // share even while in flight
    try {
      const out = await promise;
      state.lastMs = performance.now() - t0;
      state.lastSql = sql;
      out.__ducklab = { ms: state.lastMs, bytes: state.bytes - bytesBefore };
      return out;
    } catch (err) {
      state.queryCache.delete(sql);               // failed SQL is not cacheable
      throw err;
    }
  }

  /* ---- builders (validated inputs; explicit file lists from catalog, P7) -- */

  function catalogVariable(varId) {
    if (!VAR_RE.test(varId)) throw newEngineError('bad-variable', 'variable id rejected: ' + varId);
    const cat = state.catalog;
    if (!cat) throw newEngineError('no-catalog', 'catalog not loaded yet');
    const v = (cat.variables || []).find((x) => x.id === varId);
    if (!v) throw newEngineError('unknown-variable', 'variable not in catalog: ' + varId);
    return v;
  }

  function observedFile(varId, era) {
    const v = catalogVariable(varId);
    const files = v.files && v.files[era || 'observed'];
    if (!files || !files.length) {
      throw newEngineError('era-unavailable',
        'era "' + (era || 'observed') + '" has no files for ' + varId + ' yet');
    }
    return files.map(absPath);
  }

  function intYear(y) {
    const n = Number(y);
    if (!Number.isInteger(n) || n < 1900 || n > 2100) {
      throw newEngineError('bad-year', 'year must be an integer 1900-2100: ' + y);
    }
    return n;
  }

  // Arrow table → plain objects (the UI layer consumes rows, not Arrow).
  // int64 columns (era-C year/month are int64) arrive as BigInt; the UI does
  // plain arithmetic on them, so widen to Number centrally (>2^53 not used).
  function toRows(table) {
    if (!table) return [];
    const widen = (v) => (typeof v === "bigint" ? Number(v) : v);
    return table.toArray().map((r) => {
      const o = r.toJSON();
      for (const k in o) o[k] = widen(o[k]);
      return o;
    });
  }

  async function slice(opts) {
    const era = opts.era || 'observed';
    const varId = opts.variable;
    const district = String(opts.district || '');
    if (!DISTRICT_RE.test(district)) {
      throw newEngineError('bad-district', 'district id rejected: ' + district);
    }
    const files = observedFile(varId, era).map((f) => "'" + f + "'").join(', ');
    let where = "district_id = '" + district + "'";
    if (opts.yearRange) {
      const [a, b] = opts.yearRange.map(intYear);
      where += ' AND year BETWEEN ' + Math.min(a, b) + ' AND ' + Math.max(a, b);
    }
    // P5: ::DOUBLE cast lives in the projection list, never in WHERE
    const sql =
      'SELECT year, month, value::DOUBLE AS value ' +
      'FROM read_parquet([' + files + ']) ' +
      'WHERE ' + where + ' ORDER BY year, month';
    return toRows(await query(sql));
  }

  async function mapMonth(opts) {
    const era = opts.era || 'observed';
    const varId = opts.variable;
    const m = DATE_RE.exec(String(opts.date || ''));
    if (!m) throw newEngineError('bad-date', 'date must be YYYY-MM: ' + opts.date);
    const files = observedFile(varId, era).map((f) => "'" + f + "'").join(', ');
    const sql =
      'SELECT district_id, value::DOUBLE AS value ' +
      'FROM read_parquet([' + files + ']) ' +
      'WHERE year = ' + Number(m[1]) + ' AND month = ' + Number(m[2]);
    return toRows(await query(sql));
  }

  /* Era A (atlas reconstruction): one year of one scale, all districts.
   * Layout mirrors era B exactly (data/parquet/atlas/variable=<id>/
   * year=<yyyy>/part-0.parquet), so one partition per fetch (M6.3). */
  async function atlasYear(opts) {
    const cat = state.catalog || (await ensureCatalog());
    const eraA = cat.eras && cat.eras.atlas;
    if (!eraA || !eraA.available) {
      throw newEngineError('era-a-unavailable',
        'era A has no published store yet (promotion pending; R3).');
    }
    const v = catalogVariable(opts.variable);
    const files = (v.files && v.files.atlas) || [];
    if (!files.length) {
      throw newEngineError('no-files', 'no atlas files for ' + v.id);
    }
    const year = intYear(opts.year);
    const f = files.find((p) => {
      const m = /year=(\d{4})\//.exec(p.replace(/\\/g, '/') + '/');
      return m && +m[1] === year;
    });
    if (!f) {
      throw newEngineError('no-files',
        'no atlas partition for ' + v.id + ' year ' + year);
    }
    let where = '';
    if (opts.month) {
      const mo = intYear(opts.month);
      if (mo < 1 || mo > 12) {
        throw newEngineError('bad-month', 'month must be 1-12: ' + opts.month);
      }
      where = ' WHERE month = ' + mo;
    }
    return toRows(await query(
      'SELECT district_id, year, month, value::DOUBLE AS value ' +
      'FROM read_parquet([\'' + absPath(f) + '\'])' + where +
      ' ORDER BY month, district_id'));
  }

  /* Era A vs era B cross-validation (task M6.6). The product is a built
   * artifact (validation-studies/crossval/01_build_overlap.py), not an
   * on-the-fly join: the UI reads the precomputed per-district metrics (the
   * map/table source) and the area-weighted monthly agreement series. The
   * street-level overlap file is available for drill-down/download but is
   * never fetched for a first paint (7.7 MB). */
  async function crossval(opts) {
    const cat = state.catalog || (await ensureCatalog());
    const cv = cat.crossval;
    if (!cv) {
      throw newEngineError('no-crossval',
        'cross-validation product not built yet (task M6.6).');
    }
    const part = opts.part === 'monthly' ? 'monthly' : 'per_district';
    const file = cv.files && cv.files[part];
    if (!file) {
      throw newEngineError('no-crossval-file', 'crossval file missing: ' + part);
    }
    let where = '';
    const conds = [];
    if (opts.variable) {
      const allowed = cv.variables || [];
      if (allowed.indexOf(opts.variable) === -1) {
        throw newEngineError('bad-variable',
          'not a cross-validated variable: ' + opts.variable);
      }
      conds.push("variable = '" + opts.variable + "'");
    }
    if (opts.district) {
      if (!/^[a-z0-9-]+$/.test(String(opts.district))) {
        throw newEngineError('bad-district', 'district id rejected');
      }
      conds.push("district_id = '" + opts.district + "'");
    }
    if (conds.length) where = ' WHERE ' + conds.join(' AND ');
    const double = (c) => c + '::DOUBLE AS ' + c;
    const cols = part === 'monthly'
      ? ['variable', 'date', 'n_districts', 'mean_a', 'mean_b', 'diff',
         'state_agree', 'both_drought', 'class_exact', 'class_near']
      : ['variable', 'district_id', 'n', 'n_window', 'coverage', 'r', 'bias',
         'rmsd', 'sd_diff', 'state_agree', 'both_drought', 'severe_agree',
         'class_exact', 'class_near', 'a_drought_share', 'b_drought_share',
         'a_mean', 'b_mean'];
    const proj = cols.map((c) => (c === 'variable' || c === 'district_id' ||
      c === 'date' || c === 'n' || c === 'n_window' || c === 'n_districts')
      ? c : double(c)).join(', ');
    const order = part === 'monthly' ? ' ORDER BY variable, date'
      : ' ORDER BY variable, district_id';
    return toRows(await query(
      'SELECT ' + proj + ' FROM read_parquet([\'' + absPath(file) + '\'])' +
      where + order));
  }

  /* X7 seam uncertainty (task M6.8): the per-district population SD of the
   * era B - era A difference, computed ONCE by the cross-validation builder
   * over the D6 window (1981-2014). SPEI-12 is the series named by the X7
   * memo; it is the value every projection tooltip quotes. Cached: the map
   * tooltip re-evaluates on every hover and must not issue a query each time. */
  let seamPromise = null;
  function seamUncertainty(reload) {
    if (reload) seamPromise = null;
    if (!seamPromise) {
      seamPromise = crossval({ variable: 'spei_12', part: 'per_district' })
        .then((rows) => {
          const out = new Map();
          for (const r of rows) {
            const v = Number(r.sd_diff);
            if (Number.isFinite(v)) out.set(r.district_id, v);
          }
          return out;
        })
        .catch((err) => {
          seamPromise = null;   // allow a retry after a transient failure
          throw err;
        });
    }
    return seamPromise;
  }

  /* One district, one month, every era-B indicator — the district-profile
   * strip (M10.6). Reads the committed observed Parquet files directly so a
   * direct permalink does not have to download ten wide CSVs first. */
  async function observedAt(opts) {
    const cat = state.catalog || (await ensureCatalog());
    const did = String(opts.district || '');
    if (!/^[a-z0-9-]+$/.test(did)) {
      throw newEngineError('bad-district', 'district id rejected');
    }
    const m = /^(\d{4})-(\d{2})$/.exec(String(opts.date || ''));
    if (!m) throw newEngineError('bad-date', 'date must be YYYY-MM');
    const files = [];
    const seen = new Set();
    for (const v of cat.variables || []) {
      const list = (v.files && v.files.observed) || [];
      for (const f of list) {
        if (!seen.has(f)) { seen.add(f); files.push(absPath(f)); }
      }
    }
    if (!files.length) {
      throw newEngineError('no-observed', 'no observed Parquet files in catalog');
    }
    const sql = "SELECT variable, value::DOUBLE AS value FROM read_parquet([" +
      files.map((f) => "'" + f + "'").join(',') + "]) WHERE district_id = '" +
      did + "' AND year = " + Number(m[1]) + " AND month = " + Number(m[2]) +
      " ORDER BY variable";
    return toRows(await query(sql));
  }

  async function national(opts) {
    const cat = state.catalog || (await ensureCatalog());
    if (!cat.national) {
      throw newEngineError('no-national',
        'national pre-aggregate not generated yet (task M1.10); use slice()');
    }
    // variable is whitelist-validated against the catalog before it touches
    // the SQL string (the ids are catalog keys, so this is both safe and
    // honest: an unknown id cannot be smuggled in)
    let where = '';
    if (opts.variable) {
      catalogVariable(opts.variable);
      where = " WHERE variable = '" + opts.variable + "'";
    }
    return toRows(await query(
      'SELECT variable, year, month, value::DOUBLE AS value, n_districts ' +
      'FROM read_parquet(["' + absPath(cat.national) + '"])' + where +
      ' ORDER BY variable, year, month'));
  }

  async function ensemble(opts) {
    const cat = state.catalog || (await ensureCatalog());
    const eraC = cat.eras && cat.eras.projections;
    if (!eraC || !eraC.available) {
      throw newEngineError('era-c-unavailable',
        'era C has no validated products yet (Owner compute pending); ' +
        'surfaces must show fixtures only with FIXTURE banners (R3).');
    }
    const scenario = opts.scenario === 'ssp585' ? 'ssp585' : 'ssp245';
    const v = catalogVariable(opts.variable);
    // published stat partitions: scenario=<s>/stat=<st>/variable=<v>/year=<yyyy>/
    // (each holds a single `value` column — PROGRESS.md row 27/28)
    const STAT_KEYS = ['median', 'p25', 'p75', 'agreement_moderate',
      'agreement_severe', 'dir_agreement_drier', 'dir_agreement_n'];
    const statKey = opts.stat || 'median';
    if (STAT_KEYS.indexOf(statKey) === -1) {
      throw newEngineError('bad-stat', 'stat must be one of ' + STAT_KEYS.join(', ') + ': ' + statKey);
    }
    let files =
      ((v.files && v.files.projections && v.files.projections[scenario]) || {})[statKey] || [];
    if (!files.length) throw newEngineError('no-files', 'no ' + scenario + '/' + statKey + ' files for ' + v.id);
    // year pruning at the FILE level first: one file per year, so a window
    // query never even opens the footers of out-of-window partitions
    if (opts.yearRange) {
      const [a, b] = opts.yearRange.map(intYear);
      const lo = Math.min(a, b), hi = Math.max(a, b);
      files = files.filter((f) => {
        const m = /year=(\d{4})\//.exec(f.replace(/\\/g, '/') + '/');
        return m ? (+m[1] >= lo && +m[1] <= hi) : true;
      });
      if (!files.length) {
        throw newEngineError('no-files',
          'no ' + scenario + '/' + statKey + ' files for ' + v.id + ' in ' + lo + '-' + hi);
      }
    }
    let where = '';
    if (opts.district) {
      const district = String(opts.district);
      if (!DISTRICT_RE.test(district)) {
        throw newEngineError('bad-district', 'district id rejected: ' + district);
      }
      where = "district_id = '" + district + "'";
    }
    if (opts.yearRange) {
      const [a, b] = opts.yearRange.map(intYear);
      const yr = 'year BETWEEN ' + Math.min(a, b) + ' AND ' + Math.max(a, b);
      where = where ? where + ' AND ' + yr : yr;
    }
    const clause = where ? ' WHERE ' + where : '';
    // district_id is carried on every row so callers can aggregate state or
    // national series with the v1.0 area-weighting rule (harmless for slices)
    return toRows(await query(
      'SELECT district_id, year, month, value::DOUBLE AS value ' +
      'FROM read_parquet([' + files.map((f) => "'" + absPath(f) + "'").join(', ') + '])' +
      clause + ' ORDER BY year, month'));
  }

  /* ---- exports ----------------------------------------------------------- */

  DIE.Engine = {
    ensureEngine, ensureCatalog, query, slice, mapMonth, national, ensemble,
    atlasYear, crossval, seamUncertainty, observedAt,
    bytes, lastMs,
    version: DUCKDB_VERSION,
    catalog: () => state.catalog,
    isReady: () => !!state.conn,
    reset() {   // test hook only
      state.initPromise = null; state.catalogPromise = null; state.catalog = null;
      state.queryCache = new Map();
      state.bytes = 0; state.requests = 0; state.lastMs = 0;
    },
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = DIE.Engine;
})();
