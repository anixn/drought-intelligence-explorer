#!/usr/bin/env python3
"""Drought Intelligence Explorer — pipeline orchestrator.

Typical quarterly update (see docs/data-update-guide.md for the full runbook):

    python run.py update                          # fetch what is missing,
                                                   # reprocess, re-export,
                                                   # validate
    python run.py update --start 2026-07 --end 2026-09
    python run.py status                          # inventory of what is on disk
    python run.py download --start 2026-07        # step 1 only
    python run.py selftest                        # offline end-to-end test

Steps: download -> prepare -> zonal -> indicators -> export -> validate.
Each step is idempotent and can be re-run alone with the same command.
`indicators`, `export`, `update` and `gee` all refresh ../data/ in place and
run validation, so no manual copy from data_processed/ is required.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from die_pipeline import common                     # noqa: E402
from die_pipeline import download_chirps, download_era5land, download_modis_ndvi  # noqa: E402
from die_pipeline import prepare_rasters, zonal_stats, indicators, export_app, validate  # noqa: E402


def _latest_wanted(cfg: dict, back: int = 1) -> str:
    import time as _t
    t = _t.gmtime()
    y, m = t.tm_year, t.tm_mon - back
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def step_download(cfg: dict, start: str, end: str) -> None:
    common.banner("STEP 1/6 — download")
    months = common.month_range(start, end)
    print(f"window {start} .. {end} ({len(months)} months)")
    download_chirps.download(cfg, months)
    try:
        download_era5land.download(cfg, months)
    except SystemExit:
        print("  ERA5-Land skipped (cdsapi not configured) — SPEI/SMA will "
              "be missing until ~/.cdsapirc is set up (guide section 2.2)")
    # NDVI only from 2000-02 onward
    ndvi_start = max(start, "2000-02")
    if ndvi_start <= end:
        try:
            download_modis_ndvi.download(cfg, common.month_range(ndvi_start, end))
        except SystemExit:
            print("  MODIS NDVI skipped (Earthdata ~/.netrc not configured) — "
                  "VCI will be missing until it is set up (guide section 2.3), "
                  "or drop AppEEARS GeoTIFFs into data_raw/appeears/")


def step_prepare(cfg: dict, start: str, end: str) -> None:
    common.banner("STEP 2/6 — prepare rasters")
    months = common.month_range(start, end)
    prepare_rasters.prepare_chirps(cfg, months)
    prepare_rasters.prepare_era5land(cfg, months)
    prepare_rasters.prepare_modis(cfg, common.month_range(max(start, "2000-02"), end))
    prepare_rasters.prepare_appeears(cfg)


def step_zonal(cfg: dict) -> None:
    common.banner("STEP 3/6 — zonal statistics")
    districts, _ = common.load_registry(cfg)
    for var in cfg["variables"]:
        zonal_stats.run_var(cfg, var, districts)


def step_indicators(cfg: dict) -> None:
    common.banner("STEP 4/6 — indicators")
    indicators.compute(cfg)


def step_export(cfg: dict) -> None:
    common.banner("STEP 5/6 — export application data")
    export_app.run(cfg)


def step_validate(cfg: dict) -> int:
    common.banner("STEP 6/6 — validate")
    return validate.validate(cfg)


def cmd_update(cfg: dict, args) -> int:
    t0 = time.time()
    start = args.start or cfg["history"]["start"]
    end = args.end or _latest_wanted(cfg)
    # An explicit window and a full pass fetch the same way; every stage is
    # idempotent and content-aware, so only genuinely missing months are
    # touched (the identical if/else branches here were audit finding F8).
    step_download(cfg, start, end)
    step_prepare(cfg, start, end)
    step_zonal(cfg)
    step_indicators(cfg)
    step_export(cfg)
    rc = step_validate(cfg)
    print(f"\nTotal time: {(time.time() - t0) / 60:.1f} min")
    if rc == 0:
        print("\nNext: commit data/ to git and push — GitHub Pages deploys "
              "automatically. Review docs/data-update-guide.md section 6 for "
              "the final checklist (banner wording, README badge).")
    return rc


def _apply_gee_metadata(cfg: dict) -> None:
    """Swap the app provenance block for the Google Earth Engine route."""
    gee_meta = (cfg.get("gee") or {}).get("app_metadata") or {}
    for key in ("data_mode", "methodology_version", "data_provenance",
                "disclaimer"):
        if gee_meta.get(key):
            cfg["app_metadata"][key] = gee_meta[key]
    if gee_meta.get("sources"):
        cfg["app_metadata"]["sources"] = gee_meta["sources"]


def cmd_gee(cfg: dict, args) -> int:
    """GEE extraction -> indicators -> export -> validate."""
    t0 = time.time()
    gee = cfg.get("gee") or {}
    end = args.end or gee.get("end") or "2025-12"
    start = args.start or cfg["history"]["start"]
    export_start = (args.export_start or gee.get("export_start")
                    or cfg["export"]["period_start"])

    # The indicator/export steps read these two windows from config.
    cfg["history"]["end"] = end
    cfg["export"]["period_start"] = export_start
    cfg["export"]["period_end"] = end
    _apply_gee_metadata(cfg)

    if not args.skip_extract:
        from die_pipeline import gee_export
        gee_export.run(
            cfg,
            project=args.project,
            start=start,
            end=end,
            vars=args.vars,
            chunk_months=args.chunk_months,
            boundary_asset=args.boundary_asset,
            upload_boundary=args.upload_boundary,
            force=args.force,
        )
    else:
        common.banner("GEE extraction skipped — reusing "
                      "data_processed/series/*.csv")

    step_indicators(cfg)
    step_export(cfg)
    rc = step_validate(cfg)
    print(f"\nGEE build total time: {(time.time() - t0) / 60:.1f} min")
    if rc == 0:
        print("\nNext: review data/ and commit it. The app period is now "
              f"{export_start}..{end}. See docs/gee-update-guide.md §7 for "
              "the one-time UI wording switch.")
    return rc


def cmd_status(cfg: dict) -> int:
    common.banner("Pipeline status")
    rows = []
    for var, spec in cfg["variables"].items():
        d = common.processed_dir(cfg, "rasters", spec["dir"])
        n = len(glob.glob(os.path.join(d, "*.tif")))
        rows.append((f"rasters/{spec['dir']}", n))
    chirps = len(glob.glob(os.path.join(
        common.raw_dir(cfg, cfg["downloads"]["chirps"]["dir"]), "*.tif")))
    era = len(glob.glob(os.path.join(
        common.raw_dir(cfg, cfg["downloads"]["era5land"]["dir"]), "*.nc")))
    modis = len(glob.glob(os.path.join(
        common.raw_dir(cfg, cfg["downloads"]["modis"]["dir"]), "*", "*.hdf")))
    appears = len(glob.glob(os.path.join(
        common.raw_dir(cfg, cfg["downloads"]["appeears"]["dir"]), "**", "*.tif"),
        recursive=True))
    print(f"  raw/chirps tifs        : {chirps}")
    print(f"  raw/era5land nc files  : {era}")
    print(f"  raw/modis hdf tiles    : {modis}")
    print(f"  raw/appeears tifs      : {appears}")
    for name, n in rows:
        print(f"  processed/{name:14s}: {n} months")
    for var in ("precip", "pet", "soil", "ndvi"):
        p = common.processed_file(cfg, "series", f"{var}.csv")
        if os.path.exists(p):
            import pandas as pd
            df = pd.read_csv(p, usecols=["date"])
            print(f"  series/{var}.csv      : {df['date'].nunique()} months "
                  f"({df['date'].min()} .. {df['date'].max()})")
    inds = common.processed_dir(cfg, "indicators")
    for f in sorted(glob.glob(os.path.join(inds, "*.csv"))):
        print(f"  indicators/{os.path.basename(f):12s}: present")
    md = common.load_app_metadata(cfg)
    if md:
        print(f"\n  app metadata: mode={md['data_mode']} period="
              f"{md['period']['start']}..{md['period']['end']} "
              f"updated={md['last_updated']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="update",
                    choices=["update", "download", "prepare", "zonal",
                             "indicators", "export", "validate", "status",
                             "selftest", "gee"])
    ap.add_argument("--config", default=None)
    ap.add_argument("--start", default=None, help="YYYY-MM window start")
    ap.add_argument("--end", default=None, help="YYYY-MM window end")
    ap.add_argument("--project", default=None,
                    help="GEE: Google Cloud project id (else gee.project)")
    ap.add_argument("--export-start", default=None,
                    help="GEE: first month written to data/drought/*.csv")
    ap.add_argument("--vars", nargs="+", default=None,
                    choices=["precip", "pet", "soil", "ndvi"],
                    help="GEE: subset of variables to extract")
    ap.add_argument("--chunk-months", type=int, default=None,
                    help="GEE: months per reduceRegions request (default 12)")
    ap.add_argument("--boundary-asset", default=None,
                    help="GEE: projects/<project>/assets/<name>")
    ap.add_argument("--upload-boundary", action="store_true",
                    help="GEE: create the boundary asset from the local GeoJSON")
    ap.add_argument("--force", action="store_true",
                    help="GEE: recompute cached chunks")
    ap.add_argument("--skip-extract", action="store_true",
                    help="GEE: reuse data_processed/series/*.csv")
    args = ap.parse_args(argv)

    if args.command == "selftest":
        import selftest
        return selftest.main([])

    cfg = common.load_config(args.config)
    if args.command == "update":
        return cmd_update(cfg, args)
    if args.command == "gee":
        return cmd_gee(cfg, args)
    if args.command == "download":
        step_download(cfg, args.start or cfg["history"]["start"],
                      args.end or _latest_wanted(cfg))
        return 0
    if args.command == "prepare":
        step_prepare(cfg, args.start or cfg["history"]["start"],
                     args.end or _latest_wanted(cfg))
        return 0
    if args.command == "zonal":
        step_zonal(cfg)
        return 0
    if args.command == "indicators":
        # Rebuild indicators, then refresh the app-facing data/ folder and
        # validate it in one go so no manual copy from data_processed/ is
        # ever needed.
        step_indicators(cfg)
        step_export(cfg)
        return step_validate(cfg)
    if args.command == "export":
        step_export(cfg)
        return step_validate(cfg)
    if args.command == "validate":
        return step_validate(cfg)
    if args.command == "status":
        return cmd_status(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
