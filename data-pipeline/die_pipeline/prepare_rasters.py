"""Step 2 — convert downloads into clipped, unit-harmonised monthly GeoTIFFs.

Produces, under <processed>/rasters/<var>/YYYY-MM.tif (EPSG:4326, float32,
NaN nodata, deflate-compressed):

    precip  mm per month          <- CHIRPS v3.0 global monthly tif (or IMD)
    pet     mm per month          <- ERA5-Land 'potential_evaporation'
    soil    % volumetric water    <- ERA5-Land swvl1..3 (0-100 cm) mean
    ndvi    fraction              <- MODIS MOD13A3.061 NDVI (or AppEEARS tifs)

Unit notes (checked against the file attributes at run time):
  * ERA5-Land monthly means store accumulations as a mean daily rate in
    metres of water equivalent; PET mm/month = |pe| * 1000 * days_in_month.
    The ECMWF sign convention (negative = upward flux) is absorbed with abs().
  * ERA5-Land volumetric soil water is m3/m3; percent volumetric = 100 x m3/m3.
  * MOD13A3 NDVI is stored as int16 with scale factor 0.0001.

Usage
-----
    python -m die_pipeline.prepare_rasters                 # everything
    python -m die_pipeline.prepare_rasters --source modis  # one source
    python -m die_pipeline.prepare_rasters --start 2026-06 --end 2026-09
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np

from . import common

try:
    import rasterio
    from rasterio.merge import merge
    from rasterio.transform import from_bounds, from_origin
    from rasterio.warp import Resampling, reproject, calculate_default_transform
except ImportError:            # pragma: no cover
    rasterio = None


# ---------------------------------------------------------------------------#
# generic helpers
# ---------------------------------------------------------------------------#

def _write_tif(path: str, arr: np.ndarray, transform, crs) -> None:
    # Audit F5: write to a .part file and rename atomically, mirroring the
    # downloaders — a crash mid-write must never leave a truncated GeoTIFF
    # that later runs accept as complete.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    h, w = arr.shape
    with rasterio.open(tmp, "w", driver="GTiff", height=h, width=w,
                       count=1, dtype="float32", crs=crs, transform=transform,
                       nodata=np.nan, compress="deflate") as dst:
        dst.write(arr.astype(np.float32), 1)
    os.replace(tmp, path)


def _clip_to_bbox(cfg: dict, arr: np.ndarray, transform, res: float | None = None):
    """Slice a lat/lon grid array to the configured bbox.

    Returns (arr, transform). Works for any regular grid given its affine.
    """
    w, s, e, n = cfg["region"]["bbox"]
    inv = ~transform
    # pixel centres
    x0, y0 = inv * (w, n)      # col, row of the NW corner (fractional)
    x1, y1 = inv * (e, s)
    r0 = int(np.floor(y0))
    r1 = int(np.ceil(y1))
    c0 = int(np.floor(x0))
    c1 = int(np.ceil(x1))
    r0, c0 = max(r0, 0), max(c0, 0)
    r1, c1 = min(r1, arr.shape[0]), min(c1, arr.shape[1])
    out = arr[r0:r1, c0:c1]
    # transform * (col, row) = (x, y); for a north-up grid these are the
    # west/east edges (x) and north/south edges (y) of the clipped window.
    west, north = transform * (c0, r0)
    east, south = transform * (c1, r1)
    new_t = from_bounds(west, south, east, north, out.shape[1], out.shape[0])
    return out, new_t


def _var_dir(cfg: dict, var: str) -> str:
    return common.processed_dir(cfg, "rasters", cfg["variables"][var]["dir"])


def _is_wgs84_geographic(crs) -> bool:
    """Accept the WGS 84 geographic CRS however the provider tagged it.

    CHIRPS v3.0 GeoTIFFs declare the standard WGS 84 degree grid under the
    2-D authority EPSG:9122 instead of EPSG:4326 (GDAL emits 9122 for
    north-up degree grids). For affine/degree purposes the two are the
    same CRS, so both (and any WGS 84 geographic WKT) pass.
    """
    if crs is None:
        return False
    try:
        if crs.to_epsg() in (4326, 9122):
            return True
        if not crs.is_geographic:
            return False
        return "World Geodetic System 1984" in crs.to_wkt()
    except Exception:                                   # noqa: BLE001
        return False


def _guard(arr: np.ndarray, lo: float, hi: float, label: str) -> np.ndarray:
    bad = (~np.isfinite(arr)) | (arr < lo) | (arr > hi)
    if bad.any():
        arr = np.where(bad, np.nan, arr)
    return arr


def _log(msg: str) -> None:
    print("  " + msg)


# ---------------------------------------------------------------------------#
# CHIRPS
# ---------------------------------------------------------------------------#

def prepare_chirps(cfg: dict, months) -> int:
    raw = common.raw_dir(cfg, cfg["downloads"]["chirps"]["dir"])
    out_dir = _var_dir(cfg, "precip")
    lo, hi = cfg["variables"]["precip"]["valid_range"]
    n_ok = n_skip = 0
    for (y, m) in months:
        yms = common.ym((y, m))
        src = os.path.join(raw, f"chirps-v3.0.{yms}.tif")
        dest = os.path.join(out_dir, f"{yms}.tif")
        if not os.path.exists(src):
            n_skip += 1
            continue
        if os.path.exists(dest) and os.path.getmtime(dest) >= os.path.getmtime(src):
            continue
        with rasterio.open(src) as ds:
            if not _is_wgs84_geographic(ds.crs):
                common.die(f"unexpected CRS in {src}: {ds.crs!s}")
            arr = ds.read(1).astype(np.float32)
            arr = _guard(arr, lo, hi, yms)
            clipped, new_t = _clip_to_bbox(cfg, arr, ds.transform)
        _write_tif(dest, clipped, new_t, "EPSG:4326")
        n_ok += 1
    _log(f"precip: {n_ok} months written, {n_skip} months missing on disk")
    return 0


# ---------------------------------------------------------------------------#
# ERA5-Land
# ---------------------------------------------------------------------------#

def _nc_time_axis(nc) -> tuple[np.ndarray, str]:
    for name in ("time", "valid_time"):
        if name in nc.variables:
            return nc.variables[name], name
    raise KeyError("no time/valid_time variable found in ERA5-Land file")


# Audit F12: explicit PET unit acceptance list instead of a string heuristic.
# Anything else must fail loudly (quoting the observed units), never silently
# mis-scale PET.
PET_DAILY_UNITS = ("m/day",)            # mean daily rate, metres of water
PET_MONTHLY_UNITS = ("m", "m/month")    # monthly accumulation, metres of water


def prepare_era5land(cfg: dict, months) -> int:
    raw = common.raw_dir(cfg, cfg["downloads"]["era5land"]["dir"])
    files = sorted(glob.glob(os.path.join(raw, "era5land_*.nc")))
    if not files:
        print("  no ERA5-Land .nc files found — nothing to do "
              "(PET/SMA stay missing until the CDS is configured)")
        return 0
    try:
        import netCDF4
    except ImportError:
        print("  [ERROR] netCDF4 is not installed (pip install netCDF4) — "
              "ERA5-Land preparation skipped, PET/SMA stay missing")
        return 1

    pet_dir = _var_dir(cfg, "pet")
    soil_dir = _var_dir(cfg, "soil")
    pet_lo, pet_hi = cfg["variables"]["pet"]["valid_range"]
    soil_lo, soil_hi = cfg["variables"]["soil"]["valid_range"]

    wanted = {common.ym(t) for t in months}
    written_pet: set[str] = set()
    written_soil: set[str] = set()
    had_pet = had_soil = False
    written = 0
    for f in files:
        nc = netCDF4.Dataset(f)
        tvar, tname = _nc_time_axis(nc)
        times = netCDF4.num2date(tvar[:], tvar.units,
                                 only_use_cftime_datetimes=False,
                                 only_use_python_datetimes=True)
        lats = np.asarray(nc.variables["latitude"][:], dtype=float)
        lons = np.asarray(nc.variables["longitude"][:], dtype=float)

        lat_desc = lats[0] > lats[-1]
        # grid geometry (assume regular)
        dlat = abs(lats[1] - lats[0])
        dlon = abs(lons[1] - lons[0])
        west, east = float(min(lons[0], lons[-1])), float(max(lons[0], lons[-1]))
        north, south = float(max(lats[0], lats[-1])), float(min(lats[0], lats[-1]))
        full_transform = from_bounds(west, south, east, north, len(lons), len(lats))

        def get(name):
            return np.asarray(nc.variables[name][:], dtype=float) if name in nc.variables else None

        pe, sw1, sw2, sw3 = (get("pe"), get("swvl1"), get("swvl2"), get("swvl3"))
        if pe is None and sw1 is None:
            _log(f"{os.path.basename(f)}: none of pe/swvl1 present — skipped")
            nc.close()
            continue
        had_pet = had_pet or pe is not None
        had_soil = had_soil or sw1 is not None

        for i, dt in enumerate(np.atleast_1d(times)):
            yms = f"{dt.year:04d}-{dt.month:02d}"
            if yms not in wanted:
                continue

            # --- PET -------------------------------------------------------
            if pe is not None:
                units = str(getattr(nc.variables["pe"], "units", "") or "").strip()
                u = " ".join(units.lower().split())
                if u in PET_DAILY_UNITS:
                    daily = True
                elif u in PET_MONTHLY_UNITS:
                    daily = False
                else:
                    common.die(f"unrecognised potential_evaporation units "
                               f"{units!r} in {os.path.basename(f)} — expected "
                               f"one of {PET_DAILY_UNITS + PET_MONTHLY_UNITS}; "
                               "extend the PET_*_UNITS lists rather than "
                               "guessing the scale")
                val = np.atleast_3d(pe)[i]
                if lat_desc:
                    val = val[::-1, :]
                pet = np.abs(val) * 1000.0
                if daily:
                    pet = pet * common.days_in_month((dt.year, dt.month))
                pet = _guard(pet, pet_lo, pet_hi, yms)
                c, new_t = _clip_to_bbox(cfg, pet, full_transform)
                _write_tif(os.path.join(pet_dir, f"{yms}.tif"), c, new_t, "EPSG:4326")
                written_pet.add(yms)

            # --- soil (mean of available layers 1-3, % volumetric) ----------
            # Design choice (audit F11): the unweighted mean of the three
            # volumetric layers is used even though the layers are unevenly
            # thick (a thickness-weighted 0-100 cm mean is the alternative);
            # the same statistic is applied identically in the GEE route.
            if sw1 is not None:
                layers = [np.atleast_3d(v)[i] for v in (sw1, sw2, sw3) if v is not None]
                soil = np.mean(layers, axis=0)
                if lat_desc:
                    soil = soil[::-1, :]
                soil = _guard(soil * 100.0, soil_lo, soil_hi, yms)
                c, new_t = _clip_to_bbox(cfg, soil, full_transform)
                _write_tif(os.path.join(soil_dir, f"{yms}.tif"), c, new_t, "EPSG:4326")
                written_soil.add(yms)

            written += 1
        nc.close()
    _log(f"pet/soil: {written} month(s) written from {len(files)} file(s)")
    # Audit F9: reconcile months found in the files against months wanted, so
    # a gap (e.g. a partial-year download) is loud instead of silent.
    for label, wset, had_any in (("PET", written_pet, had_pet),
                                 ("soil moisture", written_soil, had_soil)):
        if not had_any:
            continue
        gap = sorted(wanted - wset)
        if gap:
            _log(f"[WARNING] {len(gap)} requested month(s) produced no {label} "
                 f"raster ({gap[0]}..{gap[-1]}) — they will be missing downstream")
    return 0


# ---------------------------------------------------------------------------#
# MODIS NDVI (HDF tiles) and AppEEARS GeoTIFFs
# ---------------------------------------------------------------------------#

NDVI_SUBDSET_RE = re.compile(r'":([^"]*NDVI[^"]*)"$')


def _open_ndvi_subdataset(hdf_path: str):
    with rasterio.open(hdf_path) as ds:
        subs = list(ds.subdatasets)
    for name in subs:
        tag = name.lower()
        if "ndvi" in tag and "raw" not in tag and "quality" not in tag:
            return name
    raise RuntimeError(f"no NDVI subdataset in {hdf_path}: {subs}")


def _mosaic_to_wgs84(cfg: dict, src_paths: list[str], yms: str) -> None:
    """Mosaic sinusoidal tiles, warp to EPSG:4326, clip, write."""
    datasets = [rasterio.open(_open_ndvi_subdataset(p)) for p in src_paths]
    try:
        mosaic_arr, mosaic_t = merge(datasets, nodata=-3000)
        src_crs = datasets[0].crs
    finally:
        for d in datasets:
            d.close()

    arr = mosaic_arr[0].astype(np.float32)
    arr = np.where(arr <= -3000, np.nan, arr) * 0.0001   # int16 scale factor
    arr = _guard(arr, *cfg["variables"]["ndvi"]["valid_range"], yms)

    w, s, e, n = cfg["region"]["bbox"]
    # fix the output grid to the MODIS CMG standard resolution (~926.6 m)
    res = 0.008983131
    nx = int(np.ceil((e - w) / res)) + 1
    ny = int(np.ceil((n - s) / res)) + 1
    dst_t = from_bounds(w, s, w + nx * res, s + ny * res, nx, ny)
    dst = np.full((ny, nx), np.nan, dtype=np.float32)
    reproject(source=arr, destination=dst,
              src_transform=mosaic_t, src_crs=src_crs,
              dst_transform=dst_t, dst_crs="EPSG:4326",
              src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.nearest)
    _write_tif(os.path.join(_var_dir(cfg, "ndvi"), f"{yms}.tif"), dst, dst_t, "EPSG:4326")


def prepare_modis(cfg: dict, months) -> int:
    raw = common.raw_dir(cfg, cfg["downloads"]["modis"]["dir"])
    n_ok = n_skip = 0
    for (y, m) in months:
        yms = common.ym((y, m))
        dest = os.path.join(_var_dir(cfg, "ndvi"), f"{yms}.tif")
        year_dir = os.path.join(raw, f"{y:04d}")
        hdflist = sorted(glob.glob(os.path.join(year_dir, "*.hdf")))
        want = [p for p in hdflist if f"A{y * 1000 + _doy(y, m):03d}" in os.path.basename(p)]
        if not want:
            n_skip += 1
            continue
        if os.path.exists(dest):
            continue
        try:
            _mosaic_to_wgs84(cfg, want, yms)
            n_ok += 1
        except Exception as e:                       # noqa: BLE001
            print(f"  FAILED {yms}: {type(e).__name__}: {e}")
    _log(f"ndvi: {n_ok} months written, {n_skip} months missing on disk "
         "(HDF route; AppEEARS files are handled separately)")
    return 0


def _doy(y: int, m: int) -> int:
    from datetime import date
    return date(y, m, 1).timetuple().tm_yday


_DATE_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def prepare_appeears(cfg: dict) -> int:
    """Collect AppEEARS GeoTIFF exports (already EPSG:4326) by month."""
    raw = common.raw_dir(cfg, cfg["downloads"]["appeears"]["dir"])
    files = sorted(glob.glob(os.path.join(raw, "**", "*.tif"), recursive=True))
    if not files:
        print("  no AppEEARS tifs found — nothing to do")
        return 0
    by_month: dict[str, list[str]] = {}
    for f in files:
        mm = _DATE_RE.search(os.path.basename(f))
        if not mm:
            continue
        y, mth, day = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
        if not (1 <= mth <= 12):
            continue
        by_month.setdefault(f"{y:04d}-{mth:02d}", []).append(f)
    for yms, paths in sorted(by_month.items()):
        dest = os.path.join(_var_dir(cfg, "ndvi"), f"{yms}.tif")
        if os.path.exists(dest):
            continue
        datasets = [rasterio.open(p) for p in paths]
        try:
            arr, tr = merge(datasets, nodata=-3000)
            arr = arr[0].astype(np.float32)
            arr = np.where(arr <= -3000, np.nan, arr)
            if arr.max() > 1.5:                     # still scaled integers
                arr = arr * 0.0001
            arr = _guard(arr, *cfg["variables"]["ndvi"]["valid_range"], yms)
            c, new_t = _clip_to_bbox(cfg, arr, tr)
        finally:
            for d in datasets:
                d.close()
        _write_tif(dest, c, new_t, "EPSG:4326")
    _log(f"ndvi (AppEEARS): {len(by_month)} month(s) collected from {len(files)} file(s)")
    return 0


# ---------------------------------------------------------------------------#
# IMD gridded rainfall (optional national alternative for precip)
# ---------------------------------------------------------------------------#

IMD_GRID = {"west": 66.5, "south": 6.5, "east": 100.0, "north": 38.5,
            "res": 0.25}   # Pai et al. (2014) 0.25 degree rain grid

# Audit F4: a month with fewer valid daily grids than this fraction is written
# as missing rather than summed over its available days (which would
# undercount rainfall and fabricate drought).
_IMD_MIN_DAY_FRACTION = 0.9


def prepare_imd(cfg: dict, months) -> int:
    try:
        import imdlib as imd
    except ImportError:
        common.die("imdlib is not installed (pip install imdlib) — see the guide, "
                   "section on IMD gridded rainfall")

    raw = common.raw_dir(cfg, "imd")
    years = sorted({y for (y, _) in months})
    lo, hi = cfg["variables"]["precip"]["valid_range"]
    try:
        data = imd.open_data("rain", years[0], years[-1],
                             fn_format="yearwise", file_dirs=raw).data
    except Exception as e:                           # noqa: BLE001
        common.die(f"could not open IMD .grd files in {raw}: {e}")

    res = IMD_GRID["res"]
    nlat = int(round((IMD_GRID["north"] - IMD_GRID["south"]) / res)) + 1
    nlon = int(round((IMD_GRID["east"] - IMD_GRID["west"]) / res)) + 1
    base_t = from_bounds(IMD_GRID["west"], IMD_GRID["south"],
                         IMD_GRID["east"], IMD_GRID["north"], nlon, nlat)
    written = 0
    n_not_usable = 0
    for (y, m) in months:
        yms = common.ym((y, m))
        dest = os.path.join(_var_dir(cfg, "precip"), f"{yms}.tif")
        if os.path.exists(dest):
            continue
        sel = _imd_month_slice(data, y, m)
        if sel is None:
            continue
        # Audit F4: nansum of an all-NaN month is 0.0 mm — the strongest
        # drought signal there is, fabricated from a missing month. Missing
        # and badly partial months must stay missing (never-impute policy).
        n_days = sel.shape[0]
        valid_days = np.isfinite(sel).sum(axis=0)
        monthly = np.where(valid_days == 0, np.nan, np.nansum(sel, axis=0))
        monthly = np.where(valid_days < _IMD_MIN_DAY_FRACTION * n_days,
                           np.nan, monthly)
        monthly = np.where(monthly < 0, np.nan, monthly.astype(np.float32))
        if not np.isfinite(monthly).any():
            n_not_usable += 1
            _log(f"precip (IMD): {yms} has no pixel with valid data on >= "
                 f"{_IMD_MIN_DAY_FRACTION:.0%} of its days — left missing")
            continue
        monthly = _guard(monthly, lo, hi, yms)
        _write_tif(dest, monthly, base_t, "EPSG:4326")
        written += 1
    _log(f"precip (IMD): {written} month(s) written"
         + (f", {n_not_usable} month(s) unusable (missing/partial)"
            if n_not_usable else ""))
    return 0


def _imd_month_slice(data, y: int, m: int):
    import calendar
    ndays = calendar.monthrange(y, m)[1]
    doy0 = sum(calendar.monthrange(y, mm)[1] for mm in range(1, m)) 
    n_leap = 366 if calendar.isleap(y) else 365
    if data.shape[0] != n_leap:
        return None
    return data[doy0:doy0 + ndays]


# ---------------------------------------------------------------------------#
# entry point
# ---------------------------------------------------------------------------#

def main(argv=None) -> int:
    if rasterio is None:
        common.die("rasterio is required (pip install rasterio)")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--source", default="all",
                    choices=["all", "chirps", "era5land", "modis", "appeears", "imd"])
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    end = args.end or _latest_processed(cfg)
    months = common.month_range(args.start or cfg["history"]["start"], end)

    common.banner(f"Prepare rasters — {common.ym(months[0])} .. {common.ym(months[-1])}")
    rc = 0
    if args.source in ("all", "chirps"):
        rc |= prepare_chirps(cfg, months)
    if args.source in ("all", "era5land"):
        rc |= prepare_era5land(cfg, months)
    if args.source in ("all", "modis"):
        rc |= prepare_modis(cfg, months)
    if args.source in ("all", "appeears"):
        rc |= prepare_appeears(cfg)
    if args.source == "imd":
        rc |= prepare_imd(cfg, months)
    return rc


def _latest_processed(cfg: dict) -> str:
    """Latest month already present in any processed raster directory."""
    latest = cfg["history"]["start"]
    for var in cfg["variables"]:
        d = common.processed_dir(cfg, "rasters", cfg["variables"][var]["dir"])
        for f in glob.glob(os.path.join(d, "*.tif")):
            yms = os.path.basename(f)[:-4]
            if re.fullmatch(r"\d{4}-\d{2}", yms) and yms > latest:
                latest = yms
    return latest


if __name__ == "__main__":
    sys.exit(main())
