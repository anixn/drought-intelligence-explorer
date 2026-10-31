#!/usr/bin/env python3
"""
generate_demonstration_data.py — Drought Intelligence Explorer (India)
======================================================================
Generates the SYNTHETIC DEMONSTRATION DATASET that ships with the
application. These are NOT observed measurements: every value is produced by
a documented, seeded stochastic model whose purpose is to exercise and
validate the full analytical pipeline (classification, areal aggregation,
event detection, comparison, export) with scientifically plausible
statistical structure.

Stochastic model (summary)
--------------------------
- A latent monthly hydroclimatic anomaly is built per district from three
  additive components: a national-scale AR(1) factor with Student-t
  innovations (drought clustering / fat tails), a state-scale AR(1) factor
  (regional coherence), and district-level white noise, modulated by a
  month-of-year variance profile (stronger monsoon-season variability).
- Illustrative episode forcings (2009, 2012, 2015-16, 2018-19 dry spells;
  2007, 2013, 2020 wet spells) are added to the national factor.
- Drought-proneness multipliers differentiate states (peninsular / western
  India more variance; north-east wetter and less variable).
- SPI-k  : k-month rolling sums of the latent anomaly, standardized per
            calendar month over the demonstration reference period
            (marginals ~ N(0,1) by construction, as for real SPI).
- SPEI-k : a climatic-water-balance variant that subtracts a PET proxy with
            a mild warming trend, giving late-record drying (as real SPEI).
- SMA    : soil-moisture anomaly (%) = bounded transform of the smoothed
            latent anomaly, with added soil-memory autocorrelation.
- VCI    : vegetation condition index (%) = bounded transform of short- and
            medium-term anomalies with realistic dry-season stress.
- Missing observations are injected deliberately (sparse districts, a
  pre-2015 gap in Ladakh, random dropouts, extra monsoon cloud gaps for
  VCI) so the application's missing-data handling is exercised and visible.

Reproducibility
---------------
numpy default_rng(SEED=42). Identical inputs + seed => identical outputs.

Outputs
-------
data/drought/*.csv        district x month indicator matrices (wide format)
data/metadata.json        single source of truth: indicators, thresholds,
                          classification palettes, provenance, citations
data/summaries/*.csv      precomputed drought-event and state summaries
                           (reproducibility cross-checks; the app recomputes
                           these client-side)

Usage
-----
python3 generate_demonstration_data.py <project_root>
"""

import csv
import json
import os
import sys

import numpy as np

SEED = 42
PERIOD_START = (2005, 1)
PERIOD_END = (2024, 12)
T2 = 2  # decimals for z-score indicators

# --- classification palettes (single source of truth, mirrored to metadata) ---
SPI_CLASSES = [
    {"key": "extreme_drought",  "label": "Extreme drought",   "color": "#8F252F", "min": None,   "max": -2.0, "minClosed": False, "maxClosed": True},
    {"key": "severe_drought",   "label": "Severe drought",    "color": "#B94747", "min": -2.0,  "max": -1.5, "minClosed": False, "maxClosed": True},
    {"key": "moderate_drought", "label": "Moderate drought",  "color": "#D97745", "min": -1.5,  "max": -1.0, "minClosed": False, "maxClosed": True},
    {"key": "mild_drought",     "label": "Mild drought",      "color": "#E9BE54", "min": -1.0,  "max": -0.5, "minClosed": False, "maxClosed": True},
    {"key": "near_normal",      "label": "Near normal",       "color": "#72A982", "min": -0.5,  "max": 0.5,  "minClosed": False, "maxClosed": False},
    {"key": "mildly_wet",       "label": "Mildly wet",        "color": "#A3C1CC", "min": 0.5,   "max": 1.0,  "minClosed": True,  "maxClosed": False},
    {"key": "moderately_wet",   "label": "Moderately wet",    "color": "#7BA7BE", "min": 1.0,   "max": 1.5,  "minClosed": True,  "maxClosed": False},
    {"key": "severely_wet",     "label": "Severely wet",      "color": "#4F91B8", "min": 1.5,   "max": 2.0,  "minClosed": True,  "maxClosed": False},
    {"key": "extremely_wet",    "label": "Extremely wet",     "color": "#2A5F85", "min": 2.0,   "max": None, "minClosed": True,  "maxClosed": False},
]
SMA_CLASSES = [
    {"key": "extreme_drought",  "label": "Extreme anomaly",   "color": "#8F252F", "min": None,  "max": -50.0, "minClosed": False, "maxClosed": True},
    {"key": "severe_drought",   "label": "Severe anomaly",    "color": "#B94747", "min": -50.0, "max": -30.0, "minClosed": False, "maxClosed": True},
    {"key": "moderate_drought", "label": "Moderate anomaly",  "color": "#D97745", "min": -30.0, "max": -15.0, "minClosed": False, "maxClosed": True},
    {"key": "mild_drought",     "label": "Mild anomaly",      "color": "#E9BE54", "min": -15.0, "max": -5.0,  "minClosed": False, "maxClosed": True},
    {"key": "near_normal",      "label": "Near normal",       "color": "#72A982", "min": -5.0,  "max": 5.0,   "minClosed": False, "maxClosed": False},
    {"key": "wet",              "label": "Wet anomaly",       "color": "#4F91B8", "min": 5.0,   "max": None,  "minClosed": True,  "maxClosed": False},
]
VCI_CLASSES = [
    {"key": "extreme_drought",  "label": "Extreme vegetation stress", "color": "#8F252F", "min": 0.0,   "max": 10.0, "minClosed": True,  "maxClosed": True},
    {"key": "severe_drought",   "label": "Severe vegetation stress",  "color": "#B94747", "min": 10.0,  "max": 20.0, "minClosed": False, "maxClosed": True},
    {"key": "moderate_drought", "label": "Moderate vegetation stress", "color": "#D97745", "min": 20.0,  "max": 30.0, "minClosed": False, "maxClosed": True},
    {"key": "mild_drought",     "label": "Mild vegetation stress",    "color": "#E9BE54", "min": 30.0,  "max": 40.0, "minClosed": False, "maxClosed": True},
    {"key": "near_normal",      "label": "Normal vegetation condition","color": "#72A982", "min": 40.0,  "max": 60.0, "minClosed": False, "maxClosed": False},
    {"key": "wet",              "label": "Favourable conditions",     "color": "#4F91B8", "min": 60.0,  "max": 100.0, "minClosed": True, "maxClosed": True},
]

SEASON_SIGMA = {1: 0.85, 2: 0.85, 3: 1.10, 4: 1.10, 5: 1.10, 6: 1.25,
                7: 1.30, 8: 1.30, 9: 1.25, 10: 0.95, 11: 0.90, 12: 0.85}
VCI_SEASON_OFFSET = {1: -6, 2: -5, 3: -4, 4: -2, 5: 0, 6: 5,
                     7: 8, 8: 8, 9: 5, 10: -1, 11: -3, 12: -5}

DRY_PRONE = {"maharashtra": 1.22, "karnataka": 1.18, "telangana": 1.20, "andhra-pradesh": 1.12,
             "rajasthan": 1.15, "gujarat": 1.15, "madhya-pradesh": 1.12, "chhattisgarh": 1.08,
             "odisha": 1.05, "jharkhand": 1.06, "uttar-pradesh": 1.02, "tamil-nadu": 1.05}
WET_BIASED = {"mizoram": 0.85, "meghalaya": 0.85, "arunachal-pradesh": 0.88, "assam": 0.90,
              "tripura": 0.88, "nagaland": 0.88, "manipur": 0.88, "sikkim": 0.90,
              "kerala": 0.95, "west-bengal": 0.96, "ladakh": 0.80}

EPISODES = [  # (start, end, amplitude in sigma units) — illustrative
    ((2005, 6), (2005, 9), -0.7),
    ((2007, 6), (2007, 9), +0.9),
    ((2009, 6), (2009, 9), -1.6),
    ((2012, 6), (2012, 9), -0.9),
    ((2013, 6), (2013, 9), +0.8),
    ((2014, 6), (2014, 9), -0.8),
    ((2015, 6), (2015, 12), -1.3),
    ((2016, 1), (2016, 6), -0.9),
    ((2018, 5), (2018, 12), -1.1),
    ((2019, 11), (2020, 2), -0.6),
    ((2020, 6), (2020, 9), +1.0),
    ((2021, 6), (2021, 8), +0.7),
    ((2022, 6), (2022, 8), +0.9),
    ((2023, 8), (2023, 10), -0.8),
]

SOURCES = [
    {"id": "demo-generator",
     "name": "Drought Intelligence Explorer demonstration generator",
     "role": "current dataset (synthetic)",
     "description": "Seeded stochastic generator (numpy default_rng, seed 42) producing district-month indicator matrices with SPI-like marginal distributions, spatial and temporal correlation, and injected missing observations. NOT observed data.",
     "url": "https://github.com/ankitdeshmukh/drought-intelligence-explorer (see scripts/generate_demonstration_data.py)",
     "access_date": "2026-10-31"},
    {"id": "boundaries",
     "name": "India administrative boundaries (districts, 2011+ census demarcation)",
     "role": "current boundaries",
     "description": "Community-maintained district GeoJSON, generalised for web use. Boundaries follow the source dataset's depiction and are simplified for visualisation; they carry no political endorsement and are not authoritative for legal boundary determination.",
     "url": "https://github.com/udit-001/india-maps-data",
     "access_date": "2026-10-31"},
    {"id": "imd-rainfall",
     "name": "IMD 0.25 degree gridded rainfall (Pai et al., 2014)",
     "role": "recommended production source",
     "description": "Station-based interpolated daily/monthly rainfall over India, 1901-present. Primary input for operational SPI computation in a real deployment.",
     "url": "https://imdpune.gov.in/cmpg/Griddata/Download.html",
     "access_date": "2026-10-31"},
    {"id": "imd-temperature",
     "name": "IMD 1 degree gridded temperature (Srivastava et al., 2009)",
     "role": "recommended production source",
     "description": "Gridded daily maximum/minimum temperature for Penman-Monteith or Hargreaves PET in SPEI computation.",
     "url": "https://imdpune.gov.in/",
     "access_date": "2026-10-31"},
    {"id": "era5",
     "name": "ERA5 reanalysis (Hersbach et al., 2020)",
     "role": "recommended production source",
     "description": "Global reanalysis (ECMWF) providing precipitation, temperature and soil-moisture variables; suitable for SPEI and soil-moisture anomaly baselines.",
     "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means",
     "access_date": "2026-10-31"},
    {"id": "modis-ndvi",
     "name": "MODIS MOD13A1 NDVI (Didan, 2015)",
     "role": "recommended production source",
     "description": "16-day 500 m vegetation indices used to derive the Vegetation Condition Index.",
     "url": "https://lpdaac.usgs.gov/products/mod13a1v061/",
     "access_date": "2026-10-31"},
    {"id": "esa-cci-sm",
     "name": "ESA Climate Change Initiative Soil Moisture",
     "role": "recommended production source",
     "description": "Multi-satellite merged surface soil moisture, 1978-present; basis for soil-moisture percentile/anomaly products.",
     "url": "https://esa-soilmoisture-cci.org/",
     "access_date": "2026-10-31"},
]


def month_list(start, end):
    out, y, m = [], start[0], start[1]
    while (y, m) <= end:
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def classify(v, classes):
    for c in classes:
        lo, hi = (c["min"], c["max"])
        lo_ok = (lo is None) or (v > lo) or (c["minClosed"] and v == lo)
        hi_ok = (hi is None) or (v < hi) or (c["maxClosed"] and v == hi)
        if lo_ok and hi_ok:
            return c["key"]
    return "near_normal"


def standardize_by_calendar(mat, months):
    """Empirical per-calendar-month standardization over the reference period
    (columns = time). This is the demonstration analogue of the per-month
    distribution fitting used by SPI/SPEI."""
    out = np.full_like(mat, np.nan)
    cal = np.array([m for (_, m) in months])
    for c in range(1, 13):
        cols = np.where(cal == c)[0]
        for i in range(mat.shape[0]):
            x = mat[i, cols]
            valid = x[np.isfinite(x)]
            if valid.size >= 5:
                sd = valid.std(ddof=1)
                out[i, cols] = (x - valid.mean()) / (sd if sd > 1e-9 else 1.0)
    return out


def rolling_sum(mat, k):
    out = np.full_like(mat, np.nan)
    for j in range(k - 1, mat.shape[1]):
        window = mat[:, j - k + 1: j + 1]
        ok = np.isfinite(window).all(axis=1)
        out[ok, j] = window[ok].sum(axis=1)
    return out


def ar1(rng, n, rho, df=None):
    innov = rng.standard_t(df, n) if df else rng.standard_normal(n)
    innov = innov / (np.sqrt(df / (df - 2)) if df else 1.0)
    out = np.zeros(n)
    for t in range(1, n):
        out[t] = rho * out[t - 1] + np.sqrt(1 - rho ** 2) * innov[t]
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    rng = np.random.default_rng(SEED)

    # ---- registries -------------------------------------------------------
    with open(os.path.join(root, "data", "districts.csv")) as fh:
        districts = list(csv.DictReader(fh))
    d_ids = [d["district_id"] for d in districts]
    d_states = [d["state_id"] for d in districts]
    d_state_names = [d["state_name"] for d in districts]
    d_names = [d["district_name"] for d in districts]
    areas = np.array([float(d["area_km2"]) for d in districts])
    state_ids = sorted(set(d_states))
    N, T = len(districts), 0

    months = month_list(PERIOD_START, PERIOD_END)
    T = len(months)
    date_cols = [f"{y:04d}-{m:02d}" for (y, m) in months]
    cal = np.array([m for (_, m) in months])
    season_sigma = np.array([SEASON_SIGMA[m] for m in cal])

    # ---- latent process ---------------------------------------------------
    f_nat = ar1(rng, T, rho=0.45, df=5)
    episode = np.zeros(T)
    for (ys, ms), (ye, me), amp in EPISODES:
        for t, (y, m) in enumerate(months):
            if (ys, ms) <= (y, m) <= (ye, me):
                episode[t] = amp
    f_nat = f_nat + episode

    state_factor = {s: ar1(rng, T, rho=0.40) for s in state_ids}

    beta = np.array([DRY_PRONE.get(s, 1.0) for s in d_states])
    bias = np.array([0.28 if s in WET_BIASED else 0.0 for s in d_states])

    e_dist = rng.standard_normal((N, T))
    latent = np.zeros((N, T))
    for i in range(N):
        latent[i] = beta[i] * (0.58 * f_nat + 0.42 * state_factor[d_states[i]]) + 0.55 * e_dist[i]
    latent = latent * season_sigma[None, :] / np.sqrt(0.58**2 + 0.42**2 + 0.55**2)
    latent = latent + bias[:, None]

    # PET proxy with mild warming trend (SPEI water balance)
    pet = 0.02 * np.arange(T) + 0.35 * ar1(rng, T, rho=0.5) + rng.standard_normal((N, T)) * 0.25
    wb = latent - 0.40 * pet

    spi1 = standardize_by_calendar(latent, months)
    spi3 = standardize_by_calendar(rolling_sum(latent, 3), months)
    spi6 = standardize_by_calendar(rolling_sum(latent, 6), months)
    spi12 = standardize_by_calendar(rolling_sum(latent, 12), months)
    spei1 = standardize_by_calendar(wb, months)
    spei3 = standardize_by_calendar(rolling_sum(wb, 3), months)
    spei6 = standardize_by_calendar(rolling_sum(wb, 6), months)
    spei12 = standardize_by_calendar(rolling_sum(wb, 12), months)

    # Soil moisture: latent anomaly smoothed with soil memory (AR) plus its own
    # noise, standardized per calendar month, then bounded to a percent anomaly.
    soil = np.zeros((N, T))
    for t in range(T):
        prev = soil[:, t - 1] if t else 0.0
        soil[:, t] = 0.62 * prev + 0.38 * latent[:, t] + 0.20 * rng.standard_normal(N)
    sma_z = standardize_by_calendar(soil, months)
    sma = np.clip(100 * np.tanh(0.25 * sma_z), -100, 100)

    veg = 0.55 * np.roll(spi1, 1, axis=1) + 0.45 * spi3
    veg[:, 0] = spi3[:, 0]
    veg = np.where(np.isfinite(veg), veg, 0.0)  # rolling-window start-up months
    veg = veg + 0.20 * rng.standard_normal((N, T))
    vci = np.clip(50 + 24 * veg + np.array([VCI_SEASON_OFFSET[m] for m in cal])[None, :], 0, 100)

    # ---- missing-data injection -------------------------------------------
    def inject(m, frac, subset_idx=None):
        mask = rng.random(m.shape) < frac
        if subset_idx is not None:
            keep = np.ones(m.shape, bool)
            keep[subset_idx, :] = False
            mask &= keep
        out = m.copy()
        out[mask] = np.nan
        return out

    sparse_idx = rng.choice(N, size=6, replace=False)
    ladakh_idx = [i for i, s in enumerate(d_states) if s == "ladakh"]
    sparse_mask_extra = rng.random((N, T)) < 0.22
    sparse_mask_extra[sparse_idx] = rng.random((len(sparse_idx), T)) < 0.30

    def apply_gaps(mat, base_frac, extra_sparse=True):
        out = inject(mat, base_frac)
        if extra_sparse:
            m = rng.random(out.shape) < 0.004
            out[m] = np.nan
            out[sparse_mask_extra & (rng.random(out.shape) < 0.5)] = np.nan
        return out

    def apply_pre_gap(mat, idx):
        out = mat.copy()
        t0 = 120  # 2015-01
        out[np.ix_(idx, np.arange(t0))] = np.nan
        return out

    datasets = {
        "spi_1": apply_pre_gap(apply_gaps(spi1, 0.004), ladakh_idx),
        "spi_3": apply_pre_gap(apply_gaps(spi3, 0.004), ladakh_idx),
        "spi_6": apply_pre_gap(apply_gaps(spi6, 0.004), ladakh_idx),
        "spi_12": apply_pre_gap(apply_gaps(spi12, 0.004), ladakh_idx),
        "spei_1": apply_pre_gap(apply_gaps(spei1, 0.005), ladakh_idx),
        "spei_3": apply_pre_gap(apply_gaps(spei3, 0.005), ladakh_idx),
        "spei_6": apply_pre_gap(apply_gaps(spei6, 0.005), ladakh_idx),
        "spei_12": apply_pre_gap(apply_gaps(spei12, 0.005), ladakh_idx),
        "sma": apply_pre_gap(apply_gaps(sma, 0.010), ladakh_idx),
        "vci": apply_pre_gap(apply_gaps(vci, 0.060), ladakh_idx),
    }
    vci_extra = rng.random(datasets["vci"].shape) < 0.08
    vci_extra[:, np.isin(cal, [6, 7, 8, 9])] = rng.random((N, (np.isin(cal, [6, 7, 8, 9])).sum())) < 0.09
    datasets["vci"][vci_extra] = np.nan

    # ---- write wide CSVs ---------------------------------------------------
    drought_dir = os.path.join(root, "data", "drought")
    os.makedirs(drought_dir, exist_ok=True)
    file_of = {}
    for key, mat in datasets.items():
        fname = {"spi_1": "spi_01.csv", "spi_3": "spi_03.csv", "spi_6": "spi_06.csv", "spi_12": "spi_12.csv",
                 "spei_1": "spei_01.csv", "spei_3": "spei_03.csv", "spei_6": "spei_06.csv", "spei_12": "spei_12.csv",
                 "sma": "soil_moisture.csv", "vci": "vci.csv"}[key]
        file_of[key] = f"data/drought/{fname}"
        decimals = T2 if key.startswith(("spi", "spei")) else 0
        with open(os.path.join(drought_dir, fname), "w", newline="") as fh:
            fh.write("district_id,district_name,state_name," + ",".join(date_cols) + "\n")
            for i in range(N):
                vals = []
                for j in range(T):
                    v = mat[i, j]
                    vals.append("" if not np.isfinite(v) else f"{v:.{decimals}f}")
                fh.write(f"{d_ids[i]},{d_names[i]},{d_state_names[i]}," + ",".join(vals) + "\n")

    # ---- metadata -----------------------------------------------------------
    def ind(key, label, family, name, units, accum, tooltip, description, classes, scale, fname):
        return {"id": key, "label": label, "family": family, "name": name, "units": units,
                "accumulation_months": accum, "file": f"data/drought/{fname}",
                "tooltip": tooltip, "description": description,
                "classification": "SPI/SPEI convention (McKee et al., 1993; Vicente-Serrano et al., 2010)"
                    if family in ("spi", "spei") else "Indicator-specific convention documented in methodology",
                "classes": classes, "scale": scale,
                "reference_period": f"{PERIOD_START[0]}-{PERIOD_END[0]} (demonstration)"}

    indicators = [
        ind("spi_1", "SPI-1", "spi", "Standardized Precipitation Index, 1-month", "z-score", 1,
            "One-month standardized precipitation anomaly: short-term meteorological moisture status.",
            "SPI-1 standardizes current-month precipitation against its per-calendar-month climatological distribution, isolating month-to-month meteorological fluctuations.", SPI_CLASSES, [-3, 3], "spi_01.csv"),
        ind("spi_3", "SPI-3", "spi", "Standardized Precipitation Index, 3-month", "z-score", 3,
            "Three-month standardized precipitation anomaly: seasonal (roughly a monsoon-season) drought signal.",
            "SPI-3 aggregates precipitation over the preceding three months and standardizes it per calendar month; it is a common operational window for seasonal agricultural drought.", SPI_CLASSES, [-3, 3], "spi_03.csv"),
        ind("spi_6", "SPI-6", "spi", "Standardized Precipitation Index, 6-month", "z-score", 6,
            "Six-month standardized precipitation anomaly: medium-term hydrological drought signal.",
            "SPI-6 reflects precipitation accumulated over half a year and correlates with reservoir storage and streamflow anomalies in many Indian basins.", SPI_CLASSES, [-3, 3], "spi_06.csv"),
        ind("spi_12", "SPI-12", "spi", "Standardized Precipitation Index, 12-month", "z-score", 12,
            "Twelve-month standardized precipitation anomaly: inter-annual drought signal.",
            "SPI-12 aggregates a full water year and is used for long-term water-resource and groundwater drought assessment.", SPI_CLASSES, [-3, 3], "spi_12.csv"),
        ind("spei_1", "SPEI-1", "spei", "Standardized Precipitation Evapotranspiration Index, 1-month", "z-score", 1,
            "One-month standardized climatic water balance (precipitation minus potential evapotranspiration).",
            "SPEI-1 standardizes the monthly climatic water balance, adding the effect of atmospheric evaporative demand to the SPI-1 signal.", SPI_CLASSES, [-3, 3], "spei_01.csv"),
        ind("spei_3", "SPEI-3", "spei", "Standardized Precipitation Evapotranspiration Index, 3-month", "z-score", 3,
            "Three-month standardized climatic water balance: temperature-sensitive seasonal drought signal.",
            "SPEI-3 is the seasonal water-balance analogue of SPI-3; differences between the two isolate the evaporative-demand contribution to drought.", SPI_CLASSES, [-3, 3], "spei_03.csv"),
        ind("spei_6", "SPEI-6", "spei", "Standardized Precipitation Evapotranspiration Index, 6-month", "z-score", 6,
            "Six-month standardized climatic water balance: medium-term drought including demand trends.",
            "SPEI-6 is the medium-term water-balance drought signal; because it includes potential evapotranspiration it responds to warming trends that SPI cannot see.", SPI_CLASSES, [-3, 3], "spei_06.csv"),
        ind("spei_12", "SPEI-12", "spei", "Standardized Precipitation Evapotranspiration Index, 12-month", "z-score", 12,
            "Twelve-month standardized climatic water balance: inter-annual drought including demand trends.",
            "SPEI-12 is the annual water-balance drought indicator used for multi-year drought characterization.", SPI_CLASSES, [-3, 3], "spei_12.csv"),
        ind("sma", "Soil Moisture Anomaly", "land", "Soil Moisture Anomaly (SMA)", "%", 3,
            "Percent anomaly of root-zone-equivalent soil moisture versus its seasonal climatology.",
            "SMA expresses soil-moisture departure from the per-calendar-month climatological mean as a percentage anomaly; negative values indicate soil-water deficit. Classification thresholds are indicator-specific (see methodology).", SMA_CLASSES, [-80, 80], "soil_moisture.csv"),
        ind("vci", "Vegetation Condition Index", "land", "Vegetation Condition Index (VCI)", "%", 1,
            "Percentage vegetation condition between historical stress and optimum (Kogan-style scaling).",
            "VCI rescales a vegetation index between its historical minimum (stress) and maximum (optimum); low values indicate vegetation under drought stress. Thresholds follow the Kogan (1995)-style convention and are documented in the methodology.", VCI_CLASSES, [0, 100], "vci.csv"),
    ]

    metadata = {
        "application": "Drought Intelligence Explorer",
        "region": "India",
        "version": "1.0.0",
        "data_mode": "demonstration",
        "data_provenance": "SYNTHETIC DEMONSTRATION DATASET. All indicator values are generated by a seeded stochastic model (numpy default_rng, seed 42) for interface and methodology validation. They are NOT observed measurements and must not be cited as hydroclimatic evidence.",
        "last_updated": "2026-10-31",
        "methodology_version": "demo-1.0.0",
        "random_seed": SEED,
        "period": {"start": date_cols[0], "end": date_cols[-1], "n_months": T},
        "temporal_resolution": "monthly",
        "spatial_units": "administrative districts (36 states/union territories, 724 units as supplied)",
        "spatial_resolution": "district-level aggregation (simplified boundary geometry served for visualisation)",
        "crs": "EPSG:4326 (WGS84) geographic coordinates, GeoJSON default",
        "area_method": "Precomputed equal-area statistics (Lambert Azimuthal Equal-Area centred at 22.5N, 79.5E). Areas are never derived from degree-coordinate arithmetic.",
        "reference_period": f"{PERIOD_START[0]}-01 to {PERIOD_END[0]}-12 (demonstration climatology)",
        "aggregation": {
            "areal_mean": "area-weighted mean over constituent districts using precomputed equal-area district areas",
            "affected_area": "sum of equal-area district areas whose indicator value falls in a drought class",
            "completeness": "valid district-month observations divided by expected district-month observations"
        },
        "events": {
            "method": "runs analysis (Yevjevich, 1967)",
            "threshold": -1.0,
            "min_duration_months": 3,
            "severity": "cumulative deficit below the -1.0 truncation level summed over event months",
            "intensity": "severity divided by duration"
        },
        "seasons": {
            "all": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            "cold": [1, 2],
            "pre_monsoon": [3, 4, 5],
            "sw_monsoon": [6, 7, 8, 9],
            "post_monsoon": [10, 11, 12]
        },
        "indicators": indicators,
        "sources": SOURCES,
        "citation": "Deshmukh, A. (2026). Drought Intelligence Explorer: An Interactive Geospatial Platform for Drought Monitoring and Analysis in India [computer software]. https://ankitdeshmukh.com/",
        "disclaimer": "Demonstration build: displayed values derive from a synthetic dataset and must not be interpreted as observed drought conditions, official declarations, or early-warning advisories."
    }
    with open(os.path.join(root, "data", "metadata.json"), "w") as fh:
        json.dump(metadata, fh, indent=2)

    # ---- precomputed summaries (reproducibility cross-checks) -------------
    summ_dir = os.path.join(root, "data", "summaries")
    os.makedirs(summ_dir, exist_ok=True)
    spi6m = datasets["spi_6"]
    with open(os.path.join(summ_dir, "drought_events_spi_06.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["district_id", "district_name", "state_name", "indicator",
                    "event_start", "event_end", "duration_months",
                    "severity", "mean_intensity", "min_value"])
        n_events = 0
        for i in range(N):
            series = spi6m[i]
            t = 0
            while t < T:
                if np.isfinite(series[t]) and series[t] <= -1.0:
                    t2 = t
                    while t2 < T and np.isfinite(series[t2]) and series[t2] <= -1.0:
                        t2 += 1
                    dur = t2 - t
                    if dur >= 3:
                        seg = series[t:t2]
                        sev = float(np.sum(-1.0 - seg))
                        w.writerow([d_ids[i], d_names[i], d_state_names[i], "spi_6",
                                    date_cols[t], date_cols[t2 - 1], dur,
                                    round(sev, 2), round(sev / dur, 2), round(float(seg.min()), 2)])
                        n_events += 1
                    t = t2
                else:
                    t += 1

    with open(os.path.join(summ_dir, "state_statistics_spi_06.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["state_id", "state_name", "indicator", "mean", "drought_months",
                    "affected_area_pct_mean", "severe_area_pct_mean", "completeness_pct"])
        for s in state_ids:
            idx = [i for i in range(N) if d_states[i] == s]
            sub = spi6m[idx]
            areas_s = areas[idx]
            finite = np.isfinite(sub)
            mean_v = np.nanmean(sub) if finite.any() else np.nan
            if finite.any():
                drought_area = (np.where(sub <= -0.5, 1, 0) * finite * areas_s[:, None]).sum(axis=0) / areas_s.sum()
                severe_area = (np.where(sub <= -1.5, 1, 0) * finite * areas_s[:, None]).sum(axis=0) / areas_s.sum()
                region = np.nansum(np.where(finite, sub, 0.0), axis=0) / np.maximum(finite.sum(axis=0), 1)
                drought_months = int(np.sum(np.isfinite(region) & (region <= -1.0)))
                aff, sev = drought_area.mean() * 100, severe_area.mean() * 100
                comp = finite.sum() / sub.size * 100
            else:
                drought_months, aff, sev, comp = 0, np.nan, np.nan, 0.0
            w.writerow([s, d_state_names[idx[0]], "spi_6",
                        round(float(mean_v), 3) if np.isfinite(mean_v) else "",
                        drought_months, round(float(aff), 2) if np.isfinite(aff) else "",
                        round(float(sev), 2) if np.isfinite(sev) else "", round(float(comp), 2)])

    # ---- verification report ------------------------------------------------
    print("=== demonstration dataset verification ===")
    print(f"districts: {N} | months: {T} ({date_cols[0]}..{date_cols[-1]}) | states/UTs: {len(state_ids)}")
    for key, mat in datasets.items():
        finite = np.isfinite(mat)
        vals = mat[finite]
        if vals.size == 0:
            print(f"{key:8s} !! NO VALID VALUES")
            continue
        fam = SPI_CLASSES if key.startswith(("spi", "spei")) else (SMA_CLASSES if key == "sma" else VCI_CLASSES)
        sample = np.random.default_rng(1).choice(vals, size=min(20000, vals.size))
        cls_counts = {}
        for v in sample:
            c = classify(float(v), fam)
            cls_counts[c] = cls_counts.get(c, 0) + 1
        top = ", ".join(f"{k}={100*c/sum(cls_counts.values()):.1f}%" for k, c in sorted(cls_counts.items(), key=lambda x: -x[1])[:4])
        w_area = areas[:, None] * finite
        nat = np.nansum(np.where(finite, mat, 0.0) * w_area, axis=0) / np.maximum(w_area.sum(axis=0), 1e-9)
        nat = nat[np.isfinite(nat)]
        lag1 = np.corrcoef(nat[:-1], nat[1:])[0, 1] if nat.size > 3 else float("nan")
        fpath = os.path.join(drought_dir, os.path.basename(file_of[key]))
        print(f"{key:8s} mean={vals.mean():+.2f} sd={vals.std():.2f} nationalLag1={lag1:.2f} "
              f"completeness={finite.mean()*100:.1f}% size={os.path.getsize(fpath)//1024}KB | {top}")
    ok = np.isfinite(spi3) & np.isfinite(spei3)
    ok6 = np.isfinite(spi6) & np.isfinite(spei6)
    print(f"pooled correlation SPI-3 vs SPEI-3: r={np.corrcoef(spi3[ok], spei3[ok])[0,1]:.2f} | "
          f"SPI-6 vs SPEI-6: r={np.corrcoef(spi6[ok6], spei6[ok6])[0,1]:.2f}")
    print(f"drought events (SPI-6 <= -1.0, >=3 months): {n_events}")
    print(f"total area: {areas.sum():,.0f} km2")


if __name__ == "__main__":
    main()
