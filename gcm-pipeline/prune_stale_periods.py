#!/usr/bin/env python3
"""DIE v2.0 gcm-pipeline — prune SUPERSEDED record-period outputs.

WHY THIS EXISTS (record extension, 2026-11-19)
----------------------------------------------
Every gcm-pipeline stage stamps its output with the record period it covers
(e.g. ``pr_2015-2050.nc`` -> ``work/regrid/<model>/<exp>/``). When the RAW
record grows (here: the SSP download extended from 2015-2050 to 2015-2100)
the stage writes a NEW file with the longer period and the shorter file
becomes SUPERSEDED — it is a partial view of the same record, never an
additional product.

Leaving superseded files in place is unsafe because every downstream step
discovers its inputs by glob:

  * ``03_qdm_bias_correct.regrid_file_for`` takes ``sorted(glob)[0]`` — it
    would silently pick ``2015-2050`` over ``2015-2100``;
  * ``04_pet_hargreaves`` requires EXACTLY ONE ``tasmax_*/tasmin_*`` file and
    skips the model when it sees two (silent gap);
  * ``05``/``09`` concatenate what they glob — two overlapping periods would
    export duplicate, partly contradictory partitions.

So after (and only after) a stage has produced the full-period file, the
superseded shorter-period files must be removed. This tool does exactly
that, with three hard safeguards:

  1. it only touches period-stamped files whose span is a STRICT SUBSET of
     the target span (``2015-2050`` inside ``2015-2100``);
  2. it only acts in a directory that already holds a file for the SAME base
     name covering the FULL target period, and that file must be non-empty;
  3. dry-run by default — ``--apply`` is required to delete anything.

It never touches ``1981-2014`` historical/historical-corrected products (their
span is not inside an ssp target span), never touches ``data/``, ``out/`` or
the raw store, and prints a per-directory report. The report is written to
``work/prune_report_<period>.json`` for the session record.

Usage
-----
    python prune_stale_periods.py --period 2015-2100            # dry run
    python prune_stale_periods.py --period 2015-2100 --apply    # delete
    python prune_stale_periods.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Stage roots (relative to work/) that hold period-stamped outputs.
# Pairs: (label, relative root). Each root is walked recursively; the leaf
# directories are the per-model/per-experiment stage dirs.
STAGE_ROOTS = [
    ("regrid", "regrid"),
    ("qdm", "qdm"),
    ("pet", "pet"),
    ("indices", "indices"),
    ("aggregate", "aggregate"),
    ("ensemble", "ensemble"),
]

PERIOD_RE = re.compile(r"^(?P<base>.+)_(?P<a>\d{4})-(?P<b>\d{4})$")


def parse_period(stem: str) -> tuple[str, int, int] | None:
    m = PERIOD_RE.match(stem)
    if not m:
        return None
    a, b = int(m["a"]), int(m["b"])
    if a > b:
        return None
    return m["base"], a, b


def prune_dir(d: Path, target: tuple[int, int], apply: bool) -> dict:
    """Prune superseded period files in ONE directory. Returns a report dict."""
    t0, t1 = target
    target_tag = f"{t0}-{t1}"
    by_base: dict[str, list[tuple[Path, int, int]]] = {}
    for p in sorted(d.glob("*.nc")):
        parsed = parse_period(p.stem)
        if parsed is None:
            continue
        base, a, b = parsed
        by_base.setdefault(base, []).append((p, a, b))

    removed, kept, skipped = [], [], []
    for base, files in sorted(by_base.items()):
        full = [(p, a, b) for (p, a, b) in files if (a, b) == (t0, t1)]
        if not full:
            skipped.append({"base": base, "reason": "no full-period file present"})
            continue
        keep_path = full[0][0]
        if keep_path.stat().st_size == 0:
            skipped.append({"base": base, "reason": "full-period file is empty",
                            "file": keep_path.name})
            continue
        kept.append({"base": base, "file": keep_path.name,
                     "bytes": keep_path.stat().st_size})
        for (p, a, b) in files:
            if (a, b) == (t0, t1):
                continue
            # Safeguard 1: strict subset of the target span, by BOTH ends.
            if not (t0 <= a and b <= t1 and (a, b) != (t0, t1)):
                skipped.append({"base": base, "file": p.name,
                                "reason": "span is not inside the target span"})
                continue
            rec = {"base": base, "file": p.name, "bytes": p.stat().st_size,
                   "period": f"{a}-{b}", "superseded_by": keep_path.name}
            if apply:
                p.unlink()
                rec["status"] = "deleted"
            else:
                rec["status"] = "would-delete"
            removed.append(rec)
    return {"dir": str(d), "target": target_tag, "kept": kept,
            "removed": removed, "skipped": skipped}


def collect_dirs(work_root: Path, only: str | None) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for label, rel in STAGE_ROOTS:
        if only and label != only:
            continue
        root = work_root / rel
        if not root.exists():
            continue
        # leaf = any directory that directly contains *.nc
        seen = set()
        for p in root.rglob("*.nc"):
            d = p.parent
            if d in seen:
                continue
            seen.add(d)
            out.append((label, d))
    return out


def run(work_root: Path, period: str, apply: bool, only: str | None) -> int:
    a, b = (int(x) for x in period.split("-"))
    target = (a, b)
    dirs = collect_dirs(work_root, only)
    if not dirs:
        print(f"NOTHING TO DO: no stage directories with .nc files under "
              f"{work_root}" + (f" (stage={only})" if only else ""))
        return 0

    print(f"{'PRUNE (apply)' if apply else 'PRUNE (dry run)'} — target period "
          f"{period} — {len(dirs)} stage director{'y' if len(dirs) == 1 else 'ies'}")
    reports, n_del, n_bytes = [], 0, 0
    for label, d in sorted(dirs, key=lambda t: (t[0], str(t[1]))):
        rep = prune_dir(d, target, apply)
        rep["stage"] = label
        if rep["removed"]:
            rel = d.relative_to(work_root.parent)
            print(f"  [{label}] {rel}")
            for r in rep["removed"]:
                print(f"      {r['status']:<13} {r['file']} ({r['bytes']:,} B) "
                      f"period {r['period']} -> superseded by {r['superseded_by']}")
                n_del += 1
                n_bytes += r["bytes"]
        reports.append(rep)

    out = work_root / f"prune_report_{period}.json"
    out.write_text(json.dumps({
        "target_period": period, "applied": apply,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deleted_files": n_del, "deleted_bytes": n_bytes,
        "directories": reports}, indent=2), encoding="utf-8")
    verb = "DELETED" if apply else "would delete"
    print(f"PRUNE {'DONE' if apply else 'DRY RUN'}: {verb} {n_del} file(s), "
          f"{n_bytes / 1e6:.1f} MB -> {out.name}")
    if not apply and n_del:
        print("Re-run with --apply to delete.")
    return 0


# --------------------------------------------------------------- selftest ----
def selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="die-prune-"))
    fails = []
    try:
        work = tmp / "work"
        good = work / "regrid" / "M1" / "ssp245"
        good.mkdir(parents=True)
        # full-period + superseded shorter file, same base
        (good / "pr_2015-2100.nc").write_bytes(b"x" * 10)
        (good / "pr_2015-2050.nc").write_bytes(b"x" * 5)
        (good / "pr_1981-2014.nc").write_bytes(b"x" * 5)      # must survive
        # no full-period file here -> nothing may be deleted
        other = work / "qdm" / "M1" / "ssp245"
        other.mkdir(parents=True)
        (other / "tasmax_2015-2050.nc").write_bytes(b"x" * 5)
        # full-period file EMPTY -> refuse
        empty = work / "pet" / "M1" / "ssp245"
        empty.mkdir(parents=True)
        (empty / "pet_2015-2100.nc").write_bytes(b"")
        (empty / "pet_2015-2050.nc").write_bytes(b"x" * 5)
        # file extending BEYOND the target -> must survive
        beyond = work / "indices" / "M1" / "ssp245"
        beyond.mkdir(parents=True)
        (beyond / "spi_03_2015-2100.nc").write_bytes(b"x" * 10)
        (beyond / "spi_03_2015-2105.nc").write_bytes(b"x" * 5)

        run(work, "2015-2100", apply=True, only=None)

        t1 = not (good / "pr_2015-2050.nc").exists()
        t2 = (good / "pr_2015-2100.nc").exists()
        t3 = (good / "pr_1981-2014.nc").exists()
        t4 = (other / "tasmax_2015-2050.nc").exists()
        t5 = (empty / "pet_2015-2050.nc").exists()
        t6 = (beyond / "spi_03_2015-2105.nc").exists()

        print(f"T1 superseded deleted           : {t1}")
        print(f"T2 full-period preserved        : {t2}")
        print(f"T3 historical preserved         : {t3}")
        print(f"T4 dir without full file intact  : {t4}")
        print(f"T5 empty full-period -> refuse   : {t5}")
        print(f"T6 beyond-target span preserved  : {t6}")
        for name, ok in [("T1", t1), ("T2", t2), ("T3", t3), ("T4", t4),
                         ("T5", t5), ("T6", t6)]:
            if not ok:
                fails.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print(f"SELFTEST FAILED: {', '.join(fails)}")
        return 1
    print("SELFTEST PASSED (T1-T6)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--period", help="full target period, e.g. 2015-2100")
    ap.add_argument("--apply", action="store_true",
                    help="delete superseded files (default: dry run)")
    ap.add_argument("--stage", default=None,
                    choices=[s for s, _ in STAGE_ROOTS],
                    help="limit to one stage root (default: all)")
    ap.add_argument("--work-dir", default=None,
                    help="override work root (default: config paths.yaml)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.period:
        ap.error("--period is required (or use --selftest)")
    if not re.fullmatch(r"\d{4}-\d{4}", args.period):
        ap.error("--period must look like 2015-2100")

    if args.work_dir:
        work_root = Path(args.work_dir).resolve()
    else:
        import yaml
        paths = yaml.safe_load((HERE / "config" / "paths.yaml")
                               .read_text(encoding="utf-8"))
        work_root = (HERE / paths.get("work_root", "work")).resolve()
    if not work_root.exists():
        print(f"FATAL: work root not found: {work_root}")
        return 1
    return run(work_root, args.period, args.apply, args.stage)


if __name__ == "__main__":
    sys.exit(main())
