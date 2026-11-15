#!/usr/bin/env python3
"""DIE v2.0 - data/parquet/catalog.json generator (task M1.5).

Emits the UI's source of truth per docs/v2/03 section 8.2 (the roadmap's
"section 1.5" citation is stale - the schema contract is 8.2; corrected in
the roadmap this session):

  * exact relative paths only - static hosts cannot list directories, so no
    HTTP globbing and NEVER a path that does not resolve (R3-era honesty:
    nothing is published before it exists)
  * era blocks carry labels/years/paths even when the era has no files yet,
    marked available:false, so the UI can render disabled era switches
    without fake file lists
  * national/crossval/status top-level keys are OMITTED until their products
    exist (M1.10 / M6 / M3.2) - the exact-path rule forbids 404 pointers
  * era label shows actual coverage ("1981-2025 -> current", register
    resolution M); years are bumped by the monthly refresh (M3.1)
  * deterministic bytes: fixed key order, no timestamps, stable for manifests

Usage:
  python generate_catalog.py                 # write data/parquet/catalog.json
  python generate_catalog.py --check http://127.0.0.1:8123/   # M1.5 gate:
                              every emitted path must return HTTP 200 (HEAD)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
STORE = REPO / "data" / "parquet"
CATALOG = STORE / "catalog.json"

VARIABLES = [  # (id, label, unit) - labels/units per v1.0 metadata contract
    ("spi_01", "SPI-1", "z"),
    ("spi_03", "SPI-3", "z"),
    ("spi_06", "SPI-6", "z"),
    ("spi_12", "SPI-12", "z"),
    ("spei_01", "SPEI-1", "z"),
    ("spei_03", "SPEI-3", "z"),
    ("spei_06", "SPEI-6", "z"),
    ("spei_12", "SPEI-12", "z"),
    ("sma", "Soil Moisture Anomaly", "%"),
    ("vci", "VCI", "%"),
]

ERAS = OrderedDict([
    # (key, label, path, available-now?) - years bumped by refresh (res. M)
    ("observed", ("Observed 1981-2025 -> current", "data/parquet/observed", True)),
    ("atlas", ("Atlas reconstruction (1901-2025, pending verification)", "data/parquet/atlas", False)),
    ("projections", ("CMIP6 projections 2026-2100 (Owner compute pending)", "data/parquet/projections", False)),
])


def era_years(var_id: str, era: str):
    """Actual year coverage of one era-B variable file (honesty rule: report
    what exists, not nominal windows). Returns [min, max] or None."""
    if era != "observed":
        return None
    p = STORE / "observed" / f"variable={var_id}" / "part-0.parquet"
    if not p.exists():
        return None
    tbl = pq.read_table(p, columns=["year"])
    years = tbl.column("year").to_pylist()
    return [min(years), max(years)] if years else None


def build() -> dict:
    catalog = OrderedDict()
    catalog["version"] = "2.0.0"
    catalog["eras"] = OrderedDict()
    for key, (label, path, available) in ERAS.items():
        catalog["eras"][key] = OrderedDict([
            ("label", label), ("path", path), ("available", available),
        ])
    # era-level global years for eras that have files (resolution M)
    if catalog["eras"]["observed"]["available"]:
        catalog["eras"]["observed"]["years"] = [1981, 2025]

    catalog["variables"] = []
    for var_id, label, unit in VARIABLES:
        obs_path = f"data/parquet/observed/variable={var_id}/part-0.parquet"
        files = {}
        eras = []
        if (REPO / obs_path).exists():
            files["observed"] = [obs_path]
            eras.append("observed")
        entry = OrderedDict([
            ("id", var_id), ("label", label), ("unit", unit), ("eras", eras),
            ("files", files),
        ])
        yrs = era_years(var_id, "observed")
        if yrs and yrs != [1981, 2025]:
            entry["observed_years"] = yrs   # e.g. vci [2000, 2025]
        catalog["variables"].append(entry)
    return catalog


def validate(catalog: dict) -> list[str]:
    """Paths the UI can query (available eras' files) must exist on disk.
    Unavailable eras expose no files, so their directory absence is fine."""
    problems = []
    for era in catalog["eras"].values():
        if era["available"] and not (REPO / era["path"]).exists():
            problems.append(f"available era path missing: {era['path']}")
    for var in catalog["variables"]:
        for era_files in var["files"].values():
            for f in era_files:
                if not (REPO / f).exists():
                    problems.append(f"variable path missing: {f}")
    return problems


def check_urls(base: str, catalog: dict) -> int:
    """M1.5 gate: every path in the catalog must resolve over HTTP (HEAD)."""
    import urllib.request
    paths = [era["path"] for era in catalog["eras"].values() if era["available"]]
    for var in catalog["variables"]:
        for era_files in var["files"].values():
            paths.extend(era_files)
    failures = 0
    for p in paths:
        url = base.rstrip("/") + "/" + p
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
                rng = resp.headers.get("Accept-Ranges")
        except Exception as e:  # noqa: BLE001
            code, rng = f"FAIL ({type(e).__name__})", None
        mark = "OK " if code == 200 else "BAD"
        if code != 200:
            failures += 1
        print(f"  [{mark}] {code}  Accept-Ranges={rng}  {p}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="generate data/parquet/catalog.json (M1.5)")
    ap.add_argument("--check", metavar="BASE_URL", help="HEAD-check every catalog path (M1.5 gate)")
    args = ap.parse_args()

    catalog = build()
    problems = validate(catalog)
    if problems:
        for p in problems:
            print(f"VALIDATE: {p}")
        return 1
    if not args.check:
        CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        n_files = sum(len(f) for v in catalog["variables"] for f in v["files"].values())
        print(f"Wrote {CATALOG} ({CATALOG.stat().st_size} bytes, "
              f"{len(catalog['variables'])} variables, {n_files} files)")
    else:
        failures = check_urls(args.check, catalog)
        print("URL CHECK:", "ALL PASS" if failures == 0 else f"{failures} FAILURES")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
