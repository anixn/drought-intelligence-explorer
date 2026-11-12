# AGENTS.md — Drought Intelligence Explorer (DIE) v2.0

**Persistent project instructions for OpenCode. Read this file fully at the start of every session, before touching any code.**

| Field | Value |
|---|---|
| Project | Drought Intelligence Explorer (DIE) v2.0 |
| Owner | Ankit Deshmukh, Ph.D., Assistant Professor, Dept. of Civil Engineering, PDEU (deshmukh.acad@gmail.com, ORCID 0000-0002-1433-3872) |
| Live v1.0 | https://drought.ankitdeshmukh.com (v1.0.0, released 2026-11-10) |
| Repository | https://github.com/anixn/drought-intelligence-explorer (default branch `master`) |
| Working branch | `v2-dev` — all v2 work happens here; `master` stays the live v1.0.0 release until a v2 release gate passes |
| Licence | MIT (code); Zenodo DOI 10.5281/zenodo.24113364 (v1.0.0 dataset + software) |
| Manuscript | EarthArXiv preprint v1.3 (`manuscript/main.tex`), Scientific Data data-descriptor style |
| Methodology baseline | `research-gee-1.0.2` / pipeline_version 1.1.0 — **frozen semantics**, extended not altered |

---

## 0. Mandatory session-start sequence

1. Read `AGENTS.md` (this file).
2. Read `PROGRESS.md` (repo root) — the status flag, current milestone, next recommended task, open blockers.
3. Read `docs/v2/02-roadmap-milestones.md` — the milestone and task you are resuming.
4. Read `docs/v2/05-decision-register.md` before making or revisiting any methodological choice.
5. Inspect the repository state (`git status`, `git log --oneline -15`, the files listed under PROGRESS.md → "Files created or modified"). **The code is the source of truth; if docs and code disagree, fix the docs.**
6. Resume exactly at the task recorded in PROGRESS.md → "Next recommended task". One milestone task at a time. Do not skip ahead, do not start a new milestone unless the previous one's exit gate is marked complete in PROGRESS.md.

**Never re-derive the plan from scratch; the plan lives in these documents. Never implement more than the current task.**

---

## 1. Mission

Evolve DIE v1.0.0 — a validated, published, four-workspace drought analytics platform serving 10 district-level indicators (1981–2025) — into **DIE v2.0**: a scientifically rigorous, India-focused, extensible drought record spanning three labelled eras:

- **Era A — Atlas (1901–2025, pending verification of Atlas v2):** Drought Atlas of India reconstruction (SPEI), tehsil-native source, served at district level first.
- **Era B — Observed (1981–2025 → ongoing):** the existing v1.0.0 record (SPI-1/3/6/12, SPEI-1/3/6/12, SMA, VCI), preserved as-is and extended monthly.
- **Era C — Projections (2026–2100, default):** 24 bias-corrected CMIP6 GCMs (PR, TASMAX, TASMIN → SPI/SPEI), SSP2-4.5 + SSP5-8.5, ensemble median + spread + agreement.

…into one queryable schema (Parquet + DuckDB-WASM), presented as labelled eras that are **never silently spliced**, with a standing cross-validation programme (IMD benchmark; Era A ↔ Era B overlap).

Positioning: DIE owns the *climatological record and statistical interrogation layer*. It does **not** compete with operational weekly monitors (India Drought Monitor, IMD products) — it complements them with archive depth, multi-indicator families, reproducibility and projections.

## 2. The golden rules (non-negotiable)

1. **R1 — Preserve v1.0.0.** Treat v1.0.0 as the foundation. The four workspaces (Overview `#overview`, Historical `#historical`, Events `#events`, Propagation `#propagation`), the Documentation & Resources centre, the metadata-driven data contract (`data/metadata.json`), the event rules (runs analysis, τ = −1.00 / −15 % SMA / 30 % VCI, min 3 months, censoring), the missing-data policy (never imputed), area weighting (LAEA 22.5°N 79.5°E), MK + Sen + Hamed–Rao trends, moving-block bootstrap lag correlation (seed 20261103), and the export products with reproducibility headers are **validated, published behaviour**. Never remove, silently alter, or "improve" them. Changes require a documented scientific reason in the decision register.
2. **R2 — Era honesty.** Never present 1901–2100 as one homogeneous observed series. Every surface carries era labels, source labels, and reference-period labels. Projections are never forecasts. Reconstructions, reanalysis, observations and model simulations are never mixed into one unqualified line.
3. **R3 — No fabrication.** Do not invent data, model coverage, validation results, licences, or citations. If a dataset is unavailable, ship a clearly labelled integration placeholder — never synthetic values presented as real results. Development fixtures (synthetic data used to build UI before real data exists) must be marked `FIXTURE — SYNTHETIC, NOT FOR RELEASE` in both filename and UI banner.
4. **R4 — Separation of roles.** The Owner executes all compute-intensive scientific processing (GEE exports, CMIP6 downloads, bias-correction runs). OpenCode designs, documents, codes, self-tests (on synthetic worlds), and prepares runbooks — but does **not** run GEE jobs, download multi-TB climate archives, or execute the production scientific processing. Assume computational products do **not** exist until the Owner records them in PROGRESS.md.
5. **R5 — Session discipline.** Read the tracker → inspect the code → do the one task → verify → update `PROGRESS.md` → stop. Do not attempt the whole roadmap in one session. Size each session to one task (or a tightly coupled pair).
6. **R6 — The progress file is mandatory.** Every substantial session ends with `PROGRESS.md` updated (status flag, completed/in-progress/pending, dependencies, files touched, decisions, next task). An unrecorded session is an unfinished session.
7. **R7 — Verify before "done".** Every task ends with a concrete verification (test run, numeric round-trip, checklist) recorded in PROGRESS.md. The pipeline's `selftest.py` (82 assertions, seed-deterministic) must keep passing; extend it for new code paths rather than bypassing it.
8. **R8 — UX/URL continuity.** Stable hash routes (`#overview`, `#historical`, `#events`, `#propagation`, `#data`) keep working. New surfaces get new hashes (`#atlas`, `#projections`, `#crossval`, `#engine`, `#brief`). Responsive layouts, keyboard operability, and ARIA roles are maintained in every change.
9. **R9 — Interpretation guardrails.** Correlation ≠ causation. Propagation claims require appropriate observations (no streamflow/groundwater claims from rainfall or soil moisture). Trend maps without multiple-testing correction are labelled exploratory. Composite indices and ML are analytical layers, clearly flagged, never default views.
10. **R10 — Data policy.** Missing values are never imputed, interpolated, or carried forward. Gaps are rendered, counted, and reported. Every statistic reports its sample size.

## 3. Division of labour

| Responsibility | Owner (Ankit) | OpenCode |
|---|---|---|
| Product/spec decisions, scientific arbitration | ✔ final say | propose, document, implement |
| Google Earth Engine export runs (monthly refresh, era B extension) | ✔ executes | maintain scripts/runbook |
| CMIP6 download + QDM bias correction + era C processing | ✔ executes | write all scripts, configs, selftests, runbooks |
| IMD data acquisition for validation | ✔ executes | write scripts, comparison framework |
| Front-end, engine, UI surfaces, docs, tests, releases | ✔ reviews/merges | ✔ builds |
| PROGRESS.md updates | reviews | ✔ updates every session (Owner appends compute results when done) |
| Filling `gcm-pipeline/config/models.yaml` with the final 24 models | ✔ | template + selection criteria + inventory checker |

## 4. Locked architecture (do not re-litigate; measured on the DIE-2.0 prototype)

| Layer | Choice | Why |
|---|---|---|
| Storage format | Apache Parquet, zstd, dictionary-encoded, long format | 4× smaller than CSV on real data (18.4 MB → 4.6 MB for 10 indicators × 724 districts × 540 months); columnar reads; SQL-native |
| Compute | DuckDB-WASM 1.32.0 in a Web Worker | Full analytical SQL in-browser; zero backend; in-memory file cache makes repeat queries free (measured 0 KB repeat) |
| Transport | HTTP Range requests over static files | DuckDB reads only needed byte ranges; hosts: GitHub Pages → Cloudflare R2 at scale |
| Geometry | PMTiles for district + tehsil boundaries | Single-file vector tiles, serverless, viewport-scoped fetches |
| Rendering | Leaflet (724 polys) today; deck.gl/MapLibre GL when tehsil layer or animated Atlas scrubber lands | GPU path for dense polygons |
| Charts | Plotly (vendored); `scattergl`/UPlot for 200-year series | Already proven in v1.0 |
| CSV loader | Retained as fallback / first-paint path | Offline resilience |
| Processing scripts | Python (continuity with v1.0 `data_pipeline/`); R package equivalents documented where relevant | v1.0's audited modules (`indicators.py`, `selftest.py`, `config.yaml`) are Python |
| Hosting | GitHub Pages (start) → Cloudflare R2 (scale) | $0 within free tiers |

## 5. Repository layout (target on `v2-dev`)

```
drought-intelligence-explorer/
├── AGENTS.md                    # this file (repo root — OpenCode auto-loads it)
├── PROGRESS.md                  # persistent tracker (repo root)
├── index.html                   # v1.0 shell, extended (never rewritten)
├── assets/{css,js,vendor,images}/
│   └── js/ducklab.js            # NEW: DuckDB-WASM engine service (see docs/v2/04)
├── data/
│   ├── metadata.json            # v1.0 contract — extended, never broken
│   ├── pipeline_manifest.json   # extended with checksums of new products
│   ├── drought/*.csv            # v1.0 wide CSVs — kept as fallback, kept in sync
│   ├── parquet/                 # NEW: the 1901–2100 store
│   │   ├── catalog.json         # exact-path manifest (no HTTP globbing)
│   │   ├── observed/variable=<id>/part-0.parquet
│   │   ├── atlas/variable=<id>/year=<yyyy>/part-0.parquet
│   │   ├── projections/scenario=<s>/stat=<st>/variable=<id>/year=<yyyy>/part-0.parquet
│   │   ├── cross_validation/overlap_1981_2020.parquet
│   │   └── _national_monthly.parquet, _tehsil_national_monthly.parquet
│   ├── geo/*.pmtiles            # NEW (districts, tehsils when available)
│   └── fixtures/                # clearly-labelled synthetic data for UI development
├── data-pipeline/               # v1.0 pipeline — frozen semantics (run.py, selftest.py, config.yaml)
├── gcm-pipeline/                # NEW: era C scientific processing (docs/v2/03 §3)
├── atlas-pipeline/              # NEW: era A ingestion (docs/v2/03 §2)
├── validation-studies/          # NEW: IMD benchmark + era A↔B cross-validation (docs/v2/03 §5–6)
├── scripts/                     # build-time converters (Parquet, PMTiles, aggregates)
├── docs/
│   ├── user-guide.md, methodology.md, data-sources.md   # v1.0 docs — preserved
│   └── v2/                      # this documentation suite
├── manuscript/                  # EarthArXiv preprint v1.3
└── server.py                    # Range-capable dev server (from workplan)
```

## 6. Documentation map

| File | Purpose |
|---|---|
| `docs/v2/01-vision-scope.md` | Vision, objectives, scope/non-scope, v1.0 continuity contract, era model, definition of done |
| `docs/v2/02-roadmap-milestones.md` | Full feature backlog (Tier 1/2/3), milestone plan M0–M8 with exit gates, session sizing |
| `docs/v2/03-scientific-pipelines.md` | Data pipelines: era A/B/C/D frameworks, GCM processing chain, GEE refresh, IMD validation, QA standards, data contracts |
| `docs/v2/04-frontend-ui-spec.md` | UI surfaces, engine integration, rendering, exports, accessibility, regression protection |
| `docs/v2/05-decision-register.md` | Committed decisions (D1–D5, C1–C7), conflict resolutions, open decisions, safeguards |
| `PROGRESS.md` | Live tracker — status flag, tasks, files, decisions, next task (updated every session) |

## 7. Key reference facts (from the v1.0.0 audit — cite, don't re-derive)

- **Dataset:** 10 indicators, 724 districts, 36 States/UTs, monthly 1981-01 → 2025-12 (540 months; VCI from 2000-02, 311 months); 3,715,048 valid values. Files: `data/drought/spi_01|03|06|12.csv`, `spei_01|03|06|12.csv`, `soil_moisture.csv`, `vci.csv` (wide format: `district_id,district_name,state_name,1981-01,…,2025-12`).
- **Sources (era B):** CHIRPS v2.0 daily (GEE `UCSB-CHG/CHIRPS/DAILY`), ERA5-Land monthly aggregates (`ECMWF/ERA5 Land/MONTHLY_AGGR`: PET = `potential_evaporation_sum` sign-corrected; soil water layers 1–3, 0–100 cm, equal-weight), MODIS MOD13A3.061 NDVI. Extraction: GEE `reduceRegions` with `pixelArea()` weights, 12-month chunks, tileScale 4–8, buffer fallback (6/16/16/2 km) for zero-pixel districts.
- **Standardisation:** SPI = two-parameter gamma (MLE) + mixed-distribution zeros; SPEI = three-parameter log-logistic, L-moment (PWM) estimator, Gringorten plotting-position fallback for the whole district-calendar-month series when the fit fails; per-fit gates (base mean within ±0.2, sd 0.75–1.3); ≥ 20 base years; reference 1981–2020 (VCI 2000–release). Classification: McKee 9-class z scheme; SMA −5/−15/−30/−50 %; VCI Kogan classes.
- **Events:** runs analysis (Yevjevich 1967), truncation = upper bound of moderate class (−1.00 z / −15 % / 30 % VCI), min duration 3 months, severity = Σ(τ−x), recovery = months to first value ≥ 0 (signed families only), censoring at record/period edges, missing months break runs. Sensitivity panel: durations 4/6/9/12, truncations −0.50/−1.50/−2.00.
- **Statistics:** MK (tie-corrected) + Sen slope + 90 % rank CI + Hamed–Rao correction; annual series (≥ 9 valid months); BH-FDR demo: 382/724 districts significant uncorrected → 324 after q = 0.05 (SPI-3 annual trends). Lag cross-correlation −12…+12 months, ≥ 30 pairs, moving-block bootstrap 1,000 resamples, block n^(1/3) capped 4–24, seed 20261103.
- **Areas:** Lambert Azimuthal Equal-Area `+proj=laea +lat_0=22.5 +lon_0=79.5`; served national total 3,266,386 km² (0.64 % short of published area — boundary-source property, documented, not corrected).
- **Boundaries:** community `udit-001/india-maps-data` (2011-era demarcation lineage), 724 unique features, ≈100 m generalisation, median area error 0.034 %.
- **Pipeline commands:** `python run.py gee --project <project> --end YYYY-MM`, `run.py update`, `run.py indicators|export|validate|status`, `python selftest.py` (82 assertions), `prepare_boundaries.py`. Entry list in `main.tex` Code availability.
- **Stack:** Leaflet 1.9.4, PapaParse 5.4.1, Plotly-cartesian 2.35.2, Turf 7.2, html2canvas 1.4.1; `assets/js/app.js` (123 KB, hash router); GTM GTM-MDF5QQ4D; GitHub Pages + CNAME.
- **Known v2 prototype assets:** the Owner's `work/die-2.0/` prototype (Engine Lab `#engine`, `assets/js/ducklab.js` ~330 lines, `scripts/convert_to_parquet.py` ~130 lines). If present on the machine, reuse as reference implementation; otherwise rebuild to the specs in docs/v2/03–04 (the workplan contains measured numbers).

## 8. Session protocol

**Start:** run §0. If PROGRESS.md is missing or stale, reconstruct state from git + this file, note that in the session log, and continue.

**During:**
- Implement only the current task; keep diffs scoped; match existing code style (vanilla JS, no build step, no new frameworks).
- All long work runs through persisted scripts (`scripts/`, `gcm-pipeline/`, …), never ad-hoc one-off patches appended to files.
- Any new scientific parameter goes in a config file (`config.yaml` pattern), never a hidden constant in code.
- When you need a decision you cannot make (scientific, licensing, model list), record it as an open item in PROGRESS.md → "Dependencies and unresolved issues", choose the documented default from `docs/v2/05-decision-register.md` if one exists, and continue with it flagged as provisional.

**End (before finishing every session):**
1. Run the verification relevant to the task (selftest, round-trip, checklist) and record results.
2. Update `PROGRESS.md`: status flag, session log entry (date, tasks done, files, verification results), completed/in-progress/pending, next recommended task.
3. `git commit` on `v2-dev` with a message referencing the task ID (e.g. `M1.4: era-B wide CSVs → long Parquet, round-trip verified`). Commit only what the Owner has approved as the working pattern: v2-dev commits are fine; never push to `master`.

## 9. Verification harness (what must pass before anything is called done)

- `python selftest.py` — 82 assertions, seed-deterministic; must pass unchanged unless the task explicitly extends it.
- Round-trip rule: any converted data must be verified cell-level against its source (≥ 5 random cells per file, exact match).
- Numeric regression baseline: regional summaries + selected catalogue entries snapshot; must match exactly after refactors (capture before, compare after).
- Engine checks (once live): district slice < 100 ms cold; repeat query 0 KB (byte interceptor); catalog paths all resolve (HTTP 200).
- UI checks: cycle all tabs (existing + new); zero console errors; mobile viewport pass; keyboard operability of new controls.
- Release gates: see `docs/v2/02-roadmap-milestones.md` (per-milestone exit gates) and `docs/v2/05-decision-register.md` §6 (CMIP6 module release gate).

## 10. Blockers and escalation

If genuinely blocked (missing credentials, missing dataset, ambiguous science with no documented default): stop that task, record the blocker precisely in PROGRESS.md ("what was tried, what failed, what is needed"), switch to the next independent task on the roadmap, and surface the blocker in the session log. Never invent data or credentials to unblock yourself. Never print or store secrets.
