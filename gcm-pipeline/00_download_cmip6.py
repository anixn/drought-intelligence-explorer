#!/usr/bin/env python3
"""DIE v2.0 — gcm-pipeline step 00: CMIP6 download (task M2.3, docs/v2/03 §3.2).

OWNER-EXECUTION SCRIPT (R4): this is run by the Owner; it never fabricates
model availability — whatever is missing is reported here and by
01_inventory_check.py, never papered over (docs/v2/03 §3.2).

Design (docs/v2/03 §3.2 + PROGRESS.md download policy):
  - Phase 1 (historical 1981-2014, all 24 models) is ALREADY COMPLETE on disk
    (raw_root, 2,312 files). This script's `audit` mode registers those files
    in the manifest with SHA-256; re-runs skip already-hashed files.
  - Phase 2 (ssp245+ssp585 2015-2100) is RANKING-GATED: downloads are allowed
    ONLY for the best subset (8-12 models) produced by 08_validate_gcm.py
    (out/best_subset.yaml). `--phase ssp` in download mode hard-fails without
    --subset (dry-run/plan is always allowed — planning is not downloading).
  - Resumable + idempotent: per-file .part resume (HTTP Range) for downloads;
    manifest keyed by path with (bytes, mtime) short-circuit so a killed run
    resumes without re-hashing verified files.

File layout (config/paths.yaml — matches the completed phase-1 store):
  <raw_root>/<variable>/<var>_day_<model>_<experiment>_<variant>_<grid>_<year>_v2.0.nc

Manifest: <work_root>/download_manifest.json
  {"schema":1, "raw_root":..., "files": {"<raw_root-relative path>":
    {"sha256","bytes","mtime","status","source","url","fetched_at"}}}

Modes:
  audit     hash existing raw_root files into the manifest (no network).
            --sample N hashes at most N unhashed files (quick verification).
  dry-run   query the chosen source catalog, plan what WOULD be downloaded for
            the requested phase; writes <work_root>/download_plan.json.
            No data files are fetched or written.
  download  execute a plan (audit runs first automatically).

Sources (--source):
  pangeo    Google/Pangeo CMIP6 cloud catalog (single static JSON of zarr
            stores; bbox-subset at read time). Needs: pip install zarr gcsfs.
  esgf      ESGF search API + direct NetCDF download (wget-style), per-file
            SHA-256 verified against the node's published checksum.
            Node default: https://esgf-node.llnl.gov/esg-search/search
            (override with --node if the node is slow/decommissioned; the
            Metagrid UI remains the Owner's interactive fallback).

Usage examples:
  python 00_download_cmip6.py --mode audit                       # full re-hash sweep (resumable)
  python 00_download_cmip6.py --mode audit --sample 5            # quick verify a few files
  python 00_download_cmip6.py --mode audit --models ACCESS-CM2 --variables pr
  python 00_download_cmip6.py --mode dry-run --phase ssp --source pangeo \
      --models ACCESS-CM2 --variables pr                         # plan only (no subset needed)
  python 00_download_cmip6.py --mode download --phase ssp --source pangeo \
      --subset out/best_subset.yaml                              # RANKING-GATED
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RAW_NAME_RE = re.compile(
    r"^(?P<var>pr|tasmax|tasmin)_day_(?P<model>.+?)_(?P<exp>historical|ssp245|ssp585)"
    r"_(?P<variant>r\d+i\d+p\d+f\d+|r\d+i\d+p\d+)_(?P<grid>[^_]+)"
    r"_(?P<year>\d{4})_v(?P<version>[\w.\-]+)\.nc$"
)
PANGEO_CATALOG_URL = "https://storage.googleapis.com/cmip6/pangeo-cmip6.json"
ESGF_NODE_DEFAULT = "https://esgf-node.llnl.gov/esg-search/search"
MANIFEST_SCHEMA = 1


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_configs() -> tuple[Path, Path, Path, dict, dict]:
    paths = load_yaml(HERE / "config" / "paths.yaml")
    models = load_yaml(HERE / "config" / "models.yaml")
    raw_root = Path(paths["raw_root"])
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    out_root = (HERE / paths.get("out_root", "out")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)
    if not raw_root.exists():
        sys.exit(f"FATAL: raw_root does not exist: {raw_root} (check config/paths.yaml)")
    return raw_root, work_root, out_root, paths, models


# ---------------------------------------------------------------- scanning ---
def scan_raw(raw_root: Path, models=None, variables=None, experiments=None,
             years=None) -> dict:
    """raw_root -> {(model, exp, var, year): record}. Filters are optional."""
    recs: dict[tuple, dict] = {}
    for var_dir in sorted(raw_root.iterdir()):
        if not var_dir.is_dir():
            continue
        for f in sorted(var_dir.glob("*.nc")):
            m = RAW_NAME_RE.match(f.name)
            if m is None:
                print(f"  UNPARSED (skipped): {f.name}")
                continue
            g = m.groupdict()
            key = (g["model"], g["exp"], g["var"], int(g["year"]))
            if models and g["model"] not in models:
                continue
            if variables and g["var"] not in variables:
                continue
            if experiments and g["exp"] not in experiments:
                continue
            if years and int(g["year"]) not in years:
                continue
            recs[key] = {
                "path": f, "variant": g["variant"], "grid": g["grid"],
                "version": g["version"], "bytes": f.stat().st_size,
                "mtime": int(f.stat().st_mtime),
            }
    return recs


def expected_years(models_cfg: list, model: str, exp: str) -> range:
    """Configured year window for (model, experiment) — the models.yaml windows
    (historical {start,end}, ssp245/585 {start,end}), NOT trimmed to phase
    policy: phase trimming happens via --years/--phase at the CLI."""
    for row in models_cfg:
        if row["source_id"] == model:
            w = row.get(exp) or {}
            return range(int(w.get("start", 0)), int(w.get("end", -1)) + 1)
    return range(0)


# ---------------------------------------------------------------- manifest ---
def manifest_path(work_root: Path) -> Path:
    return work_root / "download_manifest.json"


def load_manifest(work_root: Path) -> dict:
    p = manifest_path(work_root)
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            man = json.load(fh)
        if man.get("schema") != MANIFEST_SCHEMA:
            sys.exit(f"FATAL: manifest schema {man.get('schema')} != {MANIFEST_SCHEMA}: {p}")
        return man
    return {"schema": MANIFEST_SCHEMA, "created": _now(), "files": {}}


def save_manifest(work_root: Path, man: dict) -> None:
    man["updated"] = _now()
    with open(manifest_path(work_root), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2, sort_keys=True)


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def sha256_file(path: Path, buf_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(buf_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def audit_mode(args, raw_root: Path, work_root: Path, models_cfg: list) -> None:
    """Register raw_root files in the manifest with SHA-256. Resumable:
    existing manifest entries whose (bytes, mtime) still match are kept."""
    man = load_manifest(work_root)
    files = man["files"]
    want_models = set(args.models.split(",")) if args.models else None
    want_vars = set(args.variables.split(",")) if args.variables else None
    want_exps = set(args.experiments.split(",")) if args.experiments else None
    want_years = None
    if args.years:
        a, _, b = args.years.partition("-")
        want_years = range(int(a), int(b or a) + 1)
    recs = scan_raw(raw_root, want_models, want_vars, want_exps, want_years)
    hr(f"AUDIT — {len(recs)} file(s) matched (raw_root={raw_root})")
    items = sorted(recs.items())
    if args.sample:
        items = items[: args.sample]
    hashed = reused = 0
    t0 = time.time()
    for i, (key, rec) in enumerate(items):
        rel = str(rec["path"].relative_to(raw_root)).replace("\\", "/")
        prev = files.get(rel)
        if prev and prev.get("bytes") == rec["bytes"] and prev.get("mtime") == rec["mtime"] \
                and prev.get("sha256"):
            reused += 1
            continue
        digest = sha256_file(rec["path"])
        files[rel] = {
            "sha256": digest, "bytes": rec["bytes"], "mtime": rec["mtime"],
            "status": prev.get("status", "pre-existing") if prev else "pre-existing",
            "source": prev.get("source") if prev else None,
            "url": prev.get("url") if prev else None,
            "fetched_at": prev.get("fetched_at") if prev else None,
        }
        hashed += 1
        if hashed % 25 == 0:
            save_manifest(work_root, man)  # checkpoint mid-run
            print(f"  ...hashed {hashed} ({i + 1}/{len(items)}), "
                  f"{time.time() - t0:.0f}s elapsed")
    save_manifest(work_root, man)
    print(f"AUDIT DONE: {len(items)} in scope | {hashed} newly hashed | "
          f"{reused} reused from manifest | manifest={manifest_path(work_root).name}")
    if args.sample and len(items) == args.sample:
        print(f"  (--sample {args.sample}: only the first {args.sample} matched files "
              f"were hashed — full sweep later)")


# ------------------------------------------------------------------ pangeo ---
def pangeo_catalog(work_root: Path) -> list:
    """Fetch + cache the Pangeo CMIP6 catalog. The top-level JSON is an ESM
    catalog SPEC; the actual rows live in its `catalog_file` CSV (one row per
    zarr store, attribute columns included). Cached to work/ for the day."""
    cache = work_root / "pangeo-cmip6.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)
    import csv as _csv
    import io
    import requests
    print(f"  fetching Pangeo catalog spec: {PANGEO_CATALOG_URL}")
    spec = requests.get(PANGEO_CATALOG_URL, timeout=300)
    spec.raise_for_status()
    catalog_file = spec.json().get("catalog_file")
    if not catalog_file:
        sys.exit("FATAL: Pangeo catalog spec has no catalog_file key")
    print(f"  fetching catalog table: {catalog_file}")
    r = requests.get(catalog_file, timeout=600)
    r.raise_for_status()
    rows = list(_csv.DictReader(io.StringIO(r.text)))
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    print(f"  catalog cached: {len(rows)} zarr stores -> {cache.name}")
    return rows


def pangeo_available(rows: list, model: str, exp: str, var: str,
                     variant: str, grid: str | None) -> list:
    """Rows matching (model, exp, var, day table, variant member, grid).
    Never fabricates: returns only what the catalog actually lists."""
    member = variant  # r1i1p1f1 maps directly to member_id
    out = []
    for r in rows:
        if (r.get("source_id") == model and r.get("experiment_id") == exp
                and r.get("variable_id") == var and r.get("table_id") == "day"
                and r.get("member_id") == member
                and (grid is None or r.get("grid_label") == grid)):
            out.append(r)
    return out


# -------------------------------------------------------------------- esgf ---
def esgf_search(node: str, model: str, exp: str, var: str, variant: str,
                grid: str) -> list:
    """One ESGF solr-search page for (model, exp, var, day, variant, grid).
    Returns docs with filename + url + checksum parsed."""
    import requests
    params = {
        "project": "CMIP6", "source_id": model, "experiment_id": exp,
        "variable_id": var, "table_id": "day",
        "variant_label": variant, "grid_label": grid,
        "replica": "false", "fields": "title,url,checksum,checksum_type,size",
        "format": "application/solr+json", "limit": 500, "type": "File",
    }
    r = requests.get(node, params=params, timeout=120)
    r.raise_for_status()
    docs = r.json()["response"]["docs"]
    out = []
    for d in docs:
        urls = []
        for u in d.get("url", []):
            parts = u.split("|")
            if len(parts) >= 2 and "netcdf" in parts[0]:
                urls.append(parts[1])
        chk = None
        if d.get("checksum_type", [""])[0].lower() == "sha256":
            chk = d["checksum"][0]
        out.append({"title": d["title"], "urls": urls,
                    "sha256": chk, "size": d.get("size", [None])[0]})
    return out


def download_file(url: str, dest: Path, expected_sha: str | None,
                  chunk: int = 1 << 20) -> None:
    """Resumable HTTP download with .part + Range; SHA-256 verified when the
    server published a checksum."""
    import requests
    part = dest.with_suffix(dest.suffix + ".part")
    headers = {}
    mode = "wb"
    h = hashlib.sha256()
    done = 0
    if part.exists():
        done = part.stat().st_size
        headers["Range"] = f"bytes={done}-"
        mode = "ab"
        with open(part, "rb") as fh:          # resume hash from the .part bytes
            while True:
                b = fh.read(chunk)
                if not b:
                    break
                h.update(b)
    with requests.get(url, headers=headers, stream=True, timeout=300) as r:
        if done and r.status_code == 200:      # server ignored Range -> restart
            done, mode, h = 0, "wb", hashlib.sha256()
        r.raise_for_status()
        with open(part, mode) as fh:
            for b in r.iter_content(chunk_size=chunk):
                fh.write(b)
                h.update(b)
                done += len(b)
    digest = h.hexdigest()
    if expected_sha and digest != expected_sha:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {dest.name}: {digest} != {expected_sha}")
    part.replace(dest)


def pangeo_subset_to_nc(zstore: str, var: str, year: int, dest: Path,
                        bbox: dict) -> None:
    """Open a Pangeo zarr store, subset India bbox + one year, write NetCDF.
    Requires zarr + gcsfs (documented in the header docstring)."""
    try:
        import xarray as xr
        import gcsfs
        import zarr  # noqa: F401  (xarray engine requirement)
    except ImportError as e:
        sys.exit("FATAL: pangeo route needs 'pip install zarr gcsfs' "
                 f"(xarray {e} missing)")
    fs = gcsfs.GCSFileSystem(token="anon")
    ds = xr.open_zarr(fs.get_mapper(zstore), consolidated=True, use_cftime=True)
    ds = ds[[var]].sel(time=slice(f"{year}-01-01", f"{year}-12-31"))
    lat_name = "lat" if "lat" in ds.coords else "latitude"
    lon_name = "lon" if "lon" in ds.coords else "longitude"
    ds = ds.sel(**{lat_name: slice(bbox["lat_min"], bbox["lat_max"]),
                   lon_name: slice(bbox["lon_min"], bbox["lon_max"])})
    if ds.sizes.get("time", 0) == 0:
        raise RuntimeError(f"no time steps in {year} slice of {zstore}")
    tmp = dest.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp)
    tmp.replace(dest)


# ------------------------------------------------------------------ planning ---
def build_plan(args, raw_root: Path, work_root: Path, models_cfg: list,
               paths_cfg: dict, models_doc: dict) -> dict:
    """Plan downloads for the requested phase from the chosen source catalog.
    Availability comes from the SOURCE catalog — missing models are reported,
    never skipped silently (R3)."""
    phase_models = resolve_phase_models(args, models_doc)
    want_vars = args.variables.split(",") if args.variables else ["pr", "tasmax", "tasmin"]
    plan_items = []
    print()
    hr(f"DRY-RUN PLAN — phase={args.phase} source={args.source} "
       f"models={len(phase_models)} vars={','.join(want_vars)}")
    if args.source == "pangeo":
        rows = pangeo_catalog(work_root)
        bbox = (load_yaml(HERE / "config" / "reference.yaml").get("target_grid") or {})
        bbox = {k: bbox[k] for k in ("lon_min", "lon_max", "lat_min", "lat_max") if k in bbox}
    else:
        rows = None
        print(f"  ESGF node: {args.node}")
    for model in sorted(phase_models):
        cfg_variant, cfg_grid = variant_grid(models_cfg, model)
        local = scan_raw(raw_root, {model}, set(want_vars),
                         set(args.experiments.split(",")), None)
        for var in want_vars:
            for exp in args.experiments.split(","):
                avail = (pangeo_available(rows, model, exp, var, cfg_variant, cfg_grid)
                         if rows is not None else
                         esgf_search(args.node, model, exp, var, cfg_variant, cfg_grid))
                if not avail:
                    plan_items.append({"model": model, "exp": exp, "var": var,
                                       "action": "unavailable",
                                       "detail": f"not listed by {args.source} "
                                                 f"(variant {cfg_variant})"})
                    print(f"  {model:18s} {exp:10s} {var:7s} UNAVAILABLE on {args.source}")
                    continue
                have_years = {y for (m, e, v, y) in local if e == exp and v == var}
                want = [y for y in expected_years(models_cfg, model, exp)
                        if y not in have_years]
                if not want:
                    plan_items.append({"model": model, "exp": exp, "var": var,
                                       "action": "already-on-disk", "years": []})
                    print(f"  {model:18s} {exp:10s} {var:7s} already on disk")
                    continue
                if rows is not None:
                    ver = avail[0].get("version", "?")
                    plan_items.append({
                        "model": model, "exp": exp, "var": var,
                        "action": "pangeo-subset", "years": want,
                        "zstore": avail[0]["zstore"], "version": ver,
                        "bbox": bbox})
                    print(f"  {model:18s} {exp:10s} {var:7s} {len(want):3d} yr "
                          f"({want[0]}-{want[-1]}) zarr v{ver}")
                else:
                    per_year = {}
                    for a in avail:
                        m = re.search(r"_(\d{4})\d*_?v\d", a["title"]) \
                            or re.search(r"_(\d{4})-", a["title"])
                        if m:
                            per_year.setdefault(int(m.group(1)), a)
                    missing = {y: per_year[y] for y in want if y in per_year}
                    not_listed = [y for y in want if y not in per_year]
                    for y, a in sorted(missing.items()):
                        plan_items.append({"model": model, "exp": exp, "var": var,
                                           "action": "esgf-download", "year": y,
                                           "urls": a["urls"], "sha256": a["sha256"],
                                           "size": a["size"]})
                    if not_listed:
                        plan_items.append({"model": model, "exp": exp, "var": var,
                                           "action": "esgf-years-not-listed",
                                           "years": not_listed})
                    got = len(missing)
                    extra = f" (+{len(not_listed)} yr not listed)" if not_listed else ""
                    print(f"  {model:18s} {exp:10s} {var:7s} {got:3d} files "
                          f"to fetch{extra}")
    plan = {"schema": 1, "created": _now(), "phase": args.phase,
            "source": args.source, "experiments": args.experiments.split(","),
            "raw_root": str(raw_root), "items": plan_items}
    out = work_root / "download_plan.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    n_dl = sum(1 for p in plan_items if "download" in p["action"] or p["action"] == "pangeo-subset")
    print(f"PLAN: {len(plan_items)} items ({n_dl} actionable) -> {out.name}")
    return plan


def variant_grid(models_cfg: list, model: str) -> tuple[str, str | None]:
    for row in models_cfg:
        if row["source_id"] == model:
            return row.get("variant", "r1i1p1f1"), row.get("grid_label")
    sys.exit(f"FATAL: {model} not in config/models.yaml")


def resolve_phase_models(args, models_doc: dict) -> list:
    """Model list for the phase: explicit --models wins; else ssp phase takes
    --subset (best_subset.yaml); else all configured models (historical)."""
    if args.models:
        return args.models.split(",")
    if args.phase == "ssp":
        if not args.subset:
            sys.exit("FATAL: --phase ssp requires --subset <best_subset.yaml> "
                     "(ranking-before-SSP policy) — or --models for a dry-run plan.")
        sp = Path(args.subset)
        if not sp.exists():
            sys.exit(f"FATAL: subset file not found: {sp} (produced by 08_validate_gcm.py "
                     "at the validation gate — do NOT hand-edit)")
        sub = load_yaml(sp)
        ids = sub.get("source_ids") or sub.get("models") or []
        if not ids:
            sys.exit(f"FATAL: no source_ids in {sp}")
        return list(ids)
    return [row["source_id"] for row in models_doc["models"]]


def download_mode(args, raw_root: Path, work_root: Path, models_cfg: list,
                  paths_cfg: dict, models_doc: dict) -> None:
    if args.phase == "ssp" and not args.subset:
        sys.exit("FATAL: phase-2 (ssp245/ssp585) downloads are RANKING-GATED "
                 "(docs/v2/02 M2-policy): pass --subset out/best_subset.yaml "
                 "produced by 08_validate_gcm.py. Do not download all models "
                 "(~multi-hundred-GB).")
    audit_mode(args, raw_root, work_root, models_cfg)   # refresh manifest first
    plan = build_plan(args, raw_root, work_root, models_cfg, paths_cfg, models_doc)
    phase_models = resolve_phase_models(args, models_doc)
    todo = [p for p in plan["items"] if p["action"] in ("esgf-download", "pangeo-subset")]
    if args.phase == "ssp":
        allowed = set(phase_models)
        for p in todo:
            if p["model"] not in allowed:
                sys.exit(f"FATAL: plan item outside the gated subset: {p['model']}")
    hr(f"DOWNLOAD — {len(todo)} actionable item(s)")
    man = load_manifest(work_root)
    ok = fail = 0
    for p in todo:
        dest = raw_root / p["var"] / (
            f"{p['var']}_day_{p['model']}_{p['exp']}_"
            f"{variant_grid(models_cfg, p['model'])[0]}_"
            f"{variant_grid(models_cfg, p['model'])[1] or 'gn'}_{p['year']}_v2.0.nc")
        if dest.exists():
            continue
        try:
            if p["action"] == "esgf-download":
                if not p["urls"]:
                    raise RuntimeError("no netcdf URL in ESGF doc")
                download_file(p["urls"][0], dest, p["sha256"])
            else:
                pangeo_subset_to_nc(p["zstore"], p["var"], p["year"], dest, p["bbox"])
            rel = str(dest.relative_to(raw_root)).replace("\\", "/")
            man["files"][rel] = {
                "sha256": sha256_file(dest), "bytes": dest.stat().st_size,
                "mtime": int(dest.stat().st_mtime), "status": "downloaded",
                "source": args.source,
                "url": p.get("urls", [p.get("zstore")])[0],
                "fetched_at": _now()}
            save_manifest(work_root, man)      # checkpoint after EVERY file
            ok += 1
            print(f"  OK {dest.name}")
        except Exception as e:                  # noqa: BLE001 — record & continue
            fail += 1
            print(f"  FAIL {p['model']} {p['exp']} {p['var']} {p.get('year')}: {e}")
            with open(work_root / "download_errors.log", "a", encoding="utf-8") as fh:
                fh.write(f"{_now()} FAIL {json.dumps(p, default=str)} :: {e}\n")
    print(f"DOWNLOAD DONE: {ok} ok, {fail} failed "
          f"(errors logged to {work_root / 'download_errors.log'}; re-run to resume)")


def main() -> int:
    ap = argparse.ArgumentParser(description="CMIP6 download/audit/plan (M2.3)")
    ap.add_argument("--mode", choices=["audit", "dry-run", "download"], default="audit")
    ap.add_argument("--phase", choices=["historical", "ssp"], default="historical")
    ap.add_argument("--experiments", default=None,
                    help="comma list (default: historical for phase historical; "
                         "ssp245,ssp585 for phase ssp)")
    ap.add_argument("--models", help="comma list of source_ids")
    ap.add_argument("--variables", help="comma list: pr,tasmax,tasmin")
    ap.add_argument("--years", help="year or range, e.g. 1981 or 1981-1985 (audit filter)")
    ap.add_argument("--sample", type=int, help="audit: hash at most N matched files")
    ap.add_argument("--source", choices=["pangeo", "esgf"], default="pangeo")
    ap.add_argument("--node", default=ESGF_NODE_DEFAULT, help="ESGF search endpoint")
    ap.add_argument("--subset", help="best_subset.yaml (08_validate_gcm.py output) — "
                                     "required for phase ssp in download mode")
    args = ap.parse_args()
    if args.experiments is None:
        args.experiments = "historical" if args.phase == "historical" else "ssp245,ssp585"
    raw_root, work_root, out_root, paths_cfg, models_doc = load_configs()
    models_cfg = models_doc["models"]
    if args.mode == "audit":
        audit_mode(args, raw_root, work_root, models_cfg)
    elif args.mode == "dry-run":
        build_plan(args, raw_root, work_root, models_cfg, paths_cfg, models_doc)
    else:
        download_mode(args, raw_root, work_root, models_cfg, paths_cfg, models_doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
