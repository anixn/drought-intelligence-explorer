# Data Sources — Drought Intelligence Explorer (India)

**Access date for all URLs below:** 2026-10-31 · **Data mode of this build:** demonstration (synthetic)

---

## 1. What this build actually uses

| Role | Source | Notes |
|---|---|---|
| Indicator values (all 10 indicators) | **Drought Intelligence Explorer demonstration generator** — `scripts/generate_demonstration_data.py`, `numpy default_rng(42)` | Synthetic. Seeded stochastic model with SPI-like marginals, spatial/temporal correlation, illustrative episodes and injected missing observations. Reproducible; **not observations**. |
| District/state boundaries | Community-maintained India district GeoJSON (2011-census demarcation) — https://github.com/udit-001/india-maps-data | 724 districts, 36 states/UTs. Generalised for the web (coordinate precision ~100 m, median district area error 0.03%). Simplification, equal-area statistics and registries produced by `scripts/prepare_boundaries.py`. |
| District areas / centroids | Computed by `scripts/prepare_boundaries.py` | Lambert Azimuthal Equal-Area projection centred on India (22.5° N, 79.5° E). |

### File inventory

```
data/
  metadata.json                          indicator definitions, thresholds, provenance
  districts.csv, states.csv              registries: ids, names, areas, centroids
  boundaries/india_districts.geojson     724 district polygons (~470 KB)
  boundaries/india_states.geojson        36 dissolved state polygons (~72 KB)
  boundaries/india_outline.geojson       national outline (~18 KB)
  drought/spi_01|03|06|12.csv            district × month matrices, wide format
  drought/spei_01|03|06|12.csv
  drought/soil_moisture.csv              SMA (%)
  drought/vci.csv                        VCI (%)
  summaries/drought_events_spi_06.csv    precomputed runs-analysis events (cross-check)
  summaries/state_statistics_spi_06.csv  precomputed state statistics (cross-check)
```

### Data contract (what a real deployment must supply)

Each indicator CSV is wide-format: `district_id, district_name, state_name,` followed by one `YYYY-MM` column per month. Missing cells are empty. `district_id` values must match `id` properties in `india_districts.geojson`. Thresholds, units, palettes and descriptions live in `metadata.json`, so **adding or replacing a dataset never requires code changes** — see README ("Adding and updating datasets").

The application validates at load time: duplicate district rows, invalid date columns, non-numeric values, unknown district ids, boundary districts absent from the dataset, and overall completeness. The report is shown in the *Data Sources* dialog and the browser console.

## 2. Recommended production sources (NOT used by this build)

These are peer-reviewed / operational datasets suitable for a real deployment. Replace the demonstration CSVs with district-aggregated values computed from them (any scripting environment can produce the wide CSV contract above).

| Source | Use for | Access |
|---|---|---|
| **IMD 0.25° gridded rainfall** (Pai et al., 2014) | SPI at all accumulation windows | https://imdpune.gov.in/cmpg/Griddata/Download.html |
| **IMD 1° gridded temperature** (Srivastava et al., 2009) | PET for SPEI (Hargreaves or Penman–Monteith) | https://imdpune.gov.in/ |
| **ERA5 / ERA5-Land reanalysis** (Hersbach et al., 2020) | SPEI water balance, soil-moisture anomalies | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means |
| **MODIS MOD13A1 NDVI** (Didan, 2015) | VCI | https://lpdaac.usgs.gov/products/mod13a1v061/ |
| **ESA CCI Soil Moisture** | SMA / percentile products | https://esa-soilmoisture-cci.org/ |
| **CHIRPS / GPM IMERG** | Independent precipitation cross-checks | https://www.chc.ucsb.edu/data/chirps · https://gpm.nasa.gov/data/imerg |

Operational Indian references worth consulting for drought classification practice: IMD's Pan-India Standardized Precipitation Index bulletins and the National Integrated Drought Early Warning System initiatives.

## 3. How to cite

If you deploy this application with real data, cite **both** the application and every dataset you loaded, with version and access date, e.g.:

> Deshmukh, A. (2026). *Drought Intelligence Explorer* [computer software]. https://ankitdeshmukh.com/
> India Meteorological Department (2025). *0.25° gridded rainfall data set over India (1901–present)*. Accessed 2026-10-31.
> Vicente-Serrano, S. M., Beguería, S., & López-Moreno, J. I. (2010). A multiscalar drought index sensitive to global warming. *Journal of Climate*, 23(7), 1696–1718.

For the demonstration build, cite it as synthetic:

> Deshmukh, A. (2026). *Drought Intelligence Explorer* [computer software, demonstration build with synthetic data, seed 42]. https://ankitdeshmukh.com/

## 4. Boundary disclaimer

Boundaries follow the source dataset's depiction of 2011-census-demarcation districts. They are simplified for visualisation, are not authoritative for legal boundary determination, carry no political endorsement, and do not reflect district reorganisations after the source vintage.
