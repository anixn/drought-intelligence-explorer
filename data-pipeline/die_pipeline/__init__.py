"""Drought Intelligence Explorer — offline data pipeline.

Modules
-------
download_chirps      CHIRPS v3.0 monthly rainfall (no authentication)
download_era5land    ERA5-Land monthly means via the Copernicus CDS
download_modis_ndvi  MODIS MOD13A3 v061 monthly NDVI via NASA Earthdata
prepare_rasters      clip / unit-harmonise downloads into monthly GeoTIFFs
zonal_stats          area-weighted district means + pixel counts
indicators           SPI, SPEI, soil-moisture anomaly, VCI
export_app           write the application data contract (wide CSVs, metadata)
validate             app-contract and science QA on the exported dataset
"""

__version__ = "1.0.0"
