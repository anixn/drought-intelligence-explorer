# DIE v2.0 — Frontend and UI Specification

*Doc 4 of the v2.0 suite. Governs how the interface evolves without breaking v1.0.0. Architecture stays framework-free vanilla JS + Leaflet + Plotly (vendored), no build step. New capability enters as new surfaces and a new data engine — not as a rewrite.*

---

## 1. Information architecture — evolve, don't redesign

v1.0.0 surfaces (preserve exactly as-is unless a task says otherwise):

| Surface | Route | Status in v2.0 |
|---|---|---|
| Overview | `#overview` | preserved; gains currency banner (§2.3) |
| Historical Analysis | `#historical` | preserved; engine-backed behind flag (§3.4); gains FDR view (O03) |
| Drought Events | `#events` | preserved |
| Propagation & Relationships | `#propagation` | preserved |
| Documentation & Resources | book icon / `#data` | preserved; extended per §5–6 |

New surfaces (added in dependency order; each keeps its own stable hash):

| Surface | Route | Era | Milestone |
|---|---|---|---|
| Engine Lab (SQL playground + measurements) | `#engine` | all | M1 |
| Future Projections | `#projections` | C | M5 |
| Atlas Context | `#atlas` | A | M6 |
| Cross-Validation | `#crossval` | A + B | M6 |
| Monthly Brief (Tier 2) | `#brief` | B | M8+ |

Dirty-tab rendering pattern (mark tabs dirty on state change, re-render only on entry) is the v1.0 lifecycle — new tabs adopt it. Documentation stays a secondary control, never a main analytical tab.

## 2. Era honesty in the UI

### 2.1 Global era toggle (header, persistent)

`Era A — Atlas 1901–2025 | Era B — Observed 1981–2025 | Era C — Projections 2026–2100` (labels read from `metadata.json`; years reflect verified releases). The active era is always visible somewhere on screen. Surfaces declare which era they serve; the toggle deep-links to the matching surface when the current one cannot serve the selection.

### 2.2 No-splice rules

- Any time-series that spans an era boundary (e.g. a continuity timeline 1901→2100) draws explicit era boundary markers and era segment labels on the chart itself.
- Era values are never averaged, rescaled, or joined into one series without era annotation.
- When the user crosses eras in a selector, a one-line note states the seam ("Atlas reconstruction before 2026; observed CHIRPS/ERA5-Land record 1981–2025; model projections after").

### 2.3 Currency banner (every page)

> "Data current to **[YYYY-MM]** (**[N]** days lag). Last pipeline run: **[timestamp]**. [View status page]"

Reads `data/status.json` (written by the monthly refresh, docs/v2/03 §1.4). Amber styling when lag > 45 days. Component sits in the existing provenance-banner slot so the v1.0 layout does not shift.

### 2.4 Projection banner (era C surfaces)

> "Projections from 24 CMIP6 models, bias-corrected (QDM) against IMD observations and standardised on the fixed 1981–2020 window. Median shown with the 25–75 % range. Model disagreement is the finding — not noise to hide."

Plus per-statistic tooltips with the exact agreement definitions from docs/v2/03 §3.7. Projections are labelled "projections", never "forecasts" or "predictions".

## 3. Data engine integration (`assets/js/ducklab.js`)

### 3.1 Service contract

```js
DIE.Engine = {
  ensureEngine(),                 // idempotent, promise-cached init (see pitfall P1)
  query(sql),                     // → Arrow table; promise-cached per SQL string
  slice({era, variable, district, yearRange}),   // district time-slice
  mapMonth({era, variable, date}),               // all districts, one month
  national({variable}),           // pre-aggregate fast path
  ensemble({scenario, variable, district, yearRange}),
  bytes(), lastMs()               // from the byte interceptor + timing
};
```

Init sequence (prototype-verified): dynamic `import()` of DuckDB-WASM 1.32.0 from jsDelivr (`getJsDelivrBundles()`, `eh` bundle, `mvp` fallback) → worker created from a Blob whose first lines are the fetch/XHR byte interceptor (pitfall P3) then `importScripts(bundle.mainWorker)` → `db.instantiate(...)` → `connect()` → settings → `fetch('data/parquet/catalog.json')`.

Mandatory settings:

```sql
SET disable_parquet_prefetching = true;  -- else speculative row-group fetches inflate first touch
SET parquet_metadata_cache = true;
-- enable_external_file_cache stays default-true: repeat queries are 0 KB
```

### 3.2 Query patterns (implement as parameterised builders, never string-concatenated user input)

```sql
-- District time-slice (era B): ~20 ms cold on prototype data
SELECT year, month, value::DOUBLE AS value
FROM read_parquet('http://…/data/parquet/observed/variable=spi_03/part-0.parquet')
WHERE district_id = ? ORDER BY year, month;

-- Cross-variable join (impossible in the v1.0 wide-CSV loader)
WITH a AS (SELECT year, month, value v FROM read_parquet('…spi_03…') WHERE district_id = ?),
     b AS (SELECT year, month, value v FROM read_parquet('…spei_03…') WHERE district_id = ?)
SELECT a.year, a.month, a.v, b.v FROM a JOIN b USING (year, month) ORDER BY 1, 2;

-- Projections ensemble with spread
SELECT date, median, p25, p75, agreement_moderate
FROM read_parquet([<catalog files for scenario=ssp245/stat=median/variable=spi_03>])
WHERE district_id = ? AND year BETWEEN ? AND ?;
```

### 3.3 The seven measured pitfalls (prototype-hardened — do not reintroduce)

1. **Shared-load promise race.** Two callers of `ensureData()`/`ensureEngine()` must share the *promise*, not a boolean flag (the flag variant proceeds with `data === null`). Cache the promise.
2. **Browser heuristic caching.** Dev server must send `Cache-Control: no-cache` for HTML/JS/JSON (`server.py` does); bump `?v=` on every code change.
3. **Worker-side byte counting.** DuckDB reads happen in its worker; main-thread Resource Timing sees nothing. Inject the fetch+XHR interceptor into the worker blob; **exclude HEAD requests** (DuckDB HEADs file size, then GETs ranges — counting both doubles the number).
4. **Relative paths fail in httpfs.** Absolutise every `read_parquet` path.
5. **`::VARCHAR` casts in WHERE kill filter pushdown** (verified: full scan). Cast only in the projection list.
6. **`python3 -m http.server` lacks Range support.** Use `server.py` (Range-capable) or a real static host.
7. **No HTTP globbing.** `read_parquet('data/*/*.parquet')` fails on static hosting — build explicit file lists from `catalog.json`.

### 3.4 Migration rule for existing tabs

Existing tabs keep the CSV loader as default and first-paint path; the engine path activates behind `?engine=1` (per tab, starting with Historical) and must produce **identical values** (spot-checked against CSV path) before it becomes default per tab. The CSV fallback stays permanent for offline resilience and CDN-failure fallback (pitfall: jsDelivr unreachable → show message, fall back).

## 4. New surface specifications

### 4.1 Engine Lab (`#engine`, M1)

Status line (`ready · DuckDB-WASM 1.32.0 · N Parquet tables`), SQL editor with the pattern queries preloaded, result table + Plotly preview, live byte/time readouts (from `bytes()`/`lastMs()`), and the catalog browser. Purpose: the live proof that every number on the site is queryable — keep it permanent.

### 4.2 Future Projections (`#projections`, M5)

- **Controls:** scenario switch (SSP2-4.5 / SSP5-8.5; schema ready for SSP1-2.6/SSP3-7.0), variable + timescale (SPI/SPEI-1/3/6/12), time window (near 2026–2040 / mid 2041–2060 / late 2081–2100 / custom), geography (national/state/district), statistic (median | band | agreement).
- **Views:** (a) ensemble time-series with median + shaded 25–75 % band per district/region; (b) choropleth of the selected statistic for the selected month/year; (c) agreement layer (fraction of models ≤ −1.0 / ≤ −1.5; direction-of-change map per window) with exact definitions in tooltips; (d) model ranking panel (multi-metric composite from `08_validate_gcm.py`, best-subset selectable — **no single-metric ranking**); (e) SPI vs SPEI divergence map (warming fingerprint).
- **Copy anchors:** projection banner (§2.4); divergence framing: "Rainfall alone does not decide India's drought future; demand does half the work."
- **Seams:** when a user extends a district series across 2025→2026, the chart draws the era boundary marker and the seam note (§2.2).
- **Data rule:** this tab renders only validated era C products. During UI development it runs on `data/fixtures/` with a permanent `FIXTURE — SYNTHETIC, NOT FOR RELEASE` banner; fixtures never ship to the live site.

### 4.3 Atlas Context (`#atlas`, M6)

Era-labelled scrubber (1901→end; per-year tile fetch only), seasonal composites (JJAS, ONDJ, water year, calendar year), drought-frequency climatology across eras, category-share summary ("X % of units in moderate-or-worse drought"), and the historical-event anchors (1918, 1965, 1972, 1987, 2002) as pre-set view links. District-level first; tehsil layer only after the geometry gate (register).

### 4.4 Cross-Validation (`#crossval`, M6)

Era A ↔ Era B panel at 1981–2020: agreement time-series, event-match table, per-district discrepancy map, and the headline statistics (r, class agreement, event-match rate) with the interpretation guardrail text from docs/v2/03 §6. IMD benchmark results are surfaced in the Documentation centre (§5), not here — this panel is specifically the Atlas↔Observed seam.

## 5. Documentation & Resources centre extensions

New panels (in the existing `doc-*` panel system): **Methodology v2** (every formula, window, threshold, seam — era table, QDM + Hargreaves + fitting chain, event rules, uncertainty statements; content owner: task M4.4/M7.4), **Status page** (from `data/status.json`; last run, current month, lag, known issues), **Validation** (IMD benchmark memo + cross-validation summary, discrepancies published), **Data model & schema** (Parquet schema, catalog, partitioning), **Provenance** (pipeline manifests, checksums, model list, retrieval dates). Existing panels (About, Data Sources, Methods, Validation & Data Quality, Uncertainty & Limits, Reproducibility, Downloads, Version History, How-to-use, Glossary) are preserved and versioned forward.

## 6. Download portal v2 (Documentation → Downloads, M7)

- Versioned bundles generated from `catalog.json` at release time: per-era, per-variable Parquet + CSV; boundaries; schema docs; `CITATION.cff`; checksums (`pipeline_manifest.json`).
- **Parity rule:** downloadable files are byte-identical to the files the dashboard serves.
- Citation line rendered in the UI: "Deshmukh, A. (2027). Drought Intelligence Explorer v2.0 [Data set]. Zenodo. https://doi.org/…" (final form set at M7.2).
- v1.0 export products (with their `#` reproducibility headers) remain; new exports (engine query results, ensemble summaries) adopt the same header pattern (analysis state: era, indicator, geography, periods, reference window, methodology version, seed, timestamp).

## 7. Accessibility, responsiveness, performance

- **WCAG 2.1 AA:** keyboard operability for every new control (era toggle, scenario switch, scrubber), ARIA labels on charts/maps, visible focus states, contrast-checked palettes (v1.0 palette contract from `metadata.json` extended with era C diverging scales).
- **Mobile-first responsive:** new surfaces follow the v1.0 pattern — controls collapse into the study-context drawer; panels stack; touch targets ≥ 44 px; map fully operable by touch.
- **Performance budgets (from the prototype measurements):** first meaningful paint < 3 s on throttled 4G; engine init < 8 s; cold query < 100 ms (era B) / < 150 ms (era C ensemble); repeat query 0 KB; boot payload = catalog (~2 KB) only; per-file first touch ≤ ~0.5 MB.
- **Rendering scale:** Leaflet + 724 polygons is fine today. Switch triggers: tehsil layer (≈4,590 polys) or the animated Atlas scrubber → PMTiles + deck.gl/MapLibre; 200-year monthly series → Plotly `scattergl` or UPlot; object-pool Arrow tables across sibling views instead of re-querying.
- **States:** loading indicators on every engine query; explicit no-data styling distinct from "normal"; error states with retry; unsupported combinations (e.g. era C × SMA) disabled with an explanation, not silently broken.

## 8. Regression protection (what must never break)

1. The four v1.0 workspaces produce identical numbers (regression harness, M1.9).
2. All five v1.0 hash routes keep working; the book-icon docs centre keeps its ten panels.
3. Exports keep their `#` reproducibility headers; download centre products unchanged.
4. Mobile drawer, keyboard operability, ARIA roles verified after every UI task.
5. `selftest.py` stays green; the CSV fallback stays functional with the CDN unreachable.
6. Any UI change ships with the verification line in PROGRESS.md ("tabs cycled, zero console errors, mobile pass").

**Definition of success for this doc:** a user who never opens the new surfaces notices nothing except the currency banner — and a user who opens them gets three honest eras with their seams visible.
