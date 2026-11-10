# Paper Source Document — Drought Intelligence Explorer (India)

**Purpose:** This file is a complete, fact-checked extraction of the platform's features, data pipeline, methodology, and use cases, prepared as source material for manuscript drafting. It supports three candidate article types: (1) a Data Descriptor / Database paper (e.g., *Scientific Data*), (2) a Software / Tool paper (e.g., *Environmental Modelling & Software*), and (3) an application case study using the platform as a research instrument. Section 12 provides a suggested outline for each route.

**How to use:** Feed this entire file to a writing LLM together with the chosen outline from Section 12. Every claim below is traceable to the project's own documentation (`docs/methodology.md`, `docs/data-sources.md`, `docs/user-guide.md`, `README.md`). Do not let the writer go beyond the guardrails in Section 11.

---

## 1. Product summary (elevator paragraph)

The **Drought Intelligence Explorer** is an open, browser-based geospatial platform for monitoring and analysing meteorological, agricultural and land-surface drought across India at district resolution, monthly, from 1981 to 2025. It unifies ten drought indicators computed from CHIRPS precipitation, ERA5-Land evapotranspiration/soil moisture and MODIS NDVI — extracted and processed through a reproducible Google Earth Engine pipeline — into a four-workspace analytical dashboard (current conditions, historical analysis, drought events, indicator propagation) with an integrated documentation centre. All statistics are computed live in the browser from a versioned static dataset; every chart, table and export reports its sample size, and missing data are never imputed. The platform is designed as a transparent, citable research instrument rather than an operational warning system.

---

## 2. Data pipeline (production chain)

### 2.1 Source datasets (this research build)

| Role | Source | Access route | Period used |
|---|---|---|---|
| Precipitation (SPI, SPEI) | CHIRPS daily v2.0 Final (Funk et al., 2015) | Google Earth Engine `UCSB-CHG/CHIRPS/DAILY` | 1981–2025 |
| Potential evapotranspiration + soil moisture (SPEI, SMA) | ERA5-Land monthly aggregates (Muñoz-Sabater et al., 2021) | GEE `ECMWF/ERA5_LAND/MONTHLY_AGGR`, 0.1°; PET + volumetric soil water layers 1–3 (0–100 cm) | 1981–2025 |
| Vegetation greenness (VCI) | MODIS/Terra MOD13A3 v061 NDVI (Didan, 2015) | GEE `MODIS/061/MOD13A3`, 1 km monthly | 2000-02–2025-12 |
| Boundaries | Community-maintained India district GeoJSON, 2011-census demarcation | GitHub `udit-001/india-maps-data`; 724 districts, 36 states/UTs | static |

### 2.2 Processing chain (reproducible, scripted)

1. **Extraction** — `python run.py gee --project <project> --end 2025-12` pulls the three sources via Google Earth Engine and aggregates to district polygons. An offline download route (Python + R alternative, CHIRPS v3.0) ships in `data-pipeline/` with a documented update runbook.
2. **Indicator computation** — `python run.py indicators` (`data-pipeline/die_pipeline/indicators.py`) computes SPI/SPEI/SMA/VCI per district-month and writes wide-format matrices.
3. **Boundary preparation** — `data-pipeline/prepare_boundaries.py` generalises polygons (~100 m coordinate precision; median district area error 0.03%), precomputes equal-area areas and centroids in **Lambert Azimuthal Equal-Area centred on India** (`+proj=laea +lat_0=22.5 +lon_0=79.5`, WGS84), and emits district/state/outline GeoJSON.
4. **Export & validation** — `python run.py export` and `python run.py validate` write the distributed CSVs and precomputed cross-check files (`data/summaries/`).
5. **Metadata** — `data/metadata.json` records indicator definitions, thresholds, palettes, provenance, versions and per-indicator availability; it is the single source of truth consumed by the front end (adding or replacing a dataset requires no code changes).

### 2.3 Data contract and quality gates

- Each indicator CSV is wide format: `district_id, district_name, state_name,` + one `YYYY-MM` column per month; missing cells are empty; ids must match the GeoJSON.
- **Load-time validation (recomputed in the browser, user-visible report):** duplicate district rows (merged, last kept), invalid date columns (skipped), non-numeric values (treated as missing), district ids absent from boundaries (dropped), boundary districts absent from a dataset (rendered as no-data), and per-indicator completeness inside its true availability window. A "Validate all indicators" action downloads and checks the remaining matrices in small parallel batches.
- **Precomputed cross-checks:** independent runs-analysis event file and state statistics CSV ship with the data so browser-computed results can be reconciled.

---

## 3. The ten indicators

| Indicator | Family | Standardises | Units | Availability |
|---|---|---|---|---|
| SPI-1 / SPI-3 / SPI-6 / SPI-12 | Meteorological | Accumulated precipitation (McKee et al., 1993) | z-score | 1981-01*–2025-12 |
| SPEI-1 / SPEI-3 / SPEI-6 / SPEI-12 | Climatic water balance | Precipitation − PET (Vicente-Serrano et al., 2010) | z-score | 1981-01*–2025-12 |
| SMA — Soil Moisture Anomaly | Land surface | Root-zone soil moisture departure from seasonal climatology | % | 1981-01*–2025-12 |
| VCI — Vegetation Condition Index | Land surface | NDVI rescaled between historical stress and optimum (Kogan, 1995) | % | 2000-02–2025-12 |

\* multi-month windows start when the first rolling window completes (e.g., SPI-3 begins 1981-03).

**Computation details (report these — they are the methodological substance):**

- **Standardisation uses per-calendar-month distributions over a fixed reference period:** **1981–2020** (WMO-style 30 years) for SPI/SPEI/SMA; **2000–present** for VCI (MODIS record limit).
- **SPI:** two-parameter gamma fitted to positive accumulation totals per district and calendar month, mixed distribution for zero-rain months.
- **SPEI:** three-parameter log-logistic fitted to the water balance (P − PET) with the L-moment/probability-weighted-moment closed-form estimator (Vicente-Serrano et al., 2010; Singh et al., 1993) — the same method as the reference R `SPEI` package. Every fit is checked against its base sample and falls back to a distribution-free **Gringorten plotting-position** transform when unstable.
- **Classification:** SPI/SPEI use the conventional nine-category scheme (moderate drought ≤ −1.00, severe ≤ −1.50, extreme ≤ −2.00, etc.). SMA and VCI use their own bounded-percentage thresholds — z-score thresholds would be invalid on them. All thresholds live in `metadata.json` and drive map, legend, charts and statistics consistently.

---

## 4. Feature catalogue (complete)

### 4.1 Workspace 1 — Overview (current conditions)

- **Observation-date scope strip** (year/month selects, 45-year slider, "Latest" jump) driving every panel below it.
- **Four live KPI cards:** drought-affected area (equal-area km² + % of region), severe+extreme subset area, area-weighted mean indicator with its severity class, and count/share of districts in drought with the severe-or-worse subset — each with change versus the **previous available observation**, and explicit N/A when no valid data exist.
- **Interactive choropleth map** (Leaflet): discrete severity classes or continuous colour scale; hover tooltips (value + class); click-to-focus a district across the whole application; popups with district detail; district/state/outline layers and optional place labels; choice of plain offline basemap (default, zero external tiles), light reference tiles or OpenStreetMap — the basemap choice applies to **every** map in the application.
- **Full regional time series** (Plotly): area-weighted monthly mean, drought-class threshold lines, genuine gaps (no interpolation), optional ordinary-least-squares trend offered only when ≥ 120 valid months exist and labelled as descriptive.
- **Severity distribution:** share of the region's equal-area surface in each class at the selected date, no-data area reported separately.
- **District ranking (top-10):** most-affected districts by mean severity or affected area; rows below 50 % completeness flagged and excluded.
- **Animated historical evolution:** percentage of region area in drought across the full record, with playback.

### 4.2 Workspace 2 — Historical Analysis

- **Frequency:** months and % in drought, per-year bar series (season filter applies), district frequency histogram.
- **Duration & severity:** summary statistics plus per-district choropleth maps.
- **Trend analysis (inferential):** Mann–Kendall test with tie-corrected variance (S, Z, two-sided p); **Hamed–Rao (1998) variance correction** when significant lag-1–12 autocorrelation is detected on the detrended series (effective sample size n*, corrected and uncorrected Z both reported); **Sen's slope** (median of pairwise slopes) with rank-based **90 % confidence interval**; annual (default) or monthly granularity, with the autocorrelation caveat attached to the monthly option; sample size always shown; not computed below 4 observations.
- **Recurrence (empirical, non-parametric):** mean/median inter-arrival times and severity-exceedance return periods from empirical quantiles (Q50/Q75/Q90); **no distribution is fitted** and results are labelled indicative.
- **District-wise ranking table:** one row per state/UT or district (switchable); area-weighted mean indicator, drought-affected area share, severe area share, drought months, completeness; sortable, searchable, paginated; sparse rows (< 50 %) flagged and excluded from ranking; CSV export.

### 4.3 Workspace 3 — Drought Events

- **Event definition scope strip** (minimum duration 3/4/6/9/12 months; truncation level default/−0.5/−1.0/−1.5/−2.0) that re-runs detection for every Events panel, with a visible wait state.
- **Event catalogue** via runs analysis (Yevjevich, 1967) on continuous monthly series: onset, termination, duration, maximum intensity, cumulative severity (Σ deficit below truncation), mean intensity, **recovery** (months to first value ≥ 0 — stricter than merely exiting the drought class), and a **censoring flag** for events touching the record/period edge (shown but excluded from duration/severity rankings). Searchable by district, filterable by onset year, sortable, CSV export.
- **Event detail view:** the district series around the event with the shaded event window, summary statistics and a map extent.
- **Onset timeline** and **duration distribution** charts.
- **Definition-sensitivity panel:** event counts under alternative minimum-duration and truncation scenarios; the default methodology is always annotated and non-default results are visually separated — sensitivity analysis is a first-class feature, not a hidden option.

### 4.4 Workspace 4 — Propagation & Relationships

- **Lagged cross-correlation** between any indicator pair: Pearson r at lags −12…+12 months on matched months only (pairwise deletion), optimal lag = largest |r| subject to ≥ 30 matched pairs; positive lag means B responds after A.
- **Uncertainty:** 95 % confidence interval at the optimal lag via **moving-block bootstrap** (Künsch, 1989): 1 000 resamples, block length n^(1/3) capped at 4–24 months, **fixed seed 20261103**, blocks resampled jointly to preserve serial dependence. Nominal t-based p-values shown for reference only; the cross-lag selection caveat is stated in the interface.
- **Dual-series comparison chart** of the pair.
- **10 × 10 correlation heatmap:** pairwise r at each pair's optimal lag, with the by-construction correlation of nested SPI/SPEI scales flagged and cross-family comparison recommended for propagation insight.
- **District-wise optimal-lag map:** where the response lags or leads, district by district.
- **Single-date spatial comparison:** two indicators on synchronised maps for one month; difference map (B − A, diverging ramp; mixed-unit contrasts labelled as such); agreement statistics — Pearson r, r², RMSE, bias, n matched, excluded count — over matched districts only (pairwise deletion); scatter plot.
- **Honest scope statement:** streamflow/groundwater propagation is explicitly marked **unavailable** (no such observations in the dataset; nothing is simulated).

### 4.5 Documentation & Resources (integrated documentation centre)

Ten sections shipped inside the application: About; Data sources (build provenance table, per-indicator availability/missing share, full source register with access dates); Methodology (indicators, thresholds, aggregation, events, trends, correlation, missing-data policy); Validation & data quality (the live report of §2.3); Uncertainty & limitations; Reproducibility (pipeline commands, metadata, seeds); Downloads & citations; Version history; User guide; Glossary. In-page navigation; deep-linkable (`#data` / `#docs`).

### 4.6 Cross-cutting platform features

- **Ten export products, all generated client-side:** long-format region extract (district × month with value, class, area, provenance), the exact distributed wide matrix, district drought statistics, event catalogue, current ranking table, analysis-metadata JSON (complete analysis state: indicator, geography, observation and analysis periods, reference period, methodology settings, seed, export timestamp), boundary GeoJSON, current map PNG, documentation, ready-to-paste citation. **Every CSV begins with `#` comment lines** recording indicator, geography, dataset and analysis periods, reference period, methodology version, data mode/seed, source and export time — a reproducibility header travels with every number.
- **Sample-size discipline everywhere:** charts show valid counts, tables show completeness, correlations show matched months; missing months are never imputed, interpolated or silently treated as normal; KPIs show N/A rather than invented values; maps style missing units as explicit no-data.
- **Four-tier data lineage labelling** in the interface: (1) original observations → (2) derived indicator matrices → (3) spatially aggregated statistics → (4) analytical summaries. Users always know which tier they are reading.
- **Study-context sidebar + panel-local controls** (Grafana/Tableau pattern): geography, indicator and analysis period are the only global controls; workspace-specific controls sit on the panels they drive (scope strips, map toolbar, panel heads), eliminating ambiguity about what drives what.
- **Per-workspace visual identity** (accent colours) while severity palettes and plot colours stay independent of branding.
- **Accessibility:** keyboard-operable tabs (arrow keys) and controls, visible focus states, ARIA roles on tabs/dialogs/status regions, skip link, descriptive legends and tooltips, `?` shortcut to the guide.
- **Performance engineering:** parallel boot with cached indicator text, memoised analytics aggregates, hidden-tab dirty tracking, targeted filter-control rebuilds, transient slider updates, progressive chart rendering while Plotly loads, on-demand html2canvas.
- **Privacy-friendly usage telemetry** (Google Tag Manager): ~18 event kinds covering workspace switches, indicator/date changes, map interactions, exports and documentation access — designed to measure research use of the tool.
- **Pure client-side deployment:** static hosting only, no backend, no user data, no build step (vanilla JS + Leaflet + Plotly); works from the offline plain basemap with zero external tile services.

---

## 5. Methodological implementation summary (for a Methods section)

| Analysis | Method | Key parameters / safeguards |
|---|---|---|
| SPI | Two-parameter gamma per district × calendar month; mixed distribution for zero-rain months; Gringorten fallback | Reference period 1981–2020 |
| SPEI | 3-parameter log-logistic on P − PET; L-moment estimator (as R `SPEI`) | Same reference period; fit-checked |
| SMA | Root-zone (0–100 cm) soil moisture departure from seasonal climatology | Own bounded-% thresholds |
| VCI | NDVI rescaled between historical stress and optimum (Kogan, 1995) | Reference 2000–present |
| Regional aggregation | Area-weighted means using precomputed equal-area surfaces (Lambert Azimuthal Equal-Area, 22.5° N / 79.5° E) | Areas computed from the same geometry the map serves (~3.27 M km² total) |
| Event detection | Runs analysis (Yevjevich, 1967) on continuous monthly series | Truncation = moderate-drought class edge (−1.00 z; −15 % SMA; 30 % VCI); min duration 3 months; censoring flags; recovery = return to ≥ 0 |
| Trend | Mann–Kendall (tie-corrected) + Sen's slope, rank-based 90 % CI | Hamed–Rao variance correction on significant lag-1–12 autocorrelation; both Z values reported; n always shown |
| Correlation | Pearson r, lags −12…+12 months, matched months only | ≥ 30 matched pairs required |
| Correlation CI | Moving-block bootstrap (Künsch, 1989) | 1 000 resamples; block n^(1/3) capped 4–24; fixed seed 20261103; selection caveat stated |
| Comparison agreement | r, r², RMSE, bias over matched districts | Pairwise deletion; excluded counts displayed |
| Recurrence | Empirical inter-arrival times; return periods from severity quantiles Q50/Q75/Q90 | No fitted distribution; labelled indicative |
| Missing data | No imputation anywhere | Pairwise deletion; explicit no-data rendering; N/A semantics; < 50 % completeness excluded from rankings |

---

## 6. Use cases (what a user can actually do)

1. **Rapid current-conditions briefing** — open Overview, read the four KPI cards and the map: where drought is, how severe, and how the situation changed versus the previous month (policy briefings, situational awareness).
2. **Historical drought characterisation for any geography** — quantify frequency, duration, severity, trend and recurrence for All India, any state/UT or any district over 1981–2025, with optional season restriction (SW monsoon, post-monsoon, pre-monsoon, cold season).
3. **Trend detection with honest statistics** — decide whether drought conditions are worsening for a region using Mann–Kendall + Sen's slope with explicit autocorrelation handling, seeing both corrected and uncorrected results.
4. **Discrete event forensics** — build the event catalogue for any indicator, inspect a specific episode (shaded window, map extent, intensity profile, recovery time), and test how the event list responds to alternative definitions via the sensitivity panel.
5. **Multi-indicator propagation analysis** — establish which land-surface or vegetation indicator responds to which meteorological indicator, at what lag (cross-correlation with bootstrap CI), whether the lag is geographically structured (district lag map), and how all ten indicators relate (10 × 10 heatmap) — e.g., quantifying precipitation-to-vegetation drought propagation across India.
6. **Indicator inter-comparison and agreement auditing** — compare any two indicators on matched districts for a given month (r, r², RMSE, bias, difference map) to understand where indices diverge.
7. **Reproducible secondary analysis** — export any table, matrix, event catalogue or the complete analysis-state JSON (with `#` metadata headers) and take the numbers into R/Python without re-deriving anything.
8. **Data-quality auditing** — read the live validation report, per-indicator availability windows and missing shares before trusting any statistic.
9. **Teaching and methods training** — the integrated methodology, glossary and worked caveats (censoring, reference-period dependence, correlation ≠ causation) make the platform usable as instruction material for drought indices.
10. **Tool evaluation for adoption** — Documentation & Resources provides the full source register, data contract, pipeline runbook and citation, so a research group can assess and redeploy the pipeline on new data with no code changes.

**Representative research questions the platform answers out of the box** (case-study seed material):

- How did the spatial extent and severity of drought in India evolve over 1981–2025, and is there a significant trend (MK/Sen with Hamed–Rao correction)?
- What is the lag structure between meteorological drought (SPI) and vegetation response (VCI) at district level, and where is it longest?
- How sensitive are drought-event statistics (counts, durations, severity) to the event definition (minimum duration × truncation level)?
- How strongly do SPEI and SMA agree during recent droughts, and where (which districts) do they diverge?
- What share of India's land area experienced severe-or-worse drought in each decade, and how does that compare with the 1981–2020 climatology?

---

## 7. Design principles (scientific-integrity features worth claiming)

- Sample size and completeness are surfaced on every chart, table and statistic.
- Missing data are never imputed; gaps are visible everywhere (maps hatch, series gap, N/A semantics).
- Parametric fits are checked and fall back to non-parametric transforms rather than emitting unreliable values.
- Default methodology is always annotated; alternative scenarios are visually separated from defaults.
- Uncertainty is quantified where defensible (bootstrap CI for correlation; rank-based CI for Sen's slope) and explicitly *not* claimed where it is not (empirical return periods).
- Selection effects are disclosed (optimal-lag CI caveat; OLS trend restricted to ≥ 120 months and labelled descriptive).
- Association is never presented as causation; the platform says so in the interface.
- Scope limits are stated: research product, not operational monitoring; not official drought declarations; boundaries not authoritative for legal purposes.

---

## 8. Facts & numbers cheat sheet (verify against final build before submission)

- **Region:** India; **724 districts**, **36 states/UTs** (2011-census demarcation, generalised; median district area error 0.03 %).
- **Temporal coverage:** 1981-01 – 2025-12 for SPI/SPEI/SMA; 2000-02 – 2025-12 for VCI. Monthly resolution.
- **Indicators:** 10 (SPI-1/3/6/12, SPEI-1/3/6/12, SMA, VCI). ~540 district-months per indicator for SPI-3-era series; each matrix ≈ 724 × 540 ≈ 390 000 values.
- **Reference climatology:** 1981–2020 (SPI/SPEI/SMA); 2000–present (VCI).
- **Lags analysed:** 25 (−12…+12 months). **Bootstrap:** 1 000 moving-block resamples, seed 20261103.
- **Equal-area total:** ≈ 3.27 million km² (supplied boundaries).
- **Exports:** 10 products; CSVs carry `#` reproducibility headers.
- **Tech stack:** vanilla JavaScript (no framework, no build step), Leaflet, Plotly, html2canvas (on demand); static hosting; Google Tag Manager for usage telemetry.
- **Citation of the software (as shipped):** Deshmukh, A. (2026). *Drought Intelligence Explorer: An Interactive Geospatial Platform for Drought Monitoring and Analysis in India* [computer software]. https://ankitdeshmukh.com/
- **Methodology version:** research-gee-1.0.2; data mode: static research (GEE-derived).

---

## 9. Reference list (already used by the platform; reuse in the manuscript)

- McKee, T. B., Doesken, N. J., & Kleist, J. (1993). The relationship of drought frequency and duration to time scales. *Proc. 8th Conf. Applied Climatology*, 179–184.
- Vicente-Serrano, S. M., Beguería, S., & López-Moreno, J. I. (2010). A multiscalar drought index sensitive to global warming: SPEI. *Journal of Climate*, 23(7), 1696–1718.
- Kogan, F. N. (1995). Application of vegetation index and brightness temperature for drought detection. *Advances in Space Research*, 15(11), 91–100.
- Yevjevich, V. (1967). *An objective approach to definitions and investigations of continental hydrologic droughts*. Hydrology Papers No. 23, Colorado State University.
- Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica*, 13(3), 245–259.
- Kendall, M. G. (1975). *Rank Correlation Methods* (4th ed.). Charles Griffin.
- Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *JASA*, 63(324), 1379–1389.
- Hamed, K. H., & Rao, A. R. (1998). A modified Mann–Kendall trend test for autocorrelated data. *Journal of Hydrology*, 204(1–4), 182–196.
- Gilbert, R. O. (1987). *Statistical Methods in Environmental Pollution Monitoring*. Van Nostrand Reinhold.
- Künsch, H. R. (1989). The jackknife and the bootstrap for general stationary observations. *Annals of Statistics*, 17(3), 1217–1241.
- Funk, C., et al. (2015). The climate hazards infrared precipitation with stations — a new environmental record for monitoring extremes. *Scientific Data*, 2, 150066.
- Muñoz-Sabater, J., et al. (2021). ERA5-Land: a state-of-the-art global reanalysis dataset for land applications. *Earth System Science Data*, 13, 4349–4383.
- Didan, K. (2015). *MOD13A3 MODIS/Terra Vegetation Indices Monthly L3 Global 1 km SIN Grid V061*. NASA LP DAAC.
- Hersbach, H., et al. (2020). The ERA5 global reanalysis. *QJRMS*, 146(730), 1999–2049.
- WMO (2009). Lincoln Declaration on Drought Indices.
- Pai, D. S., et al. (2014). Development of a new high spatial resolution (0.25°) long period (1901–2010) daily gridded rainfall data set over India. *MAUSAM*, 65(1), 1–18.

---

## 10. Reuse value (the "why publish this" arguments)

- **For researchers:** a district-level, multi-decadal, ten-indicator drought dataset for India with a scripted, re-runnable pipeline (new end date, new districts, new indicator — same commands), plus client-side analytical tooling that would otherwise require bespoke GIS/statistics work.
- **For the drought-methods community:** a reference implementation of SPI/SPEI standardisation, runs-based event detection with censoring, MK/Sen with Hamed–Rao correction, and moving-block bootstrap correlation — all visible in the UI with their caveats, and exportable for independent verification.
- **For practitioners/educators:** zero-install access (URL only), integrated methodology and glossary, and exports that drop directly into reports or teaching material.
- **For open science:** complete provenance (source → indicator → statistic tiers), versioned metadata, fixed analysis seeds, reproducibility headers on every export, and a stated non-claim (not an operational system) that models honest tool communication.

---

## 11. Claims guardrails (do not let the manuscript claim these)

- It is **not** an operational/real-time drought monitoring or early-warning system; it is a historical and analytical explorer.
- Values are **not** official drought declarations and are not a substitute for IMD/government bulletins.
- District aggregates are not point measurements; boundaries follow the source vintage and are not authoritative for legal purposes; district reorganisations after 2011 demarcation are not represented.
- Correlation/propagation results are associations, not causal mechanisms; SPI/SPEI across accumulation windows correlate by construction.
- Event statistics depend on the stated truncation and duration choices; recurrence estimates are indicative (no fitted distributions).
- Streamflow/groundwater propagation is explicitly unavailable — nothing is simulated.
- Telemetry is aggregate usage measurement, not user tracking of content.

---

## 12. Suggested manuscript outlines (one per candidate route)

### Route A — Data Descriptor (e.g., *Scientific Data*)
Focus: the **dataset + pipeline** as the contribution; the dashboard is the access/analysis layer.
1. **Background & Summary** — Indian drought monitoring needs multi-scalar, multi-indicator, sub-national data; what this dataset provides; the dashboard as its interface.
2. **Methods** — sources (2.1); GEE extraction and district aggregation (2.2); indicator computation with references (3); boundary/equal-area preparation.
3. **Data Records** — file inventory (2.2), formats, the metadata contract, repository/Zenodo placement (to arrange), record versions.
4. **Technical Validation** — pipeline checks; in-browser validation suite (2.3); precomputed cross-check reconciliation; reference-period rationale; no-imputation policy.
5. **Usage Notes** — the dashboard workspaces, exports, and the reproducibility headers (§4, §6).
6. **Reuse Potential** — Section 10 scenarios; pipeline re-runnability.
*(Optionally pair with a short companion software paper later.)*

### Route B — Software / Tool paper (e.g., *Environmental Modelling & Software*)
Focus: **system architecture + methodological implementation + scientific value** (precedent class: dashboard tools such as the Great Lakes Dashboard in EMS).
1. **Introduction** — gaps in existing drought platforms (operational bias, single-index scope, closed pipelines, no sample-size transparency).
2. **Platform overview** — architecture: static data contract, pure client-side computation, no backend; four workspaces + documentation centre (§1, §4.6).
3. **Data pipeline** — §2 (as the tool's ingest layer).
4. **Methodological implementation** — §5, with the integrity features of §7 as first-class design contributions.
5. **Interface/UX design** — §4.6 patterns (study-context sidebar, panel-local controls, lineage tiers) framed as analysis-transparency design, not cosmetics.
6. **Use cases** — §6 workflows 1, 3, 5, 7 worked as demonstrations.
7. **Discussion** — limitations (§11), extensibility (data contract; no-code dataset swaps), reuse value (§10).

### Route C — Application case study (hydrology / remote sensing journal)
Focus: **scientific findings**; the dashboard is the instrument, briefly described in Methods.
1. **Introduction** — drought propagation and trend questions for India (see seed questions in §6).
2. **Study area & data** — India, 724 districts, the datasets of §2.1.
3. **Methods** — indicator computation and the specific analyses used (subset of §5 relevant to the chosen questions); state that the platform implements these and cite the software.
4. **Results** — e.g., spatio-temporal evolution of drought 1981–2025; propagation lags between SPI and VCI/SMA across districts; sensitivity of event statistics to definition choices.
5. **Discussion** — physical interpretation, comparison with prior Indian drought studies, implications.
6. **Conclusion** — findings; the platform as a reusable instrument (one paragraph, cite Routes A/B if published).

---

## 13. Gaps to close before submission (author to-do)

- [ ] Deposit the dataset (CSVs, boundaries, metadata) and pipeline in a citable repository (Zenodo DOI) — required for *Scientific Data*.
- [ ] Decide software licensing and add a LICENSE file; consider tagging a release (e.g., v1.0) and archiving the exact code version with the paper.
- [ ] Obtain/generate the descriptive statistics the chosen route requires (e.g., national trend results, representative propagation lags) from the platform itself — the case-study route needs actual findings.
- [ ] Confirm the boundary source licence terms for redistribution; keep the boundary disclaimer (§11).
- [ ] Verify all numbers in §8 against the final build and record the build hash/commit with the manuscript.
