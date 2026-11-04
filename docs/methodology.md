# Methodology — Drought Intelligence Explorer (India)

**Version:** research-gee-1.0.1 · **Data mode:** static research (GEE-derived) · **Last updated:** 2026-11-03
**Citation:** Deshmukh, A. (2026). *Drought Intelligence Explorer: An Interactive Geospatial Platform for Drought Monitoring and Analysis in India* [computer software]. https://ankitdeshmukh.com/

> **Read this first.** This build ships a **historical research dataset** derived with Google Earth Engine from CHIRPS precipitation, ERA5-Land evapotranspiration and soil moisture, and MODIS NDVI. Indicator values are model- and observation-based district aggregates, not official drought declarations and not a substitute for operational monitoring. Each value is reproducible from the public inputs and the documented pipeline under `data-pipeline/` (see `data-sources.md`).

---

## 1. What the indicators measure

| Indicator | Family | What it standardizes | Units |
|---|---|---|---|
| SPI-1, SPI-3, SPI-6, SPI-12 | Meteorological | Accumulated precipitation (McKee et al., 1993) | z-score |
| SPEI-1, SPEI-3, SPEI-6, SPEI-12 | Water balance | Accumulated precipitation minus potential evapotranspiration (Vicente-Serrano et al., 2010) | z-score |
| Soil Moisture Anomaly (SMA) | Land surface | Departure of root-zone-equivalent soil moisture from its seasonal climatology | % |
| Vegetation Condition Index (VCI) | Land surface | Vegetation greenness rescaled between historical stress and optimum (Kogan, 1995) | % |

SPI converts accumulated precipitation over a window into a probability-based anomaly expressed in standard deviations relative to that calendar month's climatological distribution: negative values mean precipitation deficit. SPEI applies the same machinery to the climatic water balance, so it responds both to rainfall deficits and to atmospheric evaporative demand (and hence to warming trends that SPI cannot see). SMA and VCI are land-surface states: they reflect the *consequence* of meteorological drought with lag and memory.

## 2. Accumulation periods and reference period

Accumulation windows follow the conventional interpretation:

- **1 month** — immediate meteorological fluctuation;
- **3 months** — seasonal signal, roughly one monsoon season, common for agricultural drought;
- **6 months** — medium-term signal, often correlated with reservoir storage and streamflow anomalies;
- **12 months** — inter-annual signal for water resources and groundwater.

Standardization uses the **per-calendar-month distribution over the reference period**. In this research build the reference period is **1981–2020 (WMO-style 30 years)** for SPI/SPEI and the soil-moisture anomaly, and **2000–present** for VCI (limited by the MODIS NDVI record). A fixed, stated reference period is essential: SPI/SPEI values are only comparable within the reference period used to fit the distributions; changing the period changes the values.

## 3. Standardization and classification

### 3.1 Standardization (how values are produced)

- **Real SPI/SPEI (production guidance):** for each calendar month and accumulation window, fit a parametric distribution to the reference-period sample (gamma or Pearson Type III for SPI; log-logistic is the common choice for the water balance in SPEI), then map the observed accumulation to its non-exceedance probability and invert the standard normal CDF. Values are dimensionless z-scores.
- **This research build:** SPI fits a two-parameter gamma to positive accumulation totals per district and calendar month, with a mixed distribution for zero-rain months; SPEI fits a three-parameter log-logistic to the water balance (P − PET) using the L-moment (probability-weighted-moment) closed-form estimator of Vicente-Serrano et al. (2010) / Singh et al. (1993), the same method as the reference R `SPEI` package. Each fit is checked against the base sample and falls back to a distribution-free Gringorten plotting-position transform (average ranks for tied values) when the parametric fit is unstable. The exact implementation is `data-pipeline/die_pipeline/indicators.py`.

### 3.2 Classification thresholds

SPI and SPEI use the conventional nine-category scheme (class edges are inclusive on the dry side, e.g. −2.00 is *extreme drought*):

| Class | Value range |
|---|---|
| Extreme drought | ≤ −2.00 |
| Severe drought | −2.00 … −1.50 |
| Moderate drought | −1.50 … −1.00 |
| Mild drought | −1.00 … −0.50 |
| Near normal | −0.50 … 0.50 |
| Mildly wet | 0.50 … 1.00 |
| Moderately wet | 1.00 … 1.50 |
| Severely wet | 1.50 … 2.00 |
| Extremely wet | ≥ 2.00 |

**SMA and VCI do not reuse these thresholds.** Their distributions are bounded percentages, so z-score thresholds would be invalid. Their documented conventions in this build:

| SMA class | Range (%) | | VCI class | Range (%) |
|---|---|---|---|---|
| Extreme anomaly | ≤ −50 | | Extreme vegetation stress | 0–10 |
| Severe anomaly | −50 … −30 | | Severe vegetation stress | 10–20 |
| Moderate anomaly | −30 … −15 | | Moderate vegetation stress | 20–30 |
| Mild anomaly | −15 … −5 | | Mild vegetation stress | 30–40 |
| Near normal | −5 … +5 | | Normal vegetation condition | 40–60 |
| Wet anomaly | ≥ +5 | | Favourable conditions | 60–100 |

All thresholds are stored in `data/metadata.json` (`indicators[].classes`) and drive the map, legend, charts and statistics — a single source of truth. Editing metadata changes the application consistently.

## 4. Spatial aggregation and area computation

- **Areal means are area-weighted.** The regional mean of an indicator is `Σ(value × district area) / Σ(district area)` over districts with valid observations. Unweighted means are never used for regional summaries.
- **Affected-area statistics** sum the equal-area surfaces of districts whose value falls in a drought class. Percentages use the region's total area as denominator.
- **Areas were precomputed in an equal-area projection** — Lambert Azimuthal Equal-Area centred on India (`+proj=laea +lat_0=22.5 +lon_0=79.5`, WGS84 datum) — never from degree-coordinate arithmetic. Area statistics are computed from the same simplified geometry that the map serves, so reported areas are internally consistent with the displayed map (total: ~3.27 million km² for the supplied boundaries).
- **Boundaries** are community-maintained 2011-census-demarcation district polygons (724 districts, 36 states/UTs), generalised for web delivery (coordinate precision ~100 m; median district area error 0.03%). They follow the source dataset's depiction, carry no political endorsement, and are not authoritative for legal boundary determination. District reorganisations after the source vintage are not represented.

## 5. Drought events (frequency, duration, severity)

Events are identified by **runs analysis** (Yevjevich, 1967) on the continuous monthly series:

- **Truncation level:** the upper bound of the *moderate drought* class of the current indicator — **−1.00** for SPI/SPEI z-scores, **−15 %** for SMA, **30 %** for VCI. Using the class edge keeps event identification consistent with the classification legend for every indicator.
- **Minimum duration:** 3 consecutive months. Isolated one- or two-month excursions below the truncation level are **not** events under this definition.
- **Duration:** run length in months.
- **Severity:** cumulative deficit below the truncation level over event months, `Σ(truncation − value)`; positive, in indicator units.
- **Mean intensity:** severity ÷ duration.
- Missing months break runs; no interpolation, no carry-forward.

The historical panels (frequency, duration, severity) and the regional-comparison "drought months" column use these definitions. Season filters (SW monsoon etc.) restrict frequency statistics; event runs are always identified on the continuous monthly series, because season subsetting would manufacture artificial run breaks.


**Event catalogue, censoring and recovery (Drought Events tab).** The per-district catalogue lists onset, termination, duration, maximum intensity (most negative value), cumulative severity, and the mean intensity of every run. Events that touch the start or end of the available record (or the analysis-period edge) are flagged **censored** — their true onset/termination may lie outside the observed window — and are excluded from duration/severity ranking while remaining listed. **Recovery** is the number of months from an event's end to the first value ≥ 0; it is undefined (—) when the record ends first. **Sensitivity scenarios** re-run the catalogue with alternative minimum durations or truncation levels; the default (metadata) definition is always annotated and non-default results are visually separated.

**Recurrence (Historical tab, section E).** Empirical, non-parametric statistics on the regional event sequence: mean and median inter-arrival times, and severity-exceedance return periods computed as observation years ÷ number of events reaching an empirical severity quantile (Q50/Q75/Q90). No fitted distribution is assumed, uncertainty is not quantified by these point estimates, and they are labelled indicative only.

## 6. Missing observations

Missing district-months are **never imputed, interpolated, or silently treated as normal**:

- time series show gaps;
- maps style missing units explicitly as *no data* (grey hatch swatch in the legend);
- areal statistics use only valid observations and every chart reports the valid count (n);
- comparisons use pairwise deletion of missing pairs and report the number excluded;
- the comparison table carries a completeness column and flags rows below 50 %; such rows are excluded from "most affected" ranking;
- KPI cards display **N/A** rather than invented values when no valid observations exist.

## 7. Trend analysis

Two tiers of trend information are provided, clearly separated:

**Descriptive (Overview tab).** Optional ordinary-least-squares trends are offered on the time-series chart **only when ≥ 120 valid monthly observations exist** for the current selection. The fitted line, its slope and its sample size are printed with the chart. OLS on monthly indicator values is a simple descriptive diagnostic and is labelled accordingly.

**Inferential (Historical tab, section D).** Non-parametric trend testing on the regional series over the analysis period:

- **Mann–Kendall test** (Mann 1945; Kendall 1975) with tie-corrected variance, reported as S, Z and the two-sided p-value.
- **Sen's slope** (Sen 1968) — the median of pairwise slopes — with the rank-based 90 % confidence interval (Gilbert 1987, §17.3).
- **Serial autocorrelation handling.** Monthly drought indices are strongly autocorrelated, which inflates naive significance. When the detrended series (Sen slope removed) shows significant autocorrelation (|r_k| above the 1.96/√n white-noise bound, lags 1–12), the **Hamed–Rao (1998) variance correction** is applied: the effective sample size n* is computed from the significant autocorrelations and the MK variance is scaled by n/n*. Both the corrected and the uncorrected Z are reported, and the panel states which is in force. The default input is annual area-weighted means (12 valid months per year), which largely removes month-to-month dependence; a monthly granularity option is provided with this caveat attached.
- The sample size (valid years or months) is always displayed; with < 4 observations the tests are not computed.

## 8. Correlation and propagation analysis (Propagation tab)

**Single-date spatial comparison.** Agreement statistics between two indicators are computed over **matched dates and matched spatial units only** (pairwise deletion): Pearson correlation *r*, *r²*, RMSE, and bias (mean of B−A), with *n* and the count of excluded districts displayed next to the scatter. The difference view maps B−A in native units and uses a diverging ramp; when the two indicators have different families (z-score vs %) the difference is a contrast in mixed units and is labelled as such.

**Temporal cross-correlation.** For any indicator pair, Pearson correlations are computed at lags −12…+12 months on **matched months only** (pairwise deletion; VCI contributes from 2000-02 onward). The lag convention: lag h pairs A[t] with B[t+h], so a positive optimal lag means B responds h months after A. The optimal lag maximises |r| subject to ≥ 30 matched pairs.

**Uncertainty.** The 95 % confidence interval at the optimal lag uses a **moving-block bootstrap** (1 000 resamples; block length n^1/3 capped at 4–24 months; fixed seed 20261103 for reproducibility), which preserves serial dependence in both series by resampling blocks jointly. Nominal t-based p-values are shown for reference but treat months as independent.

**Scope restrictions.** Correlation is never interpreted as causation. SPI/SPEI at different accumulation scales correlate by construction; cross-family comparisons (e.g. SPI vs VCI, SMA vs SPEI) carry the propagation interpretation. The soil-moisture anomaly is a land-surface reanalysis proxy, not observed hydrological drought. Streamflow/groundwater propagation is explicitly marked unavailable — the dataset contains no such observations and none are simulated.

## 9. Data lineage tiers

The interface distinguishes four tiers of information, all labelled:

1. **Original observations** — CHIRPS v2.0/3.0 precipitation, ERA5-Land potential evaporation and volumetric soil water, and MODIS MOD13A3 NDVI, retrieved through Google Earth Engine and aggregated to districts.
2. **Derived indicators** — the district-month matrices under `data/drought/`.
3. **Spatially aggregated statistics** — area-weighted regional means, affected areas, KPI cards (computed live in your browser).
4. **Analytical summaries** — event statistics, comparisons, exports (computed live; precomputed CSV cross-checks under `data/summaries/`).

## 10. Resolution and limitations

- Spatial unit: administrative district (724 units as supplied); values are district aggregates, not point measurements.
- Temporal resolution: monthly; SPI/SPEI/SMA cover 1981-01 to 2025-12; VCI covers 2000-02 to 2025-12 because MODIS NDVI begins then.
- Missing months are genuine input gaps: a multi-month SPI/SPEI cannot be computed until its first rolling window is complete (e.g. SPI-3 starts 1981-03), and VCI has no pre-MODIS history. Nothing is imputed.
- Event statistics depend on the stated truncation level and minimum duration; different choices will shift counts.
- The map's continuous colour scale is a linear interpolation between class-anchor colours; it is a visual aid, while all statistics use the discrete classes.
- No claim of real-time monitoring: this is a historical and analytical explorer. An operational pipeline requires the production data sources listed in `data-sources.md`.

## 11. Reproducibility

- Extraction: `python run.py gee --project <project> --end 2025-12` (Google Earth Engine); local alternative documented in `data-pipeline/docs/data-update-guide.md`.
- Indicators/export/validation: `python run.py indicators`, `python run.py export`, `python run.py validate` (`data-pipeline/die_pipeline/`).
- Boundary preparation: `data-pipeline/prepare_boundaries.py` (documented simplification and equal-area pipeline).
- Metadata: `data/metadata.json` records indicator definitions, thresholds, provenance, versions, per-indicator availability and access dates.
- Precomputed cross-checks: `data/summaries/drought_events_spi_06.csv`, `data/summaries/state_statistics_spi_06.csv`.

## References

- McKee, T. B., Doesken, N. J., & Kleist, J. (1993). The relationship of drought frequency and duration to time scales. *Proc. 8th Conference on Applied Climatology*, Anaheim, CA, 179–184.
- Vicente-Serrano, S. M., Beguería, S., & López-Moreno, J. I. (2010). A multiscalar drought index sensitive to global warming: The Standardized Precipitation Evapotranspiration Index. *Journal of Climate*, 23(7), 1696–1718.
- Kogan, F. N. (1995). Application of vegetation index and brightness temperature for drought detection. *Advances in Space Research*, 15(11), 91–100.
- Yevjevich, V. (1967). *An objective approach to definitions and investigations of continental hydrologic droughts*. Hydrology Papers No. 23, Colorado State University, Fort Collins.
- World Meteorological Organization (2009). *Inter-regional workshop on indices and early warning systems for drought* (Lincoln Declaration on Drought Indices). WMO.
- Pai, D. S., Sridhar, L., Rajeevan, M., Sreejith, O. P., Satbhai, N. S., & Mukhopadhyay, B. (2014). Development of a new high spatial resolution (0.25° × 0.25°) long period (1901–2010) daily gridded rainfall data set over India. *MAUSAM*, 65(1), 1–18.
- Srivastava, A. K., Rajeevan, M., & Kshirsagar, S. R. (2009). Development of a high resolution daily gridded temperature data set (1969–2005) for the Indian region. *MAUSAM*, 60(4), 495–504.
- Hersbach, H., et al. (2020). The ERA5 global reanalysis. *Quarterly Journal of the Royal Meteorological Society*, 146(730), 1999–2049.
- Didan, K. (2015). MOD13A1 MODIS/Terra Vegetation Indices 16-Day L3 Global 500 m SIN Grid V006. NASA LP DAAC.
- Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica*, 13(3), 245–259.
- Kendall, M. G. (1975). *Rank Correlation Methods* (4th ed.). Charles Griffin, London.
- Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association*, 63(324), 1379–1389.
- Hamed, K. H., & Rao, A. R. (1998). A modified Mann–Kendall trend test for autocorrelated data. *Journal of Hydrology*, 204(1–4), 182–196.
- Gilbert, R. O. (1987). *Statistical Methods for Environmental Pollution Monitoring*. Van Nostrand Reinhold, New York.
- Kunsch, H. R. (1989). The jackknife and the bootstrap for general stationary observations. *The Annals of Statistics*, 17(3), 1217–1241. (moving-block bootstrap)
