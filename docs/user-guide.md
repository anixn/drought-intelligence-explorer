# Drought Intelligence Explorer — User Guide

The Drought Intelligence Explorer turns district-month drought indicators for India into maps, statistics, event catalogues and downloadable research outputs. Everything runs in your browser: there is no account, backend or API key.

This guide mirrors the in-app **User guide** section of **Documentation & Resources** (open it with the book icon in the sidebar footer, or press <kbd>?</kbd> anywhere in the app to jump there), where all documentation — about, data sources, methodology, validation, uncertainty, reproducibility, version history and glossary — is consolidated in one place.

---

## 1 · Quick start

1. **Choose the scope.** In the dark **Study context** panel set the geographic extent (All India, a state/UT or a district), the drought indicator and the analysis period. These choices are global — every tab, chart, table and export follows them. The sidebar holds only these study-context choices; every other control lives on the panel it drives.
2. **Pick an observation date (Overview).** The **Observation date** strip sits directly above the Overview panels it drives — the map, KPI cards, severity distribution, ranking and animation. Use **Latest** to jump to the newest observation, or **Play** to animate the record.
3. **Drill down.** Click a district on any map (or select it in the filters) to focus the whole application on that district. The selection persists while you change tabs.
4. **Go deeper.** Use **Historical Analysis** for frequency, duration, severity, trends and recurrence; **Drought Events** for individual episodes; **Propagation & Relationships** for cross-indicator comparisons.
5. **Export.** Tables offer CSV. The sidebar footer **Export** button triggers the current workspace's primary export; **Documentation & Resources** (book icon in the footer) provides long-format data, district statistics, the event catalogue, JSON metadata, boundaries, a map PNG, documentation and the citation. Every CSV embeds its analysis settings in a `#` metadata header.

### Keyboard and deep links

- <kbd>←</kbd> / <kbd>→</kbd> move between tabs when a tab has focus.
- <kbd>Esc</kbd> closes any dialog.
- <kbd>?</kbd> jumps to this guide (Documentation & Resources · section I).
- Each workspace has a stable URL hash: `#overview`, `#historical`, `#events`, `#propagation`, and `#data` (or `#docs`) for Documentation & Resources.

---

## 2 · What each workspace is for

| Workspace | Question it answers | Key outputs |
|---|---|---|
| **1 · Overview** | Where is drought now, how severe is it, and how has it changed? | Date slider, KPI snapshot, choropleth, time series, severity distribution, district ranking, animated evolution. |
| **2 · Historical Analysis** | How often, how long and how severely has drought occurred; is there a trend? | Frequency statistics, duration/severity maps, Mann–Kendall + Sen trend, recurrence, sortable ranking table. |
| **3 · Drought Events** | Which discrete drought episodes occurred, and when did they recover? | Event catalogue, onset timeline, duration distribution, event detail, definition-sensitivity panel. |
| **4 · Propagation & Relationships** | How do indicators respond to each other, at what lag, and where? | Lagged correlation with bootstrap CI, dual series, 10×10 heatmap, district lag map, single-date comparison. |
| **Docs · Documentation & Resources** | What exactly is in the data, how was it produced, and how can I reuse it? | Data sources, validation report, uncertainty & limitations, full methodology, glossary, downloads, citation, version history. |

---

## 3 · Reading the maps

- **Discrete colours** follow the indicator's own class thresholds in `data/metadata.json`; **continuous** mode interpolates the same palette. SMA and VCI use their own bounded-percentage thresholds — SPI thresholds would be invalid on them.
- **Hover** a district for its value and class. **Click** it to select it across the application.
- The **legend** lists class ranges. Hatched grey means **no data**, never zero.
- Regional means are **area-weighted** with precomputed equal-area district surfaces; affected areas sum the same surfaces.

---

## 4 · Reading the summary cards

| Card | Meaning |
|---|---|
| **Drought-affected area** | Equal-area surface (km² and % of region) in mild-or-worse drought classes at the selected date. |
| **Severe + extreme area** | The stricter subset: severe and extreme drought classes only. |
| **Mean indicator** | Area-weighted regional mean (or the selected district's value), classified with the indicator's own thresholds. |
| **Districts in drought** | Count and share of districts at or below the mild-drought threshold, with the severe/extreme count. |

The change indicator compares with the **previous available observation**, not a fixed calendar month.

---

## 5 · What each table shows

### District-wise ranking (Historical Analysis)

One row per state/UT or district.

- **Mean indicator** — area-weighted mean over the analysis period; the season filter applies.
- **Drought-affected area** — average share of area in mild-or-worse drought. For single-district rows this is the share of valid months in drought.
- **Severe area** — the same calculation restricted to severe and extreme classes.
- **Drought months** — months whose regional mean is at or below the moderate-drought truncation level.
- **Completeness** — valid district-months ÷ expected district-months. Rows below 50% are flagged “sparse” and excluded from the top-5 ranking.

Sort by clicking a column header, search by region name, change the level (state/district) with the selector, and export the current table with its metadata header.

### Event catalogue (Drought Events)

One row per drought run.

- **Onset / Termination** — first and last month of the run (runs analysis; default: at least 3 consecutive months at or below the truncation level).
- **Duration** — run length in months.
- **Max intensity** — the driest indicator value reached during the event.
- **Cumulative severity** — sum of the deficit below the truncation level over all event months.
- **Mean intensity** — cumulative severity ÷ duration.
- **Recovery** — months from event end until the indicator first returns to ≥ 0. `—` means the record ends first.
- **Censored** — the event touches the start or end of the record/period, so its true onset or termination may lie outside the data. Censored events are shown but excluded from duration/severity rankings.

Click a row to open the event detail: the district series around the event, the shaded event window, summary statistics and a map extent.

### Dataset information (Documentation & Resources · Data sources)

The top table documents the build: data mode, region, spatial and temporal resolution, declared period, reference climatology, CRS, area method and provenance. The indicator table lists each indicator's family, units, accumulation window, valid observations, missing share, true availability window and latest observation.

### Data quality (Documentation & Resources · Validation)

A live validation report recomputed in the browser:

- duplicate district rows (merged, last row kept),
- invalid date columns (skipped),
- non-numeric values (treated as missing),
- district identifiers absent from the boundaries (dropped),
- boundary districts absent from a dataset (rendered as no-data),
- completeness inside each indicator's **true availability window**.

By default only indicators already loaded in the session are reported. Press **Validate all indicators** to download and check the remaining matrices; results appear as each indicator finishes. Missing values are never imputed.

### Comparison / agreement statistics (Propagation)

The single-date comparison panel reports, for two indicators at the same month:

- **r (Pearson)** and **r²** across matched districts,
- **RMSE** — root-mean-square difference,
- **Bias (B − A)** — mean signed difference,
- **n (matched)** — districts with valid values for both,
- **Excluded (missing)** — districts missing at least one indicator.

Pairwise deletion is used; nothing is imputed to make the sample look larger.

---

## 6 · Reading the charts

| Chart | How to read it |
|---|---|
| **Time series** | Navy line = area-weighted regional mean (or the selected district). Dotted red lines are drought-class thresholds; gaps are missing months, never interpolated. The optional OLS trend is descriptive only. |
| **Severity distribution** | Share of the region's equal-area surface in each severity class at the selected date. Wet classes are combined; no-data area is reported separately. |
| **Evolution timeline** | Percentage of region area in mild-or-worse drought through the full record. Drag the slider to set the dashboard date, or press Play. |
| **Frequency by year** | Months below the truncation level in each year. The season filter applies. |
| **District frequency histogram** | Distribution across districts of the share of valid months in drought. |
| **Trend panel** | Mann–Kendall Z and Sen's slope with a 90% rank-based CI. When serial autocorrelation is significant, a Hamed–Rao variance correction is applied and both results are reported. |
| **Recurrence** | Empirical inter-arrival times and severity-exceedance return periods. No distribution is fitted; with few events these estimates carry wide, unquantified uncertainty. |
| **Lag correlation** | Pearson r at lags −12…+12 months. A positive lag means indicator B responds after A. The diamond marks the largest \|r\|; the bar is a moving-block bootstrap 95% CI that preserves serial dependence. |
| **Correlation heatmap** | Pairwise r at each pair's optimal lag. SPI/SPEI at different accumulation windows are correlated by construction — compare across families for propagation insight. |
| **Sensitivity panel** | Event counts when the minimum duration or truncation level is changed. The default methodology is annotated; other points are explicitly alternative scenarios. |

---

## 7 · Uncertainty and data caveats

- **Sample size is always reported.** Charts show valid counts; tables show completeness; correlations show matched months.
- **Significance is not causation.** Trend tests use a 5% level; correlations use a bootstrap interval; propagation is an association, not a causal claim.
- **The dataset is a research product, not an operational drought declaration.** Values depend on the reference climatology, aggregation method and underlying model/reanalysis inputs. Read the provenance banner and `docs/methodology.md` before citing a result.
- **Missing data are never filled.** Gaps stay gaps; maps show no-data; statistics use valid observations only.
- **Short records are labelled.** VCI starts with the MODIS record (2000-02) and the interface clamps the analysis period and labels the shorter window.

---

## 8 · Downloads

All exports are generated in your browser from the loaded data.

| Export | Contents |
|---|---|
| **Region extract (long format)** | One row per district-month with value, severity class, area and provenance; reproducibility header included. |
| **Selected indicator dataset** | The distributed wide-format matrix exactly as loaded. |
| **District drought statistics** | Mean, extremes, drought months/frequency, event counts (complete and censored), durations, severity, worst event and completeness per district. |
| **Drought event catalogue** | Every identified event with district, onset, termination, duration, intensity, severity, censoring and recovery. |
| **Comparison table CSV** | The current state/district ranking with all displayed statistics. |
| **Analysis metadata (JSON)** | Complete analysis state: indicator, geography, observation and analysis periods, reference period, methodology settings, provenance and export time. |
| **Boundaries (GeoJSON)** | District and state layers with the identifiers used by every export. |
| **Current map (PNG)** | The live map view, legend and selection. Use the Plain basemap if external tiles cannot be captured. |
| **Documentation** | This guide, the full methodology and the data-source register. |
| **Citation** | Ready-to-paste application and dataset citation. |

Every CSV begins with `#` comment lines recording the indicator, geography, dataset and analysis periods, reference period, methodology version, data mode/seed, source and export timestamp.

---

## 9 · Reproducing an analysis

To reproduce a result later, keep the exported CSV or JSON metadata together with the analysis settings:

1. indicator id and dataset version (`methodology_version`),
2. geographic extent and selected region/district,
3. observation date (`dateIdx`) for snapshot statistics,
4. analysis period and season,
5. event threshold and minimum duration (defaults are recorded explicitly),
6. trend granularity and correlation lag settings where used.

The **Analysis metadata (JSON)** export records all of these in one file.
