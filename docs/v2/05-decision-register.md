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
| **D6** | **Window discipline (Owner instruction 2026-11-18: "make the validation period similar to GCM, 1981-2014; too much dangling between 1981-2025 / 1981-2020").** Three DISTINCT window roles, never conflated: (1) **Record windows** — what each era actually contains (era A 1901–2025, era B 1981–2025, era C corrected-historical 1981–2014 + ssp 2015–2100): facts, labelled, never spliced (R2). (2) **Standardisation baselines** — era B 1981–2020 (frozen published v1.0 semantics, R1) and era C model own-base 1981–2020 via the AS6 stitch (C2, already computed): NOT changed — a 40-year fit is statistically stronger than 34-year, and changing them would invalidate the published era-B indices and force a full 03–07 Owner re-run for no scientific gain. (3) **Comparison/validation window = 1981–2014** (the GCM-native historical window) — used by ALL cross-era comparisons: the 08 validation gate (already `[1981, 2014]`), `dir_agreement` base (changed from `[1981, 2020]` to `[1981, 2014]` in `config/ensemble.yaml` — scientifically better: the model baseline now comes purely from the observed-forced historical-corrected record; ssp-segment years 2015–2020 are projections and must never sit inside a model baseline), the E14/M9 events baseline (rebuilt as `baseline_1981_2014.json`), the M4 IMD benchmark, and M6.6/E17 cross-validation (era A↔B uses 1981–2014 primary with the full 1981–2025 overlap as sensitivity). Calibration windows (QDM/IMD 1981–2020) remain fitting choices, not comparison windows. Implementation landed BEFORE the Owner's pending step-07/09 re-run, so the pending run picks the new base up with no extra compute |
| **D7** | **Record-extension recomputation (Owner instruction 2026-11-19: "all the data downloaded from 2015-2100 … keep populating the data")** | When a raw record grows, the affected era is **recomputed as one consistent product over the full record and republished atomically**. Partial-record products are **superseded**, never concatenated, and never mixed with full-record products. For era C this is methodologically required rather than a convenience: QDM's τ is the **within-projection-period** non-exceedance probability (Cannon 2015), so extending the SSP record from 2015–2050 to 2015–2100 legitimately revises every ssp-year corrected value; one QDM fit per model–scenario (2015–2100) is therefore the only coherent product. Implementation consequences (2026-11-19): step 02 reuses a stored output **only when its period equals the declared `models.yaml` window** (the period is part of the reuse contract — a shorter output is recomputed); superseded period files are removed from the stage by `gcm-pipeline/prune_stale_periods.py` before the next stage consumes them (downstream steps discover inputs by glob); step 09 replaces the published partition tree wholesale, so no orphan partition survives; the revision is recorded in PROGRESS.md + manuscript and the regression baseline is re-blessed after review |
| **D8** | **Era-B naming (Owner initiative 2026-11-19: "we should not say CHIRPS/ERA5-Land SPI/SPEI, 1981–2025 as observed"; Owner proposed "Multi-Source Blended Dataset" or "Gridded Multi-Source Product"; **Owner-confirmed 2026-11-20: "Gridded Multi-Source Product (1981–2025)"**) | Era B must not be labelled simply "observed": CHIRPS is a satellite–gauge blend and ERA5-Land is reanalysis — observation-**based** gridded products, not in-situ observations (R2 precision). **"Blended" is REJECTED** (R3): the three sources are NOT merged into one field — CHIRPS drives the SPI/SPEI precipitation side, ERA5-Land drives PET and SMA, MODIS drives VCI — so a "blend" label would claim a merge that did not happen. **COMMITTED WORDING: "Gridded Multi-Source Product (1981–2025)"**, with per-indicator source attribution kept in tooltips/metadata/methodology. Applied 2026-11-20: `catalog.json` era label (regenerated via the publish path after the bare generator was found to rebuild from scratch — a real footgun, now recorded), footer period line, `#projections`/`#summary` copy and caveats; QC-context uses of "observation(s)" (valid-value counts, "observation date" scrubber, absence-of-streamflow guardrails) deliberately stay. R1 note: the v1.0 "Observations" wording was published behaviour — this is a documented revision, never a silent edit; the manuscript era-naming statements are updated in the same revision |

**Amendment cross-references (Owner memo docs/v2/06, 2026-11-15):** E14 extends the D1/D4 projections module with event analytics (Tier-1 confirmation = OD9); E16 is a sensitivity study *under* C3, never a replacement; O13 is a sensitivity run *under* D (IMD primary unchanged); E18/O14/O15 are analytical layers under safeguard rules (association ≠ causation; definitions registered before shipping). Task amendments: M2.1 `genealogy:` field (family-collapsed agreement display), M2.11 tail checks (Q–Q + p90/p95 by region/season), M2.9 sub-pixel transparency list (≤ 2 grid cells flagged + CSV), M4.3 FDR view mandatory. Backlog promotions: O02, O03 → Tier 1; F08 superseded by E18; O07 → O15. Process amendments: CI gate, per-era Zenodo deposits (software DOI stays one deposit), README freshness badge, `scripts/reproduce_figures.py`.

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

**C5 note — direction-of-change agreement (F10, implemented 2026-11-18).**
`dir_agreement_drier` is the per-district **fraction of models whose
future-window mean z is lower (drier) than that same model's own base mean**.
The base is `[1981, 2014]` (register D6 — the GCM-native historical window)
of the **AS6-stitched** series (historical-corrected 1981–2014 + ssp 2015–…),
never the ssp segment alone; a model missing either window leaves both
numerator and denominator, and the companion `dir_agreement_n` records the
exact denominator. **Effective-window rule** (declared in
`gcm-pipeline/config/ensemble.yaml`, recorded verbatim in the NC attrs →
export manifest → `metadata.json` → UI): the overlap of the configured
`[2081, 2100]` with the record when it holds ≥ `dir_agreement_min_window_years`
(10) distinct years, otherwise the **latest 10 years available** (2041–2050
while the record ended at 2050) — an explicit, labelled record-end
truncation, never a silent shortening; a record shorter than 10 years emits no
statistic. **Since the full 2015–2100 record landed (2026-11-19) the effective
window is the configured 2081–2100.** The statistic is **window-constant** per
district and is presented as a **model count, never a probability** (R9).

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
| OD1 | Final 24-model list (`gcm-pipeline/config/models.yaml`) | **RESOLVED 2026-11-18:** the Owner's genealogy memo (`Geneology.md`) enumerates the full 24-model set and confirms the lineage groupings; `genealogy:` filled (5 families × 2 + 14 singletons, sources cited), `meta.status: owner-confirmed-2026-11-18`. Gate-pooling semantics (review F3) remain an open methodology decision — genealogy is display/report metadata until a documented gate re-basing is signed off |
| OD2 | Era C start year (2026 vs 2022) | 2026 |
| OD3 | IMD temperature product (resolution/version) for the QDM reference | Verify current IMD product at M4.1; regrid to 0.25° regardless |
| OD4 | Atlas v2 release verification (licence, variables, timescales, units) | **RESOLVED 2026-11-18 (M6.1 source gate PASS, 30 checks / 9 notes):** landed archive `D:/Websites/die-data/DroughtAtlas_v2` verified by `atlas-pipeline/00_verify_atlas.py` against `atlas-pipeline/config/atlas.yaml`. Facts: DOI 10.5281/zenodo.20368514, v2, CC-BY-4.0 (Zenodo page only — no LICENCE file ships), SPEI-**1/4/12 only** (no 3/6), 0.05° grid split across TWO disjoint sibling `Gridded_SPEI` folders (115,394 cells, both needed), 1901-01..2025-12 (1,500 months), NaN tokens never imputed. Fabric deltas: 742 district polygons / 732 series / 731 coded LGD codes + 11 DISPUTED no-LGD polygons; 4,723 taluka polygons / 4,639 series; readme is stale (claims 1901–2020 + PNG atlas; files say otherwise). **Ingestion route (Owner delegated the district choice 2026-11-18, decision recorded):** geometric area-weighted aggregation of the 0.05° grid onto the **724-district v1.0 fabric** (same zonal semantics as era B §1) — the Atlas's own district/taluka/state series are QA/cross-check only. **District count decision: 724, not the Atlas's 742** (R1 continuity: every era-B product, the area registry, boundaries and UI are keyed to the 724 fabric; the Atlas's 742 include 11 DISPUTED polygons and 10 series-less polygons, its names are corrupted and its LGD codes are not a bijection — it is not a usable superset, and mapping era A onto it would make era A incomparable with eras B/C district-by-district) |
| OD5 | Tehsil geometry source + licence | Tehsil layer stays Tier 2/gated |
| OD6 | Hosting at scale (GitHub Pages vs Cloudflare R2) | GitHub Pages until payload/traffic forces R2 |
| OD7 | CMIP6 download route (ESGF vs Google/Pangeo cloud) | **Resolved 2026-11-13: Route A — raw CMIP6 + own QDM** (PROGRESS.md §8, session-2 additions) |
| OD8 | v2.0 release timing | Data-gated, not date-gated |
| OD9 | **E14 Tier-1 confirmation** (owner amendment 06 §1): future drought event analytics as the fourth `#projections` view | **RESOLVED 2026-11-18:** Owner confirmed via the session instruction "complete m5.4 to m5.8" (recorded PROGRESS.md §6); M5.8 shipped on validated era-C medians vs the observed 1981–2020 baseline — never fixtures (R3) |
| OD10 | **E16 Penman–Monteith variant definition** (inputs `huss`/`rlds`/`sfcWind`): exact formulation + which models supply them | Availability-checked in 01_inventory_check.py; runs only where supplied; committed default (C3 Hargreaves) unchanged |
| OD11 | **E18 flash-drought definition** (Ford/Otkin-style rapid-intensification rate) and compound drought–heat joint-extreme definition | One definition picked and registered before any map ships; absorbs F08 |

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
