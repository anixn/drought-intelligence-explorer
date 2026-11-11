# Google Earth Engine route — build the historical dataset to 2025-12

This route replaces the three download/preparation steps of the reference
pipeline with **Google Earth Engine (GEE)**:

```
reference:  download_chirps / era5land / modis
            -> prepare_rasters -> zonal_stats
GEE route:  gee_export (Earth Engine compositing + district aggregation)
            -> indicators -> export_app -> validate
```

Only steps 1–3 change. The scientific transforms (SPI, SPEI, SMA, VCI), the
wide-CSV contract, `metadata.json`, summaries, manifest and validation are
the **same code** as the reference pipeline. That is deliberate: Earth Engine
is excellent at monthly compositing and zonal statistics, but it has no
per-district gamma/log-logistic maximum-likelihood fit, which SPI/SPEI need.

The GEE build is configured for a historical cut-off of **2025-12** and an
export window of **1981-01 … 2025-12** (override with `--export-start`).
SPI, SPEI and SMA use the full CHIRPS/ERA5-Land archive. VCI starts with MODIS
NDVI (2000-02), so the exporter records per-indicator `available_from` /
`available_to` fields and the app clamps VCI's analysis window accordingly.
Validation measures completeness inside each indicator's own availability
window rather than across the full 1981+ span.

> **CHIRPS version:** the Earth Engine catalog currently serves CHIRPS
> **v2.0 Final** (`UCSB-CHG/CHIRPS/DAILY`), while the local download route
> targets **v3.0**. The metadata written by this route records v2.0. Do not
> mix v2.0 and v3.0 inside one climatology.

---

## 1. What gets produced

| File under `data/` | Produced by | GEE role |
|---|---|---|
| `drought/spi_01…12.csv`, `spei_01…12.csv`, `soil_moisture.csv`, `vci.csv` | `indicators.py` + `export_app.py` | GEE supplies the four monthly district series (`precip`, `pet`, `soil`, `ndvi`) |
| `metadata.json` | `export_app.py` | GEE provenance, source citations, period, reference period |
| `summaries/drought_events_spi_06.csv`, `state_statistics_spi_06.csv` | `export_app.py` | none |
| `pipeline_manifest.json` | `export_app.py` | run parameters + SHA-256 checksums |
| `districts.csv`, `states.csv`, `boundaries/*.geojson` | **already shipped** | the district polygons are the GEE `reduceRegions` units |

Intermediate files (not committed, `.gitignore`d):

```
data-pipeline/data_processed/gee_chunks/<var>/YYYY-MM__YYYY-MM.csv
data-pipeline/data_processed/gee_chunks/_meta.json
data-pipeline/data_processed/series/{precip,pet,soil,ndvi}.csv
data-pipeline/data_processed/indicators/*.csv
```

---

## 2. One-time setup

### 2.1 Python environment

```bash
cd data-pipeline
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt
```

`earthengine-api` is included in `requirements.txt`.

### 2.2 Earth Engine account and project

1. Register for Earth Engine (free for research/education/non-profit):
   <https://earthengine.google.com/signup/>
2. Create or select a Google Cloud project with the **Earth Engine API**
   enabled: <https://console.cloud.google.com/earth-engine>
3. Authenticate once on this machine:

   ```bash
   earthengine authenticate
   ```

   This stores credentials under `~/.config/earthengine/` (Windows:
   `%USERPROFILE%\.config\earthengine\`).
4. Put the project id in `config.yaml`:

   ```yaml
   gee:
     project: "ee-yourname"     # or your Cloud project id
   ```

   or pass `--project ee-yourname` on every run, or set `EE_PROJECT`.

No key is ever written into the repository, and the web app itself never
talks to Earth Engine.

### 2.3 District asset (optional, recommended)

By default the script sends the local `data/boundaries/india_districts.geojson`
(724 polygons, ~480 KB) to Earth Engine with every request. That works, but
uploading it once as an asset is faster and avoids repeated payloads:

```bash
python run.py gee --project ee-yourname \
  --boundary-asset projects/ee-yourname/assets/india_districts_724 \
  --upload-boundary --end 2025-12
```

The first run creates the asset (a few minutes) and then uses it. Later runs
only need:

```bash
python run.py gee --project ee-yourname \
  --boundary-asset projects/ee-yourname/assets/india_districts_724 \
  --end 2025-12
```

You can also upload the GeoJSON manually in the Code Editor
(**Assets → New → Table upload**) and set `gee.boundary_asset` in
`config.yaml`. The asset must keep the `id` property (or provide
`district_id`); the script normalises either name.

---

## 3. Build the historical dataset

```bash
cd data-pipeline
python run.py gee --project ee-yourname --end 2025-12
```

That single command:

1. inspects each GEE collection and skips months not yet published;
2. computes monthly images and area-weighted district statistics in chunks
   (default 12 months per request), with automatic splitting on timeout;
3. writes/updates `data_processed/series/{precip,pet,soil,ndvi}.csv`;
4. runs `indicators.py` → `export_app.py` → `validate.py`;
5. writes the application dataset through **2025-12**.

Useful variants:

```bash
# default: full SPI/SPEI/SMA record (VCI starts at MODIS, 2000-02)
python run.py gee --project ee-yourname --end 2025-12

# shorter export, 2001-01 .. 2025-12
python run.py gee --project ee-yourname --end 2025-12 --export-start 2001-01

# extract only one or two variables (e.g. test the connection first)
python run.py gee --project ee-yourname --end 2025-12 --vars precip

# reuse completed GEE chunks and only recompute indicators/export/validate
python run.py gee --skip-extract --end 2025-12

# recompute all chunks (after changing datasets/periods)
python run.py gee --project ee-yourname --end 2025-12 --force

# extraction only (no indicators/export/validate)
python -m die_pipeline.gee_export --project ee-yourname --end 2025-12 --no-postprocess
```

`python -m die_pipeline.gee_export --project …` (module route) ALSO runs
indicators → export → validate automatically and writes the dashboard's
`data/` folder in the same command; `--no-postprocess` stops after the
series files. There is no manual copy step from `data_processed/` —
`export_app.py` writes straight into `../data/drought/`,
`../data/summaries/`, `../data/metadata.json` and
`../data/pipeline_manifest.json`, which is exactly what `index.html` reads.

A first full run over 1982–2025 is typically **1–3 hours** of mostly
unattended Earth Engine time (44 years × 4 variables, chunked). Completed
chunks are cached: re-running resumes at the first missing chunk. Use
`--chunk-months 6` if your project hits memory or timeout limits.

---

## 4. How the GEE statistics are calculated

### 4.1 Monthly images

| Variable | GEE asset | Monthly operation | Unit conversion |
|---|---|---|---|
| `precip` | `UCSB-CHG/CHIRPS/DAILY` | sum of daily `precipitation` | mm/day summed → mm/month |
| `pet` | `ECMWF/ERA5_LAND/MONTHLY_AGGR` | `potential_evaporation_sum` | `abs(x) × 1000` → mm/month |
| `soil` | `ECMWF/ERA5_LAND/MONTHLY_AGGR` | mean of `volumetric_soil_water_layer_1..3` | `× 100` → % volumetric (0–100 cm) |
| `ndvi` | `MODIS/061/MOD13A3` | `NDVI` | `× 0.0001` → fraction |

Invalid values are masked with the same `valid_range` as
`config.yaml → variables` (precip 0–4000 mm, PET 0–1500 mm, soil 0–60 %,
NDVI −0.2–1.0).

### 4.2 Area-weighted district mean

For every pixel the script builds four bands:

```
v = value × pixel area
w = pixel area          (only where the value is valid)
n = 1 where valid
t = 1 everywhere        (derived from n, so it shares the value projection)
```

and calls `reduceRegions(..., reducer=sum)`. Then

```
mean = Σv / Σw
valid_pixels = Σn
total_pixels = Σt
```

`ee.Image.pixelArea()` is used instead of a hand-made `cos(latitude)` weight,
so the same formula is exact for both the geographic CHIRPS/ERA5 grids
(pixels shrink with latitude) and the equal-area sinusoidal MODIS grid.

**Native grid.** Derived images do not carry projection metadata —
`ImageCollection.sum()` reports Earth Engine's default 1° grid — so the
script reads the CRS and affine transform from the first raw image and passes
them to `reduceRegions` (`crs`, `crsTransform`). Reductions therefore run on
the native CHIRPS 0.05°, ERA5-Land 0.1° or MODIS 926 m grid. The grid is
recorded per variable in `data_processed/gee_chunks/_meta.json`.

**Coverage weighting.** `reduceRegions` weights each pixel by the fraction of
its area inside the polygon, so `n`/`t` are fractional effective pixel
counts. They are rounded to integers in the series CSV to match
`zonal_stats.py`; a row with a real mean always keeps a count of at least 1.

**Sub-pixel districts.** Because of coverage weighting, Mahe (2 km²),
Lakshadweep (2.4 km²), Yanam, Diu and similar units still receive a value from
the pixels they partially overlap. If a district's only overlapping pixels are
masked (no valid data at all), the script repeats the reduction for those few
polygons with a one-pixel buffer (`config.yaml → gee.buffer_m`). This is the
same intent as `all_touched=True` in `zonal_stats.py`.

### 4.3 What stays in Python

`indicators.py` reads the four series and computes, exactly as documented in
`docs/methodology.md`:

- **SPI** — k-month rolling precipitation, per-district/per-calendar-month
  gamma MLE with mixed-distribution zero handling, inverse-normal transform;
- **SPEI** — k-month P − PET, three-parameter log-logistic fitted with the
  **L-moment (PWM) closed-form estimator** of Vicente-Serrano et al. (2010) /
  Singh et al. (1993) — the same method as the reference R `SPEI` package —
  with a calibration check and a tie-aware Gringorten fallback. (Earlier
  builds used `scipy.stats.fisk.fit` MLE, whose location parameter collapses
  onto the sample minimum at n = 30–40 base years; that biased every SPEI
  wet by ~+0.8 z and pushed 94% of fits into the empirical fallback. The
  L-moment route keeps > 99% of fits parametric and unbiased.);
- **SMA** — percent-of-mean soil-moisture anomaly per calendar month;
- **VCI** — per-calendar-month NDVI rescaling between base-period min/max.

The empirical fallback uses average (mid) ranks for tied values, so
zero-rainfall months receive the tie block's mid-percentile rather than the
wettest plotting position (an all-dry base month maps to z ≈ 0, "identical
to climatology", never "+2.2 extremely wet").

MODIS NDVI months are composited with `mosaic()` — MOD13A3 ships as ~16–17
sinusoidal tiles per month, and taking `collection.first()` would rasterise
a single tile and mask the rest of India to no-data.

Base periods remain `1981–2020` (SPI/SPEI/SMA) and `2000–present` (VCI).
The export window is `1981-01 … 2025-12` by default; SPI/SPEI/SMA use the
whole record while VCI is labelled with its MODIS-limited availability window.

---

## 5. Verification

The command ends with `validate.py`, which checks the app contract and the
science (district ids, dates, duplicates, completeness, classification
coverage, pooled SPI-6 mean/sd, SPI-6/SPEI-6 correlation, summaries,
manifest). Exit code 0 means no errors.

Also spot-check:

```bash
python run.py status
```

and the GEE run record:

```bash
type data_processed\gee_chunks\_meta.json     # Windows
# cat data_processed/gee_chunks/_meta.json    # Linux/macOS
```

Expected sanity checks for 2025-12:

- national area-weighted SPI-6 mean near 0 over the base period, sd ≈ 1;
- drought events around 2002, 2009, 2015–16 and 2018–19 visible in SPI-3/6;
- annual PET roughly 1,200–4,000 mm depending on the district; ERA5-Land
  `pev` runs high in the humid Northeast and can exceed 700 mm/month in
  spring, so the guard is 1,500 mm/month to avoid masking real months;
- VCI completeness below 100 % is normal (monsoon cloud gaps in MODIS).

---

## 6. Updating later

The GEE chunks are keyed by month range. To add 2026 months:

```bash
python run.py gee --project ee-yourname --end 2026-06
```

Only the new chunks are computed; the indicator/export/validate chain runs
again over the full record. Bump `gee.app_metadata.methodology_version`
(e.g. `research-gee-1.1.0`) before publishing so browsers reload the data
(`data-loader.js` caches by methodology version).

To pin a uniform end month, always pass `--end`; otherwise `gee.end` from
`config.yaml` is used (currently `2025-12`).

---

## 7. Switching the interface from demonstration to research wording

**Already applied in this build.** `metadata.json → data_mode` is
`"static-research"`, the banner/README cite the GEE sources, and the
conditional UI branches in `app.js`/`map.js` select the research wording.
Keep this section for a future rebrand: the static strings live in

- `index.html` — banner, KPI tags, map corner tags, meta/intro/methodology
  paragraphs;
- `assets/js/app.js` — footer/toast/citation strings;
- `assets/js/analytics.js` — CSV export source tag;
- root `README.md` — the build notice.

Search for `demonstration` and `synthetic` (case-insensitive). Bump
`methodology_version` whenever data changes.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: No module named 'ee'` | Activate the venv and `pip install earthengine-api`. |
| `EEException: Please authorize access` | Run `earthengine authenticate` once, then retry. |
| `No Earth Engine project` | Pass `--project <id>`, set `gee.project`, or `EE_PROJECT`. |
| `Computation timed out` / `User memory limit exceeded` | Lower `--chunk-months` (6 or 3) and/or raise `gee.tile_scale` to 8. The script also splits failed chunks automatically. |
| `getInfo` response too large | Lower `--chunk-months`. Geometry is already stripped from the response. |
| A month is skipped as "not yet in GEE" | GEE publication lag: CHIRPS ~3 weeks, MODIS ~1 month, ERA5-Land ~3 months. Re-run later; completed chunks are cached. |
| `boundary asset` export fails | Upload `data/boundaries/india_districts.geojson` manually via Code Editor → Assets → Table upload, then set `gee.boundary_asset`. |
| Small districts have no values | Increase `gee.buffer_m` for that variable (e.g. precip 8000, pet/soil 20000). |
| All means empty / counts 0 | An older build reduced on the default 1° grid or expected `_sum` property names. This build passes the native CRS/transform and accepts both `band` and `band_sum`; delete `data_processed/gee_chunks` (or re-run with `--force`). |
| SPI/SPEI all missing for a district-month | Fewer than 20 base years or fewer than 8 valid base values; check the series and `min_base_years`. |
| App still shows old data | `methodology_version` must change on every data refresh. |
| CHIRPS values differ from the local route | GEE currently serves CHIRPS v2.0 Final; the local route uses v3.0. Use one version per climatology. |

---

## 9. Command reference

| Command | Purpose |
|---|---|
| `python run.py gee --project <id> --end 2025-12` | Full GEE build → indicators → export → validate |
| `python run.py gee --skip-extract --end 2025-12` | Re-run indicators/export/validate on existing series |
| `python -m die_pipeline.gee_export --project <id> --end 2025-12` | Extraction only |
| `python run.py status` | Inventory of series/indicators and app metadata |
| `python run.py validate` | Contract + science QA |
| `python run.py selftest` | Offline end-to-end test (no GEE, no network) |

The GEE extraction source is `die_pipeline/gee_export.py`; all parameters
live in `config.yaml → gee` (datasets, periods, chunk size, buffers,
provenance).
