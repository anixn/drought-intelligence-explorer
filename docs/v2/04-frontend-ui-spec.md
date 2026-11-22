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
| Drought to 2100 (agreement-first change summary) | `#summary` | B vs C | M9 (built 2026-11-19) |
| Atlas Context | `#atlas` | A | M6 |
| Cross-Validation (Record lens, D11) | `#crossval` | A + B | M6 (built 2026-11-21) |
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
**Built 2026-11-21:** the topbar chip reads "Data · Dec 2025 · N d lag" on every page, turns amber beyond 45 days, and carries the full statement (target, build date) in its tooltip; it is filled from `data/status.json`, never a hand-typed constant. The full record lives in Documentation section N.

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
- **Seam uncertainty (X7, M6.8):** the main-map tooltip appends the per-district `sd_diff` for SPEI-12 — "seam SD ±X z (era A − era B, 1981–2014; not a confidence interval)" — and the map note prints the median across districts with n. It is a measured historical disagreement, never a projection error bar.
- **Data rule:** this tab renders only validated era C products. During UI development it runs on `data/fixtures/` with a permanent `FIXTURE — SYNTHETIC, NOT FOR RELEASE` banner; fixtures never ship to the live site.

### 4.3 Atlas Context (`#atlas`, M6)

Era-labelled scrubber (1901→end; per-year tile fetch only), seasonal composites (JJAS, ONDJ, water year, calendar year), drought-frequency climatology across eras, category-share summary ("X % of units in moderate-or-worse drought"), and the historical-event anchors (1918, 1965, 1972, 1987, 2002) as pre-set view links. District-level first; tehsil layer only after the geometry gate (register).

### 4.4 Cross-Validation (`#crossval`, M6 — BUILT 2026-11-21, Record lens)

A **lens on the Record product** (D11), not a new top-level era: it asks a question about the existing record, so it sits in the record lens strip after Propagation.

- **Window:** 1981–2014, register D6 (the GCM-native comparison window). The full 1981–2025 overlap is documented as the sensitivity variant and is not built here.
- **Timescales:** SPEI-1 and SPEI-12 only — the two accumulation definitions shared by era A (Atlas ships 1/4/12) and era B (ships 1/3/6/12). SPEI-4 is era-A-only.
- **Selection panel:** timescale, map statistic (default **bias**, the divergence map; then drought-state agreement, r, within-one-class agreement, RMSD), and a CSV export with `#` reproducibility headers.
- **KPIs (`Agreement at a glance`):** districts compared (n), matched district-months, median r (unweighted), area-weighted bias, median RMSD, area-weighted state agreement, within-one-class agreement, both-drought co-occurrence. Every figure names its sample.
- **Map:** per-district choropleth from `per_district_1981_2014.parquet`; diverging ramp for bias (brown = era B drier, blue = era B wetter), sequential warm ramp for the agreement metrics; six island districts with no Atlas grid cells stay grey (R10).
- **Time series:** area-weighted national monthly agreement from `monthly_1981_2014.parquet`, with the time-mean marked and the matched-area caveat in the note.
- **Table:** worst-30 district evidence, sorted worst-first, with exhaustive n and class columns plus **Seam SD** (the X7 `sd_diff`); the full 718-district table is the CSV.
- **Era pill:** `Era A ↔ B · Compared` (split dot) — the standing receipt that two records are compared, never merged.
- **Copy guardrails:** disagreement is expected and is the content (different P/PET chains and fitting windows); compared never merged (R2); missing stays missing (R10); correlation is not agreement (R9); exact nine-class agreement is low by construction, so within-one-class leads.
- IMD benchmark results are surfaced in the Documentation centre (§5), not here — this panel is specifically the Atlas↔Gridded seam.

### 4.5 Drought to 2100 (`#summary`, M9 — BUILT 2026-11-19, MVP live)
The headline "so what" surface (Owner request: "how drought changes from now to 2100"; Owner preference: the differentiating view, NOT an Atlas re-portal):

- **One primary map, agreement-first (X2):** DEFAULT statistic = `dir_agreement_drier` (share of the 8-model committed subset whose effective-window mean is drier than their own 1981–2014 base — a count of models, never a probability, R9; window recorded verbatim from `metadata.json`). The median-based change metrics — drought-month-share change (pp), mean event duration change, mean severity per event change — are one click away and always labelled "MEDIAN-BASED".
- **Measured finding shipped as copy (2026-11-19):** the era-C ensemble-median drought-month share is ≈ 0 (median-of-subset concentration; measured Jul-2090 sd 0.41, zero months ≤ −1 for SPI-3) while the per-model members keep ~10.7 % — the agreement default exists precisely so the median is never read alone.
- **Baseline:** observed 1981–2014 era-B metrics from the committed `data/events/baseline_1981_2014.json` (register D6 window); frozen v1.0 runs analysis on both sides; the eras are never spliced — only their per-district difference is shown.
- **Per-state table:** area-weighted (v1.0 LAEA areas) with n per row (R10); national area-weighted baseline→future drought-share figures with Δpp.
- **Export:** CSV with `#` reproducibility headers (X6): selection, windows, machinery, sources.
- **Caveat block (M9.4):** simulations-not-forecasts (R2); median-based + concentration warning; **X7 seam uncertainty is measured** — median per-district SD of era A − era B SPEI-12 over 1981–2014, printed with its district count, labelled a historical disagreement rather than a confidence interval; PET-seam note (era C Hargreaves vs era B ERA5-Land).

### 4.6 Atlas 1901–2025 (`#atlas`, M6.3 — BUILT 2026-11-20, live)

The era-A scrubber surface (Owner: "start the M6.3"), deliberately an *era surface* of DIE — not an Atlas re-portal:

- **Time scrubber:** year slider 1901–2025 + month selector (default August, the JJAS core) + timescale select (SPEI-1/4/12). **Per-year tile fetch only** (M6.3 rule): one partition query per frame (`DIE.Engine.atlasYear`), cached per (timescale, year) with a bounded LRU.
- **Accumulation months:** SPEI-1 is defined for every month; SPEI-4 from April to December; SPEI-12 only in December. An empty frame states the reason and never draws placeholder values. (The class table for every Atlas timescale comes from the shared SPEI metadata table; the variable-id mapping is `spei_01 → spei_1`, with SPEI-4 falling back to the identical SPEI class table.)
- **Drought anchors:** 1918 / 1965 / 1972 / 1987 / 2002 as one-click pre-set views (documented historical episodes; setting a view is not a claim about any single month).
- **Map:** McKee-class choropleth of the selected frame; class palette from the shared era-B SPEI classification table (the Atlas z-scores use the same class definitions).
- **Class shares:** area-weighted (v1.0 LAEA registry) share of moderate-or-worse / severe-or-worse / extreme / wetter-than-normal for the displayed month, with n.
- **Banner:** attribution rendered from `metadata.json → era_a.source` (Chuphal et al. citation, DOI, CC-BY-4.0) — never hand-typed (config attribution_note).
- **Caveats:** reconstruction ≠ observation (pre-1951 station density is lower, quantified in `#crossval`); never spliced (R2); six island districts honestly absent (R10).

### 4.7 Map interaction contract (all choropleths — Owner directive 2026-11-20)

Two viewport rules implemented ONCE in `MapView.createChoropleth`, so every map in the app behaves identically:

1. **Click = zoom:** clicking any district zooms it to fill that map's own container (`fitRegion("district", id)`, animated; opt-out `zoomOnDistrictClick: false`).
2. **Never smaller than fitted:** `minZoom` = the zoom at which the national outline fits THAT map's container — scrolling out stops at "India fully fitted in the viewport of each figure". The fit zoom is computed **analytically** from the CRS at a fixed reference zoom (Leaflet's `getBoundsZoom()` starts from the current zoom and never returns below it, so a map created in a small/hidden container would otherwise deadlock its minimum high — bug found and fixed in the same change; the initial view IS the fit, and every resize/tab-entry recomputes it).

### 4.8 State-encoding permalinks (`assets/js/permalink.js`, M10.4 — BUILT 2026-11-21)

One URL grammar for every workspace: `#<tab>?<shared state>&<panel state>`.

- **Shared study context** (every lens): `ind` (metadata indicator id, e.g. `spi_3`), `date` (`YYYY-MM`), `ext` (`india|state|district`), `state` (slug), `dist` (slug), `from`/`to` (analysis years), `season` (metadata season key).
- **Panel state:** Projections `pScenario pVariable pStat pWindow pGeo pStateId pDistrict pYear pMonth pDivYear pDivMonth`; Drought to 2100 `sScenario sVariable sWindow sMetric`; Atlas `aVariable aYear aMonth`; Cross-validation `cVariable cMetric`. Record lenses without panel state inherit the shared context only.
- **Restore:** `routeFromHash` applies shared state before the tab renders, then awaits the panel's first-init promise and applies the validated panel state — so an in-flight default render can never overwrite a restored control. The address bar tracks shared state and tab switches with `replaceState` (no history spam); the **Copy link** control (sidebar footer) and the per-panel **Share** buttons always serialise fresh state.
- **Safety:** values are validated against the loaded catalog/registry/metadata before use; an unknown indicator, district, year, season or statistic is ignored and the existing/default value retained (graceful fallback, never a broken or fabricated view). Documentation section links are preserved (`#data/c-methods?…`).
- **Compatibility:** plain `#overview`, `#data`, `#data/<section>` and all R8 hashes keep working; panel keys are namespaced so no shared key can be shadowed.

### 4.9 District profile (`#/district/<id>`, M10.6 — BUILT 2026-11-21)

A dedicated path route and a Record lens: one district read as a page, without leaving the shared study context.

- **Route:** `#/district/<id>` (the path id is authoritative). `DIE.Permalink.parse/build` understands it, so Copy link and the shared state keys still work; `#district` falls back to the selected district (default Ahmedabad), and an unknown id falls back to the overview. The selected-info rail on `#overview` links here.
- **Headline answer:** the selected month's class/value for the active indicator, the share of the district's valid months that were as dry or drier, and the drought share over the analysis period. Missing months are stated, never imputed.
- **Indicator strip:** all ten era-B indicators for the selected month in **one observed-Parquet query** (`DIE.Engine.observedAt`, not ten wide-CSV downloads). Each chip is a button that makes that indicator active across the dashboard; no data is rendered as no-data.
- **Trend:** annual means over the shared period/season with Mann–Kendall (tie-corrected, Hamed–Rao when needed), Sen slope + 90% CI, and the Plotly series. Text statistics render even if Plotly is unavailable.
- **Events:** the frozen v1.0 runs analysis for the district (threshold = upper bound of the moderate class, min 3 months, censoring flagged), most recent first, with the summary note.
- **Era context:** three labelled cards — era B record/coverage, era A overlap (r, bias, RMSD, X7 seam SD) or the documented ocean-mask absence, era C projection link for this district. Eras are never spliced.
- **Sharing:** Copy link uses the district route; the cards link into `#crossval` and `#projections` with this district and the shared state pre-applied.

## 5. Documentation & Resources centre extensions

New panels (in the existing `doc-*` panel system): **Methodology v2** (every formula, window, threshold, seam — era table, QDM + Hargreaves + fitting chain, event rules, uncertainty statements; content owner: task M4.4/M7.4), **Status page** (BUILT 2026-11-21 as section N from `data/status.json`: record, data month, lag days, per-indicator coverage, era coverage, last run, versions, verification gates, known issues), **Validation** (IMD benchmark memo + cross-validation summary, discrepancies published), **Data model & schema** (Parquet schema, catalog, partitioning), **Provenance** (pipeline manifests, checksums, model list, retrieval dates). Existing panels (About, Data Sources, Methods, Validation & Data Quality, Uncertainty & Limits, Reproducibility, Downloads, Version History, How-to-use, Glossary) are preserved and versioned forward.
- **Living evidence surfaces (M10.7, built 2026-11-21):** section **K** is the citable everyday methodology — ten method blocks (indicators, standardisation, classification, aggregation, events, trends, correlation, era-C chain, era-A↔B, missing data), each with `#data/k-methodology/<anchor>` deep links, the methodology version and a page-revision date from metadata. Section **L** is the public governance and licence page: a curated decision register (D6/D8/D9/D10/D11/D13/D14/D15/D16), the verification gates, per-artefact licences, and the what-this-is/is-not statement from `metadata.disclaimer`. Section **M** renders three reality checks from the committed `data/reality_checks.json` (Rajasthan 2002, all-India SPI-3, Marathwada 2015–16), re-derived by `scripts/verify_reality_checks.py --check`; no number is hand-typed.
- **Independent benchmark (M4, built 2026-11-22):** Documentation section **D** carries an "Independent benchmark — IMD (M4)" block above the back-to-top button: the agreement table (per indicator: districts, pairs, median r, bias, RMSD, state, exact class) and the BH-FDR trend-detection table, both rendered from `data/imd_validation.json` (written by `validation-studies/imd/99_memo.py`, never hand-typed). It states the like-for-like rule (SPI shares the estimator; SPEI also changes the PET method) and links the full memo and the reproduction commands. If the artifact is missing the block says so rather than showing placeholder numbers (R3).
- **Claim trail (M10.8, built 2026-11-21):** every headline surface (Overview receipts, Summary caveats, Cross-validation, District profile, Projections, Historical trend, Events, Propagation, Atlas caveats) carries a “How this is made” link to the relevant method anchor in section K. `scripts/reproduce_figures.py` regenerates three published figures/claims from the shipped record — Figure 2 coverage (deterministic SVG + plotted data), Figure 5 all-India SPI-3 (4/547 months on the 2026-09 record, one qualifying event), Figure 6 propagation (r, n, bootstrap CI) — plus Table 5’s reality-check artifact, and `--check` compares committed references. Every value is re-derived from the shipped record at run time, so a monthly refresh changes them and the committed references must be regenerated (never hand-edited). It runs in CI with the reality-check verifier.
- **Querying the data (M7.3b, built 2026-11-22):** section **P** is the SQL field reference for the Parquet store — the file layout with partition keys, the four schemas (`district_month`, `national_monthly`, the three cross-validation tables), identifier vocabularies (district slugs, variable ids, era-C statistics), the five data rules (absent rows, `::DOUBLE` in projections only, never union eras, area-weighted national means, report n), eight copy-paste recipes (district series, one month, annual mean with the ≥ 9-month rule, drought share, national series, event runs that break on gaps, projection agreement with its denominator, worst cross-validation districts), and a gotcha table. The same content ships as `docs/sql-guide.md`, downloadable from the section and from Documentation G; Engine Lab's SQL panel carries a **SQL guide** button that opens it. The guide states which stores are not in the git checkout (era A/C) so a 404 is explained rather than mysterious.

## 6. Download portal v2 (Documentation → Downloads, M7)

- Versioned bundles generated from `catalog.json` at release time: per-era, per-variable Parquet + CSV; boundaries; schema docs; `CITATION.cff`; checksums (`pipeline_manifest.json`).
- **Parity rule:** downloadable files are byte-identical to the files the dashboard serves.
- Citation line rendered in the UI: "Deshmukh, A. (2027). Drought Intelligence Explorer v2.0 [Data set]. Zenodo. https://doi.org/…" (final form set at M7.2).
- **Citation plumbing (M10.5, built 2026-11-21):** `metadata.json` now carries the era-C `source` block (CMIP6 archive, experiments, reference dataset, methods, five citations, licence note) alongside the existing era-A block, plus a `doi` block (archived v1.0.0 DOI real; v2.0.0 explicitly `null` until minted). The citation box and `Copy citation` render the metadata citation (with the archived DOI) plus an access date. Every CSV/text export is prefixed with `# Cite:`, `# Licence:` and `# Generated: … | methodology …` via one helper (`DIE.App.citationLines`), and the map PNG gains a caption strip with the title, indicator, date, region, citation and DOI. The generated **share card** (PNG, 1200×630) carries the current view summary, the citation and both DOI statements. No DOI is ever pre-claimed (R3).
- v1.0 export products (with their `#` reproducibility headers) remain; new exports (engine query results, ensemble summaries) adopt the same header pattern (analysis state: era, indicator, geography, periods, reference window, methodology version, seed, timestamp).

## 7. Accessibility, responsiveness, performance

- **WCAG 2.1 AA:** keyboard operability for every new control (era toggle, scenario switch, scrubber), ARIA labels on charts/maps, visible focus states, contrast-checked palettes (v1.0 palette contract from `metadata.json` extended with era C diverging scales).
- **Mobile-first responsive:** new surfaces follow the v1.0 pattern — controls collapse into the study-context drawer; panels stack; touch targets ≥ 44 px; map fully operable by touch.
- **Performance budgets (from the prototype measurements):** first meaningful paint < 3 s on throttled 4G; engine init < 8 s; cold query < 100 ms (era B) / < 150 ms (era C ensemble); repeat query 0 KB; boot payload = catalog (~2 KB) only; per-file first touch ≤ ~0.5 MB.
- **Rendering scale:** Leaflet + 724 polygons is fine today. Switch triggers: tehsil layer (≈4,590 polys) or the animated Atlas scrubber → PMTiles + deck.gl/MapLibre; 200-year monthly series → Plotly `scattergl` or UPlot; object-pool Arrow tables across sibling views instead of re-querying.
- **States:** loading indicators on every engine query; explicit no-data styling distinct from "normal"; error states with retry; unsupported combinations (e.g. era C × SMA) disabled with an explanation, not silently broken.

### 7.1 M7.3 built checklist (2026-11-22)

Verified on all 11 routes at desktop and 390 × 844: **zero console errors, zero horizontal overflow**, `python data-pipeline/selftest.py` green, `python scripts/regression_check.py` green (699 values), Lighthouse accessibility **1.00** on `#overview`.

- **Touch targets ≥ 44 px** (phone widths ≤ 760 px): icon buttons, nav toggle, product/lens tokens, pagers, panel selects and search inputs, segmented controls, indicator rows, switches, doc navigation, event jump buttons and the date slider (44 px track with a 28 px thumb). Documented WCAG 2.5.8 exceptions, each carrying a CSS comment: the icon-only "?" guide button (intentional), in-sentence "Or go back to 1901 →" link, heading-embedded "Copy anchor" buttons, and visually-hidden 1 × 1 checkbox inputs whose `.switch` labels are 44 px.
- **Contrast:** `.doc-letter` chip (2.48:1 → ~13:1) and the duplicated `.ev-sep` override (1.65:1) corrected.
- **Phones keep era honesty:** the topbar status cluster returns as a compact second row showing the **era pill + currency chip** only (`--topbar-h: 90px`); `#chipDataMode`, `#chipDate` and `#chipAvail` stay desktop-only rather than being dropped without replacement.
- **Permalinks:** `permalink.js` `parse()` wraps `decodeURIComponent` in `try/catch`, so malformed hashes (`#/district/%`, over-long values) degrade to the default view instead of throwing through `routeFromHash`; behaviour-tested against 8 malformed hashes and a 4,012-character hash.
- **Engine Lab:** byte/request counters travel on a dedicated `MessageChannel` port (register I6) — no `unassociated response` warnings, counts still exact (5.19 MB / 2 requests on init, +587 KB for a 538-row scan); catalog file count is recursive (20,289 files, was `NaN`); "no query yet" replaces an empty last-query line; preset query, custom SQL, results CSV and error display all re-verified.
- **Layout contract (register I1–I5):** product bar attached to the topbar and collapsing on scroll; viewport-fitted map — on phones the display toolbar is one scrollable row (wrapped it cost ~183 px and pushed the map off-screen) with `contain: paint` so its children cannot widen the document; the observation date leads the rail (it sat below the indicator sections, which needed a full rail scroll); footer as a panel card; Historical A summary strip above aligned plots.

## 8. Regression protection (what must never break)

1. The four v1.0 workspaces produce identical numbers (regression harness, M1.9).
2. All five v1.0 hash routes keep working; the book-icon docs centre keeps its ten panels.
3. Exports keep their `#` reproducibility headers; download centre products unchanged.
4. Mobile drawer, keyboard operability, ARIA roles verified after every UI task.
5. `selftest.py` stays green; the CSV fallback stays functional with the CDN unreachable.
6. Any UI change ships with the verification line in PROGRESS.md ("tabs cycled, zero console errors, mobile pass").

**Definition of success for this doc:** a user who never opens the new surfaces notices nothing except the currency banner — and a user who opens them gets three honest eras with their seams visible.

---

## 9. Sepia Paper re-baseline (2026-11-20 — decision D10, M10.1–M10.3c built)

*This section is the current source of truth for the dashboard's visual system; §1–§8 above remain valid for behaviour, routing and engine integration.*

### 9.1 The design language

The dashboard is a **reading surface for a long climatological record**, not an app dashboard. The Sepia Paper system (Owner showcase, adopted verbatim as tokens):

| Role | Token | Value |
|---|---|---|
| Page base | `--paper` | `#F6F1E6` |
| Panel / card | `--surface` | `#FBF7EE` |
| Control rail / wells | `--surface-2` | `#EFE8D8` |
| Pressed wells | `--surface-3` | `#E8DFCC` |
| Hairline / strong | `--hairline`, `--hairline-strong` | `#E1D7C3`, `#CFC2A8` |
| Ink ramp | `--ink / --ink-strong / --ink-soft / --ink-faint` | `#2E2820 / #211C15 / #6E6250 / #6F6350` |
| Status | `--ok / --warn / --danger` | `#4A7A5A / #B08947 / #A6452F` |
| Severity ramp (data) | `--sev-*` | unchanged from the published v1.0 metadata palette |

Working rules (binding for every future surface):

1. **60/30/10** — paper dominates, ink carries structure, one accent speaks.
2. **One accent per view** — `body[data-accent]` sets exactly one chrome accent; the muted per-tab band colours (Overview `#4E6B5A`, Historical `#44586E`, Events `#8A5A2B`, Propagation `#6B4E6E`, Engine `#4F5D3A`, Projections `#8A4430`, Summary `#74425E`, Atlas `#6E6238`) still identify each workspace.
3. **Tone, not shadow** — hairline rules and surface steps before drop shadows (panels are flat; only the tooltip and mobile drawer keep elevation).
4. **Texture ≤ 5 %** — one faint grain, visible only in the paper gutters.
5. **Severity darkens** — the class ramp is luminance-ordered and never re-themed.
6. **Accent never paints data** — maps, legends, class chips and chart traces read the data palette, never `--accent`.
7. **Warm ink, never black.**

### 9.2 Typography (M10.3b)

Three voices, three jobs — one family per job, never mixed:

| Role | Family | Weights | Used for |
|---|---|---|---|
| UI | **Inter** (Google Fonts) | 400 / 500 / 600 / 700 | controls, labels, tabs, tables, chart axes, chips, dense chrome |
| Display & reading | **Literata** (Google Fonts; variable optical 7–72, italic 400) | 400 / 600 | brand, panel and view titles, "Ask the record" questions, KPI figures, workspace intros, Documentation prose |
| Data | **IBM Plex Mono** | 400 / 500 | units, z-scores, timestamps, metadata chips, SQL editor, result cells |

Rules (binding for future surfaces):

1. **One optical serif at every size.** Literata is loaded as a variable font with `font-optical-sizing: auto`; there is no separate display/text cut, so a 15 px panel title and a 27 px KPI figure come from the same family. It was chosen for its large x-height and open apertures: the first pass (Source Serif 4) read as cramped at title size on sepia paper.
2. **Key figures read like print.** `.kpi-value` uses the serif with `lining-nums tabular-nums`; every comparable number (KPIs, stat cells, tables, evidence chips, legend ranges) is tabular so columns do not jump when a value changes.
3. **Body 14 px / 1.55.** Prose is capped at 88 ch with `text-wrap: pretty`; headings use `text-wrap: balance`. Mono stays for data only — never for sentences.
4. **Type never encodes data.** Class colours and the severity ramp are unchanged; the serif is a reading voice, not a semantic one.
5. **Fallbacks are deliberate.** The serif chain continues to Source Serif 4 → Iowan Old Style → Palatino Linotype → Book Antiqua → Georgia, so a blocked font CDN degrades to the previous system serif without layout breakage; the UI chain keeps Inter → system UI.
6. `meta[name="theme-color"]` follows the paper base (`#F6F1E6`), not the retired navy.

### 9.3 Accent themes

Four persisted paper accents selected from the sidebar "Paper accent" control (Reading Room `#6B2B1F` default, Field Notes `#55612F`, Drafting Table `#31506B`, Hydrograph `#14594F`). They re-point `--accent*` chrome tokens only, persist in `localStorage['die.accent']`, and never touch the severity ramp, so a class colour quoted in a report means the same thing after the reader changes their paper. Reset filters does not reset the accent.

### 9.4 Depth-1 answer layer

- **"Ask the record"** band at the top of `#overview`: four question cards (now / trend / events / future) plus an Atlas deep link. Cards are `<button>`s (keyboard + screen-reader equivalent), route via `switchTab`, and `latest` additionally snaps the shared date cursor to the most recent available month. Cards never state a number — they point at where the number and its receipt live.
- **Receipts line** under the summary cards: `era · product · window · baseline · n`, filled by `renderEvidence()` from `metadata.json` and the computed region statistics — never hand-typed, and it reports `n = 0` honestly.
- **Era pill** in the topbar: standing `Era A/B/C` label per tab ("C − B · Delta to 2100" on `#summary`), colour-coded by era, with the no-splice wording in its accessible label. This is R2 made visible on every surface without adding a banner to each view.
- **Default reading position (D12):** boot and Reset open on **July 2002**, the documented monsoon failure (410/724 districts ≤ −1.0; 151 ≤ −2.0; 76.8 % area in drought; 23.3 % extreme), not the newest month — December 2025 is wet and made the landing view look as if drought had disappeared. Implemented in `filters.js` (`DEFAULT_DATE`, `resolveDefaultDate`); **Latest** still snaps to the newest observation, and indicators that do not cover 2002 fall back to latest.

### 9.5 Product-first navigation (M10.3c, revised 2026-11-22 — register I7)

The review's "question-first, not technique-first" principle is implemented as a two-tier navigation, not by renaming workspaces:

- **Top row — products/eras.** `Record 1981–2025` (era B), `Projections 2015–2100` (era C), `Atlas 1901–2025` (era A), then a hairline, then `Engine Lab` (a tool, not an era). Each is a hash link, so routes stay stable and no custom click handler is needed.
- **Topbar utilities — help and reference.** `How to use` (opens `tour.html`) and `Documentation` (`#data`) moved out of the product row: they are reference material, so they sit with the brand and the fullscreen control. `Documentation` carries `aria-current="page"` while `#data` is open. On phones both become icon-only 44 px targets and fullscreen is dropped, keeping the topbar at two rows.
- **Second row — lenses.** The analytical tabs of the active product: four record lenses (Overview, Historical Analysis, Drought Events, Propagation & Relationships, plus Cross-validation and District profile), two projection lenses (Future Projections, Drought to 2100). Single-surface groups hide the lens strip.
- **Hover/focus explainers (2026-11-22).** Every product link, lens button and topbar utility carries `data-tip-title` / `data-tip-body`; one shared `#navTip` card appears after a 450 ms hover delay, immediately on keyboard focus, and is dismissed by leaving, clicking, scrolling, resizing or `Escape`. The tooltip is `role="tooltip"` and is linked with `aria-describedby` only while visible.
- The active product link carries `aria-current="page"`; each lens row remains a real `role="tablist"` with `role="tab"` buttons and roving tabindex. `syncNavGroup()` in `app.js` owns the reveal logic.
- The four era-B lenses are **not** merged: they answer different questions (current state, statistics/trends, individual events, cross-indicator lag) about one gridded multi-source record. The structure makes that relationship visible instead of presenting four peer products.
- Fixed group tokens preserve product identity across lenses; the paper accent is not used for the band.

### 9.5b Guided tour (`tour.html`, 2026-11-22 — register I8)

`tour.html` is a standalone, static page in the same Sepia Paper system (it links `assets/css/style.css` and only adds tour-local layout). It exists because the dashboard is dense and the documentation centre is reference, not onboarding:

- **Content:** what the platform is and is not; the three eras as cards (A reconstruction / B gridded record / C projections), never spliced; ten numbered stops, each with what you are looking at, one concrete "try this", and deep links into the live view (`#overview?ind=spi_3&date=2002-07`, `#projections`, `#atlas`, `#crossval`, `#engine`, …); a "where things live" table; a "reading a number honestly" list (era, baseline, n, gaps, uncertainty); the not-operational disclaimer.
- **No fabrication:** every statement is a published behaviour (event rule, trend method, bootstrap seed, eras, reference period). No screenshots are embedded (they would go stale), and no numbers are invented.
- **Entry points:** topbar `How to use`; Documentation rail; user-guide section I; `#engine` rail cross-link.
- Verified: 22 internal links resolve, 0 console warnings, Lighthouse Accessibility 1.00 / Best Practices 1.00 / SEO 1.00, zero horizontal overflow at 390 px.

### 9.5c Rail consoles (2026-11-22 — register I9)

The sidebar is not decoration and not a place to leave controls that do not apply:

- **Record lenses:** the study context (observation date on Overview, geography, indicator, analysis period) — shared state that every Record panel follows.
- **Projections:** an **Era C console** — live read-outs of scenario, indicator, statistic and window, plus four preset chips (Agreement, Median + band, Direction, Late century) that drive the panel's own selects through their `change` events, so the panel remains the single source of truth.
- **Atlas:** an **Atlas scrubber console** — live timescale/month/year, plus the five drought anchors, reusing the panel's own anchor buttons.
- **Documentation:** a **contents index** (Reference / v2.0 evidence / Version & handbook) wired to the existing `data-doc` routing, plus the tour link. The era-B study context is hidden here and on Engine Lab (it would drive nothing).
- Read-outs refresh on `switchTab`, on control changes, when the lazy module's first render settles, and — for lists built at init (projection indicators, atlas months) — through a `MutationObserver`.

### 9.6 What must not regress

1. All nine hash routes and the docs deep-links unchanged (R8); the era pill is a label, never a filter.
2. Data colours, class boundaries, event rules and every analytic result identical to v1.0.0 (R1) — the theme is chrome-only.
3. Keyboard operability: accent swatches and ask cards are real buttons; the era pill is focusable with its full era statement as the accessible name.
4. Lighthouse accessibility ≥ 95 (measured 100 after the ink-faint darkening to `#6F6350` for ≥ 4.5:1 on `--surface-2`); zero console errors across all surfaces.
5. Any new surface ships with its era pill mapping (add to `ERA_BY_TAB`), accent-neutral styling and a receipts-capable meta line.
