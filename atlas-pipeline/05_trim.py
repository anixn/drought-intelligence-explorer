#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""05_trim.py — Owner-authorised trim of the Drought Atlas archive
(config/atlas.yaml trim policy; Owner authorisation 2026-11-20).

Deletes ONLY the `delete_after_ingest` / `delete_now_if_present` globs and
REFUSES anything matching the `keep` list. Dry-run by default: nothing is
deleted without --apply. Records before/after sizes per item and writes
work/trim_report.json (the PROGRESS record). The QA evidence this trim
supersedes is committed at atlas-pipeline/validation/district_qa/
(732-series QA, r median ≥ 0.996) — the trim happens only after that
snapshot exists (enforced here).

Usage:
    python 05_trim.py             # dry run: prints the plan, deletes nothing
    python 05_trim.py --apply     # delete (keep-list protected)
    python 05_trim.py --selftest  # synthetic fixture asserts the policy
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return 0


def matches_any(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) or rel.startswith(pat.rstrip("/*") + "/")
               for pat in patterns)


def build_plan(local_root: Path, cfg: dict) -> dict:
    keep = cfg.get("keep", [])
    delete = list(cfg.get("delete_after_ingest", [])) + \
        list(cfg.get("delete_now_if_present", []))
    items, protected = [], []
    seen = set()
    for pat in delete:
        if pat.endswith("/**"):
            cands = [local_root / pat[:-3]]
        elif "*" in Path(pat).name:
            parent = local_root / (Path(pat).parent if str(Path(pat).parent) != "."
                                   else "")
            if not parent.is_dir():
                continue
            cands = [p for p in parent.iterdir()
                     if fnmatch.fnmatch(p.name, Path(pat).name)]
        else:
            cands = [local_root / pat]
        for c in cands:
            if not c.exists():
                continue
            rel = str(c.relative_to(local_root)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            if matches_any(rel, keep):
                protected.append({"item": rel, "pattern": pat})
                continue
            items.append({"item": rel, "pattern": pat,
                          "bytes": dir_size(c)})
    return {"items": items, "protected": protected}


def run(cfg_path: Path, apply: bool) -> int:
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["atlas"]
    local_root = Path(cfg["local_root"])

    # X-safety: the QA evidence snapshot must be committed before Z-score goes
    qa = HERE / "validation" / "district_qa" / "district_qa.json"
    if not qa.exists():
        raise SystemExit("FATAL: QA evidence snapshot missing: " + str(qa) +
                         " — commit it before trimming (the QA read Z-score/)")

    total_before = dir_size(local_root)
    plan = build_plan(local_root, cfg)
    print("=" * 74)
    print(f"ATLAS TRIM ({'APPLY' if apply else 'DRY RUN'}) — root: {local_root}")
    print("=" * 74)
    for it in plan["items"]:
        print(f"  {'WOULD DELETE' if not apply else 'DELETING    '} "
              f"{it['item']:58s} {it['bytes'] / 1e6:9.1f} MB")
    for it in plan["protected"]:
        print(f"  PROTECTED (keep list)      {it['item']}  <- {it['pattern']}")
    del_bytes = sum(i["bytes"] for i in plan["items"])
    print(f"  total to delete: {del_bytes / 1e6:.1f} MB of "
          f"{total_before / 1e6:.1f} MB")
    if plan["protected"]:
        print("  ABORT: keep-list collision — nothing deleted")
        return 1
    if not plan["items"]:
        print("  nothing to delete (already trimmed)")
        return 0
    if not apply:
        print("  dry run — pass --apply to delete")
        return 0
    for it in plan["items"]:
        p = local_root / it["item"]
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    total_after = dir_size(local_root)
    report = {
        "schema": "die-atlas-trim/1.0",
        "authorisation": "Owner 2026-11-20 ('you can delete the unused atlas "
                         "file'); policy = config/atlas.yaml trim block",
        "qa_snapshot": "atlas-pipeline/validation/district_qa/ (committed)",
        "before_bytes": total_before,
        "after_bytes": total_after,
        "deleted": plan["items"],
        "kept": cfg.get("keep", []),
    }
    (HERE / "work" / "trim_report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    print(f"  AFTER: {total_after / 1e6:.1f} MB  "
          f"(freed {(total_before - total_after) / 1e6:.1f} MB)")
    print("  report -> work/trim_report.json")
    return 0


def selftest() -> int:
    """Synthetic fixture: keep-list item matching a delete glob is protected."""
    import tempfile
    import yaml as _yaml
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "archive"
    for rel in ("Z-score/India/x", "Gridded_SPEI/y", "latlon_India_0.05degree.csv",
                "STATE_BOUNDARY.shp"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 10)
    cfg = {"local_root": str(root),
           "keep": ["Gridded_SPEI/**"],
           "delete_after_ingest": ["Z-score/**", "latlon_India_0.05degree.csv",
                                   "STATE_BOUNDARY.*"],
           "delete_now_if_present": []}
    cfg_path = tmp / "atlas.yaml"
    cfg_path.write_text(_yaml.safe_dump({"atlas": cfg}))
    # fake QA snapshot so the run() guard passes
    vq = HERE / "validation" / "district_qa"
    vq.mkdir(parents=True, exist_ok=True)
    guard = vq / "district_qa.json"
    existed = guard.exists()
    if not existed:
        guard.write_text("{}")
    try:
        plan = build_plan(root, cfg)
        names = [i["item"].replace("\\", "/") for i in plan["items"]]
        ok = ("Z-score" in names and "latlon_India_0.05degree.csv" in names
              and "STATE_BOUNDARY.shp" in names
              and not any(n.startswith("Gridded_SPEI") for n in names)
              and not plan["protected"])
        # and the keep guard: a delete glob that would hit a kept path
        cfg2 = dict(cfg)
        cfg2["delete_after_ingest"] = cfg["delete_after_ingest"] + ["Gridded_SPEI/y"]
        plan2 = build_plan(root, cfg2)
        ok2 = any(i["item"].replace("\\", "/") == "Gridded_SPEI/y"
                  for i in plan2["protected"])
        print(("PASS" if ok and ok2 else "FAIL") +
              " selftest: keep-list protection")
        return 0 if ok and ok2 else 1
    finally:
        if not existed:
            guard.unlink()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run(HERE / "config" / "atlas.yaml", args.apply)


if __name__ == "__main__":
    sys.exit(main())
