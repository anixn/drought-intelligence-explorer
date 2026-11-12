# DIE v2.0 — Scientific Pipelines and Data Processing Framework

*Doc 3 of the v2.0 suite. Defines every data pipeline: what OpenCode builds (code, configs, self-tests, runbooks) and what the Owner executes (GEE exports, CMIP6 downloads, bias-correction runs, data acquisition). **Nothing in this document implies the computational processing has been completed** — every Owner-executed step is gated and recorded in `PROGRESS.md`.*

---

## 0. Pipeline landscape

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                    DATA/PARQUET STORE                     │
 Era A (atlas)      │  atlas/variable=…/year=…/part-0.parquet                   │
 Era B (observed)   │  observed/variable=…/part-0.parquet        ───► catalog.json
 Era C (projections)│  projections/scenario=…/stat=…/variable=…/year=…/…        │
 Cross-validation   │  cross_validation/overlap_1981_2020.parquet               │
                    └──────────────────────────────────────────────────────────┘
                        ▲                    ▲                      ▲
     atlas-pipeline/ ───┘   data-pipeline/ ───┘   gcm-pipeline/ ─────┘
     (Atlas ingestion)      (v1.0, frozen +        (00–09 chain, Owner
     Owner: download          monthly refresh        executes; OpenCode
     Atlas v2                 mode; Owner runs       writes/tests/runbook)
                              GEE monthly)
```

One schema spans eras (§8.1). Era pipelines are siblings under the repo; the v1.0 `data-pipeline/` is frozen in semantics and extended only in documented ways.

## 1. Era B — Observed (preserved v1.0.0 pipeline + Parquet conversion + monthly refresh)

### 1.1 Frozen scientific core (do not modify semantics)

The v1.0.0 pipeline (`data-pipeline/`) produced the released record (`research-gee-1.0.2`, pipeline_version 1.1.0): CHIRPS v2.0 daily → monthly; ERA5-Land PET (`potential_evaporation_sum`, sign-corrected, m→mm) + root-zone soil water (layers 1–3, 0–100 cm, equal-weight); MOD13A3.061 NDVI; GEE `reduceRegions` with `pixelArea()` weights on native grids, 12-month chunks, tileScale 4–8, split-retry, checkpoint cache, grid-matched buffer fallback (6/16/16/2 km) for zero-pixel districts; SPI (gamma MLE + mixed zeros), SPEI (log-logistic, L-moments, Gringorten fallback), SMA (percent-of-mean), VCI (Kogan rescale); fit gates (base mean ±0.2, sd 0.75–1.3, ≥ 20 base years); reference 1981–2020 (VCI 2000–release). Commands: `run.py gee|update|indicators|export|validate|status`, `selftest.py` (82 assertions), `config.yaml` for every parameter.

**Rule:** era B science is frozen. Any change (e.g. CHIRPS v2.0 → v3.0 alignment when the GEE catalogue mirrors it; thickness-weighted soil moisture as alternative product) is a **new data version with its own regression note**, not an in-place edit of released values.

### 1.2 Parquet conversion (build-time; task M1.3–M1.5)

`scripts/convert_to_parquet.py` converts the ten released wide CSVs to the long-format store:

- One Parquet file per variable under `data/parquet/observed/variable=<id>/part-0.parquet`, ids: `spi_01, spi_03, spi_06, spi_12, spei_01, spei_03, spei_06, spei_12, sma, vci` (match existing file names `soil_moisture.csv` → `sma`, `vci.csv` → `vci`).
- Schema (§8.1): `district_id` (string, dictionary-encoded), `year` (int16), `month` (int8), `value` (float32). Missing cells are **absent rows**, not nulls-with-fake-values.
- Compression zstd; row groups aligned to district boundaries (60 districts/group — measured prototype finding).
- Print per-variable row counts and file sizes; expected era B total ≈ 25–30 MB (measured prototype: 18.4 MB wide CSV → 4.6 MB Parquet for the same content; v1.0 CSVs total ≈ 17 MB).
- Round-trip verification: ≥ 5 random cells per variable must match the CSV exactly (task M1.4).

### 1.3 Pre-aggregates (task M1.10)

`data/parquet/_national_monthly.parquet`: area-weighted national monthly series per variable (LAEA weights from the v1.0 district areas), ~42 KB on prototype data — serves every default national view. `_tehsil_national_monthly.parquet` follows when era A lands. Regional (state) pre-aggregates may follow the same pattern if default views need them.

### 1.4 Monthly refresh mode (task M3.1)

Extend `data-pipeline/run.py` with a monthly-increment mode (new flag, e.g. `run.py monthly --end 2026-01`):

1. Owner runs the GEE extraction for the new month(s) (same chunk/checkpoint machinery).
2. `indicators.py` recomputes only affected district-month fits (fixed 1981–2020 parameters — no refitting, by design).
3. `export_app.py` appends new columns to the wide CSVs, bumps `metadata.json` (`last_updated`, availability windows) and `pipeline_manifest.json` (checksums).
4. `scripts/convert_to_parquet.py --incremental` rewrites the affected variable files (small files — rewrite is safer than append) and regenerates `catalog.json`.
5. Writes `data/status.json`: last successful run timestamp, current data month, lag in days, pipeline version, known issues.

`validate.py` runs at the end; non-zero exit blocks release. **The 45-day lag target is enforced by the banner (docs/v2/04 §2.3), amber beyond it.**

## 2. Era A — Atlas ingestion (`atlas-pipeline/`)

### 2.1 Source verification gate (Owner, before any ingestion)

Candidate: *Drought Atlas of India, 1901–2025* (Version 2), Zenodo DOI 10.5281/zenodo.20368514 (from the references catalogue — **verify the landing page before implementation**; fallback: v1, 1901–2021, Chuphal et al. 2024, Sci Data 11:7). Record in the decision register: licence (expected CC-BY; verify redistribution terms), exact variables and timescales (expected SPEI-1/4/12 — **do not assume SPI is present**), PET method used by the Atlas, input products, spatial resolution and units (gridded 0.05° vs pre-aggregated tehsil/district tables), calendar, missing-data conventions, and version/DOI. If the release differs from expectations, adapt the ingestion and note the delta — never assume.

### 2.2 Ingestion design (`atlas-pipeline/`)

```
atlas-pipeline/
├── config/atlas.yaml          # release DOI, file paths, variables, units, grid
├── 00_verify_atlas.py         # structural checks: grid, calendar, coverage, licence file
├── 01_atlas_to_district.py    # aggregate Atlas grids → 724 districts (or ingest released district tables if provided)
├── 02_atlas_parquet.py        # era A long Parquet, per-year tiles per variable
├── 03_atlas_composites.py     # seasonal composites: JJAS, ONDJ, water year, calendar year
├── selftest_atlas.py          # synthetic mini-Atlas end-to-end
└── README.md                  # Owner runbook (download, verify, ingest)
```

- **District-first** (724 v1.0 fabric, area-weighted LAEA, same zonal semantics as v1.0 — buffer fallback for sub-pixel units). Tehsil layer (O01) is gated on a verified, licensed tehsil geometry source; the v1.0 manuscript deliberately deferred sub-district units until such a source is defensible — keep that gate.
- If the Atlas ships pre-aggregated tehsil/district tables, ingest those directly (less re-derivation error) and document the aggregation the Atlas used; else compute zonal aggregation from the grids.
- Output partitioning: `data/parquet/atlas/variable=<id>/year=<yyyy>/part-0.parquet`, per-year tiles (~10 KB each on prototype measurements), so the Atlas scrubber fetches only the touched year.
- Composites land in `data/parquet/atlas/composites/variable=<id>/season=<jjas|ondj|wy|cy>/stat=<mean|min|share_below_truncation>/…` (exact keys fixed when era A ships).
- **Labels:** era A values are Atlas *reconstructions* (SPEI from the Atlas's own P/PET chain) — never merged with era B values; the cross-validation panel (§6) is the only sanctioned comparison surface.

## 3. Era C — GCM processing framework (`gcm-pipeline/`) — the centrepiece

### 3.0 Division of labour for this pipeline

OpenCode writes **every script, config, self-test and runbook** and proves the chain on a synthetic world. The Owner executes the production runs (downloads are multi-hundred-GB; QDM is CPU-bound) and records progress in PROGRESS.md. Scripts must be resumable, checkpointed, and idempotent — a killed run resumes without corruption.

### 3.1 Directory and configs

```
gcm-pipeline/
├── config/
│   ├── models.yaml        # the final 24 models (OWNER fills; see template below)
│   ├── reference.yaml     # reference dataset choice + paths + target grid
│   └── paths.yaml         # raw/ work/ out/ roots (gitignored)
├── 00_download_cmip6.py
├── 01_inventory_check.py
├── 02_regrid_025.py
├── 03_qdm_bias_correct.py
├── 04_pet_hargreaves.py
├── 05_spi_spei_compute.py
├── 06_district_aggregate.py
├── 07_ensemble_stats.py
├── 08_validate_gcm.py
├── 09_export_parquet.py
├── selftest_gcm.py
├── README.md              # Owner runbook
├── work/                  # intermediates (never shipped)
└── out/                   # validated products → data/parquet/projections/
```

`config/models.yaml` (template — the example row is format illustration only, **not** the final list; the Owner supplies the verified 24):

```yaml
# SELECTION CRITERIA (all must hold):
#   - activity_id CMIP6, experiment_id in {historical, ssp245, ssp585}
#   - table_id day (daily); variables: pr, tasmax, tasmin
#   - one documented variant per model (default r1i1p1f1); record grid_label
#   - historical coverage ≥ 1981 (for calibration 1981–2020 the model
#     historical 1981–2014 is combined with ssp 2015–2020)
#   - future coverage to 2100
models:
  - source_id: "EXAMPLE-ONLY"   # ← replace with the verified 24 (Owner, task M2.1)
    variant: "r1i1p1f1"
    grid_label: "gn"
    historical: {start: 1950, end: 2014}
    ssp245:     {start: 2015, end: 2100}
    ssp585:     {start: 2015, end: 2100}
```

`config/reference.yaml` (committed default; final choice recorded in the decision register):

```yaml
target_grid: {res_deg: 0.25, lon_min: 67.0, lon_max: 99.0, lat_min: 6.0, lat_max: 38.0}
calibration_window: [1981, 2020]     # fixed, matches era B reference discipline
reference:
  precipitation:
    primary:   {name: "IMD 0.25° daily gridded rainfall (Pai et al. 2014 lineage)", path: "..."}
    alternate: {name: "CHIRPS v2.0 (era-B consistency check)", path: "..."}
  temperature:
    primary:   {name: "IMD gridded daily Tmax/Tmin — VERIFY current product resolution/version", path: "..."}
    alternate: {name: "ERA5-Land t2m/tmn/tmx", path: "..."}
  pet_reference_mode: "hargreaves-on-reference-temperature"   # see §3.5
```

**Why IMD as primary:** the Owner's instruction designates IMD gridded historical datasets for comparison *and* bias correction; IMD is station-interpolated national data (independent of the satellite-gauge blend that feeds era B), so era C is anchored to an independent reference. CHIRPS/ERA5-Land remain as alternates and cross-checks. This supersedes the earlier suggestion of a CHIRPS/ERA5-Land reference; both references can be run and compared in the validation stage (§3.8).

### 3.2 Step 00 — download (`00_download_cmip6.py`)

- Source routes (both scripted; Owner picks by bandwidth): (a) ESGF Metagrid/Wget with per-model search templates (subset to India bbox at request time where the node supports it); (b) Google/Pangeo CMIP6 cloud zarr (`gs://cmip6`) with bbox subsetting at read time.
- Per (model, experiment, variable) chunk files; resumable; SHA-256 per file recorded to `work/download_manifest.json`; re-run skips verified files.
- Output: `work/raw/<model>/<experiment>/<variable>.nc` (or zarr refs).
- **Never fabricate model availability** — anything missing is reported by `01_inventory_check.py`, not papered over.

### 3.3 Step 01 — inventory gate (`01_inventory_check.py`)

Builds the availability matrix (model × variable × experiment × period × calendar type) from what actually downloaded; hard-fails the pipeline on: missing variables, missing scenario runs, < 1981 historical coverage, incompatible calendars (noleap/365_day vs standard are handled at regrid — recorded, not failed), or variant mismatches vs `models.yaml`. Prints a human-readable matrix for the Owner.

### 3.4 Step 02 — regrid (`02_regrid_025.py`)

- Conservative remapping for `pr` (preserves area means; flux-consistent), bilinear for `tasmin/tasmax`.
- Calendar harmonisation to standard/proleptic Gregorian; document per-model calendar.
- Unit normalisation: pr kg m⁻² s⁻¹ → mm/day → monthly totals; tas K → °C.
- Verification: domain-mean monthly precip conserved within tolerance on synthetic fields; a bilinear spot-check against known values.
- Output: `work/regrid/<model>/<experiment>/<variable>_<period>.nc`.

### 3.5 Step 03/04 — QDM bias correction + PET (`03_qdm_bias_correct.py`, `04_pet_hargreaves.py`)

**QDM (Quantile Delta Mapping, Cannon et al. 2015), per grid cell, per calendar month:**

1. Calibrate: reference observed distribution (1981–2020), model historical distribution (1981–2014 historical combined with 2015–2020 scenario — one consistent model baseline), per variable.
2. For each model value `x` in period p: compute its non-exceedance probability τ within the model's own projected-period distribution; take the relative change Δ = ratio `x / Q_model,hist(τ)` for precipitation (multiplicative) or difference `x − Q_model,hist(τ)` for temperature (additive); map back as `Q_reference(τ) · Δ` (precip) or `Q_reference(τ) + Δ` (temperature).
3. Precipitation zero-guard (τ where reference quantile is 0 → corrected 0); physical range guards as in v1.0 (precip 0–4,000 mm/month).
4. Implementation tests (mandatory, in `selftest_gcm.py`): identity test (model data = reference data ⇒ output = reference data); trend-preservation test on a synthetic warming signal (delta must survive correction); quantile-inversion test.

The explicit design goal — preserving the model's *change signal* while correcting the *distribution* — is what makes QDM acceptable for drought indices fitted on a fixed window. Document the known caveat: bias correction can still distort multivariate dependence (pr vs tas); the SPI–SPEI divergence surface (§3.7) is partly the honest readout of that.

**PET — Hargreaves (Hargreaves & Samani 1985; FAO-56 Ra):**

`PET = 0.0023 · Ra · (Tmean + 17.8) · (Tmax − Tmin)^0.5` (mm/day), Ra = extraterrestrial radiation from latitude + day of year (FAO-56 equations), aggregated to mm/month. Applied **identically** to the bias-corrected model temperatures and to the reference temperatures, so the era C water balance is method-internal-consistent. Spot-check against a published worked example. Record the caveat: Hargreaves is a temperature-based approximation, **not** FAO-56 Penman–Monteith and **not** ERA5-Land's model PET used in era B — the era B ↔ era C SPEI seam is therefore methodological as well as climatic, handled only through era labelling and the cross-validation panel (§6), never by splicing.

### 3.6 Step 05 — SPI/SPEI (`05_spi_spei_compute.py`) — reuse, don't reinvent

- Import the v1.0 `data-pipeline/indicators.py` machinery (or a thin adapter around it): SPI = two-parameter gamma + mixed-distribution zeros; SPEI = three-parameter log-logistic, L-moment (PWM) estimator, tie-aware Gringorten fallback replacing the parametric fit for the whole cell-calendar-month series when the fit gate fails; per-fit calibration gates (base mean within ±0.2, sd 0.75–1.3); ≥ 20 base years; warm-up months stay missing.
- Fits are per grid cell × calendar month on the **fixed 1981–2020 window** (C2); future values map through those fixed parameters.
- Bounds: era C values clipped to [−5, +5] (projected late-century ensembles can legitimately exceed the era B QA bound of ±4; the clip count per variable is written to the fit report and surfaced in validation). This era-specific difference is a registered decision, not an inconsistency.
- The GEV fallback suggested in earlier planning is an **optional sensitivity variant** (`--spei-fallback gev`), not the default — era C keeps the v1.0 Gringorten fallback for methodological continuity.
- Time windows available: SPI/SPEI-1/3/6/12 (schema accommodates 24 as well; not built in v2.0).

### 3.7 Steps 06/07 — district aggregation + ensemble statistics

`06_district_aggregate.py`: area-weighted aggregation of corrected/standardised grid fields to the 724-district fabric — supersampled rasterisation of the district polygons on the 0.25° grid with area-proportional fractional weights (or the GEE `pixelArea()` route if rasters are uploaded as assets); buffer-fallback semantics for sub-pixel districts identical to v1.0; LAEA areas reused from `data/districts.csv`; per-district valid-pixel counts carried through.

`07_ensemble_stats.py`: per (scenario, variable, district, month) over the 24 models —

| Statistic | Exact definition |
|---|---|
| `median` / `p25` / `p75` | quantiles over the n available models (n recorded; never assume 24) |
| `agreement_moderate` | fraction of models with value ≤ −1.0 that month |
| `agreement_severe` | fraction of models with value ≤ −1.5 that month |
| `dir_agreement_drier` | fraction of models whose window mean (e.g. 2081–2100) is drier than their 1981–2020 mean (per window; used for change maps) |
| `n_models` | contributing model count |

Definitions are fixed in code, printed into the manifest, and rendered verbatim in UI tooltips (docs/v2/04 §4.2). Per-model district series are retained in `work/` (and optionally shipped as per-model partitions) so individual models stay inspectable — never hide disagreement behind the ensemble mean.

### 3.8 Step 08 — validation gate (`08_validate_gcm.py`, mandatory before anything public)

Checks (non-zero exit blocks release; report written to `out/validation_report.json`):

1. Corrected historical ensemble (1981–2014) statistically consistent with the reference: pooled SPI/SPEI mean/sd by region and season within declared tolerances.
2. Drought frequency, duration, severity (v1.0 event machinery) ensemble vs observed over 1981–2014, by region.
3. Model performance ranking: per model — Pearson r, bias, RMSD, drought-class agreement vs observed SPI and SPEI (1981–2014), by season; **multi-metric composite rank (documented weights, no single-metric ranking)**; best-performing subset (8–12 models) exported to `out/best_subset.yaml`; ranking CSV shipped to the UI panel.
4. SPI–SPEI divergence quantified (national + regional, per scenario/window) — the warming fingerprint the UI must present, not hide.
5. Clip counts, missing-model months, calendar anomalies — all reported.

**Gate-failure fallback (committed):** if the validation gate fails after two documented remediation rounds, publish observed-only v2.0 (eras A + B, freshness, downloads) and ship projections in the following cycle. Record every attempt in PROGRESS.md.

### 3.9 Step 09 — export (`09_export_parquet.py`)

Partition layout (every file ≤ ~0.5 MB):

```
data/parquet/projections/
  scenario=ssp245/stat=median/variable=spi_03/year=2031/part-0.parquet
  scenario=ssp245/stat=p25|p75|agreement_moderate|agreement_severe|dir_agreement_drier/…
  scenario=ssp585/…
```

Rows carry `district_id, year, month, value` (+ `model_id` on per-model partitions); `catalog.json` and `pipeline_manifest.json` (checksums, model list, base period, bias-correction block) are regenerated; `metadata.json` gains the era C variable block with availability windows.

### 3.10 Compute and storage envelope (ESTIMATES — measured values replace them at M2)

| Item | Estimate |
|---|---|
| Raw downloads (24 models × 3 vars × hist + 2 SSPs, daily, India-subset) | ~100–500 GB depending on subset support |
| Regridded monthly 0.25° India grid (129 × 65 cells, float32) | ~0.15 GB per model-experiment-variable; work dir ~20–30 GB total |
| QDM + PET + indices per model-experiment | CPU-hours, not days (vectorised per calendar month) |
| Era C Parquet store (2 SSPs × 10 stats/variables × 75 years) | well under the ~180 MB all-eras budget from the workplan |

All estimates are to be replaced with measured numbers in the runbook after the first model completes (Owner records them in PROGRESS.md).

### 3.11 Synthetic-world self-test (`selftest_gcm.py`)

A 3-model × 2-scenario × 41-year synthetic world (seed-deterministic) with known biases and an injected drying trend exercises steps 02→09 end-to-end and asserts: regrid conservation, QDM identity + trend preservation, PET formula correctness, SPI/SPEI calibration gates, ensemble statistic exactness, partition sizes, catalog integrity. This is how OpenCode proves the framework **without executing any production compute**.

## 4. Era D — reanalysis bridge (Tier 3, design sketch only)

Optional ERA5-Land bridge (1950–2025 district SMA/PET/T2m context) using the existing v1.0 extraction machinery pointed at the pre-1981 window. Value: context for the 1950s–1970s; never spliced into era B (different standardisation window needed — design a documented bridge-specific reference window before building). Schema and partitioning already accommodate it (`data/parquet/reanalysis/…`). Do not build until Tier 1/2 are done.

## 5. IMD benchmark validation study (`validation-studies/imd/`)

Purpose (v1.0 manuscript's top roadmap item): an independent, quantitative comparison of the era B record against IMD gridded observations, published with discrepancies visible.

```
validation-studies/imd/
├── 00_download_imd.py         # Owner-run; IMD 0.25° daily rainfall (Pai et al. 2014 lineage)
│                              # + IMD gridded temperature (VERIFY current resolution/version, record in register)
├── 01_imd_monthly.py          # daily → monthly totals/means, India bbox, calendar harmonisation
├── 02_imd_indicators.py       # IMD-SPI/SPEI via data-pipeline/indicators.py (same gates, window 1981–2020)
├── 03_imd_district.py         # IMD grid → 724 districts (same zonal semantics)
├── 04_compare.py              # the comparison suite (below)
├── 05_fdr_trends.py           # BH-FDR district trend-map view (extends the v1.0 demonstration)
└── README.md
```

Comparison suite (by season: JJAS, ONDJ, annual; by region: state clusters; per indicator where IMD supports it):

| Metric | Definition |
|---|---|
| Pearson r | era B vs IMD monthly series per district/region/season |
| Bias, RMSD | mean and root-mean-square difference (indicator units) |
| Drought-class agreement | share of district-months in the same McKee class |
| Event match rate | v1.0 event machinery run on both series; share of months where both flag drought |
| Trend-map FDR view | MK + Sen per district on both records; BH q = 0.05 |

Deliverables: `validation_report.json` + a validation memo (Markdown) + the Methodology-page-v2 section (docs/v2/04 §5). **Rule: numbers come only from Owner-executed runs; pending runs leave the memo sections explicitly marked, never filled with synthetic values.**

## 6. Era A ↔ Era B cross-validation (`validation-studies/crossval/`)

Standing panel at the 1981–2020 overlap (task M6.6):

- Input: era A SPEI (Atlas) vs era B SPEI (v1.0), matched district-months, matched timescale (the Atlas timescales govern; if the Atlas provides SPEI-12 only at matching definition, compare that; document all mismatches).
- Metrics: r, bias, RMSD, class agreement, event match rate, severity-class match; per-district discrepancy map (`era_b − era_a` diverging ramp).
- Output: `data/parquet/cross_validation/overlap_1981_2020.parquet` (schema: `district_id, date, era_a_value, era_b_value, diff, event_match, class_match`).
- Interpretation guardrail: differences are expected and *are the content* — different P/PET chains (Atlas vs CHIRPS/ERA5-Land), different PET methods (§3.5), different fitting windows. The panel documents them; it does not average them away. Era A and era B are never spliced into one series.

## 7. QA and validation standards (global)

Inherited three-tier discipline (software testing → statistical calibration → scientific consistency):

1. **Software:** every pipeline gets a seed-deterministic synthetic-world self-test (`selftest.py` for era B stays green; `selftest_gcm.py`; `selftest_atlas.py`). Numeric regression baseline (M1.9) protects v1.0 behaviour across refactors.
2. **Statistical calibration:** the v1.0 per-fit gates (mean ±0.2, sd 0.75–1.3, ≥ 20 base years, Gringorten fallback) apply to every standardised product in every era. Fit reports (`_report.json`) are written per run and auditable.
3. **Release gates:** per-indicator completeness ≥ 90 % inside availability window (70 % hard fail), pooled base-period stats within ±0.25 / 0.70–1.40, physical limits (z within ±4 era B; [−5, +5] clip era C), complete classification coverage; era C additionally gated by `08_validate_gcm.py` (CMIP6 release gate, register §6).
4. **Provenance:** every run writes JSON metadata (parameters, source identifiers, months available, checksums); manifests carry SHA-256; every config parameter lives in a config file, never in code.
5. **Missing data:** never imputed anywhere; gaps are rows-absent, rendered as no-data, counted in every statistic.
6. **Boundary/licence policy:** geometry redistributions carry attribution + source disclaimers; separable layers; licence verification precedes any new geometry (tehsil gate) or dataset integration.

## 8. Data contracts

### 8.1 Parquet long-format schema (all eras)

Core columns (era-spanning queries work via UNION ALL):

| Column | Type | Notes |
|---|---|---|
| `district_id` | string (dictionary) | v1.0 registry id (slug, e.g. `andhra-pradesh-anantapur`); tehsil-grain files (if added) use `tehsil_id` |
| `year` | int16 | |
| `month` | int8 | 1–12 |
| `value` | float32 | standardised index, anomaly %, or VCI % |

Era-optional columns added only where needed (DuckDB handles missing columns per file): `model_id` (per-model partitions), `scenario` (`ssp245|ssp585`), `stat` (`median|p25|p75|agreement_moderate|agreement_severe|dir_agreement_drier`), `source_id`, `flag` (`ok|missing|censored|buffered`). Long format (not wide) is a locked decision: cross-variable SQL joins (`SPI-3 × SPEI-3` for one district) become trivial; adding a variable adds files, not rewrites.

### 8.2 `catalog.json` (UI's source of truth, loaded on boot, ~2 KB)

```json
{
  "version": "2.0.0",
  "eras": {
    "observed":    { "label": "Observed 1981–2025",   "years": [1981, 2025], "path": "data/parquet/observed" },
    "atlas":       { "label": "Atlas 1901–2025",      "years": [1901, 2025], "path": "data/parquet/atlas" },
    "projections": { "label": "CMIP6 2026–2100",      "years": [2026, 2100], "path": "data/parquet/projections" }
  },
  "variables": [
    { "id": "spi_03", "label": "SPI-3", "unit": "z", "eras": ["atlas", "observed", "projections"],
      "files": { "observed": ["data/parquet/observed/variable=spi_03/part-0.parquet"],
                 "atlas":    ["data/parquet/atlas/variable=spi_03/year=1901/part-0.parquet", "…"],
                 "projections": { "ssp245": ["…"], "ssp585": ["…"] } } }
  ],
  "national": "data/parquet/_national_monthly.parquet",
  "crossval": "data/parquet/cross_validation/overlap_1981_2020.parquet",
  "status": "data/status.json"
}
```

Rules: exact paths only (plain static hosts cannot list directories — no HTTP globbing); relative paths stored, absolutised with `location.origin + '/'` at query-build time (DuckDB httpfs does not resolve relative paths); the JS builds `read_parquet([...])` argument lists from this catalog.

### 8.3 `pipeline_manifest.json` v2 (extends v1.0 manifest)

Adds: `base_period`, `bias_correction {method: QDM, reference, target_grid}`, `pet_formula` per era, `distributions {SPI: gamma, SPEI: log-logistic}`, `bounds` per era, `scenarios`, `n_models`, `model_list`, `era_c_start`, and SHA-256 checksums for every shipped product — alongside the existing v1.0 run parameters (which remain intact for the era B record).

### 8.4 `metadata.json` extension policy

v1.0 keys untouched. Additions: `eras` block (id, label, years, sources, reference windows, PET method, standardisation notes); per-era variable definitions with availability windows; era banner copy strings. Every UI classification/palette/threshold continues to be read from this file (v1.0 contract), so new eras become data changes, not code changes.

## 9. References for methods (verify details at implementation time; full catalogue in the Owner's references file)

- QDM: Cannon, Sobie & Murdock (2015), *J. Climate* 28, 6938–6959; South-Asia CMIP6 practice: Mishra, Bhatia & Tiwari (2020), *Sci. Data* 7, 195.
- Hargreaves PET: Hargreaves & Samani (1985); FAO-56 (Allen et al. 1998) Ra equations.
- SPI: McKee et al. (1993); Stagge et al. (2015) distribution evaluation. SPEI: Vicente-Serrano et al. (2010); L-moment fitting: Beguería et al. (2014), Hosking (1990). Gringorten (1963).
- Drought Atlas of India: Chuphal et al. (2024) *Sci. Data* 11:7; v2 release Zenodo 10.5281/zenodo.20368514 (**verify**).
- IMD grids: Pai et al. (2014) *Mausam* 65, 1–18 (rainfall); Srivastava et al. (2009) *Atmos. Sci. Lett.* (temperature — verify current product).
- Existing v1.0 method citations remain authoritative for era B (see `manuscript/main.tex`).

