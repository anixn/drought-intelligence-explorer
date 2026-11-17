#!/usr/bin/env python3
"""DIE v2.0 gcm-pipeline — production SSP chain runner (M2.14 helper).

Runs steps 01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09 in ssp mode
against the real Owner data (paths.yaml raw_root/raw_root_ssp), in order,
stopping at the first non-zero exit. Each step keeps its own skip logic
(SHA-256-verified outputs are reused), so the runner is resumable: re-run
after a failure and completed steps are skipped.

The runner NEVER publishes: step 09 runs staging-only (X9). `--publish`
stays a deliberate manual Owner action (X1 gate + sign-off + regression
--bless on the catalog fingerprints).

Usage:
  python run_ssp_chain.py [--upto 07] [--log work/ssp_chain_log.txt]

Every step's full output is appended to --log; the console shows the tail
of the current step.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def proj_env_fix(env: dict) -> dict:
    """PostGIS sets global PROJ_LIB/GDAL_DATA to unusable locations; point
    them at this env's rasterio data when present (no-op on CI)."""
    import sysconfig
    sp = sysconfig.get_paths()["purelib"]
    proj = Path(sp) / "rasterio" / "proj_data"
    gdal = Path(sp) / "rasterio" / "gdal_data"
    if proj.exists():
        env["PROJ_LIB"] = str(proj)
    if gdal.exists():
        env["GDAL_DATA"] = str(gdal)
    return env


STEPS = [
    ("01", "inventory gate", "01_inventory_check.py", []),
    ("02", "regrid historical+ssp245+ssp585", "02_regrid_025.py",
     ["--experiments", "historical,ssp245,ssp585"]),
    ("03", "QDM ssp245+ssp585", "03_qdm_bias_correct.py",
     ["--mode", "ssp", "--experiments", "ssp245,ssp585"]),
    ("04", "PET ssp245+ssp585", "04_pet_hargreaves.py",
     ["--mode", "ssp", "--experiments", "ssp245,ssp585"]),
    ("05", "indices ssp245+ssp585 (stitched)", "05_spi_spei_compute.py",
     ["--mode", "ssp", "--experiments", "ssp245,ssp585"]),
    ("06", "district aggregate ssp245+ssp585", "06_district_aggregate.py",
     ["--mode", "ssp", "--experiments", "ssp245,ssp585"]),
    ("07", "ensemble ssp245+ssp585", "07_ensemble_stats.py",
     ["--mode", "ssp", "--experiments", "ssp245,ssp585"]),
    ("08", "validation gate ssp (X1 evidence)", "08_validate_gcm.py",
     ["--mode", "ssp"]),
    ("09", "export ssp (STAGING ONLY - X9)", "09_export_parquet.py",
     ["--mode", "ssp"]),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--upto", default="09",
                    help="stop after this step number (default 09)")
    ap.add_argument("--log", default="work/ssp_chain_log.txt")
    args = ap.parse_args()

    log_path = HERE / args.log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = proj_env_fix(os.environ.copy())
    env["PYTHONUTF8"] = "1"
    log = open(log_path, "a", encoding="utf-8")
    log.write(f"\n{'=' * 78}\nSSP CHAIN RUN {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
              f"{'=' * 78}\n")
    log.flush()

    for num, label, script, script_args in STEPS:
        cmd = [PY, "-X", "utf8", script] + script_args
        print(f"[chain] step {num}: {label} ...", flush=True)
        log.write(f"\n----- step {num}: {label} | {' '.join(cmd)}\n")
        log.flush()
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=HERE, env=env, stdout=log,
                              stderr=subprocess.STDOUT)
        dt = time.time() - t0
        log.write(f"----- step {num} rc={proc.returncode} ({dt:.0f}s)\n")
        log.flush()
        if proc.returncode != 0:
            print(f"[chain] step {num} FAILED rc={proc.returncode} "
                  f"({dt:.0f}s) - see {log_path}", flush=True)
            return 1
        print(f"[chain] step {num} OK ({dt:.0f}s)", flush=True)
        if num == args.upto:
            print(f"[chain] stopped after step {num} (--upto)", flush=True)
            break

    log.write(f"CHAIN RUN COMPLETE {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.close()
    print("[chain] COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
