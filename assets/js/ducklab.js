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
  // v1.0 tab views) — a page-relative URL would resolve against the page path.
  const CATALOG_URL = new URL('/data/parquet/catalog.json', location.origin).href;

  const DISTRICT_RE = /^[a-z0-9-]{1,64}$/;     // v1.0 registry slugs
  const VAR_RE = /^[a-z0-9_]{1,32}$/;
  const DATE_RE = /^(\d{4})-(0[1-9]|1[0-2])$/;

  /* ---- worker-side byte interceptor (P3) -------------------------------- */
  /* Injected verbatim as the first lines of the worker blob. Counts GET
   * response bytes only; HEADs are excluded. Posts typed deltas to the main
   * thread — the main-side listener filters by type; duckdb-wasm's own
   * handler ignores unknown types. */
  const WORKER_INTERCEPTOR = `
    (function () {
      self.__ducklab = { bytes: 0, requests: 0 };
      function track(url, method, contentLength) {
        if (String(method || 'GET').toUpperCase() === 'HEAD') return;
        var n = 0;
        if (contentLength != null) {
          n = parseInt(contentLength, 10);
          if (!isFinite(n) || n < 0) n = 0;
        }
        self.__ducklab.bytes += n;
        self.__ducklab.requests += 1;
        try { self.postMessage({ type: 'ducklab-bytes', delta: n }); } catch (e) {}
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
      state.catalogPromise = fetch(CATALOG_URL, { cache: 'no-store' })  // P2
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

  // Arrow table → plain objects (the UI layer consumes rows, not Arrow)
  function toRows(table) {
    if (!table) return [];
    return table.toArray().map((r) => r.toJSON());
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

  async function national(opts) {
    const cat = state.catalog || (await ensureCatalog());
    const v = catalogVariable(opts.variable);
    if (!cat.national) {
      throw newEngineError('no-national',
        'national pre-aggregate not generated yet (task M1.10); use slice()');
    }
    void v;
    return toRows(await query(
      'SELECT * FROM read_parquet(["' + absPath(cat.national) + '"])'));
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
    const district = String(opts.district || '');
    if (!DISTRICT_RE.test(district)) {
      throw newEngineError('bad-district', 'district id rejected: ' + district);
    }
    const statKey = opts.stat || 'median';
    const files =
      ((v.files && v.files.projections && v.files.projections[scenario]) || [])
        .filter((f) => f.indexOf('stat=' + statKey + '/') !== -1);
    if (!files.length) throw newEngineError('no-files', 'no ' + scenario + '/' + statKey + ' files for ' + v.id);
    let where = "district_id = '" + district + "'";
    if (opts.yearRange) {
      const [a, b] = opts.yearRange.map(intYear);
      where += ' AND year BETWEEN ' + Math.min(a, b) + ' AND ' + Math.max(a, b);
    }
    return toRows(await query(
      'SELECT year, month, median, p25, p75, agreement_moderate ' +
      'FROM read_parquet([' + files.map((f) => "'" + absPath(f) + "'").join(', ') + ']) ' +
      'WHERE ' + where + ' ORDER BY year, month'));
  }

  /* ---- exports ----------------------------------------------------------- */

  DIE.Engine = {
    ensureEngine, ensureCatalog, query, slice, mapMonth, national, ensemble,
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
