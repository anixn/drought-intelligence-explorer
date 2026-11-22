"""Verify a published R2 snapshot from the public URL (M7.1 gate).

Checks the four things the browser needs and nothing else:

  1. catalog reachable, parses, and reports a version
  2. HEAD works and advertises Content-Length + Accept-Ranges
  3. a Range request returns 206 with exactly the requested bytes
  4. CORS headers are returned for the dashboard origin
  5. (optional) byte parity: remote size == local size for a sample

Usage:
    python scripts/verify_r2.py --base https://pub-xxxx.r2.dev/v2026.09/ \
        --origin https://drought.ankitdeshmukh.com
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]


def head(url: str, origin: str | None):
    return requests.head(url, timeout=30, allow_redirects=True,
                         headers={"Origin": origin} if origin else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True,
                    help="public snapshot prefix, e.g. https://pub-x.r2.dev/v2026.09/")
    ap.add_argument("--origin", default="https://drought.ankitdeshmukh.com")
    ap.add_argument("--sample", default="observed/variable=spi_03/part-0.parquet",
                    help="object to use for the range/parity checks")
    args = ap.parse_args(argv)

    base = args.base if args.base.endswith("/") else args.base + "/"
    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(("PASS  " if ok else "FAIL  ") + name + ((" — " + detail) if detail else ""))

    # 1. catalog
    try:
        r = requests.get(base + "parquet/catalog.json", timeout=30)
        ok = r.status_code == 200
        version = None
        if ok:
            cat = r.json()
            version = cat.get("version")
            ok = bool(cat.get("variables")) and version is not None
        record("catalog.json", ok, f"HTTP {r.status_code}, version {version}")
    except Exception as e:  # noqa: BLE001
        record("catalog.json", False, str(e))

    # 2. HEAD on a parquet object
    sample_url = base + "parquet/" + args.sample
    try:
        h = head(sample_url, args.origin)
        size = h.headers.get("Content-Length")
        ranges = (h.headers.get("Accept-Ranges") or "").lower()
        record("HEAD parquet", h.status_code == 200 and size is not None,
               f"HTTP {h.status_code}, {size} bytes, accept-ranges={ranges or '—'}")
    except Exception as e:  # noqa: BLE001
        record("HEAD parquet", False, str(e))

    # 3. Range
    try:
        r = requests.get(sample_url, headers={"Range": "bytes=0-1023"}, timeout=30)
        got = r.headers.get("Content-Range", "")
        record("Range 0-1023", r.status_code == 206 and len(r.content) == 1024,
               f"HTTP {r.status_code}, {len(r.content)} bytes, Content-Range={got or '—'}")
    except Exception as e:  # noqa: BLE001
        record("Range 0-1023", False, str(e))

    # 4. CORS
    try:
        r = requests.get(base + "parquet/catalog.json", timeout=30,
                         headers={"Origin": args.origin})
        allow = r.headers.get("Access-Control-Allow-Origin")
        expose = r.headers.get("Access-Control-Expose-Headers", "")
        record("CORS", allow in (args.origin, "*"),
               f"allow-origin={allow or '—'}, expose={expose or '—'}")
    except Exception as e:  # noqa: BLE001
        record("CORS", False, str(e))

    # 5. parity with the local file (sample only)
    local = REPO / "data" / "parquet" / args.sample
    if local.exists():
        try:
            h = head(sample_url, args.origin)
            remote = int(h.headers.get("Content-Length", -1))
            record("byte parity (sample)", remote == local.stat().st_size,
                   f"local {local.stat().st_size} vs remote {remote}")
        except Exception as e:  # noqa: BLE001
            record("byte parity (sample)", False, str(e))

    # 6. wide CSV
    try:
        h = head(base + "drought/spi_03.csv", None)
        record("wide CSV", h.status_code == 200,
               f"HTTP {h.status_code}, {h.headers.get('Content-Length')} bytes")
    except Exception as e:  # noqa: BLE001
        record("wide CSV", False, str(e))

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        print("Base URL used:", base)
        print("Common fixes: bucket not public (r2.dev not allowed), CORS missing, "
              "or the snapshot prefix is wrong.")
        return 1
    print("Snapshot is readable by the dashboard:", base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
