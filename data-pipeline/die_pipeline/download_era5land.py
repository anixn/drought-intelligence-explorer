"""Step 1b — download ERA5-Land monthly means from the Copernicus CDS.

Requires a free Copernicus Climate Data Store account and an API key.
One-time setup (see docs/data-update-guide.md section 3 for details):

    1. Register at https://cds.climate.copernicus.eu/
    2. Open your profile page and copy the API key (it looks like
       "xxxxxxxx-xxxx-...") — the page shows the exact ~/.cdsapirc content.
    3. Create ~/.cdsapirc containing (never commit this file):

           url: https://cds.climate.copernicus.eu/api
           key: <your-personal-access-token>

The dataset is licensed under the Copernicus Products Licence (free use with
attribution). Requests are split per year to stay well inside queue limits;
each year request bundles all configured variables.

Usage
-----
    python -m die_pipeline.download_era5land --start 2025-01 --end 2025-09
    python -m die_pipeline.download_era5land --backfill 1981
"""

from __future__ import annotations

import argparse
import os
import sys

from . import common

try:
    import cdsapi
except ImportError:            # pragma: no cover
    cdsapi = None


def request_for(cfg: dict, year: int, months: list[int]) -> dict:
    d = cfg["downloads"]["era5land"]
    w, s, e, n = cfg["region"]["bbox"]
    return {
        "variable": list(d["variables"]),
        "year": f"{year:04d}",
        "month": [f"{m:02d}" for m in months],
        "day": ["01"],                      # monthly means carry one date per month
        "time": "00:00",
        "area": [n, w, s, e],               # [North, West, South, East]
        "data_format": "netcdf",
        "download_format": "unarchived",
        "product_type": d["product_type"],
    }


def _months_on_disk(raw: str, years: list[int]) -> dict[str, set[str]]:
    """YYYY-MM months actually inside each relevant era5land_*.nc file.

    Reads the netCDF time axis (the same parsing preparation uses), so a
    file that exists but contains only part of a year is reported as what
    it is — the audit's F1 fix. Returns {} when netCDF4 is unavailable.
    """
    import glob as _glob

    try:
        import netCDF4
        import numpy as np
        from .prepare_rasters import _nc_time_axis
    except ImportError:
        return {}
    out: dict[str, set[str]] = {}
    for y in years:
        for f in sorted(_glob.glob(os.path.join(raw, f"era5land_{y:04d}*.nc"))):
            try:
                nc = netCDF4.Dataset(f)
            except OSError:
                continue
            try:
                tvar, _ = _nc_time_axis(nc)
                times = netCDF4.num2date(tvar[:], tvar.units,
                                         only_use_cftime_datetimes=False,
                                         only_use_python_datetimes=True)
                out[f] = {f"{dt.year:04d}-{dt.month:02d}"
                          for dt in np.atleast_1d(times)}
            except Exception:                            # noqa: BLE001
                continue
            finally:
                nc.close()
    return out


def _dest_name(year: int, mlist: list[int]) -> str:
    """Span-encoded file name so different request windows never collide.

    A mid-year backfill writes era5land_2026.01-09.nc; the October quarterly
    request for 10-12 then writes era5land_2026.10-12.nc instead of being
    blocked by (or overwriting) the partial-year file. Full-year requests
    keep the plain era5land_<year>.nc name (preparation globs era5land_*.nc).
    """
    if len(mlist) == 12:
        return f"era5land_{year}.nc"
    return f"era5land_{year}.{mlist[0]:02d}-{mlist[-1]:02d}.nc"


def download(cfg: dict, months, overwrite: bool = False) -> int:
    if cdsapi is None:
        common.die("cdsapi is not installed. Run: pip install cdsapi "
                   "(and configure ~/.cdsapirc — see the guide).")

    d = cfg["downloads"]["era5land"]
    raw = common.raw_dir(cfg, d["dir"])
    dataset = d["dataset"]

    # group requested months by year
    by_year: dict[int, list[int]] = {}
    for (y, m) in months:
        by_year.setdefault(y, []).append(m)

    client = cdsapi.Client(quiet=True, progress=False)
    failed = 0
    for year in sorted(by_year):
        mlist = sorted(by_year[year])
        span = f"{year}-{mlist[0]:02d}" + ("" if len(mlist) == 12
                                           else f"..{mlist[-1]:02d}")
        dest = os.path.join(raw, _dest_name(year, mlist))
        # Skip only when every requested month is verifiably on disk (audit
        # F1): a partial-year file must never block the months it lacks.
        on_disk = _months_on_disk(raw, [year])
        have: set[str] = set()
        for months_in_file in on_disk.values():
            have |= months_in_file
        need = {f"{year}-{m:02d}" for m in mlist}
        if need <= have and not overwrite:
            print(f"  present     {span}  ({len(need)} month(s) verified on "
                  "the netCDF time axes)")
            continue
        if need - have:
            miss = sorted(need - have)
            print(f"  fetching    {span}  — {len(miss)} month(s) not yet on "
                  f"disk ({miss[0]}..{miss[-1]})")
        print(f"  requesting  {span}  (queued at CDS; typically minutes)...")
        try:
            r = request_for(cfg, year, mlist)
            client.retrieve(dataset, r).download(dest + ".part")
            os.replace(dest + ".part", dest)
            print(f"  downloaded  {span}  ({os.path.getsize(dest) / 1e6:.1f} MB)")
        except Exception as e:                       # noqa: BLE001 - report any CDS failure
            failed += 1
            print(f"  FAILED      {span} — {type(e).__name__}: {e}")
            print("             check ~/.cdsapirc, your CDS licence acceptance, "
                  "and https://status.copernicus.eu/")

    # Visibility line (audit F1): requested months that are still not on disk
    # after this run, so a stale PET/soil record cannot go unnoticed.
    on_disk = _months_on_disk(raw, sorted(by_year))
    have = set()
    for months_in_file in on_disk.values():
        have |= months_in_file
    still = [common.ym(t) for t in months if common.ym(t) not in have]
    if still:
        print(f"  [WARNING] {len(still)} requested month(s) are not on disk "
              f"after this run ({still[0]}..{still[-1]}) — PET/SMA will be "
              "missing for them until a later run fetches them")

    print(f"\nERA5-Land: done, {failed} failed request(s).")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--start", default=None, help="YYYY-MM")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: last month)")
    ap.add_argument("--backfill", type=int, default=None, metavar="YEAR",
                    help="download the full archive from this year")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    if args.backfill:
        months = common.month_range(f"{args.backfill}-01",
                                    args.end or _latest_useful_month())
    else:
        start = args.start or "1981-01"
        end = args.end or _latest_useful_month()
        months = common.month_range(start, end)

    common.banner(f"ERA5-Land monthly means — {len(months)} months "
                  f"({common.ym(months[0])} .. {common.ym(months[-1])})")
    return download(cfg, months, overwrite=args.overwrite)


def _latest_useful_month() -> str:
    """ERA5-Land lags real time by roughly 2-3 months; ask for 3 back."""
    import time
    t = time.gmtime()
    y, m = t.tm_year, t.tm_mon - 3
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


if __name__ == "__main__":
    sys.exit(main())
