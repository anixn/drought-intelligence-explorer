#!/usr/bin/env python3
"""DIE v2.0 — gcm-pipeline step 01: inventory gate (task M2.4, docs/v2/03 §3.3).

Builds the availability matrix (model × variable × experiment × period ×
calendar) from what ACTUALLY exists under raw_root (config/paths.yaml), and
hard-fails the pipeline on (docs/v2/03 §3.3):
  - missing variables for an era-C ensemble model (pr + tasmax + tasmin
    historical 1981-2014 all required),
  - missing historical years within the required 1981-2014 window
    (calibration needs 1981-2020 = model historical 1981-2014 + ssp 2015-2020
    — AS6; phase-1 scope recorded in models.yaml download policy),
  - variant multiplicity (two variants mixed for the same model/var/exp —
    one documented variant per model is a selection criterion),
  - models in config absent from disk (when meta.historical_phase1 == complete
    this is a hard failure; otherwise informational).

NOT failures (recorded, not failed — §3.3):
  - calendar differences (noleap/365_day vs proleptic_gregorian) — handled at
    regrid (02), recorded per model here,
  - SSP runs not yet downloaded (phase 2 is ranking-gated) — summarised only,
  - variant/grid_label MISMATCHES vs models.yaml template defaults while
    meta.status is provisional — the filenames are authoritative and models.yaml
    is the template ("update this file from their output, never the reverse").
    Once the Owner confirms the list at OD1, set meta.strict_variant: true and
    mismatches become hard failures.

Outputs: human-readable matrix (stdout) + work/inventory.json (machine).

Usage:
  python 01_inventory_check.py                    # full matrix + gate
  python 01_inventory_check.py --no-calendar-scan # skip NetCDF header reads
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REQUIRED_HIST = (1981, 2014)   # phase-1 window: models.yaml download policy + calibration ≥1981
ERA_C_VARS = ("pr", "tasmax", "tasmin")


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def scan_raw(raw_root: Path) -> tuple[dict, list]:
    """raw_root -> {(model, exp, var): {"years": {year: record}, ...}} + unparsed list."""
    groups: dict = OrderedDict()
    unparsed = []
    import re
    name_re = re.compile(
        r"^(?P<var>pr|tasmax|tasmin)_day_(?P<model>.+?)_(?P<exp>historical|ssp245|ssp585)"
        r"_(?P<variant>r\d+i\d+p\d+f\d+|r\d+i\d+p\d+)_(?P<grid>[^_]+)"
        r"_(?P<year>\d{4})_v(?P<version>[\w.\-]+)\.nc$")
    if not raw_root.exists():
        sys.exit(f"FATAL: raw_root does not exist: {raw_root}")
    for var_dir in sorted(raw_root.iterdir()):
        if not var_dir.is_dir():
            continue
        for f in sorted(var_dir.glob("*.nc")):
            m = name_re.match(f.name)
            if m is None:
                unparsed.append(f.name)
                continue
            g = m.groupdict()
            key = (g["model"], g["exp"], g["var"])
            grp = groups.setdefault(key, {"years": {}, "variants": set(),
                                          "grids": set(), "versions": set()})
            grp["years"][int(g["year"])] = {
                "path": str(f), "variant": g["variant"], "grid": g["grid"],
                "bytes": f.stat().st_size}
            grp["variants"].add(g["variant"])
            grp["grids"].add(g["grid"])
            grp["versions"].add(g["version"])
    return groups, unparsed


def calendar_of(path: str) -> dict | None:
    """NetCDF header metadata (calendar, units, grid size) — cheap open."""
    try:
        import netCDF4 as nc
        with nc.Dataset(path) as d:
            t = d.variables.get("time")
            lat_name = next((k for k in ("lat", "latitude", "rlat") if k in d.variables), None)
            lon_name = next((k for k in ("lon", "longitude", "rlon") if k in d.variables), None)
            return {
                "calendar": getattr(t, "calendar", None) if t is not None else None,
                "time_units": getattr(t, "units", None) if t is not None else None,
                "lat": len(d.dimensions[lat_name]) if lat_name else None,
                "lon": len(d.dimensions[lon_name]) if lon_name else None,
            }
    except Exception as e:                          # noqa: BLE001 — record, don't crash
        return {"error": str(e)}


def fmt_years(years: set) -> str:
    if not years:
        return "-"
    ys = sorted(years)
    runs, s, p = [], ys[0], ys[0]
    for y in ys[1:]:
        if y == p + 1:
            p = y
            continue
        runs.append((s, p))
        s = p = y
    runs.append((s, p))
    return ",".join(f"{a}-{b}" if b > a else str(a) for a, b in runs)


def main() -> int:
    ap = argparse.ArgumentParser(description="CMIP6 inventory gate (M2.4)")
    ap.add_argument("--no-calendar-scan", action="store_true")
    args = ap.parse_args()

    paths = load_yaml(HERE / "config" / "paths.yaml")
    doc = load_yaml(HERE / "config" / "models.yaml")
    raw_root = Path(paths["raw_root"])
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    meta = doc.get("meta", {})
    phase1_complete = meta.get("historical_phase1") == "complete"
    strict_variant = bool(meta.get("strict_variant", False))

    groups, unparsed = scan_raw(raw_root)
    # ssp files may live in a separate root (paths.raw_root_ssp, M2.13):
    # merge them in; historical never overridden, same-key ssp records
    # prefer the ssp root.
    raw_root_ssp_cfg = paths.get("raw_root_ssp")
    raw_root_ssp = Path(raw_root_ssp_cfg).resolve() if raw_root_ssp_cfg else None
    if raw_root_ssp and raw_root_ssp != raw_root and raw_root_ssp.exists():
        g_ssp, unparsed_ssp = scan_raw(raw_root_ssp)
        for k, g in g_ssp.items():
            if k[1] == "historical" and k in groups:
                continue          # historical stays sourced from raw_root
            merged = groups.setdefault(k, {"years": {}, "variants": set(),
                                           "grids": set(), "versions": set()})
            merged["years"].update(g["years"])
            merged["variants"] |= g["variants"]
            merged["grids"] |= g["grids"]
            merged["versions"] |= g["versions"]
        unparsed = unparsed + unparsed_ssp
    else:
        raw_root_ssp = None
    cfg_models = {row["source_id"]: row for row in doc["models"]}

    problems, notes = [], []
    per_model = OrderedDict()
    cal_cache: dict = {}
    t0 = _dt.datetime.now()

    # --- models on disk but not in config (informational) -------------------
    disk_models = sorted({m for (m, e, v) in groups})
    extra = [m for m in disk_models if m not in cfg_models]
    if extra:
        notes.append(f"models on disk but NOT in models.yaml: {', '.join(extra)}")

    # --- per-config-model gate ----------------------------------------------
    for model, row in cfg_models.items():
        excl = row.get("era_c_ensemble") is False
        mrec = {"config_variant": row.get("variant"), "config_grid": row.get("grid_label"),
                "era_c_ensemble": not excl, "experiments": {}}
        for exp in ("historical", "ssp245", "ssp585"):
            exprec = {"vars": {}}
            for var in ERA_C_VARS:
                grp = groups.get((model, exp, var))
                if grp is None:
                    if exp == "historical" and (not excl or var == "pr"):
                        msg = f"{model}/{exp}/{var}: ABSENT on disk"
                        if phase1_complete and exp == "historical":
                            if excl and var != "pr":
                                pass          # excluded models need pr only
                            else:
                                problems.append(msg)
                        else:
                            notes.append(msg + " (phase 2, ranking-gated)")
                    continue
                years = set(grp["years"])
                variants = grp["variants"]
                grids = grp["grids"]
                vrec = {"n_years": len(years),
                        "coverage": fmt_years(years),
                        "variants": sorted(variants), "grids": sorted(grids),
                        "versions": sorted(grp["versions"])}
                # variant multiplicity = fatal (mixing runs breaks the record)
                if len(variants) > 1:
                    problems.append(f"{model}/{exp}/{var}: MULTIPLE variants "
                                    f"{sorted(variants)} — one documented variant per model")
                # variant/grid mismatch vs config template
                cv, cg = row.get("variant"), row.get("grid_label")
                if cv and cv not in variants:
                    msg = (f"{model}/{exp}/{var}: variant {sorted(variants)} on disk "
                           f"!= config {cv}")
                    (problems if strict_variant else notes).append(msg)
                    if not strict_variant:
                        vrec["config_mismatch"] = True
                if cg and cg not in grids:
                    msg = (f"{model}/{exp}/{var}: grid {sorted(grids)} on disk "
                           f"!= config {cg}")
                    (problems if strict_variant else notes).append(msg)
                # calendar scan (one file per model/exp/var)
                if exp == "historical" and not args.no_calendar_scan:
                    sample = grp["years"][min(years)]["path"]
                    if sample not in cal_cache:
                        cal_cache[sample] = calendar_of(sample)
                    vrec["calendar"] = cal_cache[sample]
                # historical completeness
                if exp == "historical":
                    a, b = REQUIRED_HIST
                    missing = [y for y in range(a, b + 1) if y not in years]
                    if missing and (not excl or var == "pr"):
                        problems.append(
                            f"{model}/{exp}/{var}: {len(missing)} missing year(s) in "
                            f"{a}-{b}: {fmt_years(set(missing))}")
                # ssp coverage gate (M2.13, real phase-2 data): the AS6
                # calibration seam needs ssp 2015-2020 for every era-C model
                # that runs the ssp chain; coverage past 2020 is reported,
                # and a truncated record end (vs the models.yaml contract)
                # is a NOTE, never silently accepted.
                if exp.startswith("ssp"):
                    missing_seam = [y for y in range(2015, 2021)
                                    if y not in years]
                    if missing_seam:
                        problems.append(
                            f"{model}/{exp}/{var}: {len(missing_seam)} missing "
                            f"year(s) in the AS6 calibration seam 2015-2020: "
                            f"{fmt_years(set(missing_seam))}")
                    row_exp = row.get(exp) or {}
                    end_cfg = int(row_exp.get("end", 2100))
                    truncated = [y for y in range(max(years) + 1, end_cfg + 1)
                                 if y not in years]
                    if truncated:
                        notes.append(
                            f"{model}/{exp}/{var}: record ends {max(years)} "
                            f"(config end {end_cfg}); {len(truncated)} pending "
                            f"download year(s) - era-C record truncated "
                            f"honestly at {max(years)} (R3)")
                exprec["vars"][var] = vrec
            mrec["experiments"][exp] = exprec
        per_model[model] = mrec

    # --- matrix print --------------------------------------------------------
    hr("CMIP6 INVENTORY — availability matrix (disk = raw_root)")
    print(f"raw_root: {raw_root}")
    print(f"models on disk: {len(disk_models)} | config models: {len(cfg_models)} "
          f"| unparsed filenames: {len(unparsed)}")
    print()
    hdr = f"{'model':18s} {'ens':>3s} {'hist pr':>16s} {'hist tasmax':>16s} {'hist tasmin':>16s}"
    print(hdr)
    print("-" * len(hdr))
    for model, row in cfg_models.items():
        excl = row.get("era_c_ensemble") is False
        cells = []
        for var in ERA_C_VARS:
            grp = groups.get((model, "historical", var))
            if grp is None:
                cells.append(f"{'—':>16s}")
            else:
                cells.append(f"{len(grp['years']):>3d}yr".rjust(7) +
                             f" {fmt_years(set(grp['years']))[:8]:>8s}")
        print(f"{model:18s} {'no' if excl else 'yes':>3s} {cells[0]:>16s} "
              f"{cells[1]:>16s} {cells[2]:>16s}")
    print()
    for exp in ("ssp245", "ssp585"):
        yrs = sorted({y for (m, e, v), g in groups.items() if e == exp
                      for y in g["years"]})
        if yrs:
            print(f"{exp}: {len({m for (m, e, v) in groups if e == exp})} "
                  f"model(s) on disk, coverage {yrs[0]}-{yrs[-1]} "
                  f"(ssp root: {raw_root_ssp or raw_root})")
        else:
            print(f"{exp}: 0 model(s) on disk — phase 2, ranking-gated "
                  f"(downloads after 08_validate_gcm.py best_subset)")
    # calendar summary
    cals = sorted({c.get("calendar") for c in cal_cache.values()
                   if c and c.get("calendar")})
    if cals:
        print(f"calendars seen: {', '.join(cals)} "
              f"(differences handled at regrid step 02 — recorded, not failed)")
    if unparsed:
        print(f"UNPARSED filenames: {unparsed[:5]}{'...' if len(unparsed) > 5 else ''}")

    print()
    if notes:
        print(f"NOTES ({len(notes)}):")
        for nmsg in notes:
            print(f"  - {nmsg}")
    if problems:
        print(f"\nGATE: FAIL — {len(problems)} problem(s):")
        for pmsg in problems:
            print(f"  ! {pmsg}")
        status = "FAIL"
        rc = 1
    else:
        print("GATE: PASS — inventory consistent with models.yaml + phase policy")
        status = "PASS"
        rc = 0

    out = work_root / "inventory.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"schema": 1, "generated": t0.isoformat(timespec="seconds"),
                   "raw_root": str(raw_root),
                   "raw_root_ssp": str(raw_root_ssp) if raw_root_ssp else None,
                   "status": status,
                   "required_historical": list(REQUIRED_HIST),
                   "unparsed": unparsed, "problems": problems, "notes": notes,
                   "models": per_model}, fh, indent=2, default=str)
    print(f"machine-readable matrix -> {out.name}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
