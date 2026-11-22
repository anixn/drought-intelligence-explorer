# Drought Intelligence Explorer — India

**An interactive geospatial platform for historical drought analysis in India.**
A fully static, client-side research application: HTML5 + CSS3 + vanilla JavaScript (ES6+), Leaflet, Plotly and PapaParse. No frameworks, no backend, no database, no API keys, no mandatory external services. Leaflet and PapaParse are the only blocking libraries; Plotly loads in the background and html2canvas is fetched only when a map PNG is exported.

[![Software DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24113363.svg)](https://doi.org/10.5281/zenodo.24113363)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Live app](https://img.shields.io/badge/Live%20app-drought.ankitdeshmukh.com-2A5F85)](https://drought.ankitdeshmukh.com/)
[![Data](https://img.shields.io/badge/Data-data.ankitdeshmukh.com-6E6238)](https://data.ankitdeshmukh.com/)

> **Current build: v2.0.0 — three labelled eras, never spliced.** Era A is the Drought Atlas of India SPEI reconstruction (1901–2025, served at district level); era B is the observation-based gridded multi-source product (SPI-1/3/6/12, SPEI-1/3/6/12, soil-moisture anomaly and VCI, 1981-01 → 2026-09, from CHIRPS v2.0, ERA5-Land and MODIS MOD13A3); era C is a 24-model bias-corrected CMIP6 ensemble (2015–2100, SSP2-4.5 and SSP5-8.5). Indicator values are model- and observation-based estimates, not official drought declarations. Bulk data (Parquet + the wide CSVs) are served from an immutable R2 snapshot selected by `data/data-source.json`; the browser reads them with HTTP Range requests. Missing values are never imputed and every statistic reports its sample size.

> **New to the dashboard?** Start with the [guided tour](tour.html) (topbar → *How to use*), the [user guide](docs/user-guide.md), or the SQL field reference in Documentation **P** / [`docs/sql-guide.md`](docs/sql-guide.md).

---

## Contents

- [Products, lenses and help](#products-lenses-and-help)
- [Features](#features)
- [Repository structure](#repository-structure)
- [Run locally](#run-locally)
- [Deploy on GitHub Pages](#deploy-on-github-pages)
- [Configuring the base path](#configuring-the-base-path)
- [Adding and updating datasets](#adding-and-updating-datasets)
- [Data validation and quality](#data-validation-and-quality)
- [Citation](#citation)
- [Manuscript](#manuscript)
- [Technology, performance and design decisions](#technology-performance-and-design-decisions)
- [License](#license)

## Products, lenses and help

The interface is **product-first**: the top bar lists the four data products and tools — `Record · 1981–present`, `Projections · 2015–2100`, `Atlas · 1901–2025`, `Engine Lab` — and a second row holds the lenses of the active product. Each product is a labelled era; the lenses are questions asked of it. Hovering or focusing any product, lens or topbar utility shows a one-line explanation. Help and reference live with the brand: **How to use** opens the guided tour ([`tour.html`](tour.html)); **Documentation** opens the reference centre.

- **Record** (era B) — lenses: **Overview** (map, headline area, national series, ranking, evolution), **Historical Analysis** (frequency, duration, severity, Mann–Kendall + Sen trends, recurrence, ranking), **Drought Events** (runs analysis catalogue, onset timeline, detail, sensitivity), **Propagation & Relationships** (lagged cross-correlation −12…+12 months with a moving-block bootstrap CI, 10×10 heatmap, optimal-lag map, spatial comparison), **Cross-validation** (era A ↔ era B over 1981–2014: agreement, bias, seam uncertainty) and **District profile** (`#/district/<id>`).
- **Projections** (era C) — **Future Projections** (scenario, statistic and window controls; ensemble band, agreement map, divergence, ranking, events) and **Drought to 2100** (agreement-first summary and change metrics).
- **Atlas** (era A) — per-year scrubber for SPEI-1/4/12, class shares, historical anchors (1918, 1965, 1972, 1987, 2002), caveats.
- **Engine Lab** — SQL over the published Parquet store in the browser (DuckDB-WASM), with presets, arbitrary queries, row counts, timings, byte traffic and CSV export.
- **Documentation** (A–P) — About, data sources, methodology, validation (including the independent IMD benchmark), uncertainty, reproducibility, downloads and citation, version history, the user guide and glossary, governance and licences, reality checks, data status, and the SQL field reference (P).

The sidebar is the study context for the Record lenses (observation date, geography, indicator, analysis period) and a **product console** on Projections and Atlas (live read-outs plus quick presets); Documentation gets a contents index. The product consoles mirror and drive the panel controls, so the panel select remains the single source of truth. Every surface carries its era, window, baseline and sample size.

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
│   └── data-sources.md         provenance, production sources, citation guidance
├── data-pipeline/              offline Python pipeline that turns public gridded
│                               datasets into data/ — see its README. Entry points:
│                               run.py (update / gee / indicators / export /
│                               validate / status), selftest.py (82-assertion
│                               offline end-to-end test), verify_paper_claims.py
│                               (reproduces the quantitative evidence quoted in
│                               the manuscript), prepare_boundaries.py. Route
│                               guides in data-pipeline/docs/.
├── manuscript/                 LaTeX source of the EarthArXiv preprint
│                               (main.tex + figures/); see manuscript/README.md
├── CITATION.cff                machine-readable citation metadata (cff 1.2.0)
├── CNAME                       custom domain for GitHub Pages
├── LICENSE                     MIT license (application code)
├── .nojekyll                   bypasses GitHub Pages Jekyll processing
└── README.md
```

## Run locally

The app fetches data with `fetch()`, so it must be served over HTTP (opening `index.html` directly from disk shows a guard message instead of the app):

```bash
cd drought-intelligence-explorer
python3 -m http.server 8000
# open http://localhost:8000/
```

Any static server works too: `npx serve`, `php -S`, nginx…

**Regenerating the data** requires the pipeline environment (`data-pipeline/requirements.txt`: Python 3.10+ with `numpy`, `pandas`, `scipy`, `pyyaml`, `requests`, `rasterio`, `pyproj`, `netCDF4`; `cdsapi`, `earthaccess` and `earthengine-api` are needed only for their specific download routes):

```bash
cd data-pipeline
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Boundary preparation (`prepare_boundaries.py`) additionally needs Node.js on the PATH (`npx mapshaper`) plus the Python packages `shapely` and `pyproj`.

## Deploy on GitHub Pages

1. Create a repository (e.g. `drought-intelligence-explorer`) and push this folder's contents.
2. In **Settings → Pages**, set *Source* to your branch (`/ (root)`), or to `/docs` if you move the app into a `docs/` folder.
3. Wait for the build; the app is available at `https://<user>.github.io/<repo>/`.
4. For a **custom domain** (e.g. `ankitdeshmukh.com` or a subdomain): add your `CNAME` file or configure it in Settings → Pages → Custom domain. The base-path auto-detection (below) then resolves to `/` automatically.

The `.nojekyll` file prevents GitHub Pages' Jekyll from touching files whose names it treats specially.

### Bulk data hosting (R2)

GitHub Pages serves the **application**; the data live in an immutable Cloudflare R2 snapshot and the repository carries only a pointer:

- `data/data-source.json` names the snapshot (`base`, `snapshot`, `public_base`); `base: null` means same-origin, which is what a bare clone and local development use.
- The loader and the DuckDB engine resolve `data/parquet/…` and `data/drought/…` through that base; `metadata.json`, `status.json`, `reality_checks.json` and the boundary GeoJSON stay with the code.
- Publishing a refresh: `python scripts/publish_r2.py --version vYYYY.MM --write-pointer --public-base …`, then commit the pointer. Verify with `python scripts/verify_r2.py --base …/vYYYY.MM/`.
- Why: one monthly refresh is ~13 MB of permanent git history and era C alone is ~895 MB, while a GitHub Pages site is capped at 1 GB. The full contract is in [`docs/v2/03-scientific-pipelines.md`](docs/v2/03-scientific-pipelines.md) §10.

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

## Adding and updating datasets

### Update the bundled record

The repository ships an offline pipeline for exactly this:

```bash
cd data-pipeline
python run.py update     # downloads missing months -> computes indicators
                         # -> writes data/ -> validates
```

It pulls CHIRPS v3.0 rainfall, ERA5-Land PET/soil moisture and MODIS NDVI
(no credentials needed for CHIRPS; free CDS and Earthdata accounts for the
other two), computes SPI/SPEI/SMA/VCI exactly as documented in
`docs/methodology.md`, and writes the full data contract. The step-by-step
guide — including the first-time 1981-present backfill — is
**`data-pipeline/docs/data-update-guide.md`**. Note that the offline route
targets CHIRPS v3.0, while the shipped release was extracted through Google
Earth Engine from CHIRPS v2.0; do not mix the two versions in one record
(the route guides cover this).

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

### Bring your own indicator matrices (manual contract)

1. Compute district-month indicator values with any tool you like (Python/R/CDO/QGIS). Output **wide CSV**: first three columns `district_id,district_name,state_name`, then one `YYYY-MM` column per month; empty cell = missing.
2. Keep `district_id` identical to the `id` property in `data/boundaries/india_districts.geojson` (or regenerate boundaries with `data-pipeline/prepare_boundaries.py` and new ids — then also regenerate `data/districts.csv`/`states.csv`).
3. Drop the files into `data/drought/`.
4. Update `data/metadata.json`:
   - `data_mode`: `"static-research"`,
   - `data_provenance`, `last_updated`, `methodology_version`, `period`,
   - for each indicator: `file`, `reference_period`, `classes` (thresholds are yours to define — the whole UI follows them),
   - recommended: `available_from` / `available_to` (e.g. `2000-02` for VCI) so the UI can label and clamp a shorter data record,
   - `sources`: real citations with access dates.
5. Reload the app. The banner, chips, KPI provenance tags, methodology tab and footer all read from metadata, so the interface updates automatically.

### Add a new indicator

Add one entry to `metadata.indicators` (with `classes`, `scale`, `file`, tooltips) and its CSV. It appears in the sidebar, map legend, charts, comparison and downloads with no code changes.

### Regenerate boundaries from a new source GeoJSON

```bash
python3 data-pipeline/prepare_boundaries.py <raw_districts.geojson> .
```

This cleans the raw file, rounds coordinates (districts at ~100 m precision, states at ~1 km), dissolves states/outline, repairs invalid geometries and recomputes equal-area statistics and centroids.

## Data validation and quality

At load time the application checks every dataset for: duplicate district rows (merged, last kept), invalid date columns (skipped), non-numeric values (treated as missing), district ids missing from the boundaries (dropped), boundary districts absent from the dataset (rendered as no-data), and overall completeness. The report appears in **Documentation & Resources** (book icon in the sidebar footer → Validation and data quality) and the browser console. Only indicators already loaded in the session are reported by default; **Validate all indicators** downloads the remaining matrices in small parallel batches and updates the report as each one finishes. Missing observations are never imputed or treated as normal conditions — see `docs/methodology.md` §6.

## Citation

If the platform or the dataset contributes to your research, please cite it. The canonical machine-readable metadata is [CITATION.cff](CITATION.cff) (cff-version 1.2.0); Zenodo archives the release with a versioned DOI.

**Software — the platform and its pipelines (v2.0.0):**

```bibtex
@software{deshmukh2026droughtexplorer,
  author  = {Deshmukh, Ankit},
  orcid   = {0000-0002-1433-3872},
  title   = {Drought Intelligence Explorer: a multi-era district drought
             record and analytics platform for India},
  year    = {2026},
  version = {2.0.0},
  doi     = {10.5281/zenodo.24113363},
  url     = {https://github.com/anixn/drought-intelligence-explorer}
}
```

The DOI shown is the **concept DOI**, which always resolves to the latest archived release; each release also receives its own version DOI (v2.0.0 is minted by the GitHub–Zenodo integration when the release is published).

**Dataset — the district record (snapshot `v2026.09`, 1901–2100):**

> Deshmukh, A. (2026). *Drought Intelligence Explorer v2.0.0 — district drought record for India (1901–2100)* [Data set], version 2.0.0, snapshot v2026.09. Zenodo. DOI pending; meanwhile cite the archived dataset URL, <https://data.ankitdeshmukh.com/v2026.09/>, with the software DOI above.

**Preprint:** the accompanying manuscript ([`manuscript/`](manuscript/)) is prepared for [EarthArXiv](https://eartharxiv.org/); insert the preprint DOI here once minted.

Citation templates for the input products (CHIRPS, ERA5-Land, MODIS) are in [`docs/data-sources.md`](docs/data-sources.md).

## Manuscript

The [`manuscript/`](manuscript/) folder holds the LaTeX source of the platform's data-descriptor preprint (manuscript version 1.3): `main.tex` with an inline bibliography and the six figures in `manuscript/figures/`. Compile with `tectonic main.tex` or `latexmk -pdf main.tex`; see `manuscript/README.md` for details, including regenerating Figure 2 from `data/metadata.json`. Every quantified methodological claim in the paper is checkable with one command, `python verify_paper_claims.py` in `data-pipeline/`.

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

The application code and the data pipeline are released under the MIT License (see `LICENSE`). The Zenodo archival record is published under CC BY 4.0. Data licensing follows the source datasets: CHIRPS, ERA5-Land and MODIS have their own terms and citation requirements — see `docs/data-sources.md` before redistributing derived data.

---

*Developed by **Ankit Deshmukh, Ph.D.** — Assistant Professor, Department of Civil Engineering, Pandit Deendayal Energy University, India ([ORCID: 0000-0002-1433-3872](https://orcid.org/0000-0002-1433-3872)). Research domains: Computational Hydrology | Drought Analysis | Geospatial Modelling | Hydroclimatic Extremes. Live platform: [drought.ankitdeshmukh.com](https://drought.ankitdeshmukh.com/).*
