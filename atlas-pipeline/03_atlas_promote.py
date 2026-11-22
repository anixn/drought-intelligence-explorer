#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""03_atlas_promote.py — era-A promotion (task M6.2b, Owner-gated).

Promotes the VERIFIED staging store (02_atlas_to_district.py output) into
the repo contract, additively and idempotently:

  1. verify the staging tree (layout, 375 partitions, row total vs the
     ingest manifest, every file non-empty);
  2. copy `work/atlas_store/atlas/` -> `data/parquet/atlas/`
     (rmtree + copytree, mirroring the era-C publish; the store stays
     Owner-local/gitignored until release — same decision as era C);
  3. catalog.json: ADDITIVE merge (never the bare gc.build() — that
     rebuild wiped the projections contract once, footgun recorded
     2026-11-20). Only the atlas era block + the three era-A variables
     are touched; observed/projections blocks pass through untouched;
  4. metadata.json: additive `era_a` block (provenance, route, QA, seams);
  5. pipeline_manifest.json: additive era-A block with per-file SHA-256;
  6. report written to work/promote_report.json.

X9-style write safety: everything under data/ is written by THIS script
only when the staging verification passes; a failure before the copy
leaves data/ untouched.

Usage:
    python 03_atlas_promote.py                # real promotion
    python 03_atlas_promote.py --selftest     # synthetic fixture, deterministic
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))

PART_RE = re.compile(r"^variable=(spei_\d\d)/year=(\d{4})/part-0\.parquet$")
EXPECTED_VARS = ("spei_01", "spei_04", "spei_12")
ERA_LABEL = "Atlas reconstruction (SPEI) 1901-2025"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_staging(staging: Path) -> dict:
    """Verify the staging tree; return {files: {(var, year): path}, rows}."""
    import pyarrow.parquet as pq
    files = {}
    total_rows = 0
    root = staging / "atlas"
    if not root.is_dir():
        raise SystemExit(f"FATAL: staging root missing: {root}")
    for var in EXPECTED_VARS:
        vdir = root / f"variable={var}"
        if not vdir.is_dir():
            raise SystemExit(f"FATAL: staging variable dir missing: {vdir}")
        years = sorted(p.parent for p in vdir.rglob("*.parquet"))
        for ydir in years:
            m = PART_RE.match(str(ydir.relative_to(root)).replace("\\", "/")
                              + "/part-0.parquet")
            if not m:
                raise SystemExit(f"FATAL: unexpected staging layout: {ydir}")
            f = ydir / "part-0.parquet"
            if f.stat().st_size == 0:
                raise SystemExit(f"FATAL: empty partition: {f}")
            files[(var, int(m.group(2)))] = f
            total_rows += pq.ParquetFile(f).metadata.num_rows
    years_by_var = {v: sorted(y for (vv, y) in files if vv == v)
                    for v in EXPECTED_VARS}
    return {"files": files, "rows": total_rows, "years": years_by_var}


def promote(repo: Path, staging: Path, atlas_cfg_path: Path | None = None,
            expect: dict | None = None) -> dict:
    """Full promotion against a repo root (real or selftest fixture).

    expect: {files: int, year_start: int, year_end: int, years_per_var: int}
    defaults to the verified real-record contract (M6.1 gate).
    """
    expect = expect or {"files": 375, "year_start": 1901, "year_end": 2025,
                        "years_per_var": 125}
    import pyarrow.parquet as pq
    import yaml  # noqa: F401  (config parsed only for provenance strings)
    import generate_catalog as gc

    # ---- 1. staging verification ------------------------------------------
    scanned = scan_staging(staging)
    n_files = len(scanned["files"])
    if n_files != expect["files"]:
        raise SystemExit(f"FATAL: expected {expect['files']} partitions, "
                         f"found {n_files}")
    for var, ys in scanned["years"].items():
        if ys[0] != expect["year_start"] or ys[-1] != expect["year_end"] \
                or len(ys) != expect["years_per_var"]:
            raise SystemExit(f"FATAL: {var} year coverage {ys[0]}..{ys[-1]} "
                             f"({len(ys)} years) != {expect['year_start']}.."
                             f"{expect['year_end']} ({expect['years_per_var']})")
    manifest_path = staging.parent / "ingest" / "ingest_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) \
        if manifest_path.exists() else {}
    if manifest.get("rows") and manifest["rows"] != scanned["rows"]:
        raise SystemExit("FATAL: staging row total "
                         f"{scanned['rows']} != ingest manifest {manifest['rows']}")

    # ---- 2. copy into data/parquet/atlas ------------------------------------
    dest = repo / "data" / "parquet" / "atlas"
    src = staging / "atlas"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    n_copied = sum(1 for _ in dest.rglob("*.parquet"))
    if n_copied != n_files:
        raise SystemExit(f"FATAL: copy mismatch {n_copied} != {n_files}")
    bytes_total = sum(f.stat().st_size for f in dest.rglob("*.parquet"))

    # ---- 3. catalog: ADDITIVE merge into the EXISTING catalog ---------------
    cat_path = repo / "data" / "parquet" / "catalog.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    paths_by_var = {}
    for (var, year), f in sorted(scanned["files"].items()):
        rel = str(f.relative_to(src)).replace("\\", "/")
        paths_by_var.setdefault(var, []).append("data/parquet/atlas/" + rel)
    gc.apply_atlas(cat, {"label": ERA_LABEL, "years": [1901, 2025],
                         "files": paths_by_var})
    problems = gc.validate(cat, repo)
    if problems:
        for p in problems:
            print("CATALOG VALIDATE:", p)
        raise SystemExit("FATAL: catalog validation failed")
    cat_path.write_text(json.dumps(cat, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    # ---- 4. metadata.json: additive era_a block ------------------------------
    md_path = repo / "data" / "metadata.json"
    md = json.loads(md_path.read_text(encoding="utf-8")) if md_path.exists() else {}
    cfg = {}
    if atlas_cfg_path and Path(atlas_cfg_path).exists():
        cfg = yaml.safe_load(Path(atlas_cfg_path).read_text(encoding="utf-8")).get("atlas", {})
    rel_cfg = cfg.get("release", {})
    qa = manifest.get("national_qa", {})
    md["era_a"] = OrderedDict([
        ("id", "atlas"),
        ("label", ERA_LABEL),
        ("banner",
         "ERA A (reconstruction) - Drought Atlas of India SPEI at 1/4/12-month "
         "scales, 0.05-degree grid area-weighted onto the 724-district fabric "
         "(route OD4). A reconstruction, never spliced with the era-B Gridded "
         "Multi-Source Product or era-C projections (R2); era-labelled on "
         "every surface."),
        ("status", "reconstruction - verified ingest, QA attached"),
        ("source", OrderedDict([
            ("title", rel_cfg.get("title", "Drought Atlas of India, 1901-2025")),
            ("version", rel_cfg.get("version", 2)),
            ("doi", rel_cfg.get("doi", "10.5281/zenodo.20368514")),
            ("licence", rel_cfg.get("licence", "CC-BY-4.0")),
            ("citation", (rel_cfg.get("citation") or "").strip()),
        ])),
        ("window", [1901, 2025]),
        ("timescales", ["spei_01", "spei_04", "spei_12"]),
        ("route", "geometric area-weighted aggregation of the 0.05-degree "
                  "grid onto 724 districts (Sutherland-Hodgman LAEA clip "
                  "weights, gcm-pipeline/06 machinery); the Atlas's own "
                  "742-polygon/732-series fabric is QA-only, never published"),
        ("rows", scanned["rows"]),
        ("files", n_copied),
        ("missing", "the six island districts have no Atlas grid cells "
                    "(documented ocean mask); values absent, never imputed "
                    "(R10)"),
        ("seam", "era A and era B are NEVER spliced; the 1981-2025 overlap "
                 "is cross-validation material only (M6.6, register D6 "
                 "comparison window)"),
        ("national_qa", OrderedDict(
            (k, OrderedDict([("r", v.get("r")), ("mean_bias", v.get("mean_bias")),
                             ("sd_ratio", v.get("sd_ratio"))]))
            for k, v in qa.items())),
        ("roundtrip_ok", manifest.get("roundtrip_ok")),
    ])
    md_path.write_text(json.dumps(md, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    # ---- 5. pipeline_manifest.json: additive era-A block ---------------------
    pm_path = repo / "data" / "pipeline_manifest.json"
    pm = json.loads(pm_path.read_text(encoding="utf-8")) if pm_path.exists() else {}
    era_files = OrderedDict()
    for f in sorted(dest.rglob("*.parquet")):
        rel = str(f.relative_to(repo)).replace("\\", "/")
        era_files[rel] = OrderedDict([("bytes", f.stat().st_size),
                                      ("sha256", sha256(f))])
    pm["era_a"] = OrderedDict([
        ("schema", "die-pipeline-manifest-era-a/1.0"),
        ("staging", str(staging / "atlas")),
        ("ingest_manifest_sha256", sha256(manifest_path)
         if manifest_path.exists() else None),
        ("totals", OrderedDict([("files", len(era_files)),
                                ("bytes", bytes_total)])),
        ("files", era_files),
    ])
    pm_path.write_text(json.dumps(pm, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    report = {
        "schema": "die-atlas-promote/1.0",
        "rows": scanned["rows"], "files": n_copied,
        "bytes": bytes_total,
        "catalog_label": ERA_LABEL,
        "national_qa_scales": sorted(qa.keys()),
        "dest": str(dest),
    }
    (HERE / "work" / "promote_report.json").parent.mkdir(parents=True,
                                                         exist_ok=True)
    (HERE / "work" / "promote_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------- selftest --
def selftest() -> int:
    """Synthetic mini-fixture: 2 vars x 2 years, 3 districts; asserts the
    additive merge, the copy, the manifest and metadata blocks."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    tmp = HERE / "work" / "test-output" / "selftest-atlas"
    if tmp.exists():
        shutil.rmtree(tmp)
    repo = tmp / "repo"
    staging = tmp / "staging"
    (repo / "data" / "parquet").mkdir(parents=True)
    for d in ("data/boundaries", "work/ingest"):
        (staging.parent / d).mkdir(parents=True, exist_ok=True) if False else None
    (tmp / "ingest").mkdir(parents=True)

    districts = ["gujarat-ahmedabad", "bihar-patna", "kerala-thiruvananthapuram"]
    years = [1901, 1902]
    rows_total = 0
    for var in ("spei_01", "spei_04", "spei_12"):
        for y in years:
            vals = []
            for i, d in enumerate(districts):
                for m in range(1, 13):
                    rows_total += 1
                    vals.append({"district_id": d, "year": y, "month": m,
                                 "value": float(((i * 12 + m) % 7) - 3) / 2})
            out = staging / "atlas" / f"variable={var}" / f"year={y}"
            out.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(vals), out / "part-0.parquet")
    (tmp / "ingest" / "ingest_manifest.json").write_text(json.dumps(
        {"rows": rows_total, "national_qa": {"spei_01": {"r": 0.98}},
         "roundtrip_ok": True}), encoding="utf-8")

    # minimal existing catalog with a projections block that MUST survive
    cat = {
        "version": "2.0.0",
        "eras": {
            "observed": {"label": "o", "path": "data/parquet/observed",
                         "available": True},
            "atlas": {"label": "old", "path": "data/parquet/atlas",
                      "available": False},
            "projections": {"label": "p", "path": "data/parquet/projections",
                            "available": True, "years": [2015, 2100]},
        },
        "variables": [
            {"id": "spei_01", "label": "SPEI-1", "unit": "z", "eras": ["observed"],
             "files": {"observed": ["data/parquet/observed/x.parquet"]}},
        ],
        "national": "data/parquet/_national_monthly.parquet",
    }
    (repo / "data" / "parquet" / "catalog.json").write_text(json.dumps(cat))
    (repo / "data" / "parquet" / "_national_monthly.parquet").write_bytes(b"x")
    (repo / "data" / "parquet" / "observed").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "parquet" / "observed" / "x.parquet").write_bytes(b"x")
    (repo / "data" / "parquet" / "projections").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "metadata.json").write_text("{}")
    (repo / "data" / "pipeline_manifest.json").write_text("{}")

    report = promote(repo, staging, atlas_cfg_path=None,
                     expect={"files": 6, "year_start": 1901, "year_end": 1902,
                             "years_per_var": 2})

    checks = []
    cat2 = json.loads((repo / "data" / "parquet" / "catalog.json").read_text())
    # T1 projections block survived the additive merge
    checks.append(("T1 projections preserved",
                   cat2["eras"]["projections"]["available"] is True
                   and cat2["eras"]["projections"]["years"] == [2015, 2100]))
    # T2 atlas block applied with exact paths
    v = cat2["variables"][0]
    checks.append(("T2 atlas files applied",
                   cat2["eras"]["atlas"]["available"] is True
                   and len(v["files"].get("atlas", [])) == 2
                   and "atlas" in v["eras"]))
    # T3 copy complete
    n_parquet = sum(1 for _ in (repo / "data" / "parquet" / "atlas").rglob("*.parquet"))
    checks.append(("T3 partitions copied", n_parquet == 6
                   and report["rows"] == rows_total))
    # T4 metadata era_a block additive
    md = json.loads((repo / "data" / "metadata.json").read_text())
    checks.append(("T4 metadata era_a", md["era_a"]["id"] == "atlas"
                   and md["era_a"]["rows"] == rows_total
                   and md["era_a"]["national_qa"]["spei_01"]["r"] == 0.98))
    # T5 pipeline manifest sha256 per file
    pm = json.loads((repo / "data" / "pipeline_manifest.json").read_text())
    checks.append(("T5 manifest checksums",
                   len(pm["era_a"]["files"]) == 6
                   and all(e["sha256"] for e in pm["era_a"]["files"].values())))
    # T6 idempotent re-run reproduces byte-identical catalog
    r1 = (repo / "data" / "parquet" / "catalog.json").read_bytes()
    promote(repo, staging, atlas_cfg_path=None,
            expect={"files": 6, "year_start": 1901, "year_end": 1902,
                    "years_per_var": 2})
    r2 = (repo / "data" / "parquet" / "catalog.json").read_bytes()
    checks.append(("T6 idempotent", r1 == r2))

    fails = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    print("SELFTEST " + ("PASS" if not fails else "FAIL: " + ", ".join(fails)))
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    cfg = HERE / "config" / "atlas.yaml"
    report = promote(REPO, HERE / "work" / "atlas_store", atlas_cfg_path=cfg)
    print(json.dumps(report, indent=1))
    print("PROMOTE DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
