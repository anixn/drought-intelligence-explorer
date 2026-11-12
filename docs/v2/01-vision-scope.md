# DIE v2.0 — Vision, Objectives and Scope

*Doc 1 of the v2.0 suite. Companion files: 02-roadmap-milestones, 03-scientific-pipelines, 04-frontend-ui-spec, 05-decision-register. Authority: this doc defines **what** and **why**; 02 defines **when/what order**; 03 defines **how (data)**; 04 defines **how (UI)**; 05 defines **which choice applies when documents disagree**.*

---

## 1. Product vision

DIE v1.0.0 (live 2026-11-10, DOI 10.5281/zenodo.24113364) proved a specific idea: a fully static, browser-based, metadata-driven drought analytics platform can publish a reproducible, multi-indicator, district-level climate record and survive peer review of its methods. It serves 10 indicators (SPI-1/3/6/12, SPEI-1/3/6/12, SMA, VCI) for 724 districts over 540 months (1981–2025), with four analytical workspaces, an embedded documentation centre, a checksummed release manifest, and an 82-assertion offline self-test.

**DIE v2.0 extends that proven platform — it does not replace it.** The v2.0 vision:

> **India's seamless 1901–2100 district-scale drought record with model-spread honesty and a statistical interrogation layer — built as labelled eras, one schema, and honest about seams.**

Three eras, one queryable contract:

| Era | ID | Source | Time | Spatial units | Variables |
|---|---|---|---|---|---|
| **A — Atlas** | `atlas` | Drought Atlas of India (Chuphal et al., Zenodo — **verify v2 release before integration**) | 1901–2025 (v2) or 1901–2021 (v1) | tehsil-native source; served at district level first | SPEI-1/3/6/12 (per Atlas release) |
| **B — Observed** | `observed` | Existing v1.0.0 pipeline: CHIRPS v2.0, ERA5-Land, MODIS MOD13A3.061 via GEE | 1981–2025 → extended monthly | district (724) | SPI-1/3/6/12, SPEI-1/3/6/12, SMA, VCI |
| **C — Projections** | `projections` | 24 CMIP6 GCMs (PR, TASMAX, TASMIN), QDM bias-corrected vs IMD reference | 2026–2100 (default; 2022–2100 is an open decision) | district (724) | SPI-1/3/6/12, SPEI-1/3/6/12 |
| **D — Reanalysis bridge** (optional, Tier 3) | `reanalysis` | ERA5-Land monthly, 1950 onward | 1940/1950–2025 | district (724) | SMA, PET, T2m context |

**What DIE v2.0 is not trying to do:** out-operationalise the India Drought Monitor (weekly cadence), IMD bulletins, or KrishiDrought (4-week agricultural forecasts). DIE owns the climatological record, the statistical interrogation layer, and the reproducible projections. This positioning is deliberate and appears in the UI copy.

## 2. Objectives — the seven verbs

Every v2.0 feature must serve at least one of these product capabilities (inherited from the implementation specification, kept as the acceptance lens):

1. **Monitor** — where is drought occurring now and in the recent past, and how is it evolving? (v1.0 Overview, extended with currency banner and status page.)
2. **Characterise** — quantify frequency, duration, severity, intensity, onset, termination, recovery, recurrence and spatial extent. (v1.0 Historical + Events, extended with change-point tests and multiple-testing control.)
3. **Understand** — how deficits develop, propagate, persist and recover across families. (v1.0 Propagation, extended with event fingerprinting; streamflow/groundwater claims stay impossible until real observations exist.)
4. **Compare** — indicators, regions, periods, models, scenarios. (Extended: era comparisons, model ranking, cross-validation panels.)
5. **Project** — defensible future drought assessment under CMIP6 scenarios with mandatory uncertainty disclosure. (New: era C module — the flagship.)
6. **Assess risk** — combine hazard with exposure/vulnerability *without conflating the concepts*. (Tier 3; hazard/exposure/vulnerability maps stay separate.)
7. **Reproduce** — provenance, versions, parameters, checksums, exportable settings on everything. (v1.0 standard, extended to the new eras.)

## 3. Scope

### 3.1 In scope (v2.0 core = Tier 1)

- DuckDB-WASM + Parquet data engine over the existing static architecture (CSV loader retained as fallback/first paint), with measured-partition discipline (no first-touch file > ~0.5 MB; `catalog.json` exact-path manifest; no HTTP globbing).
- Era B preserved and extended: monthly refresh pipeline, public status page, currency banner (< 45-day lag target).
- Era C projections module: 24 GCMs, QDM bias correction vs IMD reference (1981–2020), Hargreaves PET on corrected TASMIN/TASMAX, SPI (gamma) + SPEI (log-logistic/L-moments, v1.0 machinery) fitted on the fixed 1981–2020 window, district aggregation, ensemble median + 25–75 % band + agreement layers, model ranking, SSP2-4.5 + SSP5-8.5 (schema ready for SSP1-2.6/SSP3-7.0).
- Era A Atlas integration: ingestion of the verified Atlas release, era-labelled tab, seasonal composites, drought-frequency climatology, category shares, historical events (1918, 1965, 1972, 1987, 2002) identifiable.
- Cross-validation programme: (i) DIE vs IMD 0.25° benchmark study; (ii) Era A ↔ Era B overlap panel (1981–2020), with discrepancies published, not hidden.
- Download portal v2: versioned Parquet + CSV identical to what the dashboard serves, schema documentation, Zenodo DOI, citation line.
- Methodology page v2 documenting every formula, window, threshold and seam (including the PET-method seam between eras).
- Mobile + WCAG 2.1 AA hardening, permalinks, Engine Lab (SQL playground + measurement surface).

### 3.2 Out of scope for v2.0 (deliberately excluded; do not spend early effort)

- Hydrological modelling (VIC/CWatM), observed streamflow/groundwater integration (no public district-month observation source identified — the platform keeps stating that absence rather than simulating it).
- Operational warning, real-time declaration, or any product that substitutes for IMD bulletins.
- Unvalidated prediction claims, chatbots that paraphrase charts, ML without a defined scientific question.
- Arbitrary weighted composite indices as default views (a labelled DIE-CDI analytical layer is Tier 3, only after validation earns trust).
- Global coverage expansion (the engine is region-parameterised, but v2.0 validates India first).
- Large daily multi-model CMIP6 rasters in the browser (precompute; serve products, not raw models).
- Full public API / backend (architecture stays backend-free).

### 3.3 Tier 2 (optional, build after Tier 1) and Tier 3 (future)

Full classification with worth/effort/dependencies in `02-roadmap-milestones.md`. Headlines: tehsil layer (gated on a verified boundary source), ENSO/IOD conditioning, monthly India Drought Brief, Hindi interface, permalinks/embeds, alerts, reservoir/groundwater/crop-exposure overlays, compound drought–heat and flash-drought analysis, risk & vulnerability workspace, story mode.

## 4. Continuity contract with v1.0.0 (must never break)

| v1.0.0 asset | v2.0 treatment |
|---|---|
| Four workspaces + Documentation centre | Preserved as-is; new surfaces added alongside; no redesign of existing tabs |
| `data/metadata.json` contract (single source of truth for thresholds, palettes, availability windows) | Extended (new era/variable blocks), never restructured; per-indicator availability windows already make new data a data change, not a code change |
| Wide CSVs in `data/drought/` | Kept in sync with the Parquet store; remain the fallback loader path |
| Methodology version `research-gee-1.0.2` semantics (gamma/L-moment machinery, fit gates, Gringorten fallback, event rules) | Frozen for era B; **reused, not reimplemented**, for era C computation |
| Event detection + censoring rules | Frozen; era C events use the same machinery with a documented fixed reference window |
| Missing-data policy (never imputed) | Global rule, all eras |
| Area-weighted statistics (LAEA, precomputed district areas) | Global rule, all eras and spatial units |
| Export products with `#` reproducibility headers | Pattern extended to new products (engine queries, Parquet downloads, manifests) |
| Hash routes, responsive layouts, keyboard/ARIA operability | Preserved; new routes added |
| Pipeline commands (`run.py …`, `selftest.py`) | Preserved; new pipelines are siblings (`gcm-pipeline/`, `atlas-pipeline/`), not forks |
| CITATION.cff, Zenodo DOI, MIT licence | Versioned forward (v2.0.0 gets its own DOI + citation line) |

## 5. Non-negotiable scientific principles (apply to every era and feature)

1. Clearly distinguish observations, gridded reconstructions, reanalysis, historical GCM simulations and future projections — in data model, UI labels and documentation.
2. Do not concatenate eras into one unqualified time series; where continuity views exist (e.g. 1901→2100 timeline), era boundaries are drawn and labelled on the chart.
3. Every analytical result traces to source data versions and calculation settings (analysis manifest pattern from v1.0 exports).
4. Uncertainty is quantified where defensible (ensemble spread, agreement, bootstrap CIs) and explicitly not claimed where it is not (empirical recurrence).
5. Statistical safeguards: serial-correlation-aware trend tests; multiple-testing control for district-level maps; sensitivity to reference periods, PET methods and thresholds; sample sizes reported everywhere.
6. Do not infer hydrological drought from rainfall or soil moisture; do not label soil-moisture or vegetation anomalies as streamflow or groundwater drought.
7. Bias correction must be tested to preserve the climate-change signal (QDM design goal); document method, reference, and validation.
8. Keep model-specific distributions visible; never hide disagreement behind an ensemble mean.
9. India is the default focus; the analytical engine does not hard-code Indian administrative units (stable generic `spatial_unit_id` + registries).
10. Report implemented, partially implemented, blocked and deferred features separately (PROGRESS.md vocabulary).

## 6. Definition of Done — DIE v2.0

- [ ] Three eras live: A (1901–2025 or 1901–2021 per verified release), B (1981–2025 → current), C (2026–2100), one schema, era labels always visible, no silent splicing.
- [ ] GCM projections tab: scenario switch (SSP2-4.5/SSP5-8.5), ensemble median + 25–75 % band, agreement layer (exact definitions documented), model ranking panel, SPI–SPEI divergence map.
- [ ] Atlas tab: seasonal composites, frequency climatology, category shares, 1918/1965/1972/1987/2002 identifiable.
- [ ] Cross-validation surfaces: IMD benchmark study published; Era A↔B overlap panel (1981–2020) with event-match and class-agreement statistics.
- [ ] Monthly refresh with public status page and currency banner (lag < 45 days).
- [ ] Methodology page v2: every formula, window, threshold, seam (incl. PET-method seam) documented.
- [ ] Download portal: versioned Parquet + CSV, schema docs, Zenodo DOI, citation line.
- [ ] Mobile + WCAG 2.1 AA pass; permalinks for every view.
- [ ] All queries served via DuckDB-WASM over Parquet (CSV fallback intact); no backend.
- [ ] `selftest.py` passing + extended self-tests for new pipelines; regression baseline green.
- [ ] Total static payload within hosting free tier; mobile first-paint < 3 s on throttled 4G.
- [ ] Preprint/manuscript v2 outline updated; India Drought Brief workflow demonstrated (Tier 2 if not ready).

## 7. Audience and reach

- **Researchers** (primary): defensible, traceable, exportable district-level drought statistics; reproducible projections; stable identifiers.
- **Drought-methods community**: reference implementation of standardisation with fit gates and fallbacks, runs-based detection with censoring, bootstrap lag machinery, era cross-validation.
- **Practitioners/educators** (secondary): zero-install access, honest caveats, plain-language interpretation layers (Tier 2: Monthly Brief, Hindi legends).
