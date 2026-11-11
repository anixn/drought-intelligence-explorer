# Data pipeline — Drought Intelligence Explorer (India)

Offline Python (reference) and R pipelines that turn public gridded
datasets into the application's static data bundle, so the web app itself
stays backend-free and key-free.

**Read `docs/data-update-guide.md` first** — it contains the source
catalogue (verified URLs), credential setup, the first-time backfill, and
the quarterly update runbook.

## Quickstart

```bash
cd data-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python selftest.py          # offline end-to-end test — must PASS
python run.py status        # what is on disk / what the app currently holds
python run.py update        # download missing months -> compute -> export -> validate
```

`python run.py indicators` also refreshes `../data/` and validates the result,
so there is no manual copy from `data_processed/`.

Credentials (only the download steps need them; the app never does):

- `~/.cdsapirc` — Copernicus CDS key, for ERA5-Land (PET + soil moisture)
- `~/.netrc` — NASA Earthdata login, for MODIS NDVI tiles
- CHIRPS v3.0 rainfall needs no account

### Google Earth Engine route (no gridded downloads)

If you have an Earth Engine project, GEE can replace steps 1–3
(download → prepare → zonal) and produce the same district-month series.
Steps 4–6 (indicators → export → validate) are unchanged:

```bash
cd data-pipeline
python run.py gee --project ee-yourname --end 2025-12
```

This builds the historical dataset through **2025-12** into `data/`
(SPI/SPEI/SMA/VCI, metadata, summaries, manifest). Setup, dataset mapping,
checkpointing, caveats (GEE serves CHIRPS v2.0, not v3.0) and troubleshooting
are in **`docs/gee-update-guide.md`**. Only the extraction step needs
`earthengine-api` and one `earthengine authenticate`; the web app stays
backend-free and key-free.

## What it produces

Into the repository's `data/` folder (all committed to git, ~20 MB):

- `drought/spi_01|03|06|12.csv`, `spei_01|03|06|12.csv`,
  `soil_moisture.csv`, `vci.csv` — wide district × month matrices
- `metadata.json` — provenance switched to `static-research`
  (thresholds/palettes preserved)
- `summaries/drought_events_spi_06.csv`, `summaries/state_statistics_spi_06.csv`
- `pipeline_manifest.json` — run parameters + SHA-256 checksums

SPI, SPEI and SMA cover the full **1981-01 … 2025-12** archive (multi-month
SPI/SPEI series necessarily begin a few months later while their first rolling
window fills). VCI starts at the first MODIS NDVI month (**2000-02**). Each
indicator entry in `metadata.json` therefore carries `available_from`,
`available_to`, `available_months` and `completeness_pct`; the dashboard uses
these to label and clamp its analysis window instead of pretending VCI has
1980s data.

The app reads **only** the files above. Intermediate tables stay in
`data_processed/` and are not loaded by `index.html`:

| Path | Format | Read by the app? |
|---|---|---|
| `data/drought/*.csv` | wide: `district_id,district_name,state_name,YYYY-MM,…` | yes |
| `data_processed/series/*.csv` | long: `district_id,district_name,state_name,date,mean,valid_pixel_count,total_pixel_count` | no |
| `data_processed/indicators/*.csv` | long: `district_id,date,value` | no |

After an extraction, rebuild the app files from the intermediate indicator
tables with `python run.py export` (which also validates), or run
`python run.py gee --skip-extract` to execute indicators → export → validate.
The extraction step alone never writes to `data/`.

## Steps (each runnable alone)

| Command | Purpose |
|---|---|
| `python -m die_pipeline.download_chirps` | CHIRPS v3.0 monthly rainfall (no auth) |
| `python -m die_pipeline.download_era5land` | ERA5-Land monthly means (CDS) |
| `python -m die_pipeline.download_modis_ndvi` | MOD13A3 v061 NDVI tiles (Earthdata) |
| `python -m die_pipeline.prepare_rasters` | clip + unit harmonisation → monthly GeoTIFFs |
| `python -m die_pipeline.zonal_stats` | area-weighted district means + pixel counts |
| `python -m die_pipeline.indicators` | SPI, SPEI, SMA, VCI |
| `python -m die_pipeline.export_app` | write the app contract |
| `python -m die_pipeline.validate` | contract + science QA |
| `python -m die_pipeline.gee_export` | GEE extraction (alternative to the first five rows) |

`python run.py <command>` wraps them with the shipped `config.yaml`.
`python run.py gee` wraps GEE extraction + indicators + export + validate.

## Scientific method (summary)

- **SPI** (McKee et al., 1993): k-month rolling precipitation totals,
  two-parameter gamma per district & calendar month over the base period,
  mixed-distribution zero handling, inverse-normal transform.
- **SPEI** (Vicente-Serrano et al., 2010): water balance P − PET
  (PET from ERA5-Land), 3-parameter log-logistic with a base-period
  calibration check and a Gringorten plotting-position fallback.
- **SMA**: percent-of-mean volumetric soil-water anomaly per calendar
  month (ERA5-Land layers 1–3).
- **VCI** (Kogan, 1995): per-calendar-month NDVI rescaling between the
  MODIS-era minimum and maximum.
- District aggregation: cos(latitude)-weighted pixel means, with
  valid/total pixel counts; districts smaller than a pixel are captured
  with an all-touched rasterisation fallback.

Full details and parameter locations: `docs/data-update-guide.md` §8 and
the module docstrings.

## R users

`r_alternative/drought_indices.R` mirrors the pipeline with
`terra`/`sf`/`SPEI`/`jsonlite`. See `r_alternative/README.md` — validate
it against the Python output on one month before using it for live
updates.

## Verified status (2026-10-31)

- CHIRPS v3.0 endpoint live-checked (final months available through
  2026-09).
- **Real-data micro-test**: one live CHIRPS month (2026-09) downloaded,
  clipped and aggregated over the shipped 724-district geometry — district
  means match September climatology (Andaman wettest, West Rajasthan and
  Ladakh driest).
- Compute chain verified offline by `selftest.py` (synthetic world with an
  injected 2015 drought; 82 assertions).
- `validate.py` exercised end-to-end inside the self-test: 0 errors.
- CDS/Earthdata download modules follow the current documented APIs and
  need your credentials to run.
