"""Step 1c — download MODIS MOD13A3 v061 monthly NDVI from NASA Earthdata.

Why this module looks the way it does
-------------------------------------
The legacy direct-HTTP archive at ``e4ftl01.cr.usgs.gov/MOLT/MOD13A3.061``
was **retired** when LP DAAC finished migrating to the Earthdata Cloud.
Every month directory there now returns 404, which the previous version of
this script misread as "not on server yet" (symptom: *all* ~320 months
"not published", 0 failures). MOD13A3 v061 itself is alive and complete on
the Earthdata Cloud — verified via the CMR search API — so this version
goes through CMR + the cloud endpoints using NASA's own ``earthaccess``
library, which handles the bearer-token authentication for
``data.lpdaac.earthdatacloud.nasa.gov``.

Setup (once)
------------
1. Free NASA Earthdata account: <https://urs.earthdata.nasa.gov/>
2. ``~/.netrc`` (chmod 600; on Windows the same ``_netrc`` rules apply):

       machine urs.earthdata.nasa.gov
           login <your-earthdata-username>
           password <your-earthdata-password>

3. ``pip install earthaccess`` (added to requirements.txt)

Files are stored exactly as before — ``data_raw/modis/YYYY/MOD13A3.A*.hdf``
— so ``prepare_rasters --source modis`` is unchanged.

Alternative (zero code): AppEEARS *Area* request,
<https://appears.earthdatacloud.nasa.gov/>, polygon = India, layers =
MOD13A3 v061 "1 km monthly NDVI", GeoTIFF/geographic; drop the extracted
.tif files into ``data_raw/appeears/`` and prepare_rasters picks them up.

Usage
-----
    python -m die_pipeline.download_modis_ndvi                      # 2000-02 .. latest
    python -m die_pipeline.download_modis_ndvi --start 2026-06 --end 2026-09
    python -m die_pipeline.download_modis_ndvi --backfill 2000      # same as --start 2000-02
    python -m die_pipeline.download_modis_ndvi --compute-tiles      # bbox -> tiles
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from netrc import NetrcParseError

from . import common

_TILE_RE = re.compile(r"\.(h\d{2}v\d{2})\.")


# ---------------------------------------------------------------------------#
# tile computation (unchanged — sinusoidal grid is what the product uses)
# ---------------------------------------------------------------------------#

def compute_tiles(cfg: dict) -> list[str]:
    """MODIS sinusoidal tiles intersecting the configured bbox.

    The sinusoidal grid is equal-area; tile rows are 10 degrees of latitude
    and tile columns are 10 degrees of 'equatorial longitude'. A point at
    latitude phi and longitude lambda maps to an effective longitude
    lambda*cos(phi), so high-latitude west edges spill into lower-h tiles.
    """
    import numpy as np
    from pyproj import CRS, Transformer

    w, s, e, n = cfg["region"]["bbox"]
    sinu = CRS.from_proj4("+proj=sinu +R=6371007.181 +units=m +no_defs")
    t = Transformer.from_crs(CRS.from_epsg(4326), sinu, always_xy=True)
    lons = np.arange(w, e + 1e-9, 0.25)
    lats = np.arange(s, n + 1e-9, 0.25)
    tiles = set()
    for lo in lons:
        for la in lats:
            x, y = t.transform(float(lo), float(la))
            h = int(np.floor((x / 6371007.181 + np.pi) / (np.pi / 18)))
            v = int(np.floor((np.pi / 2 - y / 6371007.181) / (np.pi / 18)))
            tiles.add(f"h{h:02d}v{v:02d}")
    return sorted(tiles)


# ---------------------------------------------------------------------------#
# earthaccess plumbing
# ---------------------------------------------------------------------------#

def _netrc_credentials() -> tuple[str | None, str | None]:
    """Read urs.earthdata.nasa.gov credentials the way the legacy code did."""
    try:
        import netrc
        n = netrc.netrc()
        login, _account, password = n.authenticators("urs.earthdata.nasa.gov")
        return login, password
    except (FileNotFoundError, NetrcParseError, KeyError):
        return None, None


NETRC_HELP = """Earthdata credentials not found. Create ~/.netrc (chmod 600) with:
  machine urs.earthdata.nasa.gov
    login <username>
    password <password>
(Windows: the file may be named _netrc in your home directory.)"""


def _prime_env_from_netrc() -> None:
    """Expose .netrc credentials to earthaccess via environment variables.

    earthaccess looks for EARTHDATA_USERNAME/EARTHDATA_PASSWORD or ~/.netrc;
    mirroring the credentials into the environment keeps working on setups
    where earthaccess's own netrc discovery and Python's disagree.
    """
    if os.environ.get("EARTHDATA_USERNAME"):
        return
    login, password = _netrc_credentials()
    if login and password:
        os.environ["EARTHDATA_USERNAME"] = login
        os.environ["EARTHDATA_PASSWORD"] = password


def _granule_name(g) -> str:
    """Best-effort producer name, e.g. MOD13A3.A2026244.h24v06.061.2026289234646."""
    for path in (("umm", "DataGranule", "ProducerGranuleId"),
                 ("umm", "DataGranule", "Id"),
                 ("meta", "native-id")):
        try:
            v = g
            for key in path:
                v = v[key]
            if isinstance(v, str) and v:
                return v
        except (KeyError, TypeError, IndexError):
            continue
    return ""


def _hdf_basename(g, fallback_name: str) -> str:
    """Exact on-disk .hdf filename, taken from the granule's data link."""
    candidates: list[str] = []
    try:
        candidates.extend(g.data_links() or [])
    except Exception:                                   # noqa: BLE001
        pass
    try:
        for link in g.get("links") or []:
            href = link.get("href", "")
            if href:
                candidates.append(href)
    except Exception:                                   # noqa: BLE001
        pass
    for url in candidates:
        base = os.path.basename(url.split("?")[0])
        if base.lower().endswith(".hdf"):
            return base
    return fallback_name + ".hdf"


def download(cfg: dict, months, overwrite: bool = False) -> int:
    """Download the India tiles for each (year, month) via earthaccess.

    Same contract as before: HDF tiles land in data_raw/modis/YYYY/, the
    run is resumable (existing non-empty files are skipped), and the
    summary line is printed at the end.
    """
    try:
        import earthaccess
    except ImportError:
        common.die("earthaccess is required for MOD13A3 downloads "
                   "(pip install earthaccess). NASA retired the legacy "
                   "e4ftl01.cr.usgs.gov archive; MODIS is now served from "
                   "the Earthdata Cloud via CMR.")

    d = cfg["downloads"]["modis"]
    raw = common.raw_dir(cfg, d["dir"])
    tiles = set(d.get("tiles") or [])
    product = d.get("product", "MOD13A3.061")
    short_name, _, version = product.partition(".")
    w, s, e, n = cfg["region"]["bbox"]

    _prime_env_from_netrc()
    try:
        earthaccess.login()
    except Exception as e:                               # noqa: BLE001
        if _netrc_credentials()[0] is None:
            common.die(NETRC_HELP + f"\nDetails: {e}")
        common.die(f"earthaccess login failed: {type(e).__name__}: {e}\n{NETRC_HELP}")

    ok = present = missing = failed = 0
    for (y, m) in months:
        yms = common.ym((y, m))
        t0 = f"{y:04d}-{m:02d}-01T00:00:00Z"
        t1 = (f"{y:04d}-{m:02d}-{common.days_in_month((y, m)):02d}"
              f"T23:59:59Z")
        try:
            granules = earthaccess.search_data(
                short_name=short_name, version=version,
                bounding_box=(w, s, e, n), temporal=(t0, t1)) or []
        except Exception as e:                           # noqa: BLE001
            failed += 1
            print(f"  FAILED search {yms}: {type(e).__name__}: {e}")
            continue

        keep = []
        for g in granules:
            name = _granule_name(g)
            mo = _TILE_RE.search(name)
            if tiles and mo and mo.group(1) not in tiles:
                continue                                 # outside the bbox tiles
            keep.append((g, name))

        if not keep:
            missing += 1
            print(f"  not on server yet: {yms}")
            continue

        year_dir = os.path.join(raw, f"{y:04d}")
        os.makedirs(year_dir, exist_ok=True)

        todo = []
        for g, name in keep:
            dest = os.path.join(year_dir, _hdf_basename(g, name))
            if (os.path.exists(dest) and os.path.getsize(dest) > 0
                    and not overwrite):
                present += 1
                continue
            todo.append(g)

        if not todo:
            print(f"  {yms}: {len(keep)} tile(s) already present")
            continue

        try:
            files = earthaccess.download(todo, year_dir) or []
        except Exception as e:                           # noqa: BLE001
            failed += len(todo)
            print(f"  FAILED download {yms}: {type(e).__name__}: {e}")
            continue

        got = [f for f in files if f and os.path.exists(f)]
        ok += len(got)
        n_bad = len(todo) - len(got)
        failed += n_bad
        mb = sum(os.path.getsize(f) for f in got) / 1e6
        msg = f"  {yms}: {len(got)}/{len(todo)} file(s), {mb:.0f} MB"
        if n_bad:
            msg += f", {n_bad} failed"
        print(msg)
        time.sleep(0.3)                                  # be polite to the DAAC

    print(f"\nMOD13A3 (Earthdata Cloud/CMR): {ok} files downloaded, "
          f"{present} present, {missing} months not published, "
          f"{failed} failures.")
    return 1 if failed else 0


def _latest_useful_month() -> str:
    t = time.gmtime()
    y, m = t.tm_year, t.tm_mon - 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--start", default=None, help="YYYY-MM")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: last month)")
    ap.add_argument("--backfill", type=int, default=None, metavar="YEAR",
                    help="start from February of YEAR (earliest useful: 2000)")
    ap.add_argument("--tiles", nargs="*", default=None,
                    help="override the tile list from config.yaml")
    ap.add_argument("--compute-tiles", action="store_true",
                    help="print the MODIS tiles covering the configured bbox and exit")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    if args.compute_tiles:
        print("MODIS sinusoidal tiles covering bbox",
              cfg["region"]["bbox"], ":", *compute_tiles(cfg))
        return 0
    if args.tiles:
        cfg["downloads"]["modis"]["tiles"] = args.tiles

    if args.start:
        months = common.month_range(args.start, args.end or args.start)
    else:
        start = (f"{args.backfill}-02" if args.backfill
                 else "2000-02")                          # first MOD13A3 month
        end = args.end or _latest_useful_month()
        months = common.month_range(start, end)

    common.banner(f"MODIS MOD13A3.061 download (Earthdata Cloud) — "
                  f"{len(months)} months "
                  f"({common.ym(months[0])} .. {common.ym(months[-1])})")
    return download(cfg, months, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
