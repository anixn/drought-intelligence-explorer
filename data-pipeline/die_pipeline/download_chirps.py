"""Step 1a — download CHIRPS v3.0 monthly rainfall (global GeoTIFFs).

No authentication required. Verified endpoint (2026-10-31):
    https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/
        chirps-v3.0.YYYY.MM.tif          (~23 MB per month)

The *final* product is published around the third week of the following
month; the script simply skips months the server does not have yet (and
reports them), so it is safe to re-run on a schedule.

Usage
-----
    python -m die_pipeline.download_chirps [--start 2026-07] [--end 2026-09]
    python -m die_pipeline.download_chirps --backfill 1981    # full archive
    python -m die_pipeline.download_chirps --probe           # availability only
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests

from . import common


def url_for(cfg: dict, y: int, m: int) -> str:
    tpl = cfg["downloads"]["chirps"]["url_template"]
    # the template itself carries the padding (e.g. {M:02d}); pass raw ints
    return tpl.format(Y=int(y), M=int(m))


def months_to_fetch(cfg: dict, args) -> list[tuple[int, int]]:
    raw = common.raw_dir(cfg, cfg["downloads"]["chirps"]["dir"])
    if args.backfill:
        start, end = f"{args.backfill}-01", args.end or _latest_useful_month()
    else:
        start = args.start or cfg["history"]["start"]
        end = args.end or _latest_useful_month()
    return common.month_range(start, end)


def _latest_useful_month() -> str:
    """Current month minus one — the newest the final product can have."""
    today = time.gmtime()
    y, m = today.tm_year, today.tm_mon - 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def download(cfg: dict, months, probe: bool = False, overwrite: bool = False) -> int:
    raw = common.raw_dir(cfg, cfg["downloads"]["chirps"]["dir"])
    timeout = cfg["downloads"]["chirps"].get("timeout_s", 300)
    retries = cfg["downloads"]["chirps"].get("retries", 4)

    ok = missing = failed = skipped = 0
    for (y, m) in months:
        yms = common.ym((y, m))
        url = url_for(cfg, y, m)
        dest = os.path.join(raw, f"chirps-v3.0.{yms}.tif")

        if probe:
            try:
                r = requests.head(url, timeout=30, allow_redirects=True)
                if r.status_code == 200:
                    ok += 1
                    print(f"  available  {yms}  ({int(r.headers.get('content-length', 0)) / 1e6:.1f} MB)")
                else:
                    missing += 1
                    print(f"  not on server yet: {yms} (HTTP {r.status_code})")
            except requests.RequestException as e:
                failed += 1
                print(f"  probe failed: {yms} — {e}")
            continue

        if os.path.exists(dest) and os.path.getsize(dest) > 0 and not overwrite:
            skipped += 1
            continue

        last_err = None
        for attempt in range(1, retries + 1):
            try:
                with requests.get(url, timeout=timeout, stream=True) as r:
                    if r.status_code == 404:
                        missing += 1
                        print(f"  not on server yet: {yms}")
                        last_err = None
                        break
                    r.raise_for_status()
                    tmp = dest + ".part"
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=1 << 20):
                            fh.write(chunk)
                        written = fh.tell()
                    # Audit F6: verify the byte count when the server sends a
                    # Content-Length, so a cleanly-terminated-but-truncated
                    # response is retried instead of being accepted silently.
                    expected = int(r.headers.get("content-length") or 0)
                    if expected and written != expected:
                        raise requests.RequestException(
                            f"truncated download: {written} of {expected} bytes")
                    os.replace(tmp, dest)
                ok += 1
                print(f"  downloaded  {yms}  ({os.path.getsize(dest) / 1e6:.1f} MB)")
                last_err = None
                break
            except requests.RequestException as e:
                last_err = e
                time.sleep(min(2 ** attempt, 30))
        if last_err is not None:
            failed += 1
            print(f"  FAILED      {yms} — {last_err}")

    if probe:
        print(f"\nCHIRPS availability probe: {ok} available, {missing} not "
              f"published yet, {failed} unreachable.")
        return 0

    print(f"\nCHIRPS: {ok} downloaded, {skipped} already present, "
          f"{missing} not published yet, {failed} failed.")
    return 1 if (failed and not probe) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--start", default=None, help="YYYY-MM")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: last month)")
    ap.add_argument("--backfill", type=int, default=None, metavar="YEAR",
                    help="download the full archive from this year")
    ap.add_argument("--probe", action="store_true",
                    help="check server availability without downloading")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    months = months_to_fetch(cfg, args)
    common.banner(f"CHIRPS v3.0 download — {len(months)} months "
                  f"({common.ym(months[0])} .. {common.ym(months[-1])})")
    return download(cfg, months, probe=args.probe, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
