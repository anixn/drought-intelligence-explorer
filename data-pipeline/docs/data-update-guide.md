# Data Update Guide — Drought Intelligence Explorer (India)

**How to download real data, prepare it, and keep the application current —
with Python (reference) or R.**

This guide covers the whole data workflow:

1. [What the app needs](#1-what-the-app-needs) — the data contract,
2. [One-time setup](#2-one-time-setup) — environment and credentials,
3. [Source catalogue](#3-source-catalogue) — what to download and from where,
4. [First backfill](#4-first-time-backfill-1981present) — build the full
   research dataset once,
5. [The quarterly runbook](#5-quarterly-update-runbook) — the routine you
   repeat every few months (≈ 30–60 minutes of mostly unattended time),
6. [Switching the app to research mode](#6-switching-the-app-to-research-mode),
7. [Methodology parameters](#7-methodology-parameters-and-where-they-live),
8. [Quality assurance](#8-quality-assurance),
9. [Automation](#9-automation),
10. [Licensing and attribution](#10-licensing-and-attribution),
11. [Troubleshooting](#11-troubleshooting).

---

## 0. Verified status of this pipeline (2026-10-31)

| Item | Status |
|---|---|
| CHIRPS v3.0 monthly endpoint | **Live-checked**: `chirps-v3.0.2026.09.tif` exists (~23 MB); 2026-10 not yet published (normal ~3-week lag) |
| Real-data path (CHIRPS → clip → district statistics) | **Verified with live data**: September 2026 rainfall aggregated over the shipped 724-district geometry; wettest = Andaman/Uttarakhand, driest = Jaisalmer/Leh, as expected |
| ERA5-Land / MODIS download modules | Written against the current documented CDS and Earthdata APIs; **require your credentials** — not executable in this environment |
| Compute chain (zonal → indicators → export → validate) | **Verified offline end-to-end** by `python selftest.py` (46 checks, includes an injected 2015 drought recovered in SPI-3/VCI, missing-data propagation, contract conformance, and GEE series parsing/assembly) |
| QA module | Cross-checked against the shipped 1981–2025 research dataset: **0 errors**, 0 warnings (39 checks) |

---

## 1. What the app needs

The application is a pure static site; everything it reads lives in `data/`.
The pipeline (this folder) exists to produce those files from real sources.

| File | Format | Produced by | Notes |
|---|---|---|---|
| `data/drought/spi_01,03,06,12.csv`, `spei_01,03,06,12.csv`, `soil_moisture.csv`, `vci.csv` | Wide CSV: `district_id,district_name,state_name,` then one `YYYY-MM` column per month; empty cell = missing | `export_app` step | ~0.9 MB per indicator; gzip ≈ 0.3 MB over the wire |
| `data/districts.csv`, `data/states.csv` | registries: ids, names, equal-area km², centroids | **already shipped** (from `data-pipeline/prepare_boundaries.py`) | keep stable — ids must match boundary ids |
| `data/boundaries/*.geojson` | district/state/outline polygons, EPSG:4326 | **already shipped** | see §11 if you need a newer district vintage |
| `data/metadata.json` | indicators, thresholds, palette, provenance — single source of truth | patched by `export_app` | thresholds stay untouched unless you change them |
| `data/summaries/drought_events_spi_06.csv`, `state_statistics_spi_06.csv` | precomputed cross-checks | `export_app` | linked from the app's Download Centre |
| `data/pipeline_manifest.json` | run parameters + SHA-256 of every output | `export_app` | provenance record |

**Indicator definitions** (from `metadata.json`): SPI/SPEI at 1/3/6/12 months
(z-scores, 9-class McKee/Vicente-Serrano thresholds at ±0.5/1.0/1.5/2.0),
Soil-Moisture Anomaly in % (classes at −5/−15/−30/−50), VCI in %
(Kogan classes at 10/20/30/40).

**Data flow**

```
data_raw/                       (never committed — see .gitignore)
  chirps/  chirps-v3.0.YYYY.MM.tif        rainfall, 0.05°
  era5land/  era5land_YYYY.nc             PET + soil moisture, 0.1°
  modis/YYYY/*.hdf or appeears/*.tif      NDVI, 1 km
        │  step 2: prepare_rasters  (clip to India, harmonise units)
        ▼
data_processed/rasters/{precip,pet,soil,ndvi}/YYYY-MM.tif
        │  step 3: zonal_stats     (area-weighted district means, pixel counts)
        ▼
data_processed/series/*.csv
        │  step 4: indicators      (SPI, SPEI, SMA, VCI)
        ▼
data_processed/indicators/*.csv
        │  step 5: export_app      (wide CSVs, metadata, summaries, manifest)
        ▼
<repo>/data/**    →  git commit  →  GitHub Pages
```

Every step is idempotent — re-running `python run.py update` only fetches
months missing on disk.

> **Google Earth Engine alternative:** if you already have an Earth Engine
> project, `python run.py gee --project ee-yourname --end 2025-12` replaces
> steps 1–3 (download → prepare → zonal) with GEE compositing and district
> aggregation, then runs the same indicator/export/validate chain. See
> **`gee-update-guide.md`** for setup, dataset mapping and caveats.

---

## 2. One-time setup

### 2.1 Python environment (reference pipeline)

```bash
cd drought-intelligence-explorer/data-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python selftest.py          # must print: SELF-TEST PASSED
```

Python ≥ 3.10. On Linux the binary wheels of `rasterio`/`pyproj` install
without system packages.

### 2.2 Copernicus CDS account (for ERA5-Land: PET + soil moisture)

1. Register at <https://cds.climate.copernicus.eu/> (free).
2. Open your **profile page** and copy the **API key / personal access
   token**; the page shows the exact snippet to use.
3. Create `~/.cdsapirc` (permission 600, never commit it):

   ```
   url: https://cds.climate.copernicus.eu/api
   key: <your-personal-access-token>
   ```

4. Open the dataset page
   <https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means>,
   and **accept the licence** when prompted (Copernicus licence: free use
   with attribution).

### 2.3 NASA Earthdata account (for MODIS NDVI)

1. Register at <https://urs.earthdata.nasa.gov/> (free).
2. Create `~/.netrc` (permission 600, never commit it):

   ```
   machine urs.earthdata.nasa.gov
       login <your-earthdata-username>
       password <your-earthdata-password>
   ```

3. Log in once at <https://lpdaac.usgs.gov/> and
   <https://appears.earthdatacloud.nasa.gov/> with "Earthdata Login" so the
   products are visible to your account.
4. `pip install earthaccess` — NASA's client library for the Earthdata
   Cloud. MOD13A3 left the retired `e4ftl01.cr.usgs.gov` archive and is
   now served from `data.lpdaac.earthdatacloud.nasa.gov`; `earthaccess`
   does the CMR search + bearer-token authentication for you.

> The application itself never needs any credential or key — all keys stay
> on **your** machine, in `~/.cdsapirc` / `~/.netrc`, used only by this
> offline pipeline.

---

## 3. Source catalogue

| Variable | Primary source | Resolution | Record | Lag | Licence |
|---|---|---|---|---|---|
| Rainfall (SPI/SPEI) | **CHIRPS v3.0 monthly** — <https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/> | 0.05° | 1981→present | ~3 weeks | CC BY 4.0 / public domain |
| PET + soil moisture (SPEI, SMA) | **ERA5-Land monthly means** — CDS `reanalysis-era5-land-monthly-means` | 0.1° | 1950→present | ~2–3 months | Copernicus (attribution) |
| NDVI (VCI) | **MODIS/Terra MOD13A3 v061** — LP DAAC / AppEEARS | 1 km | 2000-02→present | ~1 month | NASA open |
| Rainfall (national alternative) | **IMD 0.25° gridded** — <https://imdpune.gov.in/cmpg/Griddata/Download.html> | 0.25° | 1901→present | yearly release | IMD terms (free registration) |
| Soil moisture (alternative) | ESA CCI SM — <https://esa-soilmoisture-cci.org/> | 0.25° | 1978→present | 6–12 months | CCI/ESA open |

Notes on choices (all editable in `config.yaml`):

- **CHIRPS vs IMD**: IMD's own gauge-based grid is the national reference
  for SPI; its portal requires manual (registration) downloads and yearly
  releases, which is why CHIRPS v3 (satellite+gauge blend, monthly, no
  auth, 40-year record) is the pipeline default. To use IMD instead: place
  yearwise `.grd` files in `data_raw/imd/` and run
  `python -m die_pipeline.prepare_rasters --source imd`
  (needs `pip install imdlib`; the R package `imdR` offers the same for the
  R route — verify availability on CRAN). **Do not mix** IMD and CHIRPS
  across the same months: the climatology must come from one source.
- **CHIRPS v2 is retiring**: production of v2.0 ends after December 2026;
  this pipeline targets v3.0 (citation: Funk et al., 2026).
- **ERA5-Land variables used**: `potential_evaporation` (m/day mean,
  negative by ECMWF convention → PET mm/month = |pe| × 1000 × days), and
  `volumetric_soil_water_layer_1..3` (0–100 cm mean → % volumetric ×100).
  Annual PET over India should land roughly between 1000 and 1800 mm —
  check this once (§9).
- **MODIS tiles covering India** (17): `h23v05 h23v06 h24v05 h24v06 h24v07
  h24v08 h25v05 h25v06 h25v07 h25v08 h26v05 h26v06 h26v07 h26v08 h27v06
  h27v07 h27v08` — recomputed for any bbox with
  `python -m die_pipeline.download_modis_ndvi --compute-tiles`.

---

## 4. First-time backfill (1981→present)

```bash
cd data-pipeline && source .venv/bin/activate

python -m die_pipeline.download_chirps     --backfill 1981   # ~13 GB, resumable
python -m die_pipeline.download_era5land    --backfill 1981   # CDS queue, per-year requests
# NDVI: EITHER the scripted route (2000-present, ~17 tiles/month):
python -m die_pipeline.download_modis_ndvi  --backfill 2000
# OR the AppEEARS route (recommended for the one-time backfill):
#   1. https://appears.earthdatacloud.nasa.gov/ -> Area Sample
#   2. polygon = India (or the config bbox), start 2000-01-01 .. now
#   3. layer: MOD13A3 v061 -> "1 km monthly NDVI", projection Geographic,
#      format GeoTIFF
#   4. extract the downloaded .tif files into data_raw/appeears/
#      (if the request exceeds the AppEEARS area limit, split north/south)

python run.py update          # prepare -> zonal -> indicators -> export -> validate
```

**Disk budget** (raw → processed): CHIRPS ~13 GB → ~0.5 GB; ERA5-Land
~4 GB → ~1 GB; MODIS ~10 GB → ~4 GB. Keep ~30 GB free. `data_raw/` and
`data_processed/` are git-ignored — only `data/` (≈ 10 MB) is committed.

**Runtime**: downloads run unattended (hours, dominated by CHIRPS/MODIS);
the compute chain takes roughly 20–60 minutes for 724 districts × ~550
months (zonal rasterisation is cached per grid; distribution fitting is
~8,700 gamma + log-logistic fits per indicator family).

---

## 5. Quarterly update runbook

Repeat every ~3 months (CHIRPS lags ~3 weeks, ERA5-Land ~2–3 months, so
each run typically adds 2–3 new months):

```bash
cd drought-intelligence-explorer/data-pipeline
source .venv/bin/activate

python run.py update                    # fetch missing months, recompute, export
python run.py status                    # inventory sanity check
python run.py validate                  # contract + science QA (must be 0 errors)
```

Review the console output, then:

1. **Bump `methodology_version`** in `config.yaml` → `app_metadata` when
   needed — the browser caches datasets keyed by this version
   (`data-loader.js` `cacheKey`), so **every data refresh must change it**
   or returning visitors keep seeing stale data. e.g.
   `research-1.0.0` → `research-1.1.0` (data update), `research-2.0.0`
   (method change).
2. Optionally pin the exported end month (uniform period) in
   `config.yaml` → `export.period_end` — otherwise the exporter ends at
   the latest month of any indicator, and SPEI/SMA may lag SPI by a month
   or two (shown as N/A in the app; honest but sometimes untidy).
3. Commit and deploy:

```bash
cd ..
git add data/
git commit -m "Data update through YYYY-MM (research vX.Y.Z)"
git push                                  # GitHub Pages redeploys automatically
```

4. Spot-check the live site: national map for the newest month, one
   district time series, the Data Sources dialog (period + completeness),
   and the Download Centre links.

> The shipped `data/` folder already holds the observed 1981–2025 dataset;
> `run.py update` or `run.py gee` refresh it in place. The synthetic
> generator is only for offline UI testing — if you want to try it, use a
> throwaway checkout or a git branch (`git branch demo-data`).

---

## 6. Switching the app to research mode

The first real export does most of the work automatically
(`data_mode: "static-research"`, provenance, sources with access dates,
period, reference period, manifest). Four groups of wording are **static
HTML/JS** and need a one-time manual edit — search for "demonstration"
(case-insensitive) and "synthetic" in `index.html` and `assets/js/`:

| Where | What to change |
|---|---|
| `index.html` line ~50 | `#chipDemo` chip: "Demonstration · synthetic" → e.g. "Research data · CHIRPS/ERA5-Land/MODIS" |
| `index.html` lines ~57–61 | remove the `#demoBanner` block |
| `index.html` lines ~181/188/194/200 | remove the `kpi-demo-tag` "demo" chips on the KPI cards |
| `index.html` line ~232 and ~396 | map corner tags "Demonstration data · synthetic" → "Research data" |
| `index.html` lines ~7, ~468, ~496, ~498 | meta description, intro and methodology paragraphs — replace the synthetic-dataset wording with your data description (the guide text in `docs/methodology.md` is a good source) |
| `app.js` lines ~270, ~274, ~532, ~734, ~763, ~935 | footer/toast/citation strings: "demonstration build (synthetic data)" → "research build"; drop the "seed …" clause |
| `analytics.js` line ~428 | CSV export source tag `'synthetic-demonstration'` → `'research'` |
| `README.md` | update the demonstration-mode notice at the top |

Nothing here touches computation — all analytics, classification and KPIs
read from `metadata.json` at run time.

---

## 7. Methodology parameters and where they live

| Parameter | Where | Default |
|---|---|---|
| Base (climatology) period SPI/SPEI/SMA | `config.yaml` → `base_period.spi_spei` | 1981–2020 (WMO-style 30 y) |
| VCI base period | `config.yaml` → `base_period.vci` | 2000–present |
| Minimum base years to fit | `config.yaml` → `min_base_years` | 20 (30 recommended) |
| Export window | `config.yaml` → `export` | 1981-01 → latest (VCI from 2000-02) |
| Severity thresholds & colours | `data/metadata.json` → `indicators[].classes` | SPI/SPEI 9-class; SMA −5/−15/−30/−50; VCI 10/20/30/40 |
| SMA statistic | `config.yaml` → `indicators` (`percent_mean` or `zscore`) | percent-of-mean (matches SMA classes) |
| Event definition | `data/metadata.json` → `events` | runs below −1.0, ≥ 3 months |

If you change thresholds in `metadata.json`, keep `docs/methodology.md`
and the class labels consistent — the legend, map, charts and comparison
modules all follow metadata automatically.

Fitting details (documented in `die_pipeline/indicators.py`): SPI uses the
gamma distribution with the mixed-distribution zero handling
(McKee et al., 1993; NCAR convention); SPEI uses a three-parameter
log-logistic fitted with the **L-moment (probability-weighted-moment)
closed-form estimator** of Vicente-Serrano et al. (2010) / Singh et al.
(1993) — the method used by the reference R `SPEI` package — **with a
base-period calibration check**: any district-month whose parametric fit
fails |mean(z)| ≤ 0.2 / sd(z) ∈ [0.75, 1.3] falls back to the
distribution-free Gringorten plotting-position transform (average ranks
for tied values). Counts of both routes are printed per run and stored in
`data_processed/indicators/_report.json`. Note: do not switch SPEI back to
`scipy.stats.fisk.fit` MLE — at the operational 30–40 base years the MLE
location collapses onto the sample minimum, which biases SPEI wet by
~+0.8 z and sends ~94% of fits to the fallback (this was the 2026-11-02
build's SPI/SPEI anomaly).

---

## 8. Quality assurance

`python run.py validate` (automatic, exit code non-zero on errors):

- **Contract**: month columns inside the declared period, district ids
  match registry *and* boundaries, no duplicate rows, no non-numeric cells,
  completeness per indicator (warn < 90%, fail < 70%), every finite value
  falls in exactly one metadata class, value limits.
- **Science**: pooled SPI-6 mean ≈ 0 and sd ≈ 1, national-series lag-1
  autocorrelation, SPI-6 vs SPEI-6 correlation (expect ≈ 0.4–0.95),
  summaries and manifest present.

Manual spot-checks worth doing after the first backfill (and occasionally
afterwards):

1. **Known events** — the map for the monsoon seasons of 2002, 2009,
   2015–16 and 2018–19 must show widespread deficit (SPI-3/SPI-6 ≤ −1)
   over northwest/peninsular India; 2020 and 2022 should look wetter.
   Compare against IMD's published SPI bulletins and monsoon reports.
2. **Climatology sanity** — long-term mean annual rainfall from your
   district series: Meghalaya/Western Ghats high, West Rajasthan low;
   PET annual totals ~1000–1800 mm.
3. **VCI seasonality** — NDVI-derived VCI should dip visibly in dry-season
   rabi stress years, with monsoon cloud gaps appearing as missing cells.
4. **Pixel counts** — `data_processed/series/*.csv` carries
  `valid_pixel_count` / `total_pixel_count`; small districts should be
  non-zero (the all-touched fallback handles sub-pixel districts).

---

## 9. Automation

Local cron (simplest; keeps all credentials on your machine):

```cron
# 09:00 on the 15th of Jan/Apr/Jul/Oct — quarterly refresh
0 9 15 1,4,7,10 * cd /path/to/drought-intelligence-explorer/data-pipeline \
  && /path/to/.venv/bin/python run.py update >> update.log 2>&1
```

GitHub Actions is possible (CDS token and Earthdata credentials as
encrypted repository secrets; the workflow checks out the repo, installs
requirements, runs the update, commits `data/` and pushes). The static app
itself still contains no keys. For a research site, the manual runbook
(§5) is preferred: each update is reviewed before it goes public.

---

## 10. Licensing and attribution

Record these citations (the exporter writes them into
`metadata.json` → `sources` with access dates automatically from
`config.yaml`):

- **CHIRPS v3.0** — Funk, C., et al. (2026). The Climate Hazards Center
  Infrared Precipitation with Stations, Version 3. *Scientific Data* 13,
  718. <https://doi.org/10.1038/s41597-026-07096-4>. Data repository
  DOI <https://doi.org/10.15780/G2JQ0P>. CC BY 4.0 / public domain.
- **ERA5-Land** — Muñoz-Sabater, J., et al. (2021). ERA5-Land: a
  state-of-the-art global reanalysis dataset for land applications.
  *Earth System Science Data*, 13, 4349–4383.
  <https://doi.org/10.5194/essd-13-4349-2021>. Copernicus CDS licence
  (free use with attribution).
- **MOD13A3 v061** — Didan, K. (2015). MOD13A3 MODIS/Terra Vegetation
  Indices Monthly L3 Global 1 km SIN Grid V061. NASA EOSDIS Land Processes
  DAAC. <https://doi.org/10.5067/MODIS/MOD13A3.061>. NASA open data.
- **IMD gridded rainfall** (if used) — Pai, D. S., et al. (2014).
  Development of a new high spatial resolution (0.25° × 0.25°) long period
  (1901–2010) daily gridded rainfall data set over India. *MAUSAM*, 65(1),
  1–18. Comply with IMD's data-use terms.
- **Method citations** — McKee, Doesken & Kleist (1993); Vicente-Serrano,
  Beguería & López-Moreno (2010); Kogan (1995); Yevjevich (1967).
- **Boundaries** — community-maintained (2011-census demarcation); they
  carry no political endorsement and are not authoritative for legal
  boundary determination. Verify the licence of the boundary source you
  use before redistribution.

**District vintage**: the shipped set has 724 districts (36 states/UTs).
Districts created after the 2011 census are not represented. If you switch
to a newer boundary set, regenerate registries with
`data-pipeline/prepare_boundaries.py <new_districts.geojson> .` — note this
**changes district ids** and is a breaking change for saved URLs and the
demonstration dataset.

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| CHIRPS month returns 404 | Not published yet (final product ~3rd week of the next month). The script skips and reports it; re-run later. |
| `unexpected CRS ... EPSG["9122"]` in a raw tif | Handled since 2026-10-31: CHIRPS tags its WGS 84 degree grid with the 2-D code 9122; `prepare_rasters` accepts 4326 and 9122 alike. Only a genuinely non-WGS84/non-degree grid still stops the run. |
| MODIS: *every* month "not on server yet", 0 failures | You are running the pre-2026-10-31 downloader against the retired `e4ftl01.cr.usgs.gov` host. Update `download_modis_ndvi.py` (now uses CMR + `earthaccess`) and `pip install earthaccess`. |
| CDS: *not authorised* / 403 | Licence not accepted on the dataset page, or `~/.cdsapirc` missing/typo. Never paste the token into the repo. |
| CDS requests stuck in queue | Normal at busy times; requests are split per year. Check <https://status.copernicus.eu/>. |
| ERA5-Land PET looks absurd | Check the units path once: monthly mm = \|pe\| × 1000 × days-in-month; annual totals ~1000–1800 mm. `prepare_rasters` reads the `units` attribute and reports what it assumed. |
| MODIS `.hdf` unreadable | Your GDAL lacks HDF4. Easiest fix: use the AppEEARS route (GeoTIFF). Otherwise install GDAL with HDF4 (conda-forge). |
| App shows old data after an update | Browser cache: `methodology_version` must change with every data update (§5 step 1). |
| SPI/SPEI all-NaN for a district-month | Fewer than `min_base_years` base years, or < 8 valid base values — extend `history.start` or lower `min_base_years` (not below 20). |
| `validate` flags completeness < 90% (VCI) | Real monsoon cloud gaps in MODIS NDVI — expected; document it. Persistent < 70% means a download gap: check `python run.py status`. |
| Duplicate/unknown district ids | Boundaries and registries out of sync — regenerate registries with `data-pipeline/prepare_boundaries.py`, keep ids stable. |
| Windows issues | Use WSL, or adapt paths; `.netrc` is named `_netrc` on Windows. |

---

## 12. File manifest of this pipeline

```
data-pipeline/
├── README.md                 quickstart
├── requirements.txt
├── config.yaml               every knob: periods, sources, QA thresholds
├── run.py                    orchestrator (update/status/validate/selftest/…)
├── selftest.py               offline end-to-end test (no network, no keys)
├── .gitignore                keeps data_raw/, data_processed/, .venv/ out of git
├── die_pipeline/
│   ├── common.py             config, paths, month utils, app contract, wide-CSV I/O
│   ├── download_chirps.py    CHIRPS v3.0 monthly (no auth)
│   ├── download_era5land.py  ERA5-Land monthly means (CDS API)
│   ├── download_modis_ndvi.py MOD13A3 v061 tiles (Earthdata) + tile computation
│   ├── prepare_rasters.py    clip / units / nc→tif / hdf→tif / AppEEARS / IMD
│   ├── zonal_stats.py        area-weighted district means + pixel counts
│   ├── indicators.py         SPI, SPEI, SMA, VCI
│   ├── export_app.py         wide CSVs, metadata patch, summaries, manifest
│   └── validate.py           contract + science QA
├── r_alternative/
│   ├── drought_indices.R     R port (terra/sf/SPEI/jsonlite)
│   └── README.md
└── docs/
    └── data-update-guide.md  this document
```
