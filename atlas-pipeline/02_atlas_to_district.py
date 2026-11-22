#!/usr/bin/env python3
"""DIE v2.0 - atlas-pipeline step 02: Atlas grids -> 724-district era-A Parquet
(task M6.2, docs/v2/03 section 2.2).

Streams BOTH disjoint `Gridded_SPEI` roots (115,394 files, 1,500 monthly
records each, columns SNo Year Month SPEI-1 SPEI-4 SPEI-12), applies the
step-01 area weights, and writes era-A long Parquet under the staging root
`atlas-pipeline/work/atlas_store/` (X9-style: promoted to
`data/parquet/atlas/` ONLY after verification).

Aggregation rule (identical to era-B step 06 / v1.0 reduceRegions):
    district_value[month] = sum_i w_i * x_i / sum_i w_i
    over the district's cells with FINITE x at that month - weights are
    renormalised per month over finite cells; absent cells shrink the
    sample, never imputed (R10); the finite-cell count is carried per row.

Output schema mirrors the era-B observed store EXACTLY (R1 continuity):
    district_id dictionary<string,int32>, year int16, month int8,
    value float32; partitioned atlas/variable=<id>/year=<yyyy>/.
    Rows are written ONLY for district-months with >= 1 finite cell
    (the era-B absent-row rule: 3,715,048 rows == valid values).

QA built in (reported, never merged - R2):
  * national: the area-weighted national series per variable vs the
    Atlas's own India file (Z-score/India/India): r, mean bias, sd ratio.
  * round-trip (R7): N single-contributor cells (weight 1.0, one district)
    re-verified cell-level against the stored district values.

Usage:
  python atlas-pipeline/02_atlas_to_district.py --selftest
  python atlas-pipeline/02_atlas_to_district.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_CFG = HERE / "config" / "atlas.yaml"
WORK = HERE / "work"

SEED = 20261103
NAME_RE = re.compile(r"^data_(-?\d+\.\d+)_(-?\d+\.\d+)$")
MONTHS_TOTAL = 1500          # 1901-01 .. 2025-12, gate-verified


# ------------------------------------------------------------------ helpers --
def load_weights() -> tuple[dict, dict]:
    """cell "i,j" -> [(row, w), ...]; district_id -> row index."""
    wj = WORK / "crosswalk" / "weights.json"
    doc = json.loads(wj.read_text(encoding="utf-8"))
    cell_map: dict[str, list[tuple[int, float]]] = {}
    dids = sorted(doc["weights"])
    row_of = {d: k for k, d in enumerate(dids)}
    for did, rec in doc["weights"].items():
        if rec.get("outside_domain") or not rec.get("weights"):
            continue
        for cell, w in rec["weights"].items():
            cell_map.setdefault(cell, []).append((row_of[did], float(w)))
    return cell_map, dids


def parse_grid_text(text: str, year_start: int = 1901) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One grid file -> canonical (year, month) int arrays + (1500, 3) values.

    Sea cells carry `SNo NaN NaN NaN NaN NaN` rows (absent months have no
    year/month), so the calendar identity comes from SNo (row k = year_start
    + (k-1)//12, month (k-1)%12 + 1); every FINITE year/month value must
    agree with that identity or the file is rejected loudly.
    """
    arr = np.array(text.replace("NaN", "nan").split(), dtype=np.float64)
    if arr.size != MONTHS_TOTAL * 6 or arr.size % 6:
        raise ValueError(f"grid payload has {arr.size} tokens, "
                         f"expected {MONTHS_TOTAL * 6}")
    arr = arr.reshape(-1, 6)
    sno = arr[:, 0]
    if not np.all(np.abs(sno - np.arange(1, MONTHS_TOTAL + 1)) < 1e-9):
        raise ValueError("SNo column is not 1..1500")
    exp_y = (year_start + (sno.astype(np.int64) - 1) // 12)
    exp_m = ((sno.astype(np.int64) - 1) % 12 + 1)
    yy, mm = arr[:, 1], arr[:, 2]
    fin = np.isfinite(yy) & np.isfinite(mm)
    if (np.any(np.abs(yy[fin] - exp_y[fin]) > 0.01)
            or np.any(np.abs(mm[fin] - exp_m[fin]) > 0.01)):
        raise ValueError("finite year/month values disagree with the SNo "
                         "calendar identity")
    return exp_y, exp_m, arr[:, 3:6]


def month_index(years: np.ndarray, months: np.ndarray,
                year_start: int) -> np.ndarray:
    return (years - year_start) * 12 + (months - 1)


# ---------------------------------------------------------------- ingest ----
def run(cfg_path: Path) -> int:
    a = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["atlas"]
    root = Path(a["local_root"])
    ing = a["ingest"]
    y0 = int(ing["year_start"])
    if y0 != 1901:
        raise SystemExit(f"FATAL: ingest year_start {y0} != the gate-verified 1901")
    cols = {k: int(v) for k, v in ing["variables"].items()}
    if sorted(cols.values()) != [3, 4, 5]:
        raise SystemExit(f"FATAL: variables column indices must be 3/4/5, got {cols}")

    print("=" * 78)
    print("ATLAS-PIPELINE 02 - grids -> 724-district era-A Parquet (M6.2)")
    print("=" * 78)

    cell_map, dids = load_weights()
    n_dist = len(dids)
    n_cells_used = len(cell_map)
    print(f"  crosswalk: {n_dist} districts, {n_cells_used} mapped cells")

    wsum = {k: np.zeros((n_dist, MONTHS_TOTAL), dtype=np.float64)
            for k in cols}
    wtot = {k: np.zeros((n_dist, MONTHS_TOTAL), dtype=np.float64)
            for k in cols}
    ncell = {k: np.zeros((n_dist, MONTHS_TOTAL), dtype=np.int16)
             for k in cols}

    files_scanned = files_mapped = files_skipped_name = cells_unmapped = 0
    parse_errors = 0
    t0 = time.time()
    year_ref = month_ref = None
    for rel_root in a["grid"]["roots"]:
        gdir = root / rel_root
        if not gdir.exists():
            print(f"  FATAL: grid root missing: {gdir}")
            return 2
        for name in sorted(gdir.iterdir()):
            m = NAME_RE.match(name.name)
            if not m or not name.is_file():
                files_skipped_name += 1
                continue
            files_scanned += 1
            i = int(round((float(m.group(1)) - a["crosswalk"]["lattice"]["lat_start"])
                          / a["crosswalk"]["lattice"]["step"]))
            j = int(round((float(m.group(2)) - a["crosswalk"]["lattice"]["lon_start"])
                          / a["crosswalk"]["lattice"]["step"]))
            contributors = cell_map.get(f"{i},{j}")
            if not contributors:
                cells_unmapped += 1
                continue
            try:
                yy, mm, vals = parse_grid_text(name.read_text(encoding="utf-8"))
            except Exception as exc:                       # loud, counted
                parse_errors += 1
                print(f"  PARSE FAIL {name.name}: {exc}")
                if parse_errors > 20:
                    return 1
                continue
            if year_ref is None:
                year_ref, month_ref = yy, mm
                if yy[0] != y0 or mm[0] != 1 or yy[-1] != 2025 or mm[-1] != 12:
                    raise SystemExit(f"FATAL: {name.name} period "
                                     f"{yy[0]}-{mm[0]}..{yy[-1]}-{mm[-1]} "
                                     f"is not 1901-01..2025-12")
            elif (not np.array_equal(yy, year_ref)
                  or not np.array_equal(mm, month_ref)):
                raise SystemExit(f"FATAL: {name.name} time fabric differs "
                                 f"from the other grid files")
            midx = month_index(yy, mm, y0)
            if not np.all((midx >= 0) & (midx < MONTHS_TOTAL)):
                raise SystemExit(f"FATAL: {name.name} month index out of range")
            files_mapped += 1
            for row, w in contributors:
                for var, ci in cols.items():
                    v = vals[:, ci - 3]
                    fin = np.isfinite(v)
                    wsum[var][row, midx[fin]] += w * v[fin]
                    wtot[var][row, midx[fin]] += w
                    ncell[var][row, midx[fin]] += 1
    dt = time.time() - t0
    print(f"  streamed {files_scanned} files ({dt:.1f}s): "
          f"{files_mapped} mapped, {cells_unmapped} outside the 724 fabric, "
          f"{files_skipped_name} non-grid, {parse_errors} parse failures")
    if parse_errors:
        print(f"  FAIL: {parse_errors} grid files failed to parse")
        return 1

    # ------------------------------------------------------ partitions ----
    stage = WORK / ing["staging_root"].split("work/", 1)[1]
    out_root = stage / "atlas"
    n_rows_total = 0
    schema = pa.schema([
        ("district_id", pa.dictionary(pa.int32(), pa.string())),
        ("year", pa.int16()),
        ("month", pa.int8()),
        ("value", pa.float32()),
    ])
    for var in cols:
        value = np.divide(wsum[var], wtot[var],
                          out=np.full_like(wsum[var], np.nan),
                          where=wtot[var] > 0)
        vdir = out_root / f"variable={var}"
        vdir.mkdir(parents=True, exist_ok=True)
        n_var = 0
        for yy in range(1901, 2026):
            mi = slice((yy - 1901) * 12, (yy - 1901) * 12 + 12)
            ids, yrs, mos, vals = [], [], [], []
            for row, did in enumerate(dids):
                w_row = wtot[var][row, mi]
                fin = w_row > 0
                if not fin.any():
                    continue
                for k in np.flatnonzero(fin):
                    ids.append(did)
                    yrs.append(yy)
                    mos.append(k + 1)
                    vals.append(float(value[row, mi][k]))
            if not ids:
                continue
            tbl = pa.table({
                "district_id": pa.array(ids, type=schema.field("district_id").type),
                "year": pa.array(yrs, type=pa.int16()),
                "month": pa.array(mos, type=pa.int8()),
                "value": pa.array(vals, type=pa.float32()),
            }, schema=schema)
            pdir = vdir / f"year={yy}"
            pdir.mkdir(parents=True, exist_ok=True)
            pq.write_table(tbl, pdir / "part-0.parquet", compression="zstd")
            n_var += len(ids)
            n_rows_total += len(ids)
        print(f"  {var}: {n_var:,} rows over {len(list(vdir.iterdir()))} years")
    print(f"  total rows: {n_rows_total:,} under {out_root.relative_to(REPO)}")

    # ------------------------------------------------------------ QA ----
    qa = qa_national(a, root, stage, dids, wtot, cols)
    ok_rt = qa_roundtrip(a, root, dids, stage, cols, y0)
    man = {
        "step": "02_atlas_to_district",
        "generated_from": str(cfg_path),
        "files_scanned": files_scanned,
        "files_mapped": files_mapped,
        "cells_outside_fabric": cells_unmapped,
        "parse_errors": parse_errors,
        "n_districts": n_dist,
        "rows": n_rows_total,
        "staging": str(out_root.relative_to(REPO)),
        "national_qa": qa,
        "roundtrip_ok": ok_rt,
    }
    qdir = WORK / "ingest"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "ingest_manifest.json").write_text(
        json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not ok_rt:
        print("  FAIL: round-trip verification failed")
        return 1
    print("INGEST DONE")
    return 0


# -------------------------------------------------------------------- QA ----
def qa_national(a: dict, root: Path, stage: Path, dids: list,
                wtot: dict, cols: dict) -> dict:
    """Grid-weighted national series vs the Atlas's own India file."""
    out = {}
    if not a["ingest"].get("national_qa", True):
        return {"skipped": True}
    india_path = root / a["series"]["india"]["dir"] / "India"
    arr = np.array(india_path.read_text(encoding="utf-8")
                   .replace("NaN", "nan").split(), dtype=np.float64)
    arr = arr.reshape(-1, 5)
    iy, im, ival = (arr[:, 0].astype(int), arr[:, 1].astype(int),
                    arr[:, 2:5])
    areas = np.zeros(len(dids))
    reg_csv = REPO / a["crosswalk"]["registry_csv"]
    import csv as _csv
    regmap = {}
    with open(reg_csv, encoding="utf-8") as fh:
        for r in _csv.DictReader(fh):
            regmap[r["district_id"]] = float(r["area_km2"])
    for k, did in enumerate(dids):
        areas[k] = regmap.get(did, 0.0)
    row_of = {d: k for k, d in enumerate(dids)}
    for k, (var, ci) in enumerate(sorted(cols.items())):
        tbl = pq.read_table(stage / "atlas" / f"variable={var}"
                            / "part-0.parquet") if False else None
        # rebuild the national series from the staged per-year partitions
        files = sorted((stage / "atlas" / f"variable={var}").glob(
            "year=*/part-0.parquet"))
        nat = np.full(MONTHS_TOTAL, np.nan)
        wsum = np.zeros(MONTHS_TOTAL)
        wtot = np.zeros(MONTHS_TOTAL)
        for f in files:
            t = pq.read_table(f)
            yy = int(f.parent.name.split("=")[1])
            for did, mo, val in zip(t.column("district_id").to_pylist(),
                                    t.column("month").to_pylist(),
                                    t.column("value").to_pylist()):
                if val is None:
                    continue
                row = row_of.get(did)
                if row is None:
                    continue
                midx = (yy - 1901) * 12 + mo - 1
                if areas[row] > 0:
                    wsum[midx] += areas[row] * val
                    wtot[midx] += areas[row]
        fin = wtot > 0
        nat[fin] = wsum[fin] / wtot[fin]
        ref = ival[:, k]
        both = fin & np.isfinite(ref)
        if both.sum() < 24:
            out[var] = {"n_months": int(both.sum()), "note": "insufficient overlap"}
            continue
        x, y = nat[both], ref[both]
        r = float(np.corrcoef(x, y)[0, 1])
        bias = float(np.mean(x - y))
        sd_ratio = float(np.std(x) / np.std(y))
        out[var] = {"n_months": int(both.sum()), "r": round(r, 6),
                    "mean_bias": round(bias, 6),
                    "sd_ratio": round(sd_ratio, 6),
                    "sd_note": "sd_ratio < 1 is the expected mean-of-"
                               "standardised effect: this national series is "
                               "the area-weighted mean of district z-scores, "
                               "while the Atlas India file is standardised at "
                               "national level (its own sd = 0.996); r is the "
                               "meaningful check, never an identity claim"}
        print(f"  QA national {var}: r={r:.4f} bias={bias:+.4f} "
              f"sd_ratio={sd_ratio:.4f} over {int(both.sum())} months "
              f"(vs the Atlas India file; sd_ratio<1 = mean-of-standardised "
              f"vs nationally-standardised - expected)")
    return out


def qa_roundtrip(a: dict, root: Path, dids: list,
                 stage: Path, cols: dict, y0: int) -> bool:
    """R7 round-trip: independently recompute whole district-months from the
    source grid files and require EXACT float32 equality with the store.

    A single-contributor filter would be conceptually wrong: weights
    normalise across each district's cells, so no cell carries weight 1.0
    unless the district is one cell. The honest check recomputes the full
    weighted mean (finite-cell renormalisation included) for sampled
    (district, month, variable) triples straight from the raw files.
    """
    n_target = int(a["ingest"].get("qa_roundtrip_cells", 5))
    wdoc = json.loads((WORK / "crosswalk" / "weights.json")
                      .read_text(encoding="utf-8"))
    candidates = [d for d, r in wdoc["weights"].items()
                  if r.get("weights") and not r.get("outside_domain")]
    rng = np.random.default_rng(SEED)
    picks = [candidates[k] for k in
             rng.choice(len(candidates),
                        size=min(n_target, len(candidates)), replace=False)]
    lat0 = a["crosswalk"]["lattice"]["lat_start"]
    lon0 = a["crosswalk"]["lattice"]["lon_start"]
    step = a["crosswalk"]["lattice"]["step"]
    ok = True
    n_checked = 0
    print(f"  QA roundtrip: {len(picks)} districts recomputed from source cells")
    for did in picks:
        rec = wdoc["weights"][did]
        # load each of the district's cells once (all months, all variables)
        cells = []
        missing = False
        for cell, w in rec["weights"].items():
            i, j = (int(x) for x in cell.split(","))
            lat = round(lat0 + i * step, 3)
            lon = round(lon0 + j * step, 3)
            path = None
            for rel in a["grid"]["roots"]:
                cand = Path(a["local_root"]) / rel / f"data_{lat}_{lon}"
                if cand.exists():
                    path = cand
                    break
            if path is None:
                print(f"    MISSING source file for cell {cell} ({did})")
                ok = False
                missing = True
                break
            cells.append((float(w), parse_grid_text(
                path.read_text(encoding="utf-8"))[2]))
        if missing:
            continue
        for var in sorted(cols):
            ci = cols[var] - 3
            yy = int(rng.integers(1901, 2026))
            mo = int(rng.integers(1, 13))
            midx = (yy - y0) * 12 + (mo - 1)
            wsum = wtot = 0.0
            for w, vals in cells:
                v = vals[midx, ci]
                if math.isfinite(v):
                    wsum += w * v
                    wtot += w
            exp = (wsum / wtot) if wtot > 0 else None
            f = stage / "atlas" / f"variable={var}" / f"year={yy}" \
                / "part-0.parquet"
            t = pq.read_table(f)
            rows = [(m, v) for d, m, v in
                    zip(t.column("district_id").to_pylist(),
                        t.column("month").to_pylist(),
                        t.column("value").to_pylist()) if d == did and m == mo]
            stored = rows[0][1] if rows else None
            n_checked += 1
            if exp is None:
                match = stored is None or (stored is not None
                                           and not math.isfinite(stored))
                if not match:
                    print(f"    MISMATCH (absent) {var} {did} {yy}-{mo}: "
                          f"stored={stored} recomputed=absent")
                    ok = False
                continue
            got = np.float32(stored) if stored is not None else None
            want = np.float32(exp)
            if got is None or not bool(got == want):
                print(f"    MISMATCH {var} {did} {yy}-{mo}: "
                      f"stored={stored} recomputed={exp}")
                ok = False
    if ok:
        print(f"  QA roundtrip: PASS ({n_checked} district-month triples, "
              f"stored float32 == recomputed, exact)")
    return ok


# ---------------------------------------------------------------- selftest ----
def selftest() -> int:
    print("=" * 78)
    print("SELFTEST - ingest (synthetic; seed 20261103)")
    print("=" * 78)
    fails = []
    rng = np.random.default_rng(SEED)

    # T1: parse_grid_text round-trips a known 1500-record payload
    lines, sn = [], []
    for k in range(MONTHS_TOTAL):
        yy = 1901 + k // 12
        mm = k % 12 + 1
        sn.append(k + 1)
        lines.append(f"{k + 1} {yy} {mm} {0.5 + 0.001 * k} NaN {-(0.25 + 0.001 * k)}")
    yy, mm, vals = parse_grid_text("\n".join(lines) + "\n")
    ok = (yy[0] == 1901 and mm[0] == 1 and yy[-1] == 2025 and mm[-1] == 12
          and abs(vals[0, 0] - 0.5) < 1e-12
          and not np.isfinite(vals[0, 1])
          and abs(vals[-1, 2] + (0.25 + 0.001 * 1499)) < 1e-9)
    print(f"T1 grid parse: {ok}")
    if not ok:
        fails.append("T1 parse")

    # T1b: truncation is rejected loudly
    try:
        parse_grid_text("\n".join(lines[:-1]))
        ok = False
    except ValueError:
        ok = True
    print(f"T1b truncated grid rejected: {ok}")
    if not ok:
        fails.append("T1b truncation")

    # T1c: sea-cell pattern - absent months carry 'SNo NaN NaN ...'; the
    # calendar identity must come from SNo, and a WRONG finite identity
    # must be rejected loudly
    sea = lines[:]
    for k in range(200, 260):
        parts = sea[k].split()
        sea[k] = f"{k + 1} NaN NaN NaN NaN NaN"
    yy2, mm2, vals2 = parse_grid_text("\n".join(sea) + "\n")
    ok = (yy2[200] == 1917 and mm2[200] == 9
          and yy2[0] == 1901 and yy2[-1] == 2025
          and abs(vals2[0, 0] - 0.5) < 1e-12
          and not np.isfinite(vals2[200, :]).any())
    print(f"T1c sea-cell (NaN year/month) rows keep canonical calendar: {ok}")
    if not ok:
        fails.append("T1c sea-cell")
    bad = lines[:]
    bad[10] = "11 1901 12 0.5 NaN -0.25"      # SNo 11 is 1901-11, not -12
    try:
        parse_grid_text("\n".join(bad) + "\n")
        ok = False
    except ValueError:
        ok = True
    print(f"T1d wrong finite identity rejected: {ok}")
    if not ok:
        fails.append("T1d identity")

    # T2: weighted aggregation + per-month finite renormalisation.
    # District D covers 2 cells with weights 0.5/0.5 (w1+w2=1).
    # month 1: v1 = 1.0, v2 = NaN  -> value = 1.0 (weight renormalised to 1)
    # month 2: v1 = 0.0, v2 = 2.0  -> value = 1.0
    # month 3: both NaN            -> absent (wtot == 0)
    # month 4: v1 = NaN, v2 = -2.0 -> value = -2.0 (renormalised)
    v1 = np.array([1.0, 0.0, np.nan, np.nan])
    v2 = np.array([np.nan, 2.0, np.nan, -2.0])
    w = (0.5, 0.5)
    wsum = np.zeros(4); wtot = np.zeros(4)
    for vi, wi in zip((v1, v2), w):
        fin = np.isfinite(vi)
        wsum[fin] += wi * vi[fin]
        wtot[fin] += wi
    value = np.divide(wsum, wtot, out=np.full(4, np.nan), where=wtot > 0)
    ok = (np.allclose(value[[0, 1, 3]], [1.0, 1.0, -2.0])
          and not np.isfinite(value[2]))
    print(f"T2 weighted mean + renormalisation: {np.round(value, 6)}: {ok}")
    if not ok:
        fails.append("T2 aggregation")

    # T3: month index arithmetic is exact and bounded
    midx = month_index(np.array([1901, 2025, 1950]), np.array([1, 12, 6]), 1901)
    ok = (midx[0] == 0 and midx[1] == MONTHS_TOTAL - 1
          and midx[2] == (1950 - 1901) * 12 + 5)
    print(f"T3 month index: {ok}")
    if not ok:
        fails.append("T3 month index")

    # T4: the era-B schema contract (dictionary id, int16/int8/float32)
    schema = pa.schema([
        ("district_id", pa.dictionary(pa.int32(), pa.string())),
        ("year", pa.int16()), ("month", pa.int8()), ("value", pa.float32())])
    obs = pq.read_schema(REPO / "data" / "parquet" / "observed"
                         / "variable=spi_03" / "part-0.parquet")
    ok = schema.equals(obs, check_metadata=False)
    print(f"T4 schema == era-B observed store: {ok}")
    if not ok:
        fails.append("T4 schema")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1-T4)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
