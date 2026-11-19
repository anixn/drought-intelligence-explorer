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
from typing import Iterator

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
    # D8 (2026-11-19, Owner-confirmed): era B is a "Gridded Multi-Source
    # Product", never plain "observed" - CHIRPS (satellite-gauge), ERA5-Land
    # (reanalysis) and MODIS are observation-BASED inputs, each driving its
    # own indicator family, and are never merged into one field (a "blend"
    # label would claim a merge that did not happen, R3).
    ("observed", ("Gridded Multi-Source Product 1981-2025 -> current", "data/parquet/observed", True)),
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

    # national pre-aggregate: emitted only once the file exists (exact-path
    # rule - never point at a 404). Task M1.10.
    national_path = "data/parquet/_national_monthly.parquet"
    if (REPO / national_path).exists():
        catalog["national"] = national_path
    return catalog


def apply_projections(catalog: dict, info: dict) -> None:
    """Fill the projections era block (step 09 publish, task M2.12).

    info: {"label": str, "years": [y0, y1] or None,
           "files": {scenario: {stat: {variable: [relative paths]}}}}
    Catalog contract (docs/v2/03 s8.2): variable.files.projections =
    {scenario: {stat: [paths]}} - a structured extension of the s8.2
    example (scenario->path-list), provisional until the M5 era-C surfaces
    consume it. Paths are repo-relative and exact (no globbing).
    """
    from collections import OrderedDict as _OD
    era = catalog["eras"]["projections"]
    era["label"] = info["label"]
    era["available"] = True
    if info.get("years"):
        era["years"] = info["years"]
    files_by_var: dict = {}
    for scenario, stats in info["files"].items():
        for stat, variables in stats.items():
            for var_id, paths in variables.items():
                files_by_var.setdefault(var_id, _OD()).setdefault(
                    scenario, _OD())[stat] = paths
    for var in catalog["variables"]:
        if var["id"] in files_by_var:
            var["files"]["projections"] = files_by_var[var["id"]]
            if "projections" not in var["eras"]:
                var["eras"].append("projections")


def _iter_era_paths(era_files) -> Iterator[str]:
    """Yield every path string in an era files block.

    Era blocks are either a flat list of repo-relative paths (observed,
    atlas, ...) or a NESTED {scenario: {stat: [paths]}} dict (the step-09
    projections contract, docs/v2/03 s8.2). Iterating a dict yields its
    KEYS ("ssp245"), not its leaf paths - the bug behind the publish-time
    "variable path missing: ssp245" failures; recurse instead.
    """
    if isinstance(era_files, dict):
        for v in era_files.values():
            yield from _iter_era_paths(v)
    elif isinstance(era_files, (list, tuple)):
        yield from era_files
    elif era_files is not None:
        yield era_files


def validate(catalog: dict) -> list[str]:
    """Paths the UI can query (available eras' files + national) must exist on
    disk. Unavailable eras expose no files, so their directory absence is fine."""
    problems = []
    for era in catalog["eras"].values():
        if era["available"] and not (REPO / era["path"]).exists():
            problems.append(f"available era path missing: {era['path']}")
    for var in catalog["variables"]:
        for era_files in var["files"].values():
            for f in _iter_era_paths(era_files):
                if not (REPO / f).exists():
                    problems.append(f"variable path missing: {f}")
    if "national" in catalog and not (REPO / catalog["national"]).exists():
        problems.append(f"national path missing: {catalog['national']}")
    return problems


def check_urls(base: str, catalog: dict) -> int:
    """M1.5 gate: every path in the catalog must resolve over HTTP (HEAD)."""
    import urllib.request
    paths = [era["path"] for era in catalog["eras"].values() if era["available"]]
    if "national" in catalog:
        paths.append(catalog["national"])
    for var in catalog["variables"]:
        for era_files in var["files"].values():
            paths.extend(_iter_era_paths(era_files))
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
