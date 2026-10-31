# Drought Intelligence Explorer — India

**An interactive geospatial platform for drought monitoring and analysis in India.**
A fully static, client-side research application: HTML5 + CSS3 + vanilla JavaScript (ES6+), Leaflet, Plotly, Turf.js and PapaParse. No frameworks, no backend, no database, no API keys, no mandatory external services.

> **Current build: demonstration mode.** The bundled dataset is synthetic (seeded generator, reproducible). Every value is labelled as illustrative in the interface. Swap in real, cited data by replacing files under `data/` — no code changes required.

---

## Contents

- [Features](#features)
- [Repository structure](#repository-structure)
- [Run locally](#run-locally)
- [Deploy on GitHub Pages](#deploy-on-github-pages)
- [Configuring the base path](#configuring-the-base-path)
- [Embedding in Hugo PaperMod](#embedding-in-hugo-papermod)
- [Adding and updating datasets](#adding-and-updating-datasets)
- [Data validation and quality](#data-validation-and-quality)
- [Citing the application and datasets](#citing-the-application-and-datasets)
- [Technology and design decisions](#technology-and-design-decisions)
- [License](#license)

## Features

- **10 drought indicators** at district resolution, monthly, 2005–2024: SPI-1/3/6/12, SPEI-1/3/6/12, Soil-Moisture Anomaly, Vegetation Condition Index.
- **Interactive Leaflet choropleth** with discrete severity classes *and* a continuous colour scale, hover tooltips, click-to-inspect popups, state/outline layers, optional place labels, offline default basemap.
- **KPI cards computed live from the data**: drought-affected area (equal-area km² and %), severe/extreme area, area-weighted mean intensity with classification, district counts — with explicit N/A for missing data.
- **Scientific charts** (Plotly): time series with drought threshold lines, range selector/slider, optional OLS trend (≥ 120 valid months); severity distribution (area and %); frequency-by-year bars.
- **Drought event analytics** by runs analysis (Yevjevich, 1967): frequency, duration (mean/median/max), cumulative severity and intensity, with the event definition printed next to the statistics.
- **Regional comparison table**: states or districts, sortable, searchable, paginated, CSV export, top-5 most affected highlighted, sparse-data rows flagged.
- **Analysis modules**: (A) multi-indicator comparison with synchronized maps, scatter, Pearson r / RMSE / bias and a difference map; (B) animated drought evolution with timeline of % area in drought; (C) download centre (long-format CSV extracts, district summaries, precomputed summaries, map PNG, documentation).
- **Methodology, provenance and validation** surfaces: full methodology dialog, data-source citations with access dates, and a live data-validation report (duplicates, invalid dates/values, identifier mismatches, completeness).
- **Responsive**: fixed sidebar on desktop, filter drawer on tablet/mobile, stacked charts, scrollable tables, touch-friendly controls.
- **Accessibility**: keyboard-operable controls, visible focus states, ARIA roles on tabs/dialogs/status, skip link, descriptive legends and tooltips.

## Repository structure

```
.
├── index.html                  application shell (nav, sidebar, workspace, modals)
├── assets/
│   ├── css/style.css           design system
│   ├── css/leaflet.css         bundled Leaflet stylesheet
│   ├── js/                     application modules (load order matters)
│   │   ├── data-loader.js      base path, fetching/caching, validation, classification
│   │   ├── filters.js          application state + sidebar controls
│   │   ├── map.js              Leaflet views (main + module maps), legends, PNG export
│   │   ├── charts.js           Plotly chart builders
│   │   ├── analytics.js        statistics, event analysis, CSV builders
│   │   ├── app.js              orchestration, KPIs, table, downloads, modules
│   │   └── vendor/             bundled libraries (CDN fallback configured)
│   └── images/                 logo, favicon, Leaflet icons
├── data/
│   ├── metadata.json           indicators, thresholds, provenance (single source of truth)
│   ├── districts.csv, states.csv   registries with equal-area statistics
│   ├── boundaries/             district / state / outline GeoJSON (EPSG:4326)
│   ├── drought/                indicator matrices (wide CSV: districts × months)
│   └── summaries/              precomputed event & state statistics (cross-checks)
├── docs/
│   ├── methodology.md          full scientific methodology
│   └── data-sources.md         provenance, production sources, citation guidance
├── scripts/
│   ├── prepare_boundaries.py   boundary cleaning, simplification, equal-area stats
│   └── generate_demonstration_data.py   seeded synthetic dataset generator
├── .nojekyll                   bypasses GitHub Pages Jekyll processing
└── README.md
```

## Run locally

The app fetches data with `fetch()`, so it must be served over HTTP (opening `index.html` directly from disk will show a warning):

```bash
cd drought-intelligence-explorer
python3 -m http.server 8000
# open http://localhost:8000/
```

Any static server works (`npx serve`, `php -S`, nginx…). Requirements for regenerating data: Python 3.10+ with `numpy`, `shapely`, `pyproj` (plus `npx mapshaper` for boundaries).

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

### Replace the demonstration data with real data

1. Compute district-month indicator values with any tool you like (Python/R/CDO/QGIS). Output **wide CSV**: first three columns `district_id,district_name,state_name`, then one `YYYY-MM` column per month; empty cell = missing.
2. Keep `district_id` identical to the `id` property in `data/boundaries/india_districts.geojson` (or regenerate boundaries with `scripts/prepare_boundaries.py` and new ids — then also regenerate `data/districts.csv`/`states.csv`).
3. Drop the files into `data/drought/`.
4. Update `data/metadata.json`:
   - `data_mode`: `"static-research"`,
   - `data_provenance`, `last_updated`, `methodology_version`, `period`,
   - for each indicator: `file`, `reference_period`, `classes` (thresholds are yours to define — the whole UI follows them),
   - `sources`: real citations with access dates.
5. Reload the app. The banner, chips, methodology dialog and footer all read from metadata, so the interface updates automatically — edit `index.html` (banner) and `docs/` if you want to change the wording.

### Add a new indicator

Add one entry to `metadata.indicators` (with `classes`, `scale`, `file`, tooltips) and its CSV. It appears in the sidebar, map legend, charts, comparison and downloads with no code changes.

### Regenerate the demonstration dataset

```bash
python3 scripts/generate_demonstration_data.py .
```

(seed and model parameters are constants at the top of the script; outputs are byte-identical for identical inputs and boundaries.)

### Regenerate boundaries from a new source GeoJSON

```bash
python3 scripts/prepare_boundaries.py <raw_districts.geojson> .
```

This cleans the raw file, rounds coordinates (districts at ~100 m precision, states at ~1 km), dissolves states/outline, repairs invalid geometries and recomputes equal-area statistics and centroids.

## Data validation and quality

At load time the application checks every dataset for: duplicate district rows (merged, last kept), invalid date columns (skipped), non-numeric values (treated as missing), district ids missing from the boundaries (dropped), boundary districts absent from the dataset (rendered as no-data), and overall completeness. The report appears in the **Data Sources** dialog and the browser console. Missing observations are never imputed or treated as normal conditions — see `docs/methodology.md` §6.

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

Dataset citations depend on what you deploy: cite the demonstration generator (synthetic, seed 42) for this build, or each real source you load (IMD, ERA5, MODIS, ESA CCI — templates in `docs/data-sources.md`).

## Technology and design decisions

- **Vanilla ES6+ modules (classic scripts, dependency-ordered).** No build step: the repository *is* the deployment.
- **Vendor libraries bundled locally** (`assets/js/vendor/`) with automatic CDN fallback, so the app runs offline/intranet and degrades gracefully (Plotly/Turf/html2canvas optional with explicit UI states; Leaflet/PapaParse required).
- **Default basemap is a plain offline canvas** — the core choropleth works with zero external tile services; reference tiles are opt-in.
- **Canvas renderer** (`preferCanvas`) keeps 724 polygons smooth and makes map PNG export reliable.
- **Wide CSV matrices** (~0.9 MB per indicator, gzip ≈ 0.3 MB over the wire) instead of a 200 MB long-format table; the download centre generates the documented long-format schema on demand. Indicators load lazily; sessionStorage caching is keyed by methodology version.
- **Plotly "cartesian" bundle only** — D3 was deliberately omitted (Plotly covers the required scientific charts; lighter payload).
- **Areas precomputed in an equal-area projection**; regional means are area-weighted; no degree-coordinate arithmetic anywhere.
- **Single source of truth:** classification thresholds, palettes, units, tooltips and provenance all live in `data/metadata.json`.

## License

Add a `LICENSE` file before public distribution (the intended setup is MIT for code; data licensing follows whichever real datasets you load). Until then, all rights reserved by the author.

---

*Developed as a geospatial research application by **Ankit Deshmukh, Ph.D.** — Assistant Professor, Department of Civil Engineering, Pandit Deendayal Energy University, India. Research domains: Computational Hydrology | Drought Analysis | Geospatial Modelling | Hydroclimatic Extremes.*
