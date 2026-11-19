# DIE v2.0 — Roadmap, Feature Backlog and Milestones

*Doc 2 of the v2.0 suite. Defines the full feature inventory, priority tiers, dependency-based development sequence, and per-milestone exit gates. OpenCode executes **one task per session**, updating `PROGRESS.md` each time. Milestone targets are suggestions aligned to the Dec 2026 – May 2027 build window; data-availability gates (Owner-executed compute) dominate the schedule.*

---

## 1. Priority framework

Tiers inherit the committed decision matrix (D1–D5) and the worth/effort scoring from the v2.0 specification:

- **Tier 1 — Essential (v2.0 core).** Must ship for the v2.0 release. Blocking dependencies handled by fixtures and gates (see §3).
- **Tier 2 — Optional (post-core hardening and reach).** Build after Tier 1 is verified; may slip past the release without hurting the definition of done.
- **Tier 3 — Future (v2.x / v3.0 backlog).** Documented so the schema accommodates them, but explicitly not scheduled.

Every feature carries: ID, tier, worth (1–5), effort (S/M/L), dependencies, and where it is specified (docs pointer).

## 2. Feature backlog

### 2.1 Tier 1 — Essential

| ID | Feature | Worth | Effort | Depends on | Spec |
|---|---|---|---|---|---|
| E01 | Parquet + DuckDB-WASM data engine (era B migration), Engine Lab, catalog.json | 5 | M | — | 03 §1, 04 §3 |
| E02 | Numeric regression harness (v1.0 behaviour protection) | 5 | S | E01 | 03 §7 |
| E03 | Monthly refresh pipeline + public status page + currency banner (< 45-day lag) | 5 | S–M | — (Owner runs GEE monthly) | 03 §1.4 |
| E04 | GCM processing framework (era C code, configs, synthetic self-test, runbook — Owner executes) | 5 | L | — | 03 §3 |
| E05 | Future Projections workspace (era C): scenario switch, ensemble median + 25–75 % band, agreement layer, model ranking, SPI–SPEI divergence map, projection banner | 5 | L | E04 output (fixtures for UI build) | 04 §4.2 |
| E06 | Era A Atlas integration (district level first): era-labelled tab, seasonal composites, frequency climatology, category shares, historical-event anchoring | 5 | M | Atlas v2 verification (Owner gate) | 03 §2 |
| E07 | Era A ↔ Era B cross-validation panel (1981–2020 overlap) | 4 | S | E06 | 03 §6 |
| E08 | IMD benchmark validation study (framework + memo + methodology v2 section) | 4 | M | IMD data (Owner) | 03 §5 |
| E09 | Methodology page v2 (every formula, window, threshold, seam; incl. PET-method seam) | 5 | S | E04, E06, E08 content | 04 §5 |
| E10 | Download portal v2 (versioned Parquet + CSV, schema docs, CITATION.cff, checksums) | 5 | S | E01, E04, E06 | 04 §6 |
| E11 | Zenodo v2.0.0 deposit + DOI + citation line | 5 | S | E10, release gate | 04 §6 |
| E12 | Mobile + WCAG 2.1 AA pass, permalink hardening, Engine Lab polish | 4 | S–M | — | 04 §7 |
| E13 | Global era toggle + era banners + no-splice rules | 5 | S | E05/E06 surfaces | 04 §2 |

### 2.2 Tier 2 — Optional (post-core)

| ID | Feature | Worth | Effort | Depends on | Note |
|---|---|---|---|---|---|
| O01 | Tehsil (≈4,590-unit) layer for era A | 4 | M | E06 + **verified tehsil geometry source** (licence!) | v1.0 manuscript deliberately deferred sub-district units until a maintained geometry source exists — keep that gate |
| O02 | Change-point detection (Pettitt) alongside trend tests | 4 | S | — | v1.0 roadmap item; client-side, low cost |
| O03 | Benjamini–Hochberg FDR view in district trend maps | 4 | S | — | Demo already in v1.0 Technical Validation (382 → 324 of 724 at q = 0.05) |
| O04 | Monthly India Drought Brief (auto-generated, plain language) | 4 | S | E03 | National pre-aggregate + latest month |
| O05 | Hindi legends + bilingual brief | 3 | S–M | O04 | i18n of static front end |
| O06 | Permalinks for every view + embeddable widgets | 3 | S | — | URL-param serialisation of analysis state |
| O07 | ENSO / IOD conditioning of drought risk (ONI + DMI association panels) | 3 | M | index data | Association only; never causal |
| O08 | Alerts / subscription (district crosses class) | 3 | S–M | E03 | Static-host constraint: email via third party; keep minimal or defer |
| O09 | Standardised soil-moisture index (z-score SMI switch) | 3 | S | — | Config switch exists in v1.0; class-table remap required |
| O10 | Thickness-weighted root-zone SMA sensitivity study (7/21/72 cm) | 3 | S | Owner GEE rerun | v1.0 roadmap item |
| O11 | Fixed 2001–2020 VCI baseline alternative | 3 | S | Owner GEE rerun | Release-frozen baseline remains default |
| O12 | SEAS5/C3S seasonal outlook overlay | 3 | M | data verification | Analysis-only, never operational warning |

### 2.3 Tier 3 — Future backlog (schema accommodates, not scheduled)

| ID | Feature | Worth | Note |
|---|---|---|---|
| F01 | Hydrological drought layer (GloFAS runoff → SRI/SSI, clearly labelled modelled) | 4 | Licence check; distinguish from observed flow |
| F02 | Reservoir storage integration (CWC) | 4 | PDF-parsing cost; verify access conditions |
| F03 | Groundwater (CGWB levels) | 3 | Access/completeness constraints |
| F04 | Crop exposure overlay (ICRISAT/DES calendars + yields) | 4 | Sowing-window framing |
| F05 | Population/livestock exposure (Census/WorldPop) | 3 | People-in-drought statistics |
| F06 | Drought Risk & Vulnerability workspace (hazard/exposure/vulnerability kept separate) | 4 | Implementation-spec Workspace 5; only with documented normalisation/weighting and sensitivity tests |
| F07 | Composite DIE-CDI analytical layer | 3 | Only after validation earns trust; clearly flagged, never default |
| F08 | Compound drought–heat events + flash drought detection | 4 | Documented rapid-intensification definition required |
| F09 | S2S outlook links (IMD ERFS / IRI) | 3 | Data-agreement dependent |
| F10 | Story-mode guided tours (e.g. 2002 drought) | 2 | Animation engine exists |
| F11 | Era D reanalysis bridge (ERA5-Land 1940/1950–2025 SMA/PET context) | 3 | Workplan era D; context only, never spliced |
| F12 | Explainable ML for drought drivers | 3 | Spatially blocked validation, temporal separation, transparent baselines; only for well-posed questions |
| F13 | Other-region redeployment of the same contract | 3 | Pipeline is region-parameterised by design |
| F14 | Non-stationary return periods | 3 | Sample-size and diagnostics gate |

### 2.4 Owner-amendment backlog (docs/v2/06-amendments.md, 2026-11-15)

Added by the Owner's amendments memo; tracked with the same one-task-per-session discipline. Items marked **[Owner]** need sign-off before they enter the build order.

| ID | Feature | Tier | Worth | Effort | Depends on | Spec notes |
|---|---|---|---|---|---|---|
| E14 | Future drought event analytics (era C): frozen v1.0 event machinery over validated era C products; frequency/duration/severity per window (2026–2040 / 2041–2060 / 2081–2100) vs observed baseline per district (**1981–2014** per register D6, supersedes the original 1981–2020 wording; shipped as `baseline_1981_2014.json`); fourth view in `#projections` | 1 (candidate, **[Owner: confirm]** — OD9) | 5 | M | E05 real data | Reuses event machinery; never run on fixtures for public numbers; ensemble-median-based windows with agreement reported alongside |
| E15 | People-in-drought, static exposure: projected drought-month counts × Census/WorldPop population ("X million people in moderate-or-worse drought months per year by 2050/2100") | 2 | 4 | S | E05; population grid verified (licence) | Static exposure only; hazard and exposure never conflated (register safeguard 5); minimal version of F05 promoted forward |
| E16 | PET-method sensitivity study: Hargreaves (committed C3) vs ERA5-Land PET vs a Penman–Monteith variant (`huss`, `rlds`, `sfcWind` — availability-checked in 01_inventory_check.py; run only where supplied) on 1981–2020, best-subset models; validation-study memo + methodology v2 uncertainty statement quantifying the era B↔C PET seam | 2 **[Owner: compute]** | 4 | M | M2 framework; IMD/ERA5-Land reference | Never changes the committed default (C3); sensitivity only — OD10 |
| E17 | Era B ↔ era C cross-validation panel: corrected-model-historical (1981–2014) vs observed era B over the overlap, symmetric to the Atlas↔Observed panel (r, bias, class agreement, event match, discrepancy map) | **1** (X5) | 4 | S | M2.8 outputs | Reuses crossval schema; add `era` column or second partition file; the 2025/2026 seam gets the same treatment as the 1901/1981 seam |
| E18 | Flash drought + compound drought–heat detection (era B first, era C if it holds up). Flash: one documented rapid-intensification definition picked and registered (Ford/Otkin-style). Compound: joint SPI/SPEI + Tmax extremes same month, lag-0 dependence noted | 2 | 4 | M | — | Definition fixed in code + methodology page before any map ships — OD11; absorbs Tier 3 F08 |
| O13 | Alternate-reference QDM sensitivity product: QDM chain with CHIRPS/ERA5-Land reference (register D) alongside IMD-primary; divergence as downloadable sensitivity product + methodology paragraph | 2 **[Owner: compute]** | 3 | M (Owner) | M2 chain | Schema unchanged; `reference_id` column or parallel partition root |
| O14 | Standardisation-baseline sensitivity for era C: fixed 1981–2020 (C2) vs rolling/era-specific baseline on a subset — separates climate signal from baseline-definition effect | 3 | 3 | S | E14 optional | One memo section; not a UI default |
| O15 | ENSO/IOD conditioning panels (existing O07 promoted): ONI + DMI association with district drought frequency; association only, never causal; JJAS-conditioned composites | 2 | 3 | M | index data verified | Keep out of any projection claim |
| E19 | **`#summary` tab (Owner request 2026-11-18): "how drought changes from now to 2100"** — ensemble-vs-observed shift per district on the **1981–2014 baseline (register D6)**: drought-frequency/duration/severity change (era C windows vs observed baseline), share of models agreeing on drying (`dir_agreement_drier`), area share in moderate-or-worse drought, per-state summary table, scenario toggle (SSP2-4.5 / SSP5-8.5) | 1 (candidate) | 5 | M | era C 2051–2100 download (Owner, **complete 2026-11-19**); E14 event machinery; M5.4 agreement layer | New hash `#summary` (R8); era labels + honest ensemble n (X3); agreement-first default (X2); numbers only from validated era C products past the §6 release gate — never fixtures (R3). Proposed in M8 below |

**Promotions within the existing backlog (amendment memo §1):**

- **O02 (Pettitt change-point) → Tier 1.** Wire into the Historical tab trend view next to Mann–Kendall; client-side, S effort.
- **O03 (BH-FDR view) → Tier 1.** District trend maps ship with the q = 0.05 FDR view as default-adjacent toggle (v1.0 demo: 382 → 324 of 724). Reviewers will not accept uncorrected district trend maps.
- **F08 → superseded by E18** (register marks it; definition gate moves to OD11).
- **O07 → O15** (same feature, promoted forward from Tier 2 to the amendment backlog).

**Process amendments (OpenCode-executable, memo §3):** CI workflow gating `selftest.py` + regression harness (once M1.9 lands) + `selftest_gcm.py`/`selftest_atlas.py` (once they exist); separate versioned Zenodo deposits per era dataset (software DOI stays one deposit; mapping recorded in register + CITATION.cff); README freshness badge rendering `data/status.json`; `scripts/reproduce_figures.py` closing the data↔paper loop before M7. Scheduled: CI at M1.9, badge at M3.2, DOI mapping at M7.2, figure script at M7.4.

## 3. Milestone plan (dependency-based)

Ordering logic: **engine + regression protection first** (nothing is built on a moving foundation); **GCM framework handed to the Owner as early as possible** (their downloads are the long pole and can run in parallel with UI work); freshness next (credibility); validation studies before projections UI ships real numbers; Atlas and release last. Milestones map onto the Dec 2026 – May 2027 window from the committed plan, with dates as suggestions only.

### M0 — Documentation and decision register ✅ (complete — 2026-11-12)
- Output: this documentation suite; decision register with all cross-document conflicts resolved; PROGRESS.md initialised.
- Exit gate: Owner reviews and installs the suite into the repo (`AGENTS.md`, `PROGRESS.md` → root; `docs/01–05` → `docs/v2/`).

### M1 — Foundation: engine, era-B Parquet, regression harness
*Suggested: Nov–Dec 2026. Depends on: nothing. Owner actions: none.*

| Task | Content | Size | Gate |
|---|---|---|---|
| M1.1 | Install docs, create `v2-dev` branch from `master` (tag `v2-base`), repo audit notes → PROGRESS.md | S | audit recorded; all v1.0 tabs verified working on branch |
| M1.2 | Directory skeleton per AGENTS.md §5 (`data/parquet`, `data/geo`, `data/fixtures`, `scripts/`, `gcm-pipeline/`, `atlas-pipeline/`, `validation-studies/`, `server.py`) | S | tree matches spec |
| M1.3 | `scripts/convert_to_parquet.py` — era B wide CSVs → long Parquet (zstd, dictionary-encoded, row groups aligned to 60 districts); print per-variable rows/sizes | M | total ≤ ~30 MB era B; per-file ≤ ~600 KB |
| M1.4 | Round-trip verification: ≥ 5 random cells per variable, exact match vs CSV | S | 100 % match, logged |
| M1.5 | `catalog.json` generator + schema doc (`docs/v2/03 section 8.2`) | S | all paths resolve HTTP 200 via `server.py` |
| M1.6 | `assets/js/ducklab.js` engine service (worker blob + byte interceptor + settings) — reuse `work/die-2.0` prototype if present | M | init < 8 s; district slice < 100 ms cold; repeat 0 KB |
| M1.7 | Engine Lab tab `#engine` (status, SQL box, byte/time readouts) | S | zero console errors across all tabs |
| M1.8 | Wire Historical tab to engine behind `?engine=1` flag (CSV loader default); numbers must match CSV path exactly | M | identical values on ≥ 3 spot checks |
| M1.9 | Numeric regression harness: snapshot regional summaries + catalogue entries; comparison script wired into verification | S | baseline green |
| M1.10 | Pre-aggregates: `_national_monthly.parquet` (area-weighted) | S | matches v1.0 area-weighted rule within 1e-6 |

**Exit gate M1:** all four v1.0 workspaces + docs centre behave exactly as v1.0.0 (regression harness green); engine passes Q1/Q2/Q3 checks; CSV fallback intact; mobile pass.

### M2 — GCM framework handoff (era C code ready for Owner compute)
*Suggested: Dec 2026, overlapping M1 tail. Depends on: nothing from M1 except repo skeleton. **This is the critical-path handoff — the Owner's downloads start here and run for weeks.***

| Task | Content | Size | Gate |
|---|---|---|---|
| M2.1 | `gcm-pipeline/config/models.yaml` template + selection criteria (daily pr/tasmax/tasmin, historical + ssp245 + ssp585, documented variant, 1950–2100 coverage); **amendment (06 §2): per-model `genealogy:` field (CMIP6 parent/institution family) so agreement fractions can be reported family-collapsed — ranking stays model-level, genealogy view is display-only** | S | Owner fills final 24-model list (Owner action) |
| M2.2 | `config/reference.yaml` — IMD primary reference (0.25° rainfall; temperature product per Owner choice), CHIRPS/ERA5-Land alternates; grid spec 0.25° | S | decision recorded in register |
| M2.3 | `00_download_cmip6.py` — ESGF/Pangeo-Google subsetting per model/scenario/var, resumable, manifest + SHA-256 | M | dry-run on one model var verified |
| M2.4 | `01_inventory_check.py` — availability matrix (model × var × scenario × period × calendar), fails hard on gaps | S | runs on template list |
| M2.5 | `02_regrid_025.py` — conservative remap (pr), bilinear (tasmin/tasmax) to common 0.25° grid | M | conservation test: domain-mean precip preserved within tolerance |
| M2.6 | `03_qdm_bias_correct.py` — QDM vs reference (1981–2020), per calendar month; multiplicative for precip (zero-guard), additive for temperature; preserve-change diagnostics | L | synthetic-world test: known signal preserved; quantile mapping inverts correctly |
| M2.7 | `04_pet_hargreaves.py` — Hargreaves PET on corrected tasmin/tasmax (FAO-56 Ra by latitude/day-of-year); mm/month | S | spot-check against published worked example |
| M2.8 | `05_spi_spei_compute.py` — **reuse `data-pipeline/indicators.py` machinery**; fits on fixed 1981–2020; bounds [−5, +5] for era C; per-fit gates as v1.0 | M | base-period calibration gates pass on synthetic world |
| M2.9 | `06_district_aggregate.py` — area-weighted aggregation to 724 districts; v1.0 buffer-fallback semantics for sub-pixel units; LAEA areas reused; **amendment (06 §2): sub-pixel transparency list — every district whose aggregation rests on ≤ 2 grid cells published as a `flag` value + downloadable CSV so users can filter them out** | M | national totals plausible; sub-pixel flags match v1.0 handling |
| M2.10 | `07_ensemble_stats.py` — median/p25/p75, agreement (≤ −1.0, ≤ −1.5 fractions), direction-of-change agreement (late-window vs reference mean), n_models | S | exact definitions verified on synthetic ensemble |
| M2.11 | `08_validate_gcm.py` — validation gate: corrected-historical consistency vs reference; drought frequency/duration/severity vs observed 1981–2014 by region; model ranking (multi-metric); best-subset 8–12 models; SPI–SPEI divergence quantification; **amendment (06 §2): tail checks — Q–Q comparison of corrected-historical vs reference plus p90/p95 drought-tail statistics by region/season; gate fails on declared tail tolerance breach (means can pass while tails fail)**; non-zero exit on failure | M | gate logic proven on synthetic world |
| M2.12 | `09_export_parquet.py` — era C partitions (scenario × stat × variable × year), ≤ ~0.5 MB per file; catalog update; manifest checksums | M | catalog integration test |
| M2.13 | `gcm-pipeline/selftest_gcm.py` — synthetic 3-model × 2-scenario mini-world end-to-end; seed-deterministic | M | all assertions pass |
| M2.14 | `gcm-pipeline/README.md` runbook for the Owner: env setup (conda/requirements), execution order, checkpointing, storage estimates, where outputs land, what gets recorded in PROGRESS.md | S | Owner can start downloads without further code work |

**Exit gate M2:** synthetic self-test passes end-to-end; runbook delivered; Owner confirms download start (recorded in PROGRESS.md). **No real-era-C numbers exist yet — UI builds against fixtures.**

### M3 — Freshness: monthly refresh + status page (E03)
*Suggested: Dec 2026–Jan 2027. Depends on: M1 (parquet pipeline). Owner actions: monthly GEE run from Jan 2027 onward.*

| Task | Content | Gate |
|---|---|---|
| M3.1 | Monthly-increment mode for `data-pipeline/run.py` (extend rather than fork; new months → CSV + Parquet append, catalog/metadata bump) | one incremental run verified vs full recompute |
| M3.2 | `data/status.json` + public status panel (last run, current data month, lag days, known issues, pipeline version) | status numbers match manifest |
| M3.3 | Currency banner on every page ("Data current to [YYYY-MM], [N] days lag"; amber > 45 days) | banner math verified against status.json |

**Exit gate M3:** a simulated month increments era B end-to-end; banner + status correct; v1.0 numbers unchanged (regression harness).

### M4 — IMD benchmark validation study (E08)
*Suggested: Jan 2027. Depends on: IMD data (Owner downloads). Independent of M2/M3.*

| Task | Content | Gate |
|---|---|---|
| M4.1 | `validation-studies/imd/` acquisition scripts: IMD 0.25° daily rainfall → monthly (Pai et al. 2014 product); IMD temperature product (verify current resolution/version, record in register) | Owner-run download succeeds; grid metadata recorded |
| M4.2 | IMD-SPI/SPEI computation reusing `indicators.py` (same gates, same reference window 1981–2020) | fit-report parity with era B machinery |
| M4.3 | Comparison framework: correlation, bias, RMSD, drought-class agreement, event match — by season and region; BH-FDR trend-map view (**mandatory, amendment 06 §2 — not optional**) | metrics table generated from Owner-run outputs |
| M4.4 | Validation memo template + methodology page v2 section; discrepancies published; **explicit statement (X8): IMD temperature begins 1951 — comparison restricted to 1951– onwards, pre-1951 era A temperature basis is the Atlas reconstruction** | memo drafted with real numbers (Owner-gated) |

**Exit gate M4:** validation memo exists with real IMD comparison numbers, or the memo ships with the flagged "pending Owner run" sections clearly marked (never with synthetic values).

### M5 - Future Projections workspace (E05, E13)
**Build-order constraint (amendment 06 §5 X1):** `#crossval` (M6.6) gates ANY projections surface going live; fixture-based development may proceed in parallel. Default view is AGREEMENT, not median (X2); banner states the honest ensemble n, never "24 models" (X3).
*Suggested: Feb–Mar 2027. Depends on: M2 (fixtures for build; real data for ship), M1 engine.*

| Task | Content | Gate |
|---|---|---|
| M5.1 | Era C fixture generation (`data/fixtures/`, labelled synthetic, realistic schema) | fixtures carry `FIXTURE — SYNTHETIC` banner end to end |
| M5.2 | `#projections` tab skeleton: era toggle wiring, scenario switch, variable/timescale selector | zero console errors; mobile drawer OK |
| M5.3 | Ensemble band chart (median + 25–75 %), district time-series, choropleth of ensemble stat per month/year — **choropleth DEFAULT = agreement fraction (X2); median is the secondary toggle** | queries via engine < 150 ms cold |
| M5.4 | Agreement layer (fraction of models ≤ −1.0 / ≤ −1.5; direction-of-change map) with exact definitions + per-district seam_uncertainty (X7) in tooltips; agreement-first default (X2) | definitions text matches 07_ensemble_stats output |
| M5.5 | Model ranking panel (from `08_validate_gcm.py` outputs; multi-metric, best-subset selectable) | no single-metric ranking |
| M5.6 | SPI–SPEI divergence map + copy ("Rainfall alone does not decide India's drought future; demand does half the work.") | divergence computed from shipped products only |
| M5.7 | Projection banner (**honest ensemble n from best_subset — amendment X3: the memo's "24 models" copy is rejected**; median shown with 25–75 % range; model disagreement is the finding); era labels; no-splice rules | banner present on every era C surface |
| M5.8 | **E14 future drought event analytics** (amendment 06 §2): frozen event machinery on validated era C; frequency/duration/severity per window vs 1981–2020 baseline; fourth view in `#projections`. Tier-1 entry gated on **OD9 (Owner confirmation)** | runs only on real era C data past the release gate |

**Exit gate M5 (ship gate):** tab verified on **real Owner-produced era C data** after `08_validate_gcm.py` passes (CMIP6 release gate in register §6). Until then the tab may exist in `v2-dev` behind a flag with fixtures, never on the live site.

### M6 — Atlas era A + cross-validation (E06, E07, E13)
*Suggested: Mar–Apr 2027. Depends on: Atlas v2 verification (Owner gate), M1.*

| Task | Content | Gate |
|---|---|---|
| M6.1 | Atlas v2 verification: DOI/licence/version/variables/PET method/SPEI flavour/spatial units recorded in register; v1 fallback identified | verification memo in register |
| M6.2 | `atlas-pipeline/` ingestion: Atlas grids → district long Parquet, per-year tiles (era A partitioning) | round-trip spot checks; per-year tiles ≤ ~20 KB |
| M6.3 | `#atlas` tab: era-labelled scrubber (per-year tile fetch only), seasonal composites (JJAS, ONDJ, water year, calendar year) | scrubbing 1901→end fetches only touched years |
| M6.4 | Frequency climatology maps (three eras), category-share summary ("X % of units in moderate-or-worse") | era labels explicit |
| M6.5 | Historical-event anchoring: 1918, 1965, 1972, 1987, 2002 identifiable | events reproduce against Atlas documentation |
| M6.6 | Cross-validation panel `#crossval`: era A vs era B, **1981–2014 primary window (register D6; full 1981–2025 overlap as sensitivity)** (r, bias, class agreement, event match rate, discrepancy map) | table + map render; discrepancies visible |
| M6.7 | Era A tab initially district-level; tehsil layer (O01) only after boundary-source verification | boundary decision recorded |
| M6.8 | **seam_uncertainty (X7):** per district, SD of (era A − era B) SPEI-12 over the 1981–2020 overlap, computed once at cross-validation, stored with the projections store, surfaced in projection tooltips as "±X SPEI units" | column present; tooltip copy matches computed value |

**Exit gate M6:** Atlas era live with era labels; cross-validation published; known events identifiable.

### M7 — Release: downloads, DOI, hardening (E10–E12)
*Suggested: May 2027. Depends on: M3–M6 gates.*

| Task | Content | Gate |
|---|---|---|
| M7.1 | Download portal: versioned Parquet + CSV bundles generated from catalog, schema docs, checksums; **every bundle + export carries era/source/base_period/pet_method/seam_note headers (X6) with a regression check** | files identical to dashboard-served |
| M7.2 | CITATION.cff update + Zenodo v2.0.0 deposit + DOI + citation line | DOI resolves |
| M7.3 | Mobile + WCAG 2.1 AA pass; permalink hardening; Engine Lab polish | checklist in 04 §7 green |
| M7.4 | Methodology page v2 complete; changelog; release notes; version-history panel updated | no leftover placeholders |
| M7.5 | Definition-of-Done checklist (docs/v2/01 §6) walked item by item | all boxes checked or explicitly deferred with Owner sign-off |

**Exit gate M7:** v2.0.0 tagged, DOI minted, manuscript v2 outline drafted.

### M8+ — Tier 2 / Tier 3 rollout (post-release)
Work Tier 2 (O01–O12) in worth order; Tier 3 items only when their data/licence gates are satisfied. Each item still follows one-task-per-session with tracker updates.

### M9 — `#summary` tab: drought change now → 2100 (E19, Owner request 2026-11-18)
*Suggested: after M5.8 + the Owner's 2051–2100 SSP download (COMPLETE 2026-11-19: 8-model subset × 2 scenarios × 3 variables × 2015–2100, 4,128 files) and the full-record era-C recompute. Depends on: validated era C past the register §6 gate; E14 event machinery.*

| Task | Content | Gate |
|---|---|---|
| M9.1 | Change layer: per district, era C window drought-frequency/duration/severity vs observed **1981–2014** baseline (register D6; reuses E14 outputs), rendered as the primary `#summary` map | only validated products (R3); era labels + honest n (X3) |
| M9.2 | Agreement strip: `dir_agreement_drier` share-of-models map + "X of N models agree" copy (agreement-first, X2); scenario toggle SSP2-4.5/SSP5-8.5 | definitions verbatim from `config/ensemble.yaml` |
| M9.3 | Per-state summary table + national area-share-in-drought figure (LAEA areas); downloadable CSV with reproducibility headers (X6) | state table sums to national; n reported per row (R10) |
| M9.4 | Caveat copy block: projections are simulations not forecasts (R2), seam_uncertainty ±X (X7), PET-method sensitivity pointer (OD10) | copy review vs register |

**Exit gate M9:** `#summary` live on real era C data with the same ship gate as M5 (register §6), after `#crossval` (M6.6) is live (build-order constraint X1).

## 4. Feature → milestone map

| Milestone | Features delivered |
|---|---|
| M1 | E01, E02 (+ engine foundation for everything else) |
| M2 | E04 (framework; real data by Owner during M2–M5) |
| M3 | E03 |
| M4 | E08 |
| M5 | E05, E13 |
| M6 | E06, E07 |
| M7 | E09, E10, E11, E12 |
| M8+ | O01–O12, O13–O15 (amendment backlog, docs/v2/06), then Tier 3 |
| M9 | E19 (`#summary`) |

## 5. Owner-executed compute register (what OpenCode must never assume is done)

| Item | Trigger | Where results get recorded |
|---|---|---|
| Monthly GEE export + indicator recomputation (era B extension) | from Jan 2027 monthly | PROGRESS.md session log + `data/status.json` |
| Final 24-model list | at M2.1 | `gcm-pipeline/config/models.yaml` |
| CMIP6 downloads (24 models, pr/tasmax/tasmin, historical + ssp245 + ssp585) | M2 handoff → ongoing | PROGRESS.md |
| Regrid → QDM → PET → SPI/SPEI → aggregation → ensemble → export (era C) | per model/scenario batch | PROGRESS.md + `pipeline_manifest.json` checksums |
| IMD data acquisition (rainfall; temperature) | M4 | PROGRESS.md + register |
| Atlas v2 acquisition + licence verification | M6 gate | register + PROGRESS.md |
| Era A ingestion compute (if heavy) | M6 | PROGRESS.md |

## 6. Session sizing guidance

- One task per session (S ≈ one focused session; M ≈ 2–3 sessions; L ≈ 4+ sessions broken into task sub-steps with intermediate verification).
- If a session ends mid-task, mark the task `in_progress` with precise state notes in PROGRESS.md ("what works, what remains"), so the next session resumes cleanly.
- Never start a milestone whose dependency gate is unmet — pick the next independent milestone instead (the plan is deliberately parallelisable: M2/M3/M4 are mutually independent once M1 lands).
