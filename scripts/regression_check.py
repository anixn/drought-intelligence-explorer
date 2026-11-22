#!/usr/bin/env python3
"""DIE v2.0 - numeric regression harness (task M1.9, docs/v2/02 M1.9).

Guards the era-B data contract and the derived numbers the UI serves against
accidental change during refactors (ducklab, converters, catalog, loaders).
Complements data-pipeline/selftest.py (which tests pipeline *semantics* on
synthetic worlds): this harness tests the *shipped data* itself.

What it snapshots (baseline JSON, blessed explicitly):
  1. sha256 of every era-B wide CSV and observed Parquet file
     - any byte drift in shipped data is caught; a legitimate monthly
       refresh re-blesses (see below)
  2. catalog.json structural fingerprint (variable ids, era keys, file count)
  3. per-variable CSV facts: districts, date columns, finite, empty
  4. seeded round-trip sample: 8 fixed cells per variable, parquet value
     must equal float32(csv value) exactly (the documented storage contract)
  5. numeric anchors computed with math.fsum (bit-identical across
     platforms/CPUs): national area-weighted mean per era-B indicator over
     1981-2020, and per-state finite counts/means for SPI-3
  6. national pre-aggregate fingerprint (_national_monthly.parquet)
  7. era A <-> era B cross-validation fingerprint (M6.6): file checksums,
     district counts, median r, mean bias, median seam SD (X7/M6.8) and
     overlap/monthly row counts
  8. reality-check artifact checksum (M10.7)

Usage:
  python scripts/regression_check.py            # compare against baseline
  python scripts/regression_check.py --bless    # re-bless after a legitimate
                                                # data refresh (prints a diff
                                                # first so the change is seen)

Exit 0 = baseline green; exit 1 = drift detected (details printed).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
from collections import OrderedDict
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "regression_baseline.json"
SEED = 20261103  # same constant family as v1.0 (moving-block bootstrap seed)

VARIABLES = OrderedDict([
    ("spi_01", "data/drought/spi_01.csv"), ("spi_03", "data/drought/spi_03.csv"),
    ("spi_06", "data/drought/spi_06.csv"), ("spi_12", "data/drought/spi_12.csv"),
    ("spei_01", "data/drought/spei_01.csv"), ("spei_03", "data/drought/spei_03.csv"),
    ("spei_06", "data/drought/spei_06.csv"), ("spei_12", "data/drought/spei_12.csv"),
    ("sma", "data/drought/soil_moisture.csv"), ("vci", "data/drought/vci.csv"),
])

WINDOW = ("1981-01", "2020-12")   # v1.0 reference period (C2: 1981-2020)


def sha256(path: Path) -> str:
    data = path.read_bytes()
    # Text artefacts must be LF: the baseline hashes bytes, git stores LF
    # (.gitattributes) and CI checks out LF, so a CRLF worktree file (Windows
    # text mode) would produce a platform-specific hash — exactly the drift this
    # harness reported on 2026-11-22. Fail loudly instead of blessing it.
    if path.suffix.lower() in {".json", ".csv", ".md", ".txt"} and b"\r\n" in data:
        raise SystemExit(
            f"CRLF line endings in {path}: writers must emit LF "
            f"(the baseline hashes bytes and CI checks out LF per .gitattributes)")
    return hashlib.sha256(data).hexdigest()


def f32(x: float) -> float:
    """Round a double through float32 - the parquet storage precision."""
    return struct.unpack("f", struct.pack("f", x))[0]


def load_registry() -> dict:
    """district_id -> (state_name, area_km2) from data/districts.csv."""
    out = {}
    with open(REPO / "data" / "districts.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["district_id"]] = (row["state_name"], float(row["area_km2"]))
    return out


def read_variable(var_id: str):
    """Wide CSV -> (dates, rows) where rows = [(district_id, [float|None])]."""
    path = REPO / VARIABLES[var_id]
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    dates = [c for c in header[3:] if c and c[0].isdigit()]
    out = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        vals = []
        for j in range(len(dates)):
            raw = r[3 + j].strip() if len(r) > 3 + j else ""
            vals.append(float(raw) if raw else None)
        out.append((r[0].strip(), vals))
    return dates, out


def parquet_file(var_id: str) -> Path:
    return REPO / "data" / "parquet" / "observed" / f"variable={var_id}" / "part-0.parquet"


def roundtrip_sample(var_id: str, dates: list, rows: list, registry: dict) -> list:
    """8 deterministic cells (seeded by variable id + SEED): parquet value
    must equal float32 of the CSV value, or both must be missing."""
    import random
    rng = random.Random(f"{SEED}:{var_id}")
    known = [r for r in rows if r[0] in registry]
    # read the parquet columns once per variable; to_pylist() decodes the
    # dictionary-encoded district ids (files are sorted by district_id, year,
    # month per the converter contract)
    tbl = pq.read_table(parquet_file(var_id),
                        columns=["district_id", "year", "month", "value"])
    ids = tbl.column("district_id").to_pylist()
    years = tbl.column("year").to_pylist()
    months = tbl.column("month").to_pylist()
    values = tbl.column("value").to_pylist()
    # (district, year, month) -> value
    lookup = {}
    for k in range(len(years)):
        lookup[(ids[k], years[k], months[k])] = values[k]
    cells = []
    for _ in range(8):
        did, vals = known[rng.randrange(len(known))]
        j = rng.randrange(len(dates))
        want_y, want_m = int(dates[j][:4]), int(dates[j][5:7])
        got = lookup.get((did, want_y, want_m))
        csv_val = vals[j]
        cells.append({
            "district": did, "date": dates[j], "csv": csv_val,
            "parquet": got,
            "match": (got is None and csv_val is None) or
                     (got is not None and csv_val is not None and got == f32(csv_val)),
        })
    return cells


def weighted_mean(rows: list, registry: dict, dates: list) -> float:
    """Area-weighted mean over finite district-months inside WINDOW.
    math.fsum -> bit-identical result on every platform."""
    num, den = [], []
    j_lo = dates.index(WINDOW[0]) if WINDOW[0] in dates else 0
    j_hi = dates.index(WINDOW[1]) if WINDOW[1] in dates else len(dates) - 1
    for did, vals in rows:
        reg = registry.get(did)
        if not reg:
            continue
        area = reg[1]
        for j in range(j_lo, j_hi + 1):
            v = vals[j]
            if v is not None and math.isfinite(v):
                num.append(v * area)
                den.append(area)
    return math.fsum(num) / math.fsum(den)


def compute() -> dict:
    registry = load_registry()

    out = OrderedDict()
    out["schema"] = "die-regression-baseline/1.0"
    out["seed"] = SEED
    out["window"] = list(WINDOW)

    # --- 1. checksums of shipped era-B data ------------------------------
    out["sha256"] = OrderedDict()
    for var_id, rel in VARIABLES.items():
        out["sha256"]["csv/" + var_id] = sha256(REPO / rel)
        out["sha256"]["parquet/" + var_id] = sha256(parquet_file(var_id))
    out["sha256"]["catalog.json"] = sha256(REPO / "data" / "parquet" / "catalog.json")
    reality = REPO / "data" / "reality_checks.json"
    if reality.exists():
        out["sha256"]["reality_checks.json"] = sha256(reality)
    national_path = REPO / "data" / "parquet" / "_national_monthly.parquet"
    if national_path.exists():
        out["sha256"]["national"] = sha256(national_path)

    # --- 2. catalog fingerprint ------------------------------------------
    cat = json.loads((REPO / "data" / "parquet" / "catalog.json").read_text(encoding="utf-8"))
    out["catalog"] = OrderedDict([
        ("version", cat.get("version")),
        ("variables", [v["id"] for v in cat.get("variables", [])]),
        ("eras", sorted((cat.get("eras") or {}).keys())),
        ("available_eras", sorted(k for k, e in (cat.get("eras") or {}).items() if e.get("available"))),
        ("file_count", sum(len(f) for v in cat.get("variables", [])
                           for f in (v.get("files") or {}).values())),
    ])

    # --- 3. per-variable CSV facts + 4. round-trip sample -----------------
    out["per_variable"] = OrderedDict()
    out["roundtrip"] = OrderedDict()
    for var_id in VARIABLES:
        dates, rows = read_variable(var_id)
        finite = sum(1 for _, vals in rows for v in vals if v is not None)
        empty = len(rows) * len(dates) - finite
        out["per_variable"][var_id] = OrderedDict([
            ("districts", len(rows)),
            ("date_cols", len(dates)),
            ("first_date", dates[0] if dates else None),
            ("last_date", dates[-1] if dates else None),
            ("finite", finite),
            ("empty", empty),
        ])
        out["roundtrip"][var_id] = roundtrip_sample(var_id, dates, rows, registry)

    # --- 5. numeric anchors ----------------------------------------------
    out["anchors"] = OrderedDict()
    for var_id in VARIABLES:
        dates, rows = read_variable(var_id)
        out["anchors"]["weighted_mean/" + var_id] = weighted_mean(rows, registry, dates)
    dates3, rows3 = read_variable("spi_03")
    by_state = {}
    for did, vals in rows3:
        reg = registry.get(did)
        if not reg:
            continue
        by_state.setdefault(reg[0], []).append((did, vals, reg[1]))
    state_block = OrderedDict()
    for state in sorted(by_state):
        members = by_state[state]
        finite = sum(1 for _, vals, _ in members for v in vals if v is not None)
        num, den = [], []
        j_lo = dates3.index(WINDOW[0])
        j_hi = dates3.index(WINDOW[1])
        for _, vals, area in members:
            for j in range(j_lo, j_hi + 1):
                v = vals[j]
                if v is not None and math.isfinite(v):
                    num.append(v * area)
                    den.append(area)
        state_block[state] = OrderedDict([
            ("districts", len(members)), ("finite", finite),
            ("weighted_mean", math.fsum(num) / math.fsum(den)),
        ])
    out["anchors"]["spi_03_by_state"] = state_block

    # --- 6. national pre-aggregate fingerprint (M1.10) --------------------
    if national_path.exists():
        nat_tbl = pq.read_table(national_path)
        nat_vars = nat_tbl.column("variable").to_pylist()
        nat_years = nat_tbl.column("year").to_pylist()
        nat_months = nat_tbl.column("month").to_pylist()
        nat_vals = nat_tbl.column("value").to_pylist()
        per_var = OrderedDict()
        for var_id in VARIABLES:
            ks = [k for k in range(len(nat_vars)) if nat_vars[k] == var_id]
            if not ks:
                continue
            num = []
            for k in ks:
                if (nat_years[k] * 100 + nat_months[k]) <= 202012:
                    if nat_vals[k] is not None and math.isfinite(nat_vals[k]):
                        num.append(nat_vals[k])
            per_var[var_id] = OrderedDict([
                ("rows", len(ks)),
                ("first", [nat_years[ks[0]], nat_months[ks[0]]]),
                ("last", [nat_years[ks[-1]], nat_months[ks[-1]]]),
                ("mean_1981_2020", math.fsum(num) / len(num) if num else None),
            ])
        out["national"] = per_var

    # --- 7. era A <-> era B cross-validation product (M6.6) ---------------
    cv_files = OrderedDict([
        ("overlap", "data/parquet/cross_validation/overlap_1981_2014.parquet"),
        ("per_district", "data/parquet/cross_validation/per_district_1981_2014.parquet"),
        ("monthly", "data/parquet/cross_validation/monthly_1981_2014.parquet"),
    ])
    if all((REPO / p).exists() for p in cv_files.values()):
        cv = OrderedDict()
        for key, rel in cv_files.items():
            cv["sha256/" + key] = sha256(REPO / rel)
        per = pq.read_table(REPO / cv_files["per_district"])
        dist_vars = per.column("variable").to_pylist()
        dist_r = per.column("r").to_pylist()
        dist_bias = per.column("bias").to_pylist()
        dist_sd = per.column("sd_diff").to_pylist()
        for var_id in ("spei_01", "spei_12"):
            rs = sorted(v for k, v in zip(dist_vars, dist_r)
                        if k == var_id and v is not None and math.isfinite(v))
            bs = [v for k, v in zip(dist_vars, dist_bias)
                  if k == var_id and v is not None and math.isfinite(v)]
            sds = sorted(v for k, v in zip(dist_vars, dist_sd)
                         if k == var_id and v is not None and math.isfinite(v))
            if not rs:
                continue
            mid = len(rs) // 2
            median_r = rs[mid] if len(rs) % 2 else (rs[mid - 1] + rs[mid]) / 2
            smid = len(sds) // 2
            median_sd = (sds[smid] if len(sds) % 2
                         else (sds[smid - 1] + sds[smid]) / 2)
            cv[var_id] = OrderedDict([
                ("districts", sum(1 for k in dist_vars if k == var_id)),
                ("median_r", median_r),
                ("mean_bias", math.fsum(bs) / len(bs)),
                ("median_sd_diff", median_sd),
            ])
        ov = pq.read_table(REPO / cv_files["overlap"], columns=["variable"])
        ov_vars = ov.column("variable").to_pylist()
        cv["overlap_rows"] = OrderedDict(
            (v, sum(1 for k in ov_vars if k == v))
            for v in ("spei_01", "spei_12"))
        mon = pq.read_table(REPO / cv_files["monthly"], columns=["variable"])
        mon_vars = mon.column("variable").to_pylist()
        cv["monthly_rows"] = OrderedDict(
            (v, sum(1 for k in mon_vars if k == v))
            for v in ("spei_01", "spei_12"))
        out["crossval"] = cv

    # --- 8. IMD benchmark artifact (M4.3/M4.4) ----------------------------
    imd_path = REPO / "data" / "imd_validation.json"
    if imd_path.exists():
        imd = json.loads(imd_path.read_text(encoding="utf-8"))
        out["imd"] = OrderedDict([
            ("sha256", sha256(imd_path)),
            ("period", imd.get("period")),
            ("indicators", OrderedDict(
                (i["label"], [round(i["r_median"], 4), round(i["bias"], 4),
                              round(i["state"], 4), i["districts"]])
                for i in imd.get("indicators", []))),
            ("trends", OrderedDict(
                (t["label"], [t["imd_fdr"], t["era_b_fdr"], t["both_fdr"]])
                for t in imd.get("trends", []))),
        ])
    return out


def flatten(obj, prefix=""):
    """Yield (path, value) leaves for comparison; dict/list containers are
    walked in fixed order."""
    if isinstance(obj, dict):
        for k in obj:
            yield from flatten(obj[k], prefix + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten(v, prefix + "/" + str(i))
    else:
        yield prefix, obj


def compare(old: dict, new: dict) -> list:
    problems = []
    old_leaves = dict(flatten(old))
    new_leaves = dict(flatten(new))
    for k in sorted(set(old_leaves) | set(new_leaves)):
        if k not in new_leaves:
            problems.append(f"REMOVED {k} = {old_leaves[k]!r}")
        elif k not in old_leaves:
            problems.append(f"ADDED   {k} = {new_leaves[k]!r}")
        else:
            o, n = old_leaves[k], new_leaves[k]
            if isinstance(o, bool) or isinstance(n, bool) or \
               isinstance(o, str) or isinstance(n, str):
                same = o == n
            else:
                same = (o == n) or (isinstance(o, float) and isinstance(n, float)
                                    and math.isclose(o, n, rel_tol=0, abs_tol=0))
            if not same:
                problems.append(f"CHANGED {k}: {o!r} -> {n!r}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="DIE numeric regression harness (M1.9)")
    ap.add_argument("--bless", action="store_true",
                    help="recompute and overwrite the baseline (after a "
                         "legitimate data refresh; review the diff it prints)")
    args = ap.parse_args()

    new = compute()
    problems = []
    if BASELINE.exists():
        old = json.loads(BASELINE.read_text(encoding="utf-8"))
        problems = compare(old, new)
    else:
        problems = ["no baseline yet - run with --bless to create one"]

    if args.bless:
        if problems:
            print(f"{len(problems)} drift item(s) being blessed:")
            for p in problems[:40]:
                print("  " + p)
            if len(problems) > 40:
                print(f"  ... and {len(problems) - 40} more")
        BASELINE.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"BLESSED -> {BASELINE} ({BASELINE.stat().st_size} bytes)")
        return 0

    if problems:
        print(f"REGRESSION HARNESS: {len(problems)} item(s) differ from baseline:")
        for p in problems[:40]:
            print("  " + p)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        print("If this drift is legitimate (e.g. monthly era-B refresh), "
              "review then re-run with --bless.")
        return 1
    n = len(dict(flatten(new)))
    print(f"REGRESSION HARNESS: PASS ({n} checked values, seed {SEED})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
