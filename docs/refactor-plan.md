# Drought Intelligence Explorer — Implementation Audit & Five-Tab Migration Plan

Phase 1 deliverable of the refactoring task. Produced before any code was modified.

## 1. Existing architecture (as audited)

**Stack (unchanged by this refactor).** Static, fully client-side site; no backend, no build step.
GitHub‑Pages/any-static-host compatible (base-path resolver in `data-loader.js` handles subdirectories).

| Layer | Files | Role |
|---|---|---|
| Shell | `index.html` (610 lines) | topbar, data-provenance banner, left control sidebar, 2 workspace tabs (Dashboard / Analysis Modules), 4 modals (About, Methodology, Data Sources, Download), boot overlay with sequential vendor loader + CDN fallbacks |
| State | `assets/js/filters.js` | single `DIE.state` object; every mutation flows through `Filters.set(patch)` → normalisation → `state` event with changed-key list |
| Data | `assets/js/data-loader.js` | fetch + PapaParse of `data/metadata.json`, 3 boundary GeoJSONs, `districts.csv`/`states.csv` registries, 10 wide-format indicator CSVs; per-dataset validation report; sessionStorage cache keyed by methodology version |
| Analysis | `assets/js/analytics.js` | area-weighted region stats, severity distribution, district/region series, **runs-analysis event identification (Yevjevich 1967; ≤ −1.0, ≥ 3 months)**, historical summary, state/district comparison rows, pairwise-complete indicator comparison stats, CSV export builders |
| Cartography | `assets/js/map.js` | Leaflet choropleth factory (`createChoropleth` supports per-district `valueFn`/`colorFn` overrides — reusable for new statistical maps), class + continuous legends, tooltips, click-to-select, popups, html2canvas PNG export |
| Charts | `assets/js/charts.js` | Plotly: time series (+ optional OLS trend, n ≥ 120), severity bars, frequency-by-year, comparison scatter, area-in-drought timeline |
| Orchestration | `assets/js/app.js` | boot sequence, KPI cards, selected-district/region rail, table (sort/search/paginate/CSV), Analysis tab modules A/B/C, modals, mobile drawer, toasts |
| Vendors (local) | `assets/js/vendor/` | Leaflet 1.9.4, PapaParse 5.4.1, Plotly-cartesian 2.35.2, Turf 7.2, html2canvas 1.4.1 |
| Data | `data/` | 10 indicator matrices (724 districts × 540 months; VCI 311 months from 2000‑02), boundaries, registries, metadata.json (classes/seasons/sources/events spec), 2 precomputed summaries |

**Scientific definitions in force (preserved unchanged).** McKee SPI / Vicente‑Serrano SPEI class thresholds
(minClosed/maxClosed inclusivity encoded per class in metadata); drought = any class with `drought` in key;
severe = severe+extreme; per-indicator event threshold = upper bound of moderate-drought class (−1.0 z, −15 % SMA, 30 % VCI);
area-weighted means and affected-area sums over precomputed Lambert Azimuthal Equal-Area district areas;
missing observations never imputed (NaN runs break events; charts show gaps; tables flag completeness < 50 %).

## 2. Existing feature inventory → tab migration map

| Existing feature (audited) | Destination | Treatment |
|---|---|---|
| Geographic selection (extent/state/district), indicator list, date year/month/slider, historical period + season, analysis-mode radios, map layer toggles, basemap, colour mode, reset | **Global filter bar** (geography + indicator + analysis period) and **Tab 1 contextual controls** (observation date; map settings stay in map panel head) | Sidebar is replaced by a compact always-visible filter bar; identical state semantics via `Filters.set` |
| KPI cards (affected area, severe area, mean, districts in drought; delta vs previous month; period-mean variants) | **Tab 1 Overview** (snapshot form) / period-mean KPI logic retired into Tab 2 statistics (mode radios become redundant: tab = mode) | Computation (`regionStats`) unchanged |
| Main map + legend + selected-district rail + regional summary (top‑5 affected) | **Tab 1 Overview** | Unchanged |
| Drought time series + optional OLS trend; severity distribution | **Tab 1 Overview** | Unchanged |
| Historical row 4: frequency (months, events, %, frequency-by-year chart), duration stats, severity stats | **Tab 2 Historical Analysis**, sections A/B/C | Same `historicalSummary` engine |
| Regional comparison table (state/district level, sort, search, pagination, CSV export, sparse-data flags) | **Tab 2 Historical Analysis** (district-wise ranking section) | Unchanged; period-based so it belongs with frequency ranking |
| Module A: dual synchronized maps + difference map + agreement stats + scatter | **Tab 4 Propagation** (multi-indicator spatial comparison section) | Unchanged |
| Module B: animated drought evolution (map + area timeline + play) | **Tab 1 Overview** (temporal context) — animation of current indicator/region | Unchanged |
| Module C: download centre (region long CSV, indicator wide CSV, district summary CSV, static summaries, map PNG, docs, citation) | **Tab 5 Data, Methodology & Downloads** | Unchanged + metadata enrichment |
| Modals: About, Methodology, Data Sources (incl. live validation report) | Content moves **into Tab 5**; About stays as modal (identity/orientation) | Methodology/Data-sources content restructured into tab sections |
| Validation report (duplicates, invalid values/dates, unknown ids, completeness) | **Tab 5 data-quality section** | Unchanged |
| Accessibility: ARIA tabs, focus management, skip link, reduced motion; mobile drawer; fullscreen; toasts; boot/error states | Preserved as-is | — |

**Redundancies removed (the only removals):** the analysis-mode radio group (superseded by tabs — same three modes become Overview / Historical / (comparison folded into Propagation)); the duplicate Download modal (kept as one entry point on Tab 5 only, topbar link points to Tab 5). No scientific functionality removed.

## 3. Genuinely new features (implemented, data-supported)

1. **Tab 2 D. Long-term trends** — Mann‑Kendall S/variance/Z/p with tie correction, Sen's slope + 90 % CI (rank-based), **Hamed–Rao variance correction applied when lag‑1 autocorrelation of the MK residuals is significant** (documented; plain-MK result also shown when correction not triggered). Sample size always reported.
2. **Tab 2 E. Recurrence** — empirical inter-event statistics (mean inter-arrival, empirical return period of events at/above severity quantiles) — explicitly non‑parametric, no distribution assumed.
3. **Tab 2 spatial statistic maps** — per-district drought frequency (%), mean event duration, cumulative severity choropleths reusing the existing `createChoropleth` factory with `valueFn`.
4. **Tab 3 Event Explorer** — client-side event catalogue (per-district runs analysis for the current indicator/region, sortable/filterable/paginated + CSV), event timeline (Gantt-style) + duration distribution + severity comparison, event detail view (event-specific series with shaded event window, onset/termination/duration/max intensity/cumulative severity, recovery time = months from event end to first value ≥ 0), **censoring flags** for events touching the record edges, and **sensitivity scenarios** (threshold and min-duration) clearly separated from the default methodology.
5. **Tab 4 Propagation** — temporal cross-correlation at lags −12…+12 between indicator pairs on matched months, optimal lag, n, t-based significance, **moving-block bootstrap 95 % CI** (block length from lag‑1 autocorrelation, 1 000 resamples), lag-correlation plot, **full 10×10 correlation heatmap** (pairwise-complete matched months), per-district optimal-lag map (|r| filter), and a clearly-marked *unavailable* section for streamflow/groundwater propagation (no such data in the dataset).
6. **Tab 5 reproducibility** — every CSV export gains `#`-comment metadata header (indicator, region, period, reference period, export date/time UTC, methodology version + settings, data source) with the tabular schema rows unchanged; new "analysis metadata (JSON)" export; per-indicator data-quality table (valid %, missing %, window, latest observation).
7. **Hash routing** (`#overview|#historical|#events|#propagation|#data`) — refresh/deep-link safe; geography/indicator/period state shared across tabs (single `DIE.state`).

## 4. Data limitations found in the audit (surfaced, not papered over)

- **VCI record starts 2000‑02** (MODIS); cross-correlations involving VCI use matched 2000‑02+ months only, n always displayed.
- **SPI/SPEI/SMA record 1981‑01(+lag)–2025‑12**; SPI‑3/6/12 and SPEI‑3/6/12 start after their accumulation warm-up.
- **No streamflow, groundwater, reservoir or runoff data** → hydrological-drought propagation limited to the SMA proxy; UI states this explicitly instead of manufacturing results.
- District-mean SMA/VCI are **proxies**, not observed hydrological drought; disclaimers added wherever SMA is used in propagation.
- Boundaries are simplified 2011-census vintage; areas precomputed equal-area (consistency documented).
- **Shipped dataset is a seeded demonstration build** (generator documented in `data-pipeline/generate_demonstration_data.py`). The build metadata previously labelled it `static-research`/GEE — **this refactor corrects the label** to `static-demonstration` with the generator provenance and seed recorded, so every banner/chip/footnote states the truth until the owner's real GEE export replaces the CSVs (drop-in contract unchanged). All data-mode-aware strings in the app are driven from `metadata.json`, so the real GEE export will flip every label back automatically.

## 5. Migration sequence (implemented order)

1. **Data honesty relabel** (`metadata.json` + config root `app_metadata` + data-mode-aware UI strings).
2. **Shell restructure**: five tabpanels + global filter bar + hash router (Phase 2).
3. **Tab 1 Overview** assembly from existing modules + new district ranking (Top 10).
4. **Tab 2 Historical** (existing row-4 engine + new trend/recurrence/spatial maps).
5. **Tab 3 Events**.
6. **Tab 4 Propagation** (Module A migration + new temporal analysis).
7. **Tab 5 Data/Methodology/Downloads** (+ export metadata).
8. **Verification**: numeric baseline captured pre-refactor (SPI‑3 snapshot 2025‑12: n=724, 152 drought districts, mean 0.3609, affected 628 308 km²/19.236 %; state comparison top‑3 Delhi/Sikkim/Uttarakhand ≈ 32 %; Nicobars SPI‑3 events 1994‑12→1995‑03 (dur 4, sev 1.48), 1998‑03→1998‑05 (3, 0.88), 2006‑08→2006‑10 (3, 2.80); SPI‑3 vs SPEI‑3 2025‑12: r = 0.9865, RMSE 0.173, bias −0.0053) — post-refactor values must match exactly.
