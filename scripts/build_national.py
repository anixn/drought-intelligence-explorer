#!/usr/bin/env python3
"""DIE v2.0 - national monthly pre-aggregate (task M1.10, docs/v2/03 section 1.3).

Builds data/parquet/_national_monthly.parquet: one row per (variable, year,
month) holding the AREA-WEIGHTED national mean - the v1.0 rule (Audit F3,
export_app.py lines 374-378): per month, weights = district area (km2, LAEA
registry), renormalised over districts with a finite value that month:

    nat[m] = sum(v_i * area_i, i finite at m) / sum(area_i, i finite at m)

Honesty rules:
  - months with ZERO finite values for a variable are ABSENT ROWS (never 0,
    never imputed - R10; the v1.0 verification code's 1e-9 guard produces 0
    for such months, which would be a fake value, e.g. VCI 0 = extreme
    drought, so the intent of the rule is NaN/absent and that is what ships)
  - sample size n_districts is stored per row (R10: every statistic reports
    its sample size)
  - values stored as float32 (store-wide contract); the build computes in
    float64 from the CSVs (the same float64 values the UI's CSV path loads)

Schema (long, store-consistent):
  variable dictionary<string>, year int16, month int8,
  value float32, n_districts int16 - zstd, dictionary-encoded

Verification (--verify): recomputes every cell with an INDEPENDENT
implementation (math.fsum, no numpy) and requires |parquet - fsum| <= 1e-6
(the M1.10 gate: matches the v1.0 area-weighted rule within 1e-6).

Usage:
  python scripts/build_national.py            # build + verify
  python scripts/build_national.py --verify   # verify existing file only
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "parquet" / "_national_monthly.parquet"
GATE = 1e-6

VARIABLES = OrderedDict([
    ("spi_01", "data/drought/spi_01.csv"), ("spi_03", "data/drought/spi_03.csv"),
    ("spi_06", "data/drought/spi_06.csv"), ("spi_12", "data/drought/spi_12.csv"),
    ("spei_01", "data/drought/spei_01.csv"), ("spei_03", "data/drought/spei_03.csv"),
    ("spei_06", "data/drought/spei_06.csv"), ("spei_12", "data/drought/spei_12.csv"),
    ("sma", "data/drought/soil_moisture.csv"), ("vci", "data/drought/vci.csv"),
])


def load_areas() -> dict:
    """district_id -> area_km2 (LAEA registry areas, the v1.0 weights)."""
    out = {}
    with open(REPO / "data" / "districts.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["district_id"]] = float(row["area_km2"])
    return out


def read_matrix(var_id: str):
    """Wide CSV -> (dates, ids, float64 matrix with NaN for empty)."""
    with open(REPO / VARIABLES[var_id], encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    dates = [c for c in header[3:] if c and c[0].isdigit()]
    ids, mat = [], []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        vals = np.full(len(dates), np.nan, dtype=np.float64)
        for j in range(len(dates)):
            raw = r[3 + j].strip() if len(r) > 3 + j else ""
            if raw:
                vals[j] = float(raw)
        ids.append(r[0].strip())
        mat.append(vals)
    return dates, ids, np.vstack(mat)


def build() -> None:
    areas = load_areas()
    order = [d for d in areas]                      # registry order = v1.0 order
    area_vec = np.array([areas[d] for d in order], dtype=np.float64)

    recs = []   # (variable, year, month, value, n_districts)
    stats = []
    for var_id in VARIABLES:
        dates, ids, mat = read_matrix(var_id)
        # align matrix rows to the registry areas (rows are keyed by id)
        pos = {d: k for k, d in enumerate(order)}
        aligned = np.full((len(order), mat.shape[1]), np.nan, dtype=np.float64)
        for k, did in enumerate(ids):
            if did in pos:
                aligned[pos[did]] = mat[k]
        finite = np.isfinite(aligned)
        w_area = area_vec[:, None] * finite                       # v1.0 rule
        num = np.nansum(np.where(finite, aligned, 0.0) * w_area, axis=0)
        den = w_area.sum(axis=0)
        n_cov = finite.sum(axis=0)
        written = 0
        cov_written = []
        for j, col in enumerate(dates):
            if den[j] <= 0.0:
                continue                                          # absent row
            y, m = int(col[:4]), int(col[5:7])
            v = num[j] / den[j]
            recs.append((var_id, y, m, np.float32(v), int(n_cov[j])))
            cov_written.append(int(n_cov[j]))
            written += 1
        stats.append((var_id, written, max(cov_written), min(cov_written)))

    table = pa.table({
        "variable": pa.array([r[0] for r in recs], type=pa.dictionary(pa.int32(), pa.string())),
        "year": pa.array([r[1] for r in recs], type=pa.int16()),
        "month": pa.array([r[2] for r in recs], type=pa.int8()),
        "value": pa.array([r[3] for r in recs], type=pa.float32()),
        "n_districts": pa.array([r[4] for r in recs], type=pa.int16()),
    })
    pq.write_table(table, OUT, compression="zstd", compression_level=19)
    print(f"Wrote {OUT.name} ({OUT.stat().st_size} bytes, {len(recs)} rows)")
    for var_id, written, nmax, nmin in stats:
        print(f"  {var_id:8s} {written:4d} monthly rows, coverage {nmin}-{nmax} districts")


def f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def verify() -> int:
    """Independent recomputation (math.fsum, no numpy) vs the shipped file."""
    areas = load_areas()
    tbl = pq.read_table(OUT)
    vars_in_file = tbl.column("variable").to_pylist()
    years = tbl.column("year").to_pylist()
    months = tbl.column("month").to_pylist()
    values = tbl.column("value").to_pylist()
    ns = tbl.column("n_districts").to_pylist()

    caches = {}
    max_diff = 0.0
    checked = 0
    failures = []
    for k in range(len(years)):
        var_id = vars_in_file[k]
        if var_id not in VARIABLES:
            failures.append(f"unknown variable in file: {var_id}")
            continue
        if var_id not in caches:
            dates, ids, mat = read_matrix(var_id)
            jmap = {c: j for j, c in enumerate(dates)}
            weights = []
            for did in ids:
                a = areas.get(did)
                if a is not None:
                    weights.append(a)
                else:
                    weights.append(0.0)
            caches[var_id] = (jmap, ids, mat, weights)
        jmap, ids, mat, weights = caches[var_id]
        col = f"{years[k]:04d}-{months[k]:02d}"
        j = jmap.get(col)
        if j is None:
            failures.append(f"{var_id} {col}: month not in source CSV window")
            continue
        num = []
        den = []
        n_finite = 0
        for i, did in enumerate(ids):
            v = mat[i][j]
            if v == v and math.isfinite(v):               # finite float64
                a = weights[i]
                num.append(v * a)
                den.append(a)
                n_finite += 1
        if not den:
            failures.append(f"{var_id} {col}: recomputation found no data but file has a row")
            continue
        ref = math.fsum(num) / math.fsum(den)
        got = values[k]
        diff = abs(f32(ref) - got)
        max_diff = max(max_diff, diff)
        checked += 1
        if ns[k] != n_finite:
            failures.append(f"{var_id} {col}: n_districts {ns[k]} != recomputed {n_finite}")
        if diff > GATE:
            failures.append(f"{var_id} {col}: |{got} - {ref:.9f}| = {diff:.3e} > {GATE}")

    # absent-row honesty: months with zero coverage must not be in the file
    for var_id in VARIABLES:
        dates, ids, mat = read_matrix(var_id)
        file_months = {(years[k], months[k]) for k in range(len(years)) if vars_in_file[k] == var_id}
        for j, col in enumerate(dates):
            n_finite = sum(1 for i in range(len(ids))
                           if mat[i][j] == mat[i][j] and math.isfinite(mat[i][j]))
            if n_finite == 0 and (int(col[:4]), int(col[5:7])) in file_months:
                failures.append(f"{var_id} {col}: zero-coverage month present in file (must be absent)")

    print(f"VERIFY: {checked} rows checked vs independent fsum recomputation; "
          f"max |diff| = {max_diff:.3e} (gate {GATE})")
    if failures:
        print(f"VERIFY: {len(failures)} FAILURE(S):")
        for f in failures[:20]:
            print("  " + f)
        return 1
    print("VERIFY: ALL PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="build/verify _national_monthly.parquet (M1.10)")
    ap.add_argument("--verify", action="store_true", help="verify the existing file only")
    args = ap.parse_args()
    if not args.verify:
        build()
    if not OUT.exists():
        print("no national file to verify - run without --verify first")
        return 1
    return verify()


if __name__ == "__main__":
    sys.exit(main())
