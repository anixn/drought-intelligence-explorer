# DIE v2.0 — Decision Register

*Doc 5 of the v2.0 suite. Records every committed decision, every conflict between the planning documents and its resolution, every open decision awaiting the Owner, and the standing scientific safeguards. **OpenCode must read this before making any methodological choice, and append to it (via PROGRESS.md → decisions) whenever a new decision or assumption is made.** Decisions are marked: COMMITTED / RESOLVED / OPEN (owner input needed) / PROVISIONAL (default adopted, revisit at gate).*

---

## 1. Strategic decisions (D1–D5, committed in the v2.0 planning round)

| ID | Decision | Committed choice |
|---|---|---|
| **D1** | Role of the 24-GCM archive | **Full projections module** — QDM bias correction, ensembles, new `#projections` tab |
| **D2** | Observed-record backbone | **Atlas era join** — Era A 1901–2025 (pending release verification), Era B 1981–2025, cross-validation at overlap; never one spliced series |
| **D3** | Freshness | **Monthly automated refresh** + public status page + currency banner (lag < 45 days target) |
| **D4** | Scenarios & uncertainty | **SSP2-4.5 + SSP5-8.5** at launch with median + 25–75 % band + agreement layers; schema ready for SSP1-2.6 / SSP3-7.0 |
| **D5** | Open-science posture | **Versioned download portal** + Zenodo DOI + citation line in UI |

## 2. Method choices (C1–C7) — with v1.0-continuity resolutions

| # | Choice | Committed default | Continuity note |
|---|---|---|---|
| **C1** | Bias correction | **QDM** (Cannon et al. 2015), monthly, per grid cell, per calendar month | Preserves the change signal; mandatory identity/trend-preservation tests (docs/v2/03 §3.5) |
| **C2** | Calibration window | **Fixed 1981–2020 distributions**; future mapped onto them; era C values bounded **[−5, +5]** with clip counts reported | Matches era B's fixed-window discipline (era B QA bound stays ±4 for the released record — registered difference, see §4 conflict K) |
| **C3** | PET formula | **Hargreaves** on corrected TASMIN/TASMAX, applied identically to reference and model data | Era B keeps ERA5-Land model PET (frozen); the PET seam between eras is documented, never bridged silently |
| **C4** | SPEI distribution | **Log-logistic, L-moment estimator** (v1.0 machinery); Gringorten plotting-position fallback for the whole series where fits fail | The earlier suggestion of a GEV fallback is an **optional sensitivity variant only** — v1.0's audited fallback wins for continuity |
| **C5** | Ensemble treatment | **n-model median + p25/p75 + agreement layers** (exact definitions in docs/v2/03 §3.7); multi-metric model ranking vs observed 1981–2014; best-performing subset (8–12) selectable; per-model outputs inspectable | Never show a single model; never hide disagreement behind a mean |
| **C6** | Scenarios | **SSP2-4.5 + SSP5-8.5** (D4); schema accommodates more | — |
| **C7** | Target grid | **0.25°** — conservative remap for precipitation, bilinear for temperature; district aggregation after bias correction | NEX-GDDP-style practice |

## 3. Architecture decisions (locked — measured, not argued)

| Layer | Choice |
|---|---|
| Storage | Parquet (zstd, dictionary-encoded, **long format**) |
| Compute | DuckDB-WASM 1.32.0 in a Web Worker |
| Transport | HTTP Range over static files; `catalog.json` exact-path manifest; no HTTP globbing |
| Geometry | PMTiles (districts now; tehsils when gated source verified) |
| Rendering | Leaflet (≤ 724 polys); deck.gl/MapLibre trigger points (docs/v2/04 §7) |
| Charts | Plotly (vendored); `scattergl`/UPlot for 200-year series |
| Fallback | v1.0 CSV loader stays permanent |
| Processing | Python (continuity with v1.0 `data-pipeline/`); R equivalents documented where the Owner prefers R |
| Hosting | GitHub Pages → Cloudflare R2 at scale; $0 target |

## 4. Cross-document conflicts and resolutions

The four planning inputs (build specification, implementation specification, workplan, references catalogue) disagree in places. Each conflict was arbitrated — the resolution below is binding unless the Owner reopens it:

| # | Conflict | Resolution |
|---|---|---|
| **A** | Number of eras: 3 (spec) vs 4 (workplan: + reanalysis bridge) | **Four-era schema, era D optional/Tier 3.** The unified long format costs nothing extra; the bridge is never built in v2.0 core |
| **B** | Era C start year: 2022 (spec) vs 2026 (workplan) | **2026–2100 default** (clean seam at the observed record end 2025-12). 2022–2100 with explicit overlap handling remains a documented alternative — OPEN for Owner confirmation |
| **C** | Era A span: 1901–2021 (spec + workplan) vs 1901–2025 (references: Atlas v2) | **1901–2025 if Atlas v2 verifies** (DOI 10.5281/zenodo.20368514); fallback 1901–2021 (v1). Era years live in `catalog.json`, so this is a data decision, not code |
| **D** | Bias-correction reference: CHIRPS/ERA5-Land (spec C1) vs IMD (Owner instruction) | **IMD primary** (Owner instruction — independent, station-interpolated national reference); CHIRPS/ERA5-Land retained as alternates and cross-checks. Both can be run and compared in validation |
| **E** | PET: single formula (spec C3 Hargreaves) vs era-specific (v1.0 uses ERA5-Land PET) | **Per era:** era B frozen with ERA5-Land PET; era C uses Hargreaves applied identically to reference and model. Seam documented in methodology v2 + cross-validation panel |
| **F** | SPEI fallback: GEV (spec C4) vs Gringorten (v1.0) | **Gringorten (v1.0 continuity); GEV = optional sensitivity variant** |
| **G** | Value bounds: ±4 (v1.0 release gate) vs [−5, +5] (spec C2) | **Per era:** era B ±4 unchanged (released record); era C [−5, +5] with clip counts reported (late-century ensembles legitimately exceed ±4) |
| **H** | Workspace count: 5 (impl. spec) vs 8 (spec) vs 9 (workplan prototype) vs 4 existing tabs (v1.0) | **Evolve, don't redesign:** the four v1.0 tabs are preserved; new surfaces are added (`#engine`, `#projections`, `#atlas`, `#crossval`, optional `#brief`) per docs/v2/04 §1. Documentation stays a secondary control |
| **I** | Tehsil layer: spec wants it (F06) vs manuscript's deliberate deferral pending a maintained geometry source | **District-first; tehsil gated** on a verified, licensed tehsil geometry source (registered check, M6.7) |
| **J** | Processing language: R-first (impl. spec) vs Python (v1.0 pipeline + workplan scripts) | **Python primary** (reuses audited `indicators.py`, `selftest.py`, `config.yaml`); R package equivalents documented in the runbooks for methods the Owner may run in R. The framework is language-agnostic at the interface level |
| **K** | Bound ±4 vs [−5, +5] (see C2) | Same as G — per era, registered |
| **L** | Ensemble storage: per-model partitions vs pre-averaged groups only | **Both:** ensemble stat partitions ship publicly; per-model district series retained in `work/` (optionally shipped) so model detail stays inspectable |
| **M** | Era B end-year drift with monthly refresh vs static era definitions | Era years in `catalog.json`/`metadata.json` are updated by the refresh run; era labels always show actual coverage ("1981–2025 → current") |

## 5. Open decisions (Owner input needed — tracked in PROGRESS.md)

| ID | Decision | Default until resolved |
|---|---|---|
| OD1 | Final 24-model list (`gcm-pipeline/config/models.yaml`) | Selection criteria + inventory checker shipped; nothing runs until filled |
| OD2 | Era C start year (2026 vs 2022) | 2026 |
| OD3 | IMD temperature product (resolution/version) for the QDM reference | Verify current IMD product at M4.1; regrid to 0.25° regardless |
| OD4 | Atlas v2 release verification (licence, variables, timescales, units) | Blocked until verified; era A tab cannot ship before |
| OD5 | Tehsil geometry source + licence | Tehsil layer stays Tier 2/gated |
| OD6 | Hosting at scale (GitHub Pages vs Cloudflare R2) | GitHub Pages until payload/traffic forces R2 |
| OD7 | CMIP6 download route (ESGF vs Google/Pangeo cloud) | Owner choice; both scripted |
| OD8 | v2.0 release timing | Data-gated, not date-gated |

## 6. CMIP6 module release gate (the projections tab is not "research-ready" until)

- [ ] Source dataset verified (models.yaml filled, inventory check green)
- [ ] GCM/scenario availability documented
- [ ] Historical model evaluation complete (`08_validate_gcm.py` report)
- [ ] PET and index-calculation methods documented (methodology v2)
- [ ] Bias correction justified and tested (identity + trend-preservation tests green)
- [ ] Model spread and agreement available (exact definitions published)
- [ ] Historical and future periods not misrepresented as observations (era labels + banners)
- [ ] At least one independent reproducibility check completed
- [ ] `selftest_gcm.py` green; regression baseline green

## 7. Standing scientific safeguards (apply to every era and feature)

1. Drought definitions, event rules, censoring, missing-data handling and sensitivity panels are inherited from v1.0 **unchanged** unless a documented scientific reason is registered here first.
2. Correlation, lagged association and (future) ML feature importance never establish causal propagation; streamflow/groundwater claims require streamflow/groundwater observations — none exist in the record, and the platform keeps saying so.
3. District-level trend maps stay labelled exploratory until multiple-testing control ships (O03); FDR demo numbers (382 → 324 of 724, q = 0.05) are the published evidence of scale.
4. Recurrence statistics remain empirical point estimates without fitted distributions — labelled indicative.
5. Hazard, exposure and vulnerability stay separate concepts (Tier 3 risk workspace must show them as separate maps before any combination).
6. Composite indices and ML are clearly-flagged analytical layers, never defaults; ML requires spatially blocked validation and temporally separated testing with transparent baselines.
7. Boundary vintages: the 2011-era fabric is pinned; comparisons across vintages require a documented crosswalk (none exists — so none is attempted).
8. Every automated interpretation is descriptive, rule-based, and labelled as such; no LLM-generated narrative findings in the product.
9. Every dataset entry carries: identifier, citation, provider/URL, licence + redistribution terms, version + retrieval date, variables/units, resolution, coverage, CRS/grid, quality flags, processing steps, known limitations (manifest pattern from v1.0 extended).
10. Do not cite a search result or a secondary dashboard as the sole source for a dataset; cite the dataset paper or official release, with DOI and retrieval date.

## 8. Assumptions log (verify before relying on them)

| # | Assumption | Verification owner / gate |
|---|---|---|
| AS1 | Atlas v2 (1901–2025) exists at DOI 10.5281/zenodo.20368514 and is CC-BY | Owner, M6.1 gate |
| AS2 | The Owner's `work/die-2.0/` prototype (ducklab.js, convert_to_parquet.py) is available as reference | OpenCode at M1.6 (rebuild if absent — workplan contains the specs) |
| AS3 | IMD 0.25° daily rainfall is obtainable for 1981–2020+ | Owner, M4.1 |
| AS4 | 24 CMIP6 models with daily pr/tasmax/tasmin exist for historical + ssp245 + ssp585 | Owner fills models.yaml; inventory check proves it |
| AS5 | GitHub Pages serves HTTP Range (or R2 used at scale) | M1.5 catalog check (`curl -I` every file) |
| AS6 | QDM reference window 1981–2020 works with combined model historical (1981–2014) + ssp (2015–2020) baselines | Standard practice; confirmed in validation |

---

*Any decision not covered here defaults to: preserve v1.0.0 behaviour; label eras honestly; publish limitations. When in doubt, choose the option that is more conservative scientifically and record it as PROVISIONAL.*
