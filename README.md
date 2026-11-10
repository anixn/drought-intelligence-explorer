# Drought Intelligence Explorer — India

**An interactive geospatial platform for historical drought analysis in India.**
A fully static, client-side research application: HTML5 + CSS3 + vanilla JavaScript (ES6+), Leaflet, Plotly and PapaParse. No frameworks, no backend, no database, no API keys, no mandatory external services. Leaflet and PapaParse are the only blocking libraries; Plotly loads in the background and html2canvas is fetched only when a map PNG is exported.

> **Current build: historical research data.** The bundled dataset is a Google Earth Engine extract (CHIRPS v2.0, ERA5-Land and MODIS MOD13A3) processed by the reference pipeline (methodology `research-gee-1.0.2`). Indicator values are model- and observation-based estimates, not official drought declarations. The provenance banner, chips, methodology tab and footer all update automatically from `data/metadata.json`; swapping in a new extract requires no code changes.

> **New to the dashboard?** Start with the [user guide](docs/user-guide.md) or press <kbd>?</kbd> in the app. It explains every workspace, table and chart in plain language.

---

## Contents

- [Workspaces (four tabs + documentation)](#workspaces-four-tabs--documentation)
- [Features](#features)
- [Repository structure](#repository-structure)
- [Run locally](#run-locally)
- [Deploy on GitHub Pages](#deploy-on-github-pages)
- [Configuring the base path](#configuring-the-base-path)
- [Embedding in Hugo PaperMod](#embedding-in-hugo-papermod)
- [Adding and updating datasets](#adding-and-updating-datasets)
- [Data validation and quality](#data-validation-and-quality)
- [Citing the application and datasets](#citing-the-application-and-datasets)
- [Technology, performance and design decisions](#technology-performance-and-design-decisions)
- [License](#license)

## Workspaces (four tabs + documentation)

The interface is organised into four analytical workspaces, reachable by URL hash (`#overview`, `#historical`, `#events`, `#propagation`) so refresh and deep links preserve the view. Geography, indicator and analysis period are **global study-context controls** (left panel) shared by every tab — the sidebar holds nothing else. Workspace-specific controls sit on the panels they drive, Grafana/Tableau style: an **Observation date** strip above the Overview panels, an **Event definition** strip above the Events panels, an **Indicator pair** strip above the Propagation panels, display controls (colour mode, layers, basemap) on a toolbar attached to the main map, and per-panel filters in panel heads (ranking level/search/CSV, catalogue search/year/CSV, trend granularity, sensitivity scenario, comparison pair). The basemap choice on the map toolbar applies to **every map** in the dashboard, including event-detail, propagation-pattern and comparison maps. The former fifth tab, Data & Methods, is now **Documentation & Resources**: a dedicated documentation area opened with the book icon in the sidebar footer (URL hash `#data` or `#docs`), covering About, Data Sources, Methodology, Validation & Data Quality, Uncertainty & Limitations, Reproducibility, Downloads & Citations and Version History. Each workspace has its own accent identity; drought-severity palettes and plot colours remain independent of it.

1. **Overview** — where is drought, how severe, how has it changed: date slider, snapshot KPIs (affected/severe area in equal-area km², area-weighted mean, districts in drought with change vs the previous month), the interactive district map with legend, the full time series with drought-class thresholds, the severity distribution, a top-10 most-affected-district ranking (by severity or affected area) and a historical-context timeline (% of region area in drought) with playback.
2. **Historical Analysis** — frequency (months and % in drought, per-year bars, district frequency histogram), duration and severity (summary statistics plus per-district choropleth maps), non-parametric trend analysis (Mann-Kendall with tie correction and Hamed-Rao variance correction when significant autocorrelation exists; Sen's slope with 90% confidence interval; annual or monthly granularity), empirical recurrence (inter-arrival times, severity-exceedance return periods — no fitted distribution), and the district-wise ranking table (sortable/searchable/paginated, CSV export).
3. **Drought Events** — the event catalogue (runs analysis per district: onset, termination, duration, maximum intensity, cumulative severity, censoring flag, recovery months; filterable by year/district, sortable, CSV export), the onset timeline, the duration distribution, an event detail view (event-specific series with the shaded event window and a map extent) and a definition-sensitivity panel (minimum duration / truncation scenarios, clearly separated from the default methodology).
4. **Propagation & Relationships** — lagged cross-correlation (−12…+12 months, matched months only) between any two indicators with the optimal lag, Pearson r and moving-block bootstrap 95% CI (serial dependence preserved, fixed seed), a dual-series comparison chart, a full 10×10 correlation heatmap, a district-wise optimal-lag map, the migrated single-date spatial comparison (synchronized maps, difference map, agreement statistics, scatter), and an explicitly **unavailable** section for streamflow/groundwater propagation (no such data in the dataset — nothing is simulated).
5. **Documentation & Resources** (book icon in the sidebar footer, hash `#data`/`#docs`) — dataset information (source, modes, units, windows, latest observation, reference period), per-indicator data quality (valid %, missing %) with the live validation report, uncertainty and limitations, the full methodology (indicators, thresholds, aggregation, events, trends, correlation, missing-data policy) and the download centre: long-format CSV, wide matrix, district statistics, event catalogue, analysis-metadata JSON, boundary GeoJSON, map PNG, documentation, citation — every CSV export carries a `#`-comment reproducibility header (indicator, geography, periods, reference period, export timestamp, methodology version, data mode and seed, source). Organised as About the Explorer · Data Sources · Methodology · Validation & Data Quality · Uncertainty and Limitations · Reproducibility · Downloads & Citations · Version History, plus the user guide and glossary.

## Features

- **10 drought indicators** at district resolution, monthly, 1981–2025 (SPI-1/3/6/12, SPEI-1/3/6/12, Soil-Moisture Anomaly) and 2000–2025 for the Vegetation Condition Index, which is limited by the MODIS NDVI record.
- **Interactive Leaflet choropleth** with discrete severity classes *and* a continuous colour scale, hover tooltips, click-to-inspect popups, state/outline layers, optional place labels, offline default basemap. Clicking a district focuses every tab on it.
- **KPI cards computed live from the data**: drought-affected area (equal-area km² and %), severe/extreme area, area-weighted mean intensity with classification, district counts — with explicit N/A for missing data and the change versus the previous observation.
- **Scientific charts** (Plotly): time series with drought threshold lines, range selector/slider, optional OLS trend (≥ 120 valid months); severity distribution; frequency-by-year; district ranking; event timeline and distributions; lag-correlation with bootstrap CI; correlation heatmap; trend chart with Sen slope.
- **Drought event analytics** by runs analysis (Yevjevich, 1967): catalogue, frequency, duration (mean/median/max), cumulative severity and intensity, censoring flags for events touching the record edge, recovery time, and definition-sensitivity scenarios.
- **Inferential statistics**: Mann-Kendall + Sen slope with autocorrelation handling; lagged cross-correlation with moving-block bootstrap confidence intervals; sample sizes and uncertainty always reported.
- **Regional comparison table**: states or districts, sortable, searchable, paginated, CSV export with metadata header, top-5 most affected highlighted, sparse-data rows flagged.
- **Reproducible downloads**: every export embeds the full analysis metadata; a dedicated JSON metadata export records the complete state.
- **Methodology, provenance and validation** surfaces: methodology tab, data-source citations with access dates, and a live data-validation report (duplicates, invalid dates/values, identifier mismatches, completeness).
- **Responsive**: fixed filter panel on desktop, filter drawer on tablet/mobile, stacked charts, scrollable tables, touch-friendly controls.
- **Accessibility**: keyboard-operable tabs (arrow keys) and controls, visible focus states, ARIA roles on tabs/dialogs/status, skip link, descriptive legends and tooltips, plus a `?` shortcut for the in-app guide.
- **Fast by design**: parallel boot with cached indicator text, memoised analytics aggregates, hidden-tab dirty tracking, targeted filter-control rebuilds, transient slider updates, progressive chart rendering while Plotly loads, and on-demand html2canvas.
- **Built-in guidance**: a workspace introduction on every tab, a full "How to use" dialog, a Documentation & Resources guide/glossary, purpose notes above every table, and a downloadable [user guide](docs/user-guide.md).

## Repository structure

```
.
├── index.html                  application shell (four-workspace nav +
│                               documentation centre, global filter
│                               panel, workspaces, boot loader)
├── assets/
│   ├── css/style.css           design system
│   ├── css/leaflet.css         bundled Leaflet stylesheet
│   ├── js/                     application modules (load order matters)
│   │   ├── data-loader.js      base path, fetching/caching, validation, classification
│   │   ├── stats.js            Mann-Kendall, Sen slope, block bootstrap, lagged correlation
│   │   ├── filters.js          global state + filter panel controls
│   │   ├── map.js              Leaflet views (main + statistical maps), legends, PNG export
│   │   ├── charts.js           Plotly chart builders
│   │   ├── analytics.js        statistics, event analysis, CSV builders
│   │   ├── app.js              orchestration, hash router, four view controllers + docs centre
│   │   └── vendor/             bundled libraries (CDN fallback configured)
│   └── images/                 logo, favicon, Leaflet icons
├── data/
│   ├── metadata.json           indicators, thresholds, provenance (single source of truth)
│   ├── districts.csv, states.csv   registries with equal-area statistics
│   ├── boundaries/             district / state / outline GeoJSON (EPSG:4326)
│   ├── drought/                indicator matrices (wide CSV: districts × months)
│   └── summaries/              precomputed event & state statistics (cross-checks)
├── docs/
│   ├── user-guide.md           plain-language guide: workspaces, tables, charts, exports
│   ├── methodology.md          full scientific methodology
│   ├── data-sources.md         provenance, production sources, citation guidance
│   └── refactor-plan.md        five-tab refactor audit and migration plan
├── scripts/
│   └── relabel_demo.py         data-mode relabel utility (idempotent)
├── data-pipeline/               offline pipeline that turns public gridded
│   (Python + R)                 datasets into data/ — see its README,
│                                docs/data-update-guide.md for the local
│                                runbook, and docs/gee-update-guide.md for
│                                the Google Earth Engine route (CHIRPS,
│                                ERA5-Land, MODIS). Boundary and demo-data
│                                utilities live here too:
│                                prepare_boundaries.py,
│                                generate_demonstration_data.py.
├── .nojekyll                   bypasses GitHub Pages Jekyll processing
└── README.md
```

## Run locally

The app fetches data with `fetch()`, so it must be served over HTTP (opening `index.html` directly from disk shows a guard message instead of the app).

**Easiest way (Windows, nothing to install):** double-click **`Start Drought Explorer.bat`** in the project folder. It runs the bundled `serve.ps1` (built-in PowerShell/.NET only), serves the folder on the first free port 8471–8480, and opens the app in your default browser automatically. Keep the console window open while using the app; closing it stops the server.

**Any static server works too:**

```bash
cd drought-intelligence-explorer
python3 -m http.server 8000
# open http://localhost:8000/
```

Other options: `npx serve`, `php -S`, nginx… Requirements for regenerating data: Python 3.10+ with `numpy`, `shapely`, `pyproj` (plus `npx mapshaper` for boundaries); the full data pipeline (`data-pipeline/`) additionally uses `pandas`, `scipy`, `rasterio`, `netCDF4`, `cdsapi` — see `data-pipeline/requirements.txt`.

## Deploy on GitHub Pages

1. Create a repository (e.g. `drought-intelligence-explorer`) and push this folder's contents.
2. In **Settings → Pages**, set *Source* to your branch (`/ (root)`), or to `/docs` if you move the app into a `docs/` folder.
3. Wait for the build; the app is available at `https://<user>.github.io/<repo>/`.
4. For a **custom domain** (e.g. `ankitdeshmukh.com` or a subdomain): add your `CNAME` file or configure it in Settings → Pages → Custom domain. The base-path auto-detection (below) then resolves to `/` automatically.

The `.nojekyll` file prevents GitHub Pages' Jekyll from touching files whose names it treats specially.

## Configuring the base path

All asset and data references are relative, and the app **auto-detects its base path** from the `<script src>` of `data-loader.js`. It therefore works unchanged:

- at a repository subdirectory (`https://user.github.io/drought-intelligence-explorer/`),
- at a custom domain root (`https://drought.example.app/`),
- under a nested route (`https://ankitdeshmukh.com/apps/drought/`).

If you serve the app from an unusual mount point and need to force a base path, uncomment this line near the top of `index.html`:

```html
<script>window.DIE_BASE_PATH_OVERRIDE = '/my/nested/path/';</script>
```

(Omit it entirely for auto-detection. It must end with a slash.)

## Embedding in Hugo PaperMod

Two supported patterns on an existing Hugo site (e.g. an Academic profile):

**1. iframe embed (keeps the app self-contained).** Commit the app to a folder (e.g. `static/drought-explorer/`) so it is served at `/drought-explorer/index.html`, then create a page:

```html
<!-- content/drought-explorer.md -->
---
title: "Drought Intelligence Explorer"
summary: "Interactive district-level drought analysis for India"
---
<iframe src="/drought-explorer/" style="width:100%;height:88vh;border:0"
        title="Drought Intelligence Explorer"></iframe>
```

The app auto-detects the `/drought-explorer/` base path, so no configuration is needed. Add `loading="lazy"` if you want it deferred below the fold.

**2. Direct route (recommended for a dedicated subdomain).** Point GitHub Pages (or any static host) at the repository and map a subdomain such as `drought.ankitdeshmukh.com`; then link to it from your PaperMod menu (`config.yml` → `menu.main`) or from a post. This gives the app the full viewport and clean URLs.

## Adding and updating datasets

### Update real data every few months (recommended)

The repository ships an offline pipeline for exactly this:

```bash
cd data-pipeline
python run.py update     # downloads missing months -> computes indicators
                         # -> writes data/ -> validates
```

It pulls CHIRPS v3.0 rainfall, ERA5-Land PET/soil moisture and MODIS NDVI
(no credentials needed for CHIRPS; free CDS and Earthdata accounts for the
other two), computes SPI/SPEI/SMA/VCI exactly as documented in
`docs/methodology.md`, and writes the full data contract below. The
step-by-step guide — including the first-time 1981-present backfill, the
quarterly runbook, and the one-time switch of the interface wording from
demonstration to research mode — is
**`data-pipeline/docs/data-update-guide.md`**. An R alternative lives in
`data-pipeline/r_alternative/`.

**Google Earth Engine route.** If you have an Earth Engine project, the
download/prepare/zonal steps can be replaced by GEE (CHIRPS, ERA5-Land and
MOD13A3 are all in the Earth Engine catalog), while the SPI/SPEI/SMA/VCI
computation and app export stay in the same reference Python code:

```bash
cd data-pipeline
python run.py gee --project ee-yourname --end 2025-12
```

This writes the historical dataset through **2025-12** into `data/`. Setup,
dataset mapping, checkpointing and caveats are in
**`data-pipeline/docs/gee-update-guide.md`**.

### Replace the demonstration data with real data (manual contract)

1. Compute district-month indicator values with any tool you like (Python/R/CDO/QGIS). Output **wide CSV**: first three columns `district_id,district_name,state_name`, then one `YYYY-MM` column per month; empty cell = missing.
2. Keep `district_id` identical to the `id` property in `data/boundaries/india_districts.geojson` (or regenerate boundaries with `data-pipeline/prepare_boundaries.py` and new ids — then also regenerate `data/districts.csv`/`states.csv`).
3. Drop the files into `data/drought/`.
4. Update `data/metadata.json`:
   - `data_mode`: `"static-research"`,
   - `data_provenance`, `last_updated`, `methodology_version`, `period`,
   - for each indicator: `file`, `reference_period`, `classes` (thresholds are yours to define — the whole UI follows them),
   - optional but recommended: `available_from` / `available_to` (e.g. `2000-02` for VCI) so the UI can label and clamp a shorter data record,
   - `sources`: real citations with access dates.
5. Reload the app. The banner, chips, KPI provenance tags, methodology tab and footer all read from metadata, so the interface updates automatically — the data-mode relabel utility `scripts/relabel_demo.py` shows the exact field set.

### Add a new indicator

Add one entry to `metadata.indicators` (with `classes`, `scale`, `file`, tooltips) and its CSV. It appears in the sidebar, map legend, charts, comparison and downloads with no code changes.

### Regenerate the demonstration dataset (offline UI testing only)

The shipped app uses the observed dataset in `data/`. The seeded synthetic
generator is kept in the pipeline folder for offline UI testing:

```bash
python3 data-pipeline/generate_demonstration_data.py .
```

(seed and model parameters are constants at the top of the script; outputs are byte-identical for identical inputs and boundaries. Running it overwrites `data/`, so use a throwaway checkout.)

### Regenerate boundaries from a new source GeoJSON

```bash
python3 data-pipeline/prepare_boundaries.py <raw_districts.geojson> .
```

This cleans the raw file, rounds coordinates (districts at ~100 m precision, states at ~1 km), dissolves states/outline, repairs invalid geometries and recomputes equal-area statistics and centroids.

## Data validation and quality

At load time the application checks every dataset for: duplicate district rows (merged, last kept), invalid date columns (skipped), non-numeric values (treated as missing), district ids missing from the boundaries (dropped), boundary districts absent from the dataset (rendered as no-data), and overall completeness. The report appears in **Documentation & Resources** (book icon in the sidebar footer → Validation and data quality) and the browser console. Only indicators already loaded in the session are reported by default; **Validate all indicators** downloads the remaining matrices in small parallel batches and updates the report as each one finishes. Missing observations are never imputed or treated as normal conditions — see `docs/methodology.md` §6.

## Citing the application and datasets

```bibtex
@software{deshmukh2026droughtexplorer,
  author  = {Deshmukh, Ankit},
  title   = {Drought Intelligence Explorer: An Interactive Geospatial Platform
             for Drought Monitoring and Analysis in India},
  year    = {2026},
  url     = {https://ankitdeshmukh.com/}
}
```

Dataset citations depend on what you deploy: this build uses CHIRPS v2.0 Final, ERA5-Land and MODIS MOD13A3 (templates in `docs/data-sources.md`); the synthetic generator in `data-pipeline/` is only for offline UI testing.

## Technology, performance and design decisions

- **Vanilla ES6+ modules (classic scripts, dependency-ordered).** No build step: the repository *is* the deployment.
- **Vendor libraries bundled locally** (`assets/js/vendor/`) with automatic CDN fallback, so the app runs offline/intranet and degrades gracefully. Leaflet and PapaParse are required; Plotly is optional and loads in the background; html2canvas is optional and fetched only on first PNG export.
- **Parallel boot.** After metadata, boundaries, registries and the current indicator CSV load concurrently; app modules load in parallel around `data-loader.js`. The map and summary render before the chart engine is needed.
- **Memoised analytics.** Area-weighted region statistics, series, district/event statistics, trends and comparison rows are cached per dataset/selection, so panels that share inputs do not recompute 724 × 540 matrices repeatedly.
- **Interaction-friendly state flow.** Filter controls rebuild only the parts that changed; dragging the date slider updates the map/KPIs at animation speed and defers charts to the final change event; hidden tabs are marked dirty and rendered on entry.
- **Progressive charts.** A chart requested before Plotly is ready shows a “loading chart engine” state and redraws automatically; chart zoom/pan survives data updates.
- **Default basemap is a plain offline canvas** — the core choropleth works with zero external tile services; reference tiles are opt-in.
- **Canvas renderer** (`preferCanvas`) keeps 724 polygons smooth and makes map PNG export reliable.
- **Wide CSV matrices** (~0.9 MB per indicator, gzip ≈ 0.3 MB over the wire) instead of a 200 MB long-format table; the download centre generates the documented long-format schema on demand. Indicators load lazily; sessionStorage + in-memory caches are keyed by methodology version, with hover prefetching of the next likely indicator.
- **Plotly "cartesian" bundle only** — D3 was deliberately omitted (Plotly covers the required scientific charts; lighter payload).
- **Areas precomputed in an equal-area projection**; regional means are area-weighted; no degree-coordinate arithmetic anywhere.
- **Single source of truth:** classification thresholds, palettes, units, tooltips and provenance all live in `data/metadata.json`.
- **Self-documenting interface:** workspace intros, table-purpose notes, a full guide dialog, a Documentation & Resources glossary and a downloadable user guide.

## License

The application code is released under the MIT License (see `LICENSE`). Data licensing follows the source datasets: CHIRPS, ERA5-Land and MODIS have their own terms and citation requirements — see `docs/data-sources.md` before redistributing derived data.

---

*Developed as a geospatial research application by **Ankit Deshmukh, Ph.D.** — Assistant Professor, Department of Civil Engineering, Pandit Deendayal Energy University, India. Research domains: Computational Hydrology | Drought Analysis | Geospatial Modelling | Hydroclimatic Extremes.*
