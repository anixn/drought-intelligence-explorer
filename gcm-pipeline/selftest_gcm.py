#!/usr/bin/env python3
"""DIE v2.0 - gcm-pipeline selftest_gcm.py (task M2.13, docs/v2/03 s3.11).

Deterministic orchestrator for the gcm-pipeline verification harness:
runs every step's --selftest suite (02-09) plus the frozen v1.0
data-pipeline harness, in fixed order, and fails loudly if any suite
fails. Nothing here runs production compute and nothing writes outside
work/test-output/ (the individual selftests own their scratch space).

Phase 1 (this file): wiring. Phase 2 (next session, same task ID): the
synthetic end-to-end mini world (3-model x 2-scenario, known biases +
injected drying trend) that exercises 02->09 compositionally - regrid
conservation, QDM identity + trend preservation, PET correctness,
SPI/SPEI calibration gates, ensemble exactness, partition sizes, catalog
integrity (docs/v2/03 s3.11).

Usage:
  python selftest_gcm.py              # run all suites
  python selftest_gcm.py --list       # list the suites
  python selftest_gcm.py --only 05,07 # run a subset (by prefix)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# (label, script path relative to `cwd`, cwd relative to repo root)
# Fixed order = pipeline order; the v1.0 harness first (frozen semantics
# must stay green before anything gcm-pipeline is trusted).
SUITES = [
    ("v1.0 data-pipeline harness (82 assertions)",
     "selftest.py", "data-pipeline"),
    ("02 regrid (T1a-T1e, T2, T3)", "02_regrid_025.py", "gcm-pipeline"),
    ("03 QDM (T1a-T5)", "03_qdm_bias_correct.py", "gcm-pipeline"),
    ("04 PET Hargreaves (T1a-T5)", "04_pet_hargreaves.py", "gcm-pipeline"),
    ("05 SPI/SPEI (T1-T7)", "05_spi_spei_compute.py", "gcm-pipeline"),
    ("06 district aggregation (T1-T6)", "06_district_aggregate.py",
     "gcm-pipeline"),
    ("07 ensemble statistics (T1-T5)", "07_ensemble_stats.py",
     "gcm-pipeline"),
    ("08 validation gate (T1-T7)", "08_validate_gcm.py", "gcm-pipeline"),
    ("09 export (T1-T9)", "09_export_parquet.py", "gcm-pipeline"),
]


def proj_env_fix(env: dict) -> dict:
    """Local-Windows workaround (PROGRESS M1.2 audit): PostGIS sets global
    PROJ_LIB/GDAL_DATA to unusable locations. Set them from the active env's
    rasterio bundle when those directories exist; a no-op elsewhere (the
    manylinux wheels used on CI bundle their own data)."""
    sp = Path(sys.prefix)
    for var, sub in (("PROJ_LIB", "Lib/site-packages/rasterio/proj_data"),
                     ("GDAL_DATA",
                      "Lib/site-packages/rasterio/gdal_data")):
        d = sp / sub
        if d.is_dir():
            env.setdefault(var, str(d))
    return env


def run_suite(label: str, script: str, cwd: str, python: str) -> tuple[bool, str]:
    """Run one --selftest suite; returns (ok, last-line summary)."""
    env = proj_env_fix(os.environ.copy())
    proc = subprocess.run([python, "-X", "utf8", script, "--selftest"],
                          cwd=REPO / cwd, env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1200)
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    tail = lines[-1] if lines else "(no output)"
    ok = proc.returncode == 0 and ("PASS" in out.upper())
    return ok, tail


def main() -> int:
    ap = argparse.ArgumentParser(description="gcm-pipeline selftest orchestrator (M2.13)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", metavar="PREFIX",
                    help="comma list of suite prefixes, e.g. '02,08,09' "
                         "(matches the leading number of the label)")
    args = ap.parse_args()

    suites = SUITES
    if args.only:
        keys = [k.strip() for k in args.only.split(",")]
        suites = [s for s in SUITES
                  if any(s[0].startswith(k) for k in keys)]
        if not suites:
            print(f"--only {args.only}: no suite matches")
            return 2

    if args.list:
        for label, script, _cwd in suites:
            print(f"  {label:<44} {script}")
        return 0

    print("=" * 78)
    print(f"GCM-PIPELINE SELFTEST ORCHESTRATOR - {len(suites)} suite(s)")
    print("=" * 78)
    python = sys.executable
    results = []
    for label, script, cwd in suites:
        print(f"[suite] {label:<44} {script}")
        try:
            ok, tail = run_suite(label, script, cwd, python)
        except subprocess.TimeoutExpired:
            ok, tail = False, "TIMEOUT (> 1200 s)"
        results.append((label, ok, tail))
        print(f"        -> {'PASS' if ok else 'FAIL'}   {tail[:110]}")

    n_fail = sum(1 for _l, ok, _t in results if not ok)
    print("=" * 78)
    for label, ok, tail in results:
        if not ok:
            print(f"  FAILED: {label}   ({tail})")
    print(f"RESULT: {len(results) - n_fail}/{len(results)} suites PASS"
          + ("" if n_fail == 0 else f" - {n_fail} FAILED"))
    print("=" * 78)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
