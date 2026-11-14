#!/usr/bin/env python3
"""DIE v2.0 - era B wide CSVs -> long Parquet store (tasks M1.3-M1.4).

Converts the ten released v1.0 wide CSVs in data/drought/ to the long-format
Parquet store per docs/v2/03 sections 1.2 and 8.1:

  data/parquet/observed/variable=<id>/part-0.parquet

Contract (locked - do not deviate without a register entry):
  * schema: district_id (string, dictionary), year (int16), month (int8),
    value (float32)
  * missing cells are ABSENT ROWS, never nulls and never imputed (R10)
  * compression zstd, dictionary encoding
  * row groups aligned to district boundaries, 60 districts per group
    (measured prototype finding, AGENTS.md section 4)
  * variable ids: spi_01|03|06|12, spei_01|03|06|12, sma (soil_moisture.csv),
    vci (vci.csv)
  * row order: CSV registry order (district-major), months ascending - NOT
    re-sorted, so row groups follow the v1.0 registry order deterministically

Determinism: no wall-clock values are embedded; per-file parquet key/value
metadata records the source CSV name + SHA-256 so re-runs produce identical
bytes and stable manifest checksums.

Usage:
  python convert_to_parquet.py                 # convert all variables
  python convert_to_parquet.py --verify 5      # round-trip check (M1.4):
                                               # >= N random cells per
                                               # variable vs source CSV
  python convert_to_parquet.py --convert --verify 5

Monthly refresh (--incremental, task M3.1) will rewrite affected variable
files after run.py monthly updates the CSVs; conversion itself stays a full
rewrite per variable (small files - rewrite is safer than append).
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
CSV_DIR = REPO / "data" / "drought"
OUT_DIR = REPO / "data" / "parquet" / "observed"

# Locked architecture facts (AGENTS.md section 4, docs/v2/03 sections 1.2/8.1)
ROW_GROUP_DISTRICTS = 60
ZSTD_LEVEL = 19          # measured: 632.7 vs 647.4 KB worst file vs default level; byte_stream_split gave no further gain (2026-11-14 tests). Max file ~633 KB sits ~5% over the "~600 KB" soft target - the 60-district row-group contract (locked) costs ~15% vs single-group writes and wins on read locality; total 5.54 MB is far inside the 30 MB gate.
DISTRICTS_EXPECTED = 724
SEED = 20261103          # project seed convention (AGENTS.md section 7)
SOURCE_MAP = {           # csv stem -> variable id (docs/v2/03 section 1.2)
    "spi_01": "spi_01", "spi_03": "spi_03", "spi_06": "spi_06", "spi_12": "spi_12",
    "spei_01": "spei_01", "spei_03": "spei_03", "spei_06": "spei_06", "spei_12": "spei_12",
    "soil_moisture": "sma", "vci": "vci",
}

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
SCHEMA = pa.schema([
    ("district_id", pa.dictionary(pa.int32(), pa.string())),
    ("year", pa.int16()),
    ("month", pa.int8()),
    ("value", pa.float32()),
])


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_one(csv_path: Path, var_id: str) -> dict:
    """Wide CSV -> long Parquet for one variable. Returns stats dict."""
    df = pd.read_csv(csv_path, dtype={"district_id": "string",
                                      "district_name": "string",
                                      "state_name": "string"})
    month_cols = [c for c in df.columns if MONTH_RE.match(c)]
    if not month_cols:
        raise ValueError(f"{csv_path.name}: no YYYY-MM columns found")
    bad = [c for c in df.columns if c not in ("district_id", "district_name", "state_name")
           and not MONTH_RE.match(c)]
    if bad:
        raise ValueError(f"{csv_path.name}: unexpected non-month columns {bad}")
    if df["district_id"].isna().any() or df["district_id"].duplicated().any():
        raise ValueError(f"{csv_path.name}: district_id missing or duplicated")

    n_districts = len(df)
    long = df.melt(id_vars=["district_id"], value_vars=month_cols,
                   var_name="ym", value_name="value")
    # absent rows: drop NaN (missing cells are absent, never null - R10)
    long = long.dropna(subset=["value"])
    ym = long["ym"].str.extract(r"(\d{4})-(\d{2})")
    year = ym[0].astype(np.int16).to_numpy()
    month = ym[1].astype(np.int8).to_numpy()
    value = long["value"].to_numpy(dtype=np.float64).astype(np.float32)

    # Keep CSV order (district-major, months ascending); assert it is intact.
    d_idx = long.index.to_numpy()  # melt preserves (row, col) order: row-major
    if not np.all(np.diff(d_idx) >= 0):
        raise AssertionError("melt order broken - investigate before writing")

    table = pa.Table.from_arrays(
        [pa.array(long["district_id"].to_numpy(), type=SCHEMA.field(0).type),
         pa.array(year, type=pa.int16()),
         pa.array(month, type=pa.int8()),
         pa.array(value, type=pa.float32())],
        schema=SCHEMA,
    )
    table = table.replace_schema_metadata({
        b"source_csv": csv_path.name.encode(),
        b"source_sha256": sha256_of(csv_path).encode(),
        b"variable_id": var_id.encode(),
        b"era": b"observed",
        b"rows": str(table.num_rows).encode(),
        b"produced_by": b"scripts/convert_to_parquet.py (task M1.3, docs/v2/03 s1.2/s8.1)",
    })

    # Row groups aligned to district boundaries: 60 districts per group.
    # Reindex over the full registry order so an all-absent district (possible
    # in principle) still occupies its slot with 0 rows.
    counts = (long.groupby("district_id", sort=False).size()
              .reindex(df["district_id"].to_numpy()).fillna(0).astype("int64")
              .to_numpy())
    if len(counts) != n_districts:
        raise AssertionError("district row-count decomposition failed")
    out_dir = OUT_DIR / f"variable={var_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.parquet"
    with pq.ParquetWriter(out_path, SCHEMA, compression="zstd",
                          compression_level=ZSTD_LEVEL,
                          use_dictionary=True) as writer:
        start = 0           # row index
        d_start = 0         # district index
        rows_per_district = counts
        cum = np.concatenate([[0], np.cumsum(rows_per_district)])
        while d_start < len(counts):
            d_end = min(d_start + ROW_GROUP_DISTRICTS, len(counts))
            r0, r1 = int(cum[d_start]), int(cum[d_end])
            writer.write_table(table.slice(r0, r1 - r0))
            d_start = d_end
    size = out_path.stat().st_size
    return {"var": var_id, "csv": csv_path.name, "rows": int(table.num_rows),
            "districts": int(n_districts), "months": len(month_cols),
            "present": int(table.num_rows), "cells": int(n_districts * len(month_cols)),
            "bytes": size, "groups": (len(counts) + ROW_GROUP_DISTRICTS - 1) // ROW_GROUP_DISTRICTS}


def verify_one(var_id: str, csv_path: Path, n_cells: int, rng: random.Random) -> dict:
    """Round-trip check: random cells stored in Parquet must equal the CSV cell
    parsed to float32 (exact at the contract dtype - M1.4 gate)."""
    df = pd.read_csv(csv_path, dtype={"district_id": "string"})
    month_cols = [c for c in df.columns if MONTH_RE.match(c)]
    pq_file = pq.ParquetFile(OUT_DIR / f"variable={var_id}" / "part-0.parquet")
    stored = pq_file.read().to_pandas()  # small enough (single variable)
    key = {(d, y, m): v for d, y, m, v in zip(stored["district_id"], stored["year"], stored["month"], stored["value"])}

    checked = mismatched = absent_confirmed = 0
    max_abs = 0.0
    for _ in range(n_cells):
        r = rng.randrange(len(df))
        c = month_cols[rng.randrange(len(month_cols))]
        text = str(df.at[r, c]).strip()
        cell_is_present = text not in ("", "nan", "None", "NaN")
        y, m = int(c[:4]), int(c[5:7])
        hit = key.get((df.at[r, "district_id"], y, m))
        if cell_is_present:
            want = np.float32(float(text))
            if hit is None or hit != want or (hit is not None and np.isnan(float(hit))):
                mismatched += 1
                print(f"  MISMATCH {var_id} {df.at[r, 'district_id']} {c}: csv={text} parquet={hit}")
            else:
                max_abs = max(max_abs, abs(float(hit) - float(text)))
            checked += 1
        else:
            if hit is not None:
                mismatched += 1
                print(f"  PHANTOM {var_id} {df.at[r, 'district_id']} {c}: csv empty, parquet={hit}")
            else:
                absent_confirmed += 1
    return {"var": var_id, "checked": checked, "mismatch": mismatched,
            "absent_confirmed": absent_confirmed, "max_abs_diff_vs_text": max_abs}


def main() -> int:
    ap = argparse.ArgumentParser(description="era B wide CSVs -> long Parquet (M1.3/M1.4)")
    ap.add_argument("--convert", action="store_true", help="run the conversion (default if no other mode given)")
    ap.add_argument("--verify", type=int, metavar="N", help="round-trip check with N random cells per variable (M1.4)")
    args = ap.parse_args()
    if not args.convert and args.verify is None:
        args.convert = True

    ok = True
    if args.convert:
        print(f"Converting {len(SOURCE_MAP)} variables -> {OUT_DIR}")
        total_bytes = 0
        for stem, var_id in SOURCE_MAP.items():
            csv_path = CSV_DIR / f"{stem}.csv"
            if not csv_path.exists():
                print(f"MISSING SOURCE: {csv_path}")
                ok = False
                continue
            s = convert_one(csv_path, var_id)
            total_bytes += s["bytes"]
            flag = "OK " if s["bytes"] <= 600 * 1024 else "BIG"
            print(f"  [{flag}] {s['var']:<8} rows={s['rows']:>7,} of {s['cells']:>7,} cells "
                  f"({s['districts']} districts x {s['months']} months) "
                  f"groups={s['groups']:>2}  size={s['bytes'] / 1024:>7.1f} KB  src={s['csv']}")
        print(f"TOTAL: {total_bytes / 1024 / 1024:.2f} MB "
              f"({'WITHIN' if total_bytes <= 30 * 1024 * 1024 else 'OVER'} the ~30 MB era B gate)")

    if args.verify is not None:
        if args.verify < 5:
            print("--verify N must be >= 5 (M1.4 gate)")
            return 2
        print(f"Round-trip verification: {args.verify} random cells per variable (seed {SEED})")
        rng = random.Random(SEED)
        worst = 0.0
        for stem, var_id in SOURCE_MAP.items():
            v = verify_one(var_id, CSV_DIR / f"{stem}.csv", args.verify, rng)
            worst = max(worst, v["max_abs_diff_vs_text"])
            status = "PASS" if v["mismatch"] == 0 else "FAIL"
            ok = ok and v["mismatch"] == 0
            print(f"  [{status}] {v['var']:<8} present-cells checked={v['checked']} "
                  f"absent-confirmed={v['absent_confirmed']} mismatches={v['mismatch']} "
                  f"max_abs_diff={v['max_abs_diff_vs_text']:.2e}")
        print(f"Worst |parquet - csv-text| across checks: {worst:.2e} (float32 quantisation ~1e-7 expected)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
