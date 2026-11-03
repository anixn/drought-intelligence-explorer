# Data Sources — Drought Intelligence Explorer (India)

**Access date for all URLs below:** 2026-11-02 · **Data mode of this build:** static research (GEE-derived)

---

## 1. What this build actually uses

| Role | Source | Notes |
|---|---|---|
| Rainfall (SPI/SPEI) | **CHIRPS daily precipitation v2.0 Final** via Google Earth Engine `UCSB-CHG/CHIRPS/DAILY` | Monthly totals, 1981–2025. Climate Hazards Center; public domain. The local download route in `config.yaml` targets CHIRPS v3.0. |
| Potential evapotranspiration and soil moisture (SPEI/SMA) | **ERA5-Land monthly aggregates** via Google Earth Engine `ECMWF/ERA5_LAND/MONTHLY_AGGR` | 0.1°, 1981–2025. Potential evaporation and volumetric soil water layers 1–3 (0–100 cm). Copernicus licence (attribution). |
| Vegetation condition (VCI) | **MODIS/Terra MOD13A3 v061 NDVI** via Google Earth Engine `MODIS/061/MOD13A3` | 1 km monthly, 2000-02–2025-12. VCI therefore starts in 2000, not 1981. NASA LP DAAC open data. |
| District/state boundaries | Community-maintained India district GeoJSON (2011-census demarcation) — https://github.com/udit-001/india-maps-data | 724 districts, 36 states/UTs. Generalised for the web (coordinate precision ~100 m, median district area error 0.03%). Simplification, equal-area statistics and registries produced by `data-pipeline/prepare_boundaries.py`. |
| District areas / centroids | Computed by `data-pipeline/prepare_boundaries.py` | Lambert Azimuthal Equal-Area projection centred on India (22.5° N, 79.5° E). |

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

## 2. Underlying source datasets

The research build uses the first four entries below through Google Earth Engine (CHIRPS daily, ERA5-Land, MODIS MOD13A3). The repository also ships an offline pipeline that can download CHIRPS v3.0 rainfall, ERA5-Land PET/soil moisture and MODIS NDVI directly — `data-pipeline/` (Python reference + R alternative) — then computes SPI/SPEI/SMA/VCI at district level and writes the wide-CSV contract above. See **`data-pipeline/docs/data-update-guide.md`** for the source catalogue, credential setup, first-time backfill and quarterly update runbook.

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

For the research build, cite the application plus the three source datasets:

> Deshmukh, A. (2026). *Drought Intelligence Explorer* [computer software, research build using CHIRPS, ERA5-Land and MODIS data]. https://ankitdeshmukh.com/
> Funk, C., et al. (2015). The climate hazards infrared precipitation with stations—a new environmental record for monitoring extremes. *Scientific Data*, 2, 150066.
> Muñoz-Sabater, J., et al. (2021). ERA5-Land: a state-of-the-art global reanalysis dataset for land applications. *Earth System Science Data*, 13, 4349–4383.
> Didan, K. (2015). *MOD13A3 MODIS/Terra Vegetation Indices Monthly L3 Global 1 km SIN Grid V061*. NASA EOSDIS Land Processes DAAC.

## 4. Boundary disclaimer

Boundaries follow the source dataset's depiction of 2011-census-demarcation districts. They are simplified for visualisation, are not authoritative for legal boundary determination, carry no political endorsement, and do not reflect district reorganisations after the source vintage.
