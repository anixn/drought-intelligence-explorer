/* ---------------------------------------------------------------------------
 * DIE v2.0 - Engine Lab (#engine, task M1.7; docs/v2/04 section 4.1)
 *
 * The live proof that every number on the site is queryable: a SQL surface
 * over the Parquet store, with byte/time readouts and the catalog browser.
 * - The engine is LAZY: DuckDB-WASM is fetched only when the user initialises
 *   it or runs the first query. Opening this tab costs one small catalog.json
 *   fetch and nothing else (first paint of the four v1.0 workspaces is
 *   untouched - they remain CSV-loader driven).
 * - Era honesty (R2): the catalog browser shows eras with their availability;
 *   pending eras are labelled pending, never rendered as data.
 * - Exports follow the v1.0 `#` reproducibility-header pattern (section 6).
 * - No synthetic/fabricated rows anywhere: query results are rendered as the
 *   engine returns them (missing values render as empty cells, R10).
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const EngineLab = { ready: false };

  /* module state */
  let presets = [];          // [{label, sql}]
  let lastResult = null;     // {cols, rows, sql, ms, bytes}
  let catalogLoaded = false;

  const RESULT_CAP = 200;    // rows rendered in the table (CSV exports all)

  function fmtInt(n) { return Number(n).toLocaleString("en-IN"); }
  function fmtBytes(n) {
    if (!n) return "0 B";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(2) + " MB";
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
  function fmtVal(v) {
    if (v === null || v === undefined) return "";      // R10: gaps stay gaps
    if (typeof v === "number") return String(Math.round(v * 1e6) / 1e6);
    return String(v);
  }

  function engineAvailable() { return !!(DIE.Engine && DIE.Engine.query); }

  /* ------------------------------------------------------------ catalog -- */

  function eraNote(cat) {
    const parts = Object.keys(cat.eras || {}).map((k) => {
      const e = cat.eras[k];
      return e.available
        ? e.label + ": available"
        : e.label + ": pending - no files published (labelled, never spliced)";
    });
    return parts.join(" · ");
  }

  function fileCount(cat) {
    // catalog.json nests era → scenario → stat → [paths] (projections), so
    // count leaves recursively; a flat `length` per era yields NaN.
    const walk = (node) => {
      if (Array.isArray(node)) return node.length;
      if (node && typeof node === "object") {
        return Object.keys(node).reduce((a, k) => a + walk(node[k]), 0);
      }
      return 0;
    };
    let n = 0;
    (cat.variables || []).forEach((v) => { n += walk(v.files); });
    return n;
  }

  function filesOf(v) {
    const walk = (node) => {
      if (Array.isArray(node)) return node.length;
      if (node && typeof node === "object") {
        return Object.keys(node).reduce((a, k) => a + walk(node[k]), 0);
      }
      return 0;
    };
    return walk(v && v.files);
  }

  function observedYears(v, cat) {
    if (v.observed_years) return v.observed_years.join("\u2013");
    const era = cat.eras && cat.eras.observed;
    return era && era.years ? era.years.join("\u2013") : "\u2014";
  }

  function displayLabel(label) {
    // Catalog ids use zero-padded timescales (SPEI-04, the Atlas 4-month
    // variable). The rest of the UI says SPEI-4; normalise the display only,
    // never the stored id (UX audit F11).
    return String(label || "").replace(/^(SPEI|SPI)-0(\d+)$/i, "$1-$2");
  }

  function renderCatalog(cat) {
    const tb = $("elCatalogTable").querySelector("tbody");
    const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    tb.innerHTML = (cat.variables || []).map((v) => {
      // The catalog id is useful for SQL, but it must not read as a second
      // name ("VCI vci"). Show it only when it differs from the display label,
      // and set it on its own meta line.
      const label = displayLabel(v.label);
      const idLine = norm(v.id) === norm(label)
        ? ""
        : "<span class=\"mono el-var-id\">" + esc(v.id) + "</span>";
      return "<tr><td><b>" + esc(label) + "</b>" + idLine + "</td>" +
        "<td>" + esc((v.eras || []).join(", ")) + "</td>" +
        "<td class=\"num\">" + esc(observedYears(v, cat)) + "</td>" +
        "<td class=\"num\">" + filesOf(v) + "</td></tr>";
    }).join("");
    $("elCatalogMeta").textContent =
      "data/parquet/catalog.json · " + (cat.variables || []).length +
      " variables · " + fileCount(cat) + " Parquet files";
    $("elEraNote").textContent = eraNote(cat);
    catalogLoaded = true;
  }

  /* ------------------------------------------------------------- presets -- */

  /** Build the preloaded pattern queries from the live catalog (no hardcoded
   *  file paths: the catalog is the single source of truth, P7). */
  function buildPresets(cat) {
    const abs = (rel) => DIE.Engine.absPath(rel);
    const file = (varId, era) => {
      const v = (cat.variables || []).find((x) => x.id === varId);
      if (!v || !v.files || !v.files[era || "observed"] || !v.files[era || "observed"].length) return null;
      return abs(v.files[era || "observed"][0]);
    };
    const spi3 = file("spi_03"), spi12 = file("spi_12"), vci = file("vci");
    presets = [];
    if (spi3) {
      presets.push({
        label: "District time-slice \u2014 SPI-3 (Ahmedabad)",
        sql:
          "SELECT year, month, value\n" +
          "FROM read_parquet(['" + spi3 + "'])\n" +
          "WHERE district_id = 'gujarat-ahmedabad'\n" +
          "ORDER BY year, month;"
      });
      presets.push({
        label: "One month, all districts \u2014 SPI-3 (2002-07)",
        sql:
          "SELECT district_id, value\n" +
          "FROM read_parquet(['" + spi3 + "'])\n" +
          "WHERE year = 2002 AND month = 7\n" +
          "ORDER BY value NULLS LAST;"
      });
      presets.push({
        label: "Annual mean + sample size \u2014 SPI-3 (Ahmedabad)",
        sql:
          "SELECT year, round(avg(value), 4) AS mean, count(*) AS n\n" +
          "FROM read_parquet(['" + spi3 + "'])\n" +
          "WHERE district_id = 'gujarat-ahmedabad'\n" +
          "GROUP BY year ORDER BY year;"
      });
    }
    if (spi12) {
      presets.push({
        label: "Drought months per district \u2014 SPI-12 (2000\u20132019), top 25",
        sql:
          "SELECT district_id,\n" +
          "       count(*) FILTER (WHERE value < -1.0) AS drought_months\n" +
          "FROM read_parquet(['" + spi12 + "'])\n" +
          "WHERE year BETWEEN 2000 AND 2019\n" +
          "GROUP BY district_id\n" +
          "ORDER BY drought_months DESC LIMIT 25;"
      });
    }
    if (vci) {
      presets.push({
        label: "Coverage audit \u2014 VCI (row count, year range)",
        sql:
          "SELECT count(*) AS rows, min(year) AS min_year, max(year) AS max_year,\n" +
          "       count(*) FILTER (WHERE value IS NULL) AS null_values\n" +
          "FROM read_parquet(['" + vci + "']);"
      });
    }
    if (cat.national) {
      presets.push({
        label: "National series \u2014 SPI-3 (area-weighted pre-aggregate)",
        sql:
          "SELECT year, month, round(value, 4) AS national, n_districts\n" +
          "FROM read_parquet(['" + abs(cat.national) + "'])\n" +
          "WHERE variable = 'spi_03'\n" +
          "ORDER BY year, month;"
      });
    }
    const sel = $("elPreset");
    sel.innerHTML =
      "<option value=\"\">Preloaded pattern query\u2026</option>" +
      presets.map((p, i) => "<option value=\"" + i + "\">" + esc(p.label) + "</option>").join("");
  }

  /* -------------------------------------------------------------- status -- */

  function renderStatus() {
    const E = DIE.Engine;
    const engineEl = $("elStatusEngine");
    const metaEl = $("elStatusMeta");
    if (!engineAvailable()) {
      engineEl.textContent = "engine module not loaded (CSV path unaffected)";
      metaEl.textContent = "engine module not loaded";
    } else if (E.isReady()) {
      engineEl.textContent =
        "ready \u00b7 DuckDB-WASM " + (E.version || "") +
        " \u00b7 " + (catalogLoaded ? $("elCatalogMeta").textContent.split("\u00b7 ").pop() : "catalog not loaded");
      metaEl.textContent = "ready \u00b7 " + (E.version || "");
    } else {
      engineEl.textContent = "not initialised (lazy \u2014 DuckDB fetches on first use)";
      metaEl.textContent = "not initialised";
    }
    const b = engineAvailable() ? E.bytes() : { bytes: 0, requests: 0 };
    $("elStatusBytes").textContent = fmtBytes(b.bytes);
    $("elStatusRequests").textContent = String(b.requests || 0);
    $("elStatusLast").textContent = b.lastMs != null && b.lastSql
      ? Math.round(b.lastMs) + " ms \u00b7 " + (b.lastSql.slice(0, 60) + (b.lastSql.length > 60 ? "\u2026" : ""))
      : "no query yet";
    $("elStatusSettings").textContent =
      "disable_parquet_prefetching = true \u00b7 parquet_metadata_cache = true";
  }

  /* -------------------------------------------------------------- query -- */

  async function runQuery() {
    if (!engineAvailable()) { showError("Engine module not loaded - the CSV path is unaffected."); return; }
    const sql = $("elSql").value.trim();
    if (!sql) { showError("Write a query, or pick a preloaded pattern query."); return; }

    const btn = $("elRunBtn");
    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = "Running\u2026";
    hideError();

    const before = DIE.Engine.bytes();
    try {
      const t = await DIE.Engine.query(sql);
      const cols = t.schema.fields.map((f) => f.name);
      const rows = t.toArray().map((r) => r.toJSON());
      const after = DIE.Engine.bytes();
      lastResult = { cols, rows, sql, ms: Math.round(DIE.Engine.lastMs() || 0),
                     bytes: Math.max(0, after.bytes - before.bytes) };
      renderResult();
      renderStatus();
      if (DIE.Telemetry) {
        DIE.Telemetry.track("engine_run", { rows: rows.length, ms: lastResult.ms });
      }
    } catch (err) {
      lastResult = null;
      $("elResultWrap").hidden = true;
      $("elResultMeta").hidden = true;
      showError(err && err.name === "DIEEngineError"
        ? "[" + err.kind + "] " + err.message
        : (err && err.message) || String(err));
    } finally {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }

  function renderResult() {
    const r = lastResult;
    if (!r) return;
    const shown = r.rows.slice(0, RESULT_CAP);
    $("elResultTable").querySelector("thead").innerHTML =
      "<tr>" + r.cols.map((c) => "<th scope=\"col\"" +
        (r.rows.some((row) => typeof row[c] === "number") ? " class=\"num\"" : "") +
        ">" + esc(c) + "</th>").join("") + "</tr>";
    $("elResultTable").querySelector("tbody").innerHTML = shown.map((row) =>
      "<tr>" + r.cols.map((c) => "<td" +
        (typeof row[c] === "number" ? " class=\"num\"" : "") +
        ">" + esc(fmtVal(row[c])) + "</td>").join("") + "</tr>"
    ).join("");
    $("elResultStats").textContent =
      fmtInt(r.rows.length) + " rows \u00b7 " + r.cols.length + " columns \u00b7 " +
      r.ms + " ms \u00b7 network " + fmtBytes(r.bytes) +
      (r.rows.length > RESULT_CAP
        ? " \u00b7 table shows first " + RESULT_CAP + " (CSV exports all)"
        : "");
    $("elResultMeta").hidden = false;
    $("elResultWrap").hidden = false;
  }

  function showError(msg) {
    const el = $("elError");
    el.textContent = msg;
    el.hidden = false;
  }
  function hideError() { $("elError").hidden = true; }

  /* -------------------------------------------------------------- export -- */

  /** Results CSV with the v1.0 `#` reproducibility-header pattern. */
  function exportCSV() {
    const r = lastResult;
    if (!r || !r.rows.length) return;
    const csvCell = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n]/.test(s) ? "\"" + s.replace(/"/g, "\"\"") + "\"" : s;
    };
    const lines = (DIE.App && DIE.App.citationLines
      ? DIE.App.citationLines()
      : ["# Drought Intelligence Explorer \u2014 Engine Lab export (v2.0)"]
    ).concat([
      "# exported (UTC): " + new Date().toISOString(),
      "# query: " + r.sql.replace(/\s+/g, " "),
      "# engine: DuckDB-WASM " + (DIE.Engine && DIE.Engine.version || "") +
        " \u00b7 query time " + r.ms + " ms \u00b7 network bytes " + r.bytes,
      "# source: data/parquet/* per data/parquet/catalog.json (era labels in catalog)",
      "# missing values: empty cells (never imputed \u2014 R10)",
      ""
    ]);
    lines.push(r.cols.map(csvCell).join(","));
    r.rows.forEach((row) => lines.push(r.cols.map((c) => csvCell(row[c])).join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "die-engine-query-" + Date.now() + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  /* ---------------------------------------------------------------- init -- */

  async function init() {
    if (EngineLab.ready) { refresh(); return; }
    EngineLab.ready = true;

    if (engineAvailable()) {
      try {
        const cat = await DIE.Engine.ensureCatalog();
        renderCatalog(cat);
        buildPresets(cat);
      } catch (err) {
        showError("catalog.json could not be loaded: " + ((err && err.message) || err));
      }
    } else {
      $("elStatusEngine").textContent = "engine module not loaded (CSV path unaffected)";
    }
    renderStatus();

    $("elInitBtn").addEventListener("click", async () => {
      if (!engineAvailable()) { showError("Engine module not loaded."); return; }
      const btn = $("elInitBtn");
      btn.disabled = true; const prev = btn.textContent; btn.textContent = "Initialising\u2026";
      try {
        const t0 = performance.now();
        await DIE.Engine.ensureEngine();
        const cat = await DIE.Engine.ensureCatalog();
        renderCatalog(cat); buildPresets(cat);
        $("elStatusEngine").textContent =
          "ready \u00b7 DuckDB-WASM " + (DIE.Engine.version || "") + " \u00b7 initialised in " +
          Math.round(performance.now() - t0) + " ms";
        renderStatus();
      } catch (err) {
        showError("engine init failed: " + ((err && err.message) || err));
      } finally {
        btn.disabled = false; btn.textContent = prev;
      }
    });

    $("elPreset").addEventListener("change", (e) => {
      if (e.target.value === "") return;   // placeholder: leave the editor as-is
      const p = presets[Number(e.target.value)];
      if (p) { $("elSql").value = p.sql; hideError(); }
    });
    $("elRunBtn").addEventListener("click", runQuery);
    $("elSql").addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { runQuery(); e.preventDefault(); }
    });
    $("elResultCsv").addEventListener("click", exportCSV);
  }

  /** Called on every re-entry to the tab (DIRTY mechanism). */
  function refresh() {
    if (!engineAvailable()) return;
    if (!catalogLoaded) {
      DIE.Engine.ensureCatalog()
        .then((cat) => { renderCatalog(cat); buildPresets(cat); renderStatus(); })
        .catch(() => { /* status line already reports the failure */ });
    } else {
      renderStatus();
    }
  }

  DIE.EngineLab = { init, refresh };
})();
