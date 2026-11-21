#!/usr/bin/env python3
"""DIE v2.0 - gcm-pipeline step 09: export to Parquet (task M2.12).

The ONLY gcm-pipeline step allowed to write outside work/ (X9, docs/v2/06
section 5, binding): it stages validated products into gcm-pipeline/out/
and - publish only - copies them into data/parquet/projections/ plus
regenerates catalog.json / pipeline_manifest.json / metadata.json era-C
blocks. Publish requires a PASSING step-08 validation run in the same mode
(X1: cross-validation gates projections going live).

Modes
-----
  --mode historical-corrected
      Copies the validation products (validation_report.json,
      best_subset.yaml, ranking.csv, validation_manifest.json) from
      work/validation/ into out/validation/ and writes out/export_manifest.json
      with SHA-256 checksums and the R2 labels. NO Parquet is exported: the
      historical-corrected product (QDM-corrected free-running models,
      1981-2014) is a VALIDATION-era product - never era B observations,
      never an ssp projection, never a UI surface.

  --mode ssp [--publish]
      Builds the era-C Parquet store in the committed hive layout
      (docs/v2/03 section 3.9):

        projections/scenario=<s>/stat=<st>/variable=<v>/[model=<m>/]year=<yyyy>/part-0.parquet

      from work/ensemble/<exp>/ (07 ensemble stats) and work/aggregate/
      <model>/<exp>/ (06 per-model files, committed subset only).
      Staging goes to out/projections/; with --publish the staged tree is
      copied to data/parquet/projections/ and catalog / pipeline_manifest /
      metadata gain their era-C blocks. Publish refuses unless the ssp-mode
      validation gate passed (X1).

  --dry-run
      Stages under work/test-output/ instead of out/ (X9).
  --selftest
      Synthetic mini world under work/test-output/ - the whole export
      pipeline exercised end-to-end without touching out/ or data/.

Contract (docs/v2/03 sections 3.9/8.1/8.2)
------------------------------------------
  * schema: district_id dictionary<string>, year int16, month int8,
    value float32; model_id string on per-model partitions
  * missing cells are ABSENT rows, never nulls, never imputed (R10)
  * every partition file <= ~0.5 MB (config gate max_file_bytes)
  * compression zstd level 19, dictionary encoding
  * catalog projections block: files.projections = {scenario: {stat: [paths]}}
    (structured extension of the section 8.2 example - provisional until the
    era-C UI surfaces in M5 consume it; recorded in the export manifest)
  * export manifest dir_agreement block: base period + configured/effective
    direction window, carried verbatim from the step-07 NC attributes into
    the manifest and (publish) metadata.json - never re-derived here
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
# Config-dir override (M2.13 phase 2): selftest_gcm.py points every step
# at a test config dir via DIE_CONFIG_DIR; default = the real config dir
# so production behaviour is untouched (documented in docs/v2/03 s3.11).
import os as _os
CONFIG_DIR = Path(_os.environ.get("DIE_CONFIG_DIR",
                                        str(HERE / "config")))

REPO = HERE.parent
SEED = 20261103          # project seed convention (AGENTS.md section 7)
ZSTD_LEVEL = 19

SCHEMA = pa.schema([
    ("district_id", pa.dictionary(pa.int32(), pa.string())),
    ("year", pa.int16()),
    ("month", pa.int8()),
    ("value", pa.float32()),
])
SCHEMA_MODEL = pa.schema([
    ("district_id", pa.dictionary(pa.int32(), pa.string())),
    ("year", pa.int16()),
    ("month", pa.int8()),
    ("value", pa.float32()),
    ("model_id", pa.dictionary(pa.int32(), pa.string())),
])

PRODUCED_BY = "gcm-pipeline/09_export_parquet.py (task M2.12, docs/v2/03 s3.9)"


def hr(title: str) -> None:
    print("=" * 78)
    print(title)
    print("=" * 78)


def load_yaml(p: Path) -> dict:
    import yaml
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _py(v):
    """NetCDF attribute value -> JSON-serialisable Python scalar."""
    return v.item() if hasattr(v, "item") else v


# --------------------------------------------------------------------------
# NC panel reader (same robust semantics as 08 load_district_nc, extended to
# several variables per file - the ensemble NCs carry 6 stat variables).
# --------------------------------------------------------------------------
def load_nc_panel(path: Path, wanted: list):
    """Read one step-06/07 district NC.

    Returns (panels, keys, dids, attrs): panels = {name: (ndistrict, ntime)
    float64 array, NaN-filled}; keys = [(year, month), ...]; dids = [str];
    attrs = global NC attributes. Layout robust to a (time, district) legacy
    transpose via explicit shape check (08 rule).
    """
    import netCDF4 as nc
    d = nc.Dataset(path)
    try:
        missing = [w for w in wanted if w not in d.variables]
        if missing:
            raise ValueError(f"{path.name}: missing variables {missing}")
        panels = {}
        for w in wanted:
            var = d.variables[w]
            raw = var[:]
            if raw.dtype.kind == "f":
                arr = np.asarray(np.ma.filled(raw, np.nan), float)
            else:
                # int panels (n_models, dir_agreement_n): the NaN cast would
                # fail on an int masked array, so map both the netCDF mask and
                # the declared _FillValue sentinel to NaN explicitly
                arr = np.asarray(np.ma.filled(raw, 0), float)
                if np.ma.isMaskedArray(raw):
                    arr[np.ma.getmaskarray(raw)] = np.nan
                if "_FillValue" in var.ncattrs():
                    arr[arr == float(var.getncattr("_FillValue"))] = np.nan
            panels[w] = arr
        t = d.variables["time"]
        dates = nc.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
        dids = [str(x) for x in d.variables["district"][:]]
        attrs = {a: d.getncattr(a) for a in d.ncattrs()}
    finally:
        d.close()
    keys = [(x.year, x.month) for x in dates]
    n_d, n_t = len(dids), len(keys)
    for w, arr in panels.items():
        if arr.shape == (n_d, n_t):
            pass
        elif arr.shape == (n_t, n_d):
            panels[w] = arr.T
        else:
            raise ValueError(f"{path}: {w} shape {arr.shape} does not match "
                             f"({n_d} districts, {n_t} months)")
    return panels, keys, dids, attrs


def check_calendar(keys: list) -> int:
    """0 = contiguous monthly sequence; k = first anomaly index (08 rule)."""
    for k in range(1, len(keys)):
        y, m = keys[k - 1]
        y2, m2 = keys[k]
        if not (y2 == y + (m == 12) and m2 == (1 if m == 12 else m + 1)):
            return k
    return 0


# --------------------------------------------------------------------------
# Partition writer
# --------------------------------------------------------------------------
def write_partition(out_path: Path, dids: list, year: int,
                    months: list, values: np.ndarray,
                    model_id: str | None, meta: dict) -> dict:
    """One (scenario, stat, variable[, model], year) partition.

    values: (ndistrict, n_months_of_year) float array, the year slice.
    Missing cells are ABSENT rows (R10). Returns a manifest record.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dist_idx, mon_idx = np.where(np.isfinite(values))
    n_rows = int(dist_idx.size)
    schema = SCHEMA_MODEL if model_id else SCHEMA
    arrays = [
        pa.array([dids[i] for i in dist_idx], type=schema.field(0).type),
        pa.array(np.full(n_rows, year, dtype=np.int16), type=pa.int16()),
        pa.array(np.array([months[j] for j in mon_idx], dtype=np.int8),
                 type=pa.int8()),
        pa.array(values[dist_idx, mon_idx].astype(np.float32),
                 type=pa.float32()),
    ]
    if model_id:
        arrays.append(pa.array([model_id] * n_rows,
                               type=schema.field(4).type))
    table = pa.Table.from_arrays(arrays, schema=schema)
    md = {k.encode(): str(v).encode() for k, v in meta.items()}
    md[b"rows"] = str(n_rows).encode()
    md[b"produced_by"] = PRODUCED_BY.encode()
    table = table.replace_schema_metadata(md)
    pq.write_table(table, out_path, compression="zstd",
                   compression_level=ZSTD_LEVEL, use_dictionary=True)
    return {"path": "", "rows": n_rows, "bytes": out_path.stat().st_size,
            "sha256": sha256_of(out_path)}


def partition_rel(scenario: str, stat: str, variable: str, year: int,
                  model: str | None, fname: str) -> str:
    p = Path(f"scenario={scenario}") / f"stat={stat}" / f"variable={variable}"
    if model:
        p = p / f"model={model}"
    return (p / f"year={year}" / fname).as_posix()


# --------------------------------------------------------------------------
# era-C export (ssp mode)
# --------------------------------------------------------------------------
def export_ssp(work_root: Path, staging: Path, cfg: dict,
               subset: list) -> dict:
    """Build the whole era-C hive store into staging. Returns the manifest."""
    ex = cfg["export"]
    stats = ex["stats"]                     # stat name -> NC variable name
    max_bytes = int(ex["max_file_bytes"])
    label = " ".join(ex["labels"]["ssp"].split())
    ens_root = work_root / "ensemble"
    if not ens_root.exists():
        raise FileNotFoundError(f"{ens_root} not found - run 07 in ssp mode "
                                f"first (nothing is invented, R3)")

    man = OrderedDict([
        ("schema", "die-export-manifest/1.0"),
        ("export_date", str(date.today())),
        ("mode", "ssp"),
        ("era", "projections"),
        ("era_label", label),
        ("honesty", [
            "simulations, never forecasts (R2)",
            "never spliced with observed era B (R2)",
            "present with spread + agreement, never the median alone (X2/X3)",
            "missing cells are absent rows, never imputed (R10)",
            "ensemble n recorded, never assumed (X3)",
            "direction agreement is a model COUNT, never a probability; its "
            "effective window is recorded verbatim (dir_agreement block)",
        ]),
        ("catalog_files_projections_shape",
         "{scenario: {stat: [paths]}} - structured extension of docs/v2/03 "
         "s8.2 (provisional until the M5 era-C surfaces consume it)"),
        ("subset_models", subset),
        ("gates", {"step08_ssp_required_before_publish": "X1"}),
        ("files", OrderedDict()),
    ])

    n_files = 0
    total_bytes = 0
    nc_vars = sorted(set(stats.values()))
    dir_info = None
    for exp_dir in sorted(p for p in ens_root.iterdir()
                          if p.is_dir() and p.name.startswith("ssp")):
        scenario = exp_dir.name
        for nc_path in sorted(exp_dir.glob("*_ensemble_*.nc")):
            variable = nc_path.name.split("_ensemble_")[0]
            panels, keys, dids, attrs = load_nc_panel(nc_path, nc_vars)
            if dir_info is None and "dir_agreement_window_effective" in attrs:
                eff = attrs.get("dir_agreement_window_effective")
                if eff and eff != "none":
                    dir_info = {
                        "base": _py(attrs.get("dir_agreement_base")),
                        "base_years": _py(attrs.get(
                            "dir_agreement_base_years")),
                        "window_configured": _py(attrs.get(
                            "dir_agreement_window_configured")),
                        "window_effective": _py(eff),
                        "window_note": _py(attrs.get(
                            "dir_agreement_window_note")),
                        "min_window_years": _py(attrs.get(
                            "dir_agreement_min_window_years")),
                        "definition": _stat_definition(
                            "dir_agreement_drier", attrs),
                    }
            anom = check_calendar(keys)
            if anom:
                raise ValueError(f"{nc_path.name}: calendar anomaly at "
                                 f"index {anom} - refusing to export")
            year_idx = {}
            for i, (y, _m) in enumerate(keys):
                year_idx.setdefault(y, []).append(i)
            for stat, nc_var in stats.items():
                panel = panels[nc_var]
                for year, idx in sorted(year_idx.items()):
                    if not np.isfinite(panel[:, idx]).any():
                        # no data at all in this year (e.g. a window-only
                        # statistic outside its window): write NO file, never
                        # an empty partition (R10: absent, not a stub)
                        continue
                    months = [keys[i][1] for i in idx]
                    rel = partition_rel(scenario, stat, variable, year,
                                        None, ex["partition_file"])
                    rec = write_partition(
                        staging / rel, dids, year, months, panel[:, idx],
                        None,
                        {"era": "projections", "scenario": scenario,
                         "stat": stat, "variable_id": variable,
                         "era_label": label,
                         "stat_definition": _stat_definition(stat, attrs),
                         "source_file": str(nc_path.relative_to(work_root)),
                         "source_sha256": sha256_of(nc_path)})
                    rec["path"] = rel
                    if rec["bytes"] > max_bytes:
                        raise ValueError(
                            f"partition {rel}: {rec['bytes']} bytes > gate "
                            f"{max_bytes} (config export.max_file_bytes)")
                    man["files"][rel] = rec
                    n_files += 1
                    total_bytes += rec["bytes"]

    # per-model members (committed subset only)
    pm = ex["per_model"]
    if pm.get("enabled", False):
        stat = pm["stat_name"]
        for model in subset:
            model_root = work_root / "aggregate" / model
            if not model_root.exists():
                raise FileNotFoundError(
                    f"{model_root} not found - run 06 for {model} in ssp "
                    f"mode first (R3: no invented model data)")
            for exp_dir in sorted(p for p in model_root.iterdir()
                                  if p.is_dir() and p.name.startswith("ssp")):
                scenario = exp_dir.name
                for nc_path in sorted(exp_dir.glob("*_districts_*.nc")):
                    variable = nc_path.name.split("_districts_")[0]
                    panels, keys, dids, attrs = load_nc_panel(nc_path,
                                                              [variable])
                    anom = check_calendar(keys)
                    if anom:
                        raise ValueError(f"{nc_path.name}: calendar anomaly "
                                         f"at index {anom}")
                    year_idx = {}
                    for i, (y, _m) in enumerate(keys):
                        year_idx.setdefault(y, []).append(i)
                    panel = panels[variable]
                    for year, idx in sorted(year_idx.items()):
                        if not np.isfinite(panel[:, idx]).any():
                            continue    # no rows in this year: no file (R10)
                        months = [keys[i][1] for i in idx]
                        rel = partition_rel(scenario, stat, variable, year,
                                            model, ex["partition_file"])
                        rec = write_partition(
                            staging / rel, dids, year, months, panel[:, idx],
                            model,
                            {"era": "projections", "scenario": scenario,
                             "stat": stat, "variable_id": variable,
                             "model_id": model, "era_label": label,
                             "source_file":
                                 str(nc_path.relative_to(work_root)),
                             "source_sha256": sha256_of(nc_path)})
                        rec["path"] = rel
                        if rec["bytes"] > max_bytes:
                            raise ValueError(
                                f"partition {rel}: {rec['bytes']} bytes > "
                                f"gate {max_bytes}")
                        man["files"][rel] = rec
                        n_files += 1
                        total_bytes += rec["bytes"]

    man["totals"] = {"files": n_files, "bytes": total_bytes,
                     "max_file_bytes": max_bytes}
    if dir_info is not None:
        man["dir_agreement"] = dir_info
    if n_files == 0:
        raise ValueError(
            "no ssp products found under work/ensemble|aggregate - run "
            "steps 06/07 in ssp mode first (refusing to stage an empty "
            "store, R3)")
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "export_manifest.json").write_text(
        json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"  staged {n_files} partition files "
          f"({total_bytes / 1024 / 1024:.1f} MB) -> {staging}")
    return man


def _stat_definition(stat: str, attrs: dict) -> str:
    try:
        d = json.loads(attrs.get("definitions_verbatim", "{}"))
    except json.JSONDecodeError:
        return ""
    if stat == "median":
        return d.get("median_p25_p75", "")
    return d.get(stat, "")


# --------------------------------------------------------------------------
# historical-corrected export (validation products only)
# --------------------------------------------------------------------------
def export_validation(work_root: Path, staging: Path, cfg: dict) -> dict:
    ex = cfg["export"]
    vdir = work_root / "validation"
    man = OrderedDict([
        ("schema", "die-export-manifest/1.0"),
        ("export_date", str(date.today())),
        ("mode", "historical-corrected"),
        ("era", "validation_historical_corrected"),
        ("era_label", " ".join(
            ex["labels"]["historical_corrected"].split())),
        ("honesty", [
            "QDM-corrected free-running models - NOT observed era B (R2)",
            "NOT an ssp projection and never a UI surface (X1/X5)",
            "no Parquet exported in this mode (see config/export.yaml)",
        ]),
        ("files", OrderedDict()),
    ])
    copied = 0
    for name in ex["validation_products"]:
        src = vdir / name
        if not src.exists():
            print(f"  MISSING (skipped honestly): {src}")
            continue
        dst = staging / "validation" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        man["files"][f"validation/{name}"] = {
            "bytes": dst.stat().st_size, "sha256": sha256_of(dst),
            "source_sha256": sha256_of(src),
        }
        copied += 1
    man["totals"] = {"files": copied}
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "export_manifest.json").write_text(
        json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"  copied {copied} validation product(s) -> {staging}")
    return man


# --------------------------------------------------------------------------
# publish (ssp only) - the X1-gated write into data/
# --------------------------------------------------------------------------
def ssp_gate_ok(work_root: Path) -> tuple[bool, str]:
    rep_path = work_root / "validation" / "validation_report.json"
    if not rep_path.exists():
        return False, "no work/validation/validation_report.json - run 08 first"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    if rep.get("mode") != "ssp":
        return False, f"validation report mode={rep.get('mode')!r}, need 'ssp'"
    for gname, gate in rep.get("gates", {}).items():
        if gate.get("pass") is False:
            return False, (f"validation gate {gname} FAILED "
                           f"(X1: publish blocked)")
    return True, "mode=ssp, all recorded gates pass"


def scan_projections(dest: Path, prefix: str) -> dict:
    """Scan a published/staged projections tree into catalog info."""
    files: dict = OrderedDict()
    years: set[int] = set()
    for p in sorted(dest.rglob("*.parquet")):
        rel = f"{prefix}/{p.relative_to(dest).as_posix().replace(chr(92), '/')}"
        parts = dict(seg.split("=", 1) for seg in p.relative_to(dest).parts
                     if "=" in seg)
        files.setdefault(parts["scenario"], OrderedDict()).setdefault(
            parts["stat"], OrderedDict()).setdefault(
            parts["variable"], []).append(rel)
        if "year" in parts:
            years.add(int(parts["year"]))
    return {"files": files, "years": sorted(years)}


def publish(work_root: Path, repo: Path, paths: dict, cfg: dict) -> int:
    ok, why = ssp_gate_ok(work_root)
    if not ok and cfg["export"]["publish"]["requires_ssp_gate_pass"]:
        print(f"PUBLISH REFUSED (X1): {why}")
        return 3
    print(f"PUBLISH gate: {why}")

    staging = (HERE / paths.get("out_root", "out")).resolve() / "projections"
    if not staging.exists():
        print(f"PUBLISH REFUSED: nothing staged at {staging} - "
              f"run --mode ssp first")
        return 2
    targets = cfg["export"]["publish"]["targets"]
    dest = repo / targets["parquet"]
    if dest.exists():
        n_old = sum(1 for _ in dest.rglob("*.parquet"))
        print(f"  replacing existing {dest} ({n_old} parquet files)")
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging, dest,
                    ignore=shutil.ignore_patterns("export_manifest.json"))
    n_new = sum(1 for _ in dest.rglob("*.parquet"))
    print(f"  published {n_new} parquet files -> {dest}")

    # catalog / manifests / metadata era-C blocks (additive only, R1)
    sys.path.insert(0, str(repo / "scripts"))
    import generate_catalog as gc
    existing_path = repo / targets["catalog"]
    existing = None
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except Exception as exc:            # corrupt catalog -> rebuild loses nothing we own
            print(f"  NOTE: existing catalog unreadable ({exc}); rebuilding")
    cat = gc.build()
    # Preserve era contracts owned by OTHER publish steps (era A atlas) -
    # a bare rebuild silently drops them (footgun recorded 2026-11-20).
    gc.preserve_era_blocks(cat, existing, keys=("atlas",))
    info = scan_projections(dest, targets["parquet"].replace("\\", "/"))
    gc.apply_projections(cat, {
        "label": " ".join(cfg["export"]["labels"]["ssp"].split()),
        "years": info["years"], "files": info["files"]})
    problems = gc.validate(cat, repo)
    if problems:
        for p in problems:
            print(f"CATALOG VALIDATE: {p}")
        return 1
    cat_path = repo / targets["catalog"]
    cat_path.write_text(json.dumps(cat, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"  catalog regenerated -> {cat_path} "
          f"({cat_path.stat().st_size / 1024:.0f} KB)")

    update_pipeline_manifest(repo / targets["pipeline_manifest"], dest, cfg)
    staged_man = {}
    mpath = staging / "export_manifest.json"
    if mpath.exists():
        staged_man = json.loads(mpath.read_text(encoding="utf-8"))
    update_metadata(repo / targets["metadata"], cfg, years=info["years"],
                    dir_block=staged_man.get("dir_agreement"))
    print("  pipeline_manifest.json + metadata.json era-C blocks written")
    print("  NOTE: data/ changed - review the git diff; the regression "
          "baseline fingerprints catalog.json and must be re-blessed "
          "(--bless) after review.")
    return 0


def update_pipeline_manifest(path: Path, dest: Path, cfg: dict) -> None:
    man = json.loads(path.read_text(encoding="utf-8")) if path.exists() \
        else {}
    era_c = OrderedDict([
        ("note", "era C block is additive; v1.0 keys untouched (R1)"),
        ("export_date", str(date.today())),
        ("bias_correction", {
            "method": "QDM (Cannon, Sobie & Murdock 2015)",
            "reference": "IMD 0.25 deg (Owner-computed, step 03)",
            "calibration_window": [1981, 2020],
            "bounds": [-5, 5],
            "seam": "model baseline 1981-2020 = historical 1981-2014 + "
                    "ssp 2015-2020 (AS6)",
        }),
        ("pet_formula",
         "Hargreaves-Samani (1985), per-era seam (decision E)"),
        ("distributions", {"SPI": "gamma MLE + mixed zeros",
                           "SPEI": "log-logistic L-moments "
                                   "(Gringorten fallback)"}),
        ("scenarios", sorted(p.name.split("=", 1)[1] for p in dest.iterdir()
                             if p.name.startswith("scenario="))),
        ("files", {}),
    ])
    for p in sorted(dest.rglob("*.parquet")):
        rel = p.relative_to(REPO).as_posix().replace("\\", "/")
        era_c["files"][rel] = sha256_of(p)
    man["era_c"] = era_c
    path.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def update_metadata(path: Path, cfg: dict, years: list[int] | None = None,
                    dir_block: dict | None = None) -> None:
    md = json.loads(path.read_text(encoding="utf-8")) if path.exists() \
        else {}
    labels = cfg["export"]["labels"]
    # R2/R3 era honesty: the label states the years ACTUALLY published
    # (scanned from the staged tree), never an aspirational span. While the
    # SSP inputs stop short of 2100 the label carries an explicit
    # "(... inputs pending)" suffix; once the full 2015-2100 record is
    # published the suffix disappears (2026-11-19: SSP 2015-2100 landed).
    if years:
        label = f"Projections {years[0]}-{years[-1]}"
        if years[-1] < 2100:
            label += f" ({years[-1] + 1}-2100 inputs pending)"
    else:
        label = "Projections"
    md["era_c"] = OrderedDict([
        ("id", "projections"),
        ("label", label),
        ("banner", " ".join(labels["ssp"].split())),
        ("status", "bias-corrected CMIP6 simulations - never forecasts"),
        ("scenarios", ["ssp245", "ssp585"]),
        ("ensemble", _subset_block()),
        ("pet", {"method": "Hargreaves-Samani (1985)",
                 "seam": "per-era PET (decision E): era B ERA5-Land PET "
                         "frozen; era C Hargreaves applied identically to "
                         "reference and model temperature"}),
        ("honesty", ["never spliced with observed data (R2)",
                     "spread + agreement shown alongside the median (X2/X3)",
                     "ensemble n recorded, never assumed (X3)"]),
        # Provenance block (M10.5 review finding): the era-C source chain is
        # stated in the data contract, never only in prose elsewhere. The
        # v2.0.0 application DOI is NOT claimed here; it is minted at release.
        ("source", _era_c_source()),
    ])
    if dir_block:
        # R2/R3: the EFFECTIVE window is stated verbatim (the configured
        # 2081-2100 window once the record reaches 2100; otherwise an explicit
        # record-end truncation). The statistic is a count of models, never a
        # probability (R9). Base = 1981-2014 per register D6.
        md["era_c"]["dir_agreement"] = OrderedDict([
            ("definition",
             "fraction of subset models whose effective-window mean is drier "
             "(lower z) than their own 1981-2014 base mean; window-constant "
             "per district; a count of models, never a probability"),
            ("base", dir_block.get("base")),
            ("base_years", dir_block.get("base_years")),
            ("window_configured", dir_block.get("window_configured")),
            ("window_effective", dir_block.get("window_effective")),
            ("window_note", dir_block.get("window_note")),
            ("min_window_years", dir_block.get("min_window_years")),
        ])
    path.write_text(json.dumps(md, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _era_c_source() -> dict:
    """Era-C provenance chain (M10.5). Kept here so a re-publish always
    carries it; the application DOI is deliberately absent (minted at M7.2)."""
    return OrderedDict([
        ("title", "CMIP6 historical and SSP simulations, bias-corrected"),
        ("archive", "CMIP6 (ESGF / Pangeo cloud archive)"),
        ("experiments", ["historical", "ssp245", "ssp585"]),
        ("models", "22-model archive; 8-model committed subset recorded in "
                   "era_c.ensemble"),
        ("reference_dataset",
         "IMD 0.25-degree gridded rainfall (Pai et al., 2014) and "
         "temperature (Srivastava et al., 2009)"),
        ("methods", [
            "QDM bias correction (Cannon et al., 2015)",
            "Hargreaves-Samani PET (1985) applied identically to reference "
            "and model temperature",
            "gamma SPI / log-logistic SPEI on the 0.25-degree grid, "
            "aggregated to the 724-district fabric",
        ]),
        ("citations", [
            "Eyring, V., Bony, S., Meehl, G. A., Senior, C. A., Stevens, B., "
            "Stouffer, R. J., & Taylor, K. E. (2016). Overview of the Coupled "
            "Model Intercomparison Project Phase 6 (CMIP6) experimental design "
            "and organization. Geoscientific Model Development, 9, 1937-1958. "
            "https://doi.org/10.5194/gmd-9-1937-2016",
            "O'Neill, B. C., Tebaldi, C., van Vuuren, D. P., Eyring, V., "
            "Friedlingstein, P., Hurtt, G., et al. (2016). The Scenario Model "
            "Intercomparison Project (ScenarioMIP) for CMIP6. Geoscientific "
            "Model Development, 9, 3461-3482. "
            "https://doi.org/10.5194/gmd-9-3461-2016",
            "Cannon, A. J., Sobie, S. R., & Murdock, T. Q. (2015). Bias "
            "correction of GCM precipitation by quantile mapping: How well do "
            "methods preserve changes in quantiles and extremes? Journal of "
            "Climate, 28, 6938-6959. https://doi.org/10.1175/JCLI-D-14-00754.1",
            "Pai, D. S., Sridhar, L., Rajeevan, M., Sreejith, O. P., "
            "Satbhai, N. S., & Mukhopadhyay, B. (2014). Development of a new "
            "high spatial resolution (0.25 x 0.25 degree) long period "
            "(1901-2010) daily gridded rainfall data set over India. Mausam, "
            "65(1), 1-18.",
            "Srivastava, A. K., Rajeevan, M., & Kshirsagar, S. R. (2009). "
            "Development of a high resolution daily gridded temperature data "
            "set for the Indian region. Atmospheric Science Letters, 10(4), "
            "249-254.",
        ]),
        ("licence",
         "CMIP6 model output is subject to each model's terms of use (see the "
         "ESGF record); IMD reference data per IMD terms. Derived DIE products "
         "are redistributed with attribution; the application code is MIT."),
    ])


def _subset_block() -> dict:
    """Committed subset + criterion, read from the gate outputs."""
    bs_path = HERE / "work" / "validation" / "best_subset.yaml"
    if not bs_path.exists():
        return {"n": None, "note": "best_subset.yaml not found"}
    bs = load_yaml(bs_path)
    return {"n": len(bs.get("subset", [])), "subset": bs.get("subset", []),
            "criterion_rule": bs.get("criterion_rule", ""),
            "core_size": bs.get("core_size"), "core_gap": bs.get("core_gap")}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Step 09 export (M2.12)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--publish", action="store_true",
                    help="ssp mode: also write data/parquet/projections + "
                         "catalog/manifests (X1 gate)")
    ap.add_argument("--dry-run", action="store_true",
                    help="stage into work/test-output/ instead of out/ (X9)")
    ap.add_argument("--models",
                    help="comma list override (default: best_subset.yaml "
                         "subset)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    cfg = load_yaml(CONFIG_DIR / "export.yaml")
    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    out_dir_name = (work_root / "test-output" / "out"
                    if args.dry_run else paths.get("out_root", "out"))
    out_root = (HERE / out_dir_name).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    if args.mode == "historical-corrected":
        hr("EXPORT mode=historical-corrected (validation products, no parquet)")
        man = export_validation(work_root, out_root, cfg)
        print(f"VALIDATION EXPORT DONE: {man['totals']['files']} file(s) "
              f"-> {out_root}")
        return 0

    # ssp mode
    bs_path = work_root / "validation" / "best_subset.yaml"
    if args.models:
        subset = [m.strip() for m in args.models.split(",")]
    elif bs_path.exists():
        subset = load_yaml(bs_path).get("subset")
    else:
        subset = None
    if not subset:
        print("REFUSED: no committed subset (work/validation/"
              "best_subset.yaml missing) - run 08 first (R3: no invented "
              "model list)")
        return 2
    hr(f"EXPORT mode=ssp subset={len(subset)} models")
    man = export_ssp(work_root, out_root / "projections", cfg, subset)
    t = man["totals"]
    print(f"SSP EXPORT DONE: {t['files']} files, "
          f"{t['bytes'] / 1024 / 1024:.1f} MB (gate {t['max_file_bytes']} "
          f"B/file) -> {out_root / 'projections'}")
    if args.publish:
        return publish(work_root, REPO, paths, cfg)
    print("Staging only (X9). Publishing to data/ requires --publish and "
          "the ssp-mode step-08 gate (X1).")
    return 0


# --------------------------------------------------------------------------
# selftest - synthetic mini world, writes ONLY under work/test-output/
# --------------------------------------------------------------------------
def selftest() -> int:
    import netCDF4 as nc

    base = HERE / "work" / "test-output" / "selftest"
    if base.exists():
        shutil.rmtree(base)
    world = base / "work"
    staging = base / "out" / "projections"
    fails: list[str] = []

    hr("SELFTEST - step 09 export on a synthetic world (seed 20261103)")

    # ---- synthetic world: 3 districts, 24 months, 2 vars, 2 scenarios -----
    dids = ["alpha", "bravo", "charlie"]
    months = [(y, m) for y in (2026, 2027) for m in range(1, 13)]
    tnum = np.array([np.datetime64(f"{y:04d}-{m:02d}-01")
                     for (y, m) in months])
    variables = ["spi_03", "spei_03"]
    scenarios = ["ssp245", "ssp585"]
    models = ["mA", "mB"]

    def synth_panel(seed_off: int, nan_d3: bool) -> np.ndarray:
        r = np.random.default_rng(SEED + seed_off)
        a = r.normal(0, 1, (3, len(months)))
        if nan_d3:
            a[2, :] = np.nan
        return a

    def write_world_nc(path: Path, var_specs: dict, extra_attrs: dict):
        """var_specs: {name: array}; writes the 06/07 (district, time) layout."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with nc.Dataset(path, "w") as d:
            d.createDimension("district", len(dids))
            d.createDimension("time", len(months))
            for nm, arr in var_specs.items():
                fill = (np.float32(9.96921e36)
                        if arr.dtype.kind == "f" else np.int16(-999))
                v = d.createVariable(
                    nm, "f4" if arr.dtype.kind == "f" else "i2",
                    ("district", "time"), fill_value=fill)
                v[:] = arr.astype(arr.dtype)
            tv = d.createVariable("time", "i8", ("time",))
            tv.units = "days since 2026-01-01"
            tv.calendar = "proleptic_gregorian"
            tv[:] = ((tnum - tnum[0]) / np.timedelta64(1, "D")
                     ).astype(np.int64)
            dv = d.createVariable("district", str, ("district",))
            dv[:] = np.array(dids, dtype=object)
            for k, v in extra_attrs.items():
                d.setncattr(k, v)

    for si, scenario in enumerate(scenarios):
        for vi, variable in enumerate(variables):
            seed_off = 100 * si + vi          # deterministic, no hash()
            nan_d3 = scenario == "ssp585"     # island-like NaN pattern
            med = synth_panel(seed_off, nan_d3)
            # direction stats exist ONLY in 2027 (mirrors the real
            # window-only spans: the exporter must not invent 2026 rows)
            dir_ok = np.array([y == 2027 for (y, _m) in months])
            dir_mask = dir_ok[None, :] & np.isfinite(med)
            specs = {
                "median": med,
                "p25": med - 0.5,
                "p75": med + 0.5,
                "agreement_moderate": np.where(np.isfinite(med), 0.25,
                                               np.nan),
                "agreement_severe": np.where(np.isfinite(med), 0.0, np.nan),
                "n_models": np.where(np.isfinite(med), 2, 0).astype(np.int16),
                "dir_agreement_drier": np.where(dir_mask, 0.5, np.nan),
                "dir_agreement_n": np.where(dir_mask, 2, -999).astype(np.int16),
            }
            defs = json.dumps({
                "median_p25_p75":
                    "quantiles over the n available models",
                "agreement_moderate":
                    "fraction of available models with value <= -1.0 "
                    "that month",
                "agreement_severe":
                    "fraction of available models with value <= -1.5 "
                    "that month",
                "dir_agreement_drier":
                    "fraction of models whose effective-window mean is "
                    "drier (lower z) than their own base mean; "
                    "window-constant per district (ssp mode only)",
                "dir_agreement_n":
                    "number of models with a finite base AND window mean",
                "n_models": "contributing model count"})
            write_world_nc(world / "ensemble" / scenario
                           / f"{variable}_ensemble_2026-2027.nc",
                           specs, {"definitions_verbatim": defs,
                                   "dir_agreement_base": "1981-2020",
                                   "dir_agreement_base_years": 40,
                                   "dir_agreement_window_configured":
                                       "2081-2100",
                                   "dir_agreement_window_effective":
                                       "2027-2027",
                                   "dir_agreement_window_note":
                                       "synthetic one-year window (selftest)",
                                   "dir_agreement_min_window_years": 10})
            for mi, model in enumerate(models):
                write_world_nc(
                    world / "aggregate" / model / scenario
                    / f"{variable}_districts_2026-2027.nc",
                    {variable: synth_panel(seed_off + 10 + mi, False)},
                    {"label": f"{model}/{scenario}"})

    # ---- run the exporter against the synthetic work tree ------------------
    cfg = load_yaml(CONFIG_DIR / "export.yaml")
    man = export_ssp(world, staging, cfg, models)

    # ---- T1: partition set --------------------------------------------------
    # ensemble: 2 scen x 2 vars x (6 stats x 2 yr + 2 dir stats x 1 yr) = 56;
    # members: 2 models x 2 scen x 2 vars x 2 yr = 16 -> 72.
    # The direction stats must NOT be repeated into the year they do not cover.
    n_files = len(man["files"])
    dir_2026 = [r for r in man["files"]
                if "/stat=dir_agreement_" in r and "year=2026" in r]
    dir_2027 = [r for r in man["files"]
                if "/stat=dir_agreement_drier" in r and "year=2027" in r]
    ok = n_files == 72 and not dir_2026 and len(dir_2027) == 4
    print(f"T1 partition count: {n_files} (expect 72), dir 2026 rows="
          f"{len(dir_2026)} (expect 0), dir 2027 files={len(dir_2027)} "
          f"(expect 4): {ok}")
    if not ok:
        fails.append("T1 partition set wrong")

    # ---- T2: absent-row rule (ssp585 charlie all-NaN on ensemble side) ------
    # year partition = 12 months x 2 finite districts = 24 rows (of 36)
    med585 = [rel for rel in man["files"]
              if "stat=median" in rel and "scenario=ssp585" in rel
              and "variable=spi_03" in rel and "year=2026" in rel
              and "model=" not in rel]
    ok = len(med585) == 1 and man["files"][med585[0]]["rows"] == 24
    print(f"T2 absent rows: ssp585 median 2026 rows="
          f"{man['files'][med585[0]]['rows'] if med585 else 'n/a'} "
          f"(expect 24 of 36): {ok}")
    if not ok:
        fails.append("T2 absent-row rule broken")

    # ---- T3: members rows (3 districts x 12 months = 36, both scenarios) ----
    mem = [rel for rel in man["files"] if "stat=members" in rel
           and "model=mA" in rel and "year=2026" in rel
           and "variable=spi_03" in rel]
    ok = len(mem) == 2 and all(man["files"][r]["rows"] == 36 for r in mem)
    print(f"T3 members rows: {[man['files'][r]['rows'] for r in mem]} "
          f"(expect [36, 36], one per scenario): {ok}")
    if not ok:
        fails.append("T3 members rows wrong")

    # ---- T4: cell round-trip exactness (full scan of the medians) -----------
    import netCDF4 as nc
    with nc.Dataset(world / "ensemble" / "ssp245"
                    / "spi_03_ensemble_2026-2027.nc") as d:
        ref = np.asarray(np.ma.filled(d.variables["median"][:], np.nan),
                         float)
    src_dids = dids
    bad = 0
    checked = 0
    med245 = [rel for rel in man["files"]
              if "stat=median" in rel and "scenario=ssp245" in rel
              and "variable=spi_03" in rel and "model=" not in rel]
    for rel in med245:
        df = pq.read_table(staging / rel).to_pandas()
        key = {(r.district_id, int(r.year), int(r.month)): float(r.value)
               for r in df.itertuples()}
        y = int(rel.split("year=")[1].split("/")[0])
        for j, (yy, mm) in enumerate(months):
            if yy != y:
                continue
            for i, did in enumerate(src_dids):
                want = np.float32(ref[i, j])
                got = key.get((did, yy, mm))
                if np.isnan(want):
                    if got is not None:
                        bad += 1
                        fails.append(f"phantom {rel} {did} {yy}-{mm}")
                    continue
                checked += 1
                if got is None or got != want:
                    bad += 1
                    fails.append(f"mismatch {rel} {did} {yy}-{mm}: "
                                 f"{got} != {want}")
    ok = bad == 0 and checked == 72
    print(f"T4 round-trip: {checked} cells checked, {bad} bad (expect "
          f"72, 0): {ok}")
    if not ok:
        fails.append("T4 round-trip broken")

    # ---- T5: size gate ------------------------------------------------------
    sizes = [rec["bytes"] for rec in man["files"].values()]
    ok = all(s <= cfg["export"]["max_file_bytes"] for s in sizes)
    print(f"T5 size gate: max {max(sizes)} B <= "
          f"{cfg['export']['max_file_bytes']} B: {ok}")
    if not ok:
        fails.append("T5 size gate breached")

    # ---- T6: R2 label in partition file metadata ----------------------------
    sch = pq.read_schema(staging / med585[0])
    md = sch.metadata or {}
    lab = md.get(b"era_label", b"")
    ok = b"PROJECTIONS" in lab and b"never forecasts" in lab
    print(f"T6 era label: {lab[:60].decode(errors='replace')}...: {ok}")
    if not ok:
        fails.append("T6 era label missing")

    # ---- T7: catalog apply_projections + path existence ---------------------
    sys.path.insert(0, str(REPO / "scripts"))
    import generate_catalog as gc
    cat = gc.build()
    scanned = scan_projections(staging, "out/projections")
    gc.apply_projections(cat, {"label": "Projections (selftest)",
                               "years": scanned["years"],
                               "files": scanned["files"]})
    era = cat["eras"]["projections"]
    var = next(v for v in cat["variables"] if v["id"] == "spi_03")
    proj = var["files"]["projections"]
    n_paths = sum(len(ps) for sc in proj.values() for ps in sc.values())
    all_exist = all((base / p).exists()
                    for sc in proj.values() for ps in sc.values() for p in ps)
    # gc.validate(cat) must treat the NESTED projections block as
    # {scenario: {stat: [paths]}} - if it iterates the scenario KEYS as
    # paths it emits "variable path missing: ssp245" (the bug caught at the
    # first real publish, 2026-11-17). Leaf paths always carry hive "="
    # segments, and era-path problems are environment-dependent, so the
    # assertion is: every "variable path missing" problem (if any) names a
    # hive path, never a bare scenario key.
    probs7 = [p for p in gc.validate(cat)
              if p.startswith("variable path missing")]
    ok = (era["available"] is True and era["years"] == [2026, 2027]
          and n_paths == 36          # 6 stats x 2 scen x 2 yr + 2 dir stats
                                     # x 2 scen x 1 yr + members 2x2x2
          and all_exist and "projections" in var["eras"]
          and all("scenario=" in p for p in probs7))
    print(f"T7 catalog: available={era['available']}, "
          f"years={era['years']}, {n_paths} paths (expect 36 for spi_03), "
          f"all exist={all_exist}, validate problems={len(probs7)}: {ok}")
    if not ok:
        fails.append("T7 catalog block broken")

    # ---- T8: X1 publish refusal without an ssp gate report ------------------
    ok, why = ssp_gate_ok(world)
    refused = ok is False
    informative = ("mode" in why) or ("no work/validation" in why)
    print(f"T8 X1 refusal: refused={refused} ({why}): {refused and informative}")
    if not (refused and informative):
        fails.append("T8 X1 refusal broken")

    # ---- T9: validation export manifest (labels + checksums) ----------------
    vstage = base / "out2"
    (world / "validation").mkdir(parents=True, exist_ok=True)
    (world / "validation" / "best_subset.yaml").write_text(
        "subset: [mA, mB]\n", encoding="utf-8")
    vman = export_validation(world, vstage, cfg)
    dst = vstage / "validation" / "best_subset.yaml"
    ok = (dst.exists()
          and vman["files"]["validation/best_subset.yaml"]["sha256"]
          == sha256_of(dst)
          and "NOT" in vman["era_label"])
    print(f"T9 validation export: checksum match + R2 label: {ok}")
    if not ok:
        fails.append("T9 validation export broken")

    # ---- T10: dir window carried into manifest + metadata era-C block ------
    dm = man.get("dir_agreement") or {}
    tmpp = base / "metadata_selftest.json"
    update_metadata(tmpp, cfg, years=[2026, 2027], dir_block=dm)
    blk = json.loads(tmpp.read_text(encoding="utf-8"))["era_c"].get(
        "dir_agreement", {})
    ok = (dm.get("window_effective") == "2027-2027"
          and dm.get("window_configured") == "2081-2100"
          and dm.get("base") == "1981-2020"
          and blk.get("window_effective") == "2027-2027"
          and "never a probability" in blk.get("definition", ""))
    print(f"T10 dir window: manifest={dm.get('window_effective')} "
          f"metadata={blk.get('window_effective')} (expect 2027-2027): {ok}")
    if not ok:
        fails.append("T10 dir window block broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails[:10]}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4, T5, T6, T7, T8, T9, T10)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
