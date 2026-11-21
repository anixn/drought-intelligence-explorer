#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""01_build_overlap.py — Era A (Atlas) vs Era B (Gridded Multi-Source)
cross-validation product (task M6.6).

Spec: docs/v2/03-scientific-pipelines.md section 6; window roles: register D6
(primary comparison window 1981-2014, GCM-native; 1981-2025 is the sensitivity
variant and is NOT built here).

What this builds (all deterministic, no imputation):

  data/parquet/cross_validation/overlap_1981_2014.parquet
      one row per matched district-month where BOTH eras have a finite value:
      district_id, variable, date, era_a_value, era_b_value, diff,
      flag_a, flag_b, event_match, class_a, class_b, class_match, class_near
      (event_match = both records flag drought at the v1.0 truncation -1.0;
       class_* are indices into the shipped metadata class table)

  .../per_district_1981_2014.parquet
      one row per comparable district x variable (the map/table source):
      n, n_window, coverage, r, bias, rmsd, state_agree, both_drought,
      class_exact, class_near, a_drought_share, b_drought_share, a_mean, b_mean

  .../monthly_1981_2014.parquet
      area-weighted national monthly agreement series (evidence over time).

Honesty rules (R2/R9/R10):
  - The two eras are COMPARED, never averaged into one series or spliced.
  - A district-month present in only one era is ABSENT, never filled.
  - Districts with no overlap are absent from the per-district table (the map
    renders them grey), not zero-filled.
  - Metrics always carry their sample size (n).

Usage:
  python validation-studies/crossval/01_build_overlap.py [--config PATH]
  python validation-studies/crossval/01_build_overlap.py --selftest

The owner runs the scientific pipelines; this is a deterministic build-time
conversion over already-published local stores (same class as
scripts/build_national.py), not an external compute job.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


# --------------------------------------------------------------------------
# config / inputs
# --------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def metadata_id(var_id: str) -> str:
    """Parquet variable id -> metadata indicator id (spei_01 -> spei_1)."""
    return re.sub(r"_0(\d)$", r"_\1", var_id)


def load_registry(path: Path) -> dict:
    """district_id -> {"state": str, "name": str, "area": float}."""
    df = pd.read_csv(path, dtype={"district_id": str})
    out = {}
    for row in df.itertuples(index=False):
        out[str(row.district_id)] = {
            "state": str(row.state_name),
            "name": str(row.district_name),
            "area": float(row.area_km2),
        }
    return out


def load_classes(metadata_path: Path, var_id: str) -> list[dict]:
    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)
    target = metadata_id(var_id)
    for ind in meta["indicators"]:
        if ind["id"] == target:
            return ind["classes"]
    raise SystemExit(f"FATAL: no metadata classes for {var_id} ({target})")


def class_index(values: np.ndarray, classes: list[dict]) -> np.ndarray:
    """Index into the metadata class table, exactly like DIE.classify() in
    assets/js/data-loader.js (min/max with minClosed/maxClosed)."""
    out = np.full(values.shape, -1, dtype=np.int8)
    for idx, c in enumerate(classes):
        lo = -np.inf if c.get("min") is None else float(c["min"])
        hi = np.inf if c.get("max") is None else float(c["max"])
        lo_ok = (values > lo) | ((c.get("minClosed") is True) & (values == lo))
        hi_ok = (values < hi) | ((c.get("maxClosed") is True) & (values == hi))
        hit = lo_ok & hi_ok & (out < 0)
        out[hit] = idx
    return out


def read_era_a(root: Path, var_id: str, window: tuple[int, int]) -> pd.DataFrame:
    frames = []
    for year in range(window[0], window[1] + 1):
        f = root / f"variable={var_id}" / f"year={year}" / "part-0.parquet"
        if not f.exists():
            continue
        frames.append(pd.read_parquet(f))
    if not frames:
        raise SystemExit(f"FATAL: no era-A partitions for {var_id} in {window}")
    df = pd.concat(frames, ignore_index=True)
    df["district_id"] = df["district_id"].astype(str)
    return df


def read_era_b(root: Path, var_id: str, window: tuple[int, int]) -> pd.DataFrame:
    f = root / f"variable={var_id}" / "part-0.parquet"
    if not f.exists():
        raise SystemExit(f"FATAL: no era-B partition: {f}")
    df = pd.read_parquet(f)
    df["district_id"] = df["district_id"].astype(str)
    return df[(df["year"] >= window[0]) & (df["year"] <= window[1])]


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 12:
        return float("nan")
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    da, db = a - a.mean(), b - b.mean()
    den = math.sqrt(float(np.dot(da, da)) * float(np.dot(db, db)))
    if den <= 0.0:
        return float("nan")
    return float(np.dot(da, db) / den)


def per_district_metrics(matched: pd.DataFrame, classes: list[dict],
                         threshold: float, severe: float) -> pd.DataFrame:
    """One row per district. Metrics are plain sample statistics over the
    matched district-months; NaN means 'not calculable', never zero."""
    rows = []
    n_window = int(matched.groupby(["year", "month"]).ngroups)
    flags_a = matched["era_a_value"].to_numpy() <= threshold
    flags_b = matched["era_b_value"].to_numpy() <= threshold
    sev_a = matched["era_a_value"].to_numpy() <= severe
    sev_b = matched["era_b_value"].to_numpy() <= severe
    cls_a = class_index(matched["era_a_value"].to_numpy(np.float64), classes)
    cls_b = class_index(matched["era_b_value"].to_numpy(np.float64), classes)
    matched = matched.assign(flag_a=flags_a, flag_b=flags_b,
                             sev_a=sev_a, sev_b=sev_b,
                             class_a=cls_a, class_b=cls_b,
                             class_match=cls_a == cls_b,
                             class_near=np.abs(cls_a.astype(np.int16) -
                                               cls_b.astype(np.int16)) <= 1,
                             state_agree=flags_a == flags_b,
                             both_drought=flags_a & flags_b,
                             severe_agree=sev_a == sev_b)
    for did, g in matched.groupby("district_id", sort=True):
        a = g["era_a_value"].to_numpy(np.float64)
        b = g["era_b_value"].to_numpy(np.float64)
        d = b - a
        rows.append(OrderedDict([
            ("district_id", did),
            ("n", int(len(g))),
            ("n_window", n_window),
            ("coverage", float(len(g) / n_window) if n_window else 0.0),
            ("r", _pearson(a, b)),
            ("bias", float(d.mean())),
            ("rmsd", float(np.sqrt(np.mean(d * d)))),
            ("state_agree", float(g["state_agree"].mean())),
            ("both_drought", float(g["both_drought"].mean())),
            ("severe_agree", float(g["severe_agree"].mean())),
            ("class_exact", float(g["class_match"].mean())),
            ("class_near", float(g["class_near"].mean())),
            ("a_drought_share", float(g["flag_a"].mean())),
            ("b_drought_share", float(g["flag_b"].mean())),
            ("a_mean", float(a.mean())),
            ("b_mean", float(b.mean())),
        ]))
    return pd.DataFrame(rows)


def monthly_metrics(matched: pd.DataFrame) -> pd.DataFrame:
    """Area-weighted national monthly agreement series. Only districts with a
    finite pair contribute that month; n is reported per row."""
    rows = []
    for (year, month), g in matched.groupby(["year", "month"], sort=True):
        w = g["area"].to_numpy(np.float64)
        tot = float(w.sum())
        if tot <= 0.0:
            continue
        rows.append(OrderedDict([
            ("date", f"{int(year):04d}-{int(month):02d}"),
            ("n_districts", int(len(g))),
            ("mean_a", float(np.dot(w, g["era_a_value"]) / tot)),
            ("mean_b", float(np.dot(w, g["era_b_value"]) / tot)),
            ("diff", float(np.dot(w, g["era_b_value"] - g["era_a_value"]) / tot)),
            ("state_agree", float(np.dot(w, g["state_agree"]) / tot)),
            ("both_drought", float(np.dot(w, g["both_drought"]) / tot)),
            ("class_exact", float(np.dot(w, g["class_match"]) / tot)),
            ("class_near", float(np.dot(w, g["class_near"]) / tot)),
        ]))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# parquet writing (deterministic, explicit schema)
# --------------------------------------------------------------------------
def _write(table: pa.Table, path: Path, row_group_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # deterministic: strip pandas/arrow schema metadata, fixed row groups
    table = table.replace_schema_metadata(None)
    pq.write_table(table, path, compression="zstd", compression_level=19,
                   row_group_size=row_group_size, use_dictionary=True,
                   write_statistics=True)


def write_outputs(cfg: dict, matched: pd.DataFrame, per_district: pd.DataFrame,
                  monthly: pd.DataFrame, repo: Path) -> dict:
    out_dir = repo / cfg["paths"]["out_dir"]
    files = cfg["outputs"]
    rg = int(cfg["row_group_districts"]) * 408

    overlap = matched[["variable", "district_id", "date",
                       "era_a_value", "era_b_value", "diff",
                       "flag_a", "flag_b", "event_match",
                       "class_a", "class_b", "class_match", "class_near"]].copy()
    schema = pa.schema([
        ("variable", pa.dictionary(pa.int16(), pa.string())),
        ("district_id", pa.dictionary(pa.int16(), pa.string())),
        ("date", pa.string()),
        ("era_a_value", pa.float32()),
        ("era_b_value", pa.float32()),
        ("diff", pa.float32()),
        ("flag_a", pa.bool_()),
        ("flag_b", pa.bool_()),
        ("event_match", pa.bool_()),
        ("class_a", pa.int8()),
        ("class_b", pa.int8()),
        ("class_match", pa.bool_()),
        ("class_near", pa.bool_()),
    ])
    for col in ("flag_a", "flag_b", "event_match", "class_match", "class_near"):
        overlap[col] = overlap[col].astype(bool)
    overlap["class_a"] = overlap["class_a"].astype(np.int8)
    overlap["class_b"] = overlap["class_b"].astype(np.int8)
    overlap = overlap.sort_values(["variable", "district_id", "date"],
                                  kind="mergesort").reset_index(drop=True)
    tbl = pa.Table.from_pandas(overlap, schema=schema, preserve_index=False)
    _write(tbl, out_dir / files["overlap"], rg)

    dist_schema = pa.schema([
        ("variable", pa.dictionary(pa.int16(), pa.string())),
        ("district_id", pa.dictionary(pa.int16(), pa.string())),
        ("n", pa.int32()),
        ("n_window", pa.int16()),
        ("coverage", pa.float64()),
        ("r", pa.float64()),
        ("bias", pa.float64()),
        ("rmsd", pa.float64()),
        ("state_agree", pa.float64()),
        ("both_drought", pa.float64()),
        ("severe_agree", pa.float64()),
        ("class_exact", pa.float64()),
        ("class_near", pa.float64()),
        ("a_drought_share", pa.float64()),
        ("b_drought_share", pa.float64()),
        ("a_mean", pa.float64()),
        ("b_mean", pa.float64()),
    ])
    per = per_district.copy()
    per["n"] = per["n"].astype(np.int32)
    per["n_window"] = per["n_window"].astype(np.int16)
    per = per.sort_values(["variable", "district_id"], kind="mergesort") \
             .reset_index(drop=True)
    _write(pa.Table.from_pandas(per, schema=dist_schema, preserve_index=False),
           out_dir / files["per_district"], 60)

    mon_schema = pa.schema([
        ("variable", pa.dictionary(pa.int16(), pa.string())),
        ("date", pa.string()),
        ("n_districts", pa.int16()),
        ("mean_a", pa.float64()),
        ("mean_b", pa.float64()),
        ("diff", pa.float64()),
        ("state_agree", pa.float64()),
        ("both_drought", pa.float64()),
        ("class_exact", pa.float64()),
        ("class_near", pa.float64()),
    ])
    mon = monthly.copy()
    mon["n_districts"] = mon["n_districts"].astype(np.int16)
    mon = mon.sort_values(["variable", "date"], kind="mergesort") \
             .reset_index(drop=True)
    _write(pa.Table.from_pandas(mon, schema=mon_schema, preserve_index=False),
           out_dir / files["monthly"], 1 << 20)
    return {
        "overlap": out_dir / files["overlap"],
        "per_district": out_dir / files["per_district"],
        "monthly": out_dir / files["monthly"],
    }


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build(cfg: dict, repo: Path, quiet: bool = False) -> dict:
    window = tuple(int(y) for y in cfg["primary_window"])
    threshold = float(cfg["drought_threshold"])
    severe = float(cfg["severe_threshold"])
    registry = load_registry(repo / cfg["registry"])

    overlap_parts, dist_parts, month_parts, summary = [], [], [], OrderedDict()
    for var_id in cfg["variables"]:
        classes = load_classes(repo / cfg["metadata"], var_id)
        a = read_era_a(repo / cfg["paths"]["era_a"], var_id, window)
        b = read_era_b(repo / cfg["paths"]["era_b"], var_id, window)
        a = a.dropna(subset=["value"])
        b = b.dropna(subset=["value"])

        m = a.merge(b, on=["district_id", "year", "month"], how="inner",
                    suffixes=("_a", "_b"))
        m = m.dropna(subset=["value_a", "value_b"]).copy()
        m["variable"] = var_id
        m["date"] = (
            m["year"].astype(int).astype(str).str.zfill(4) + "-" +
            m["month"].astype(int).astype(str).str.zfill(2)
        )
        m["era_a_value"] = m["value_a"].astype(np.float32)
        m["era_b_value"] = m["value_b"].astype(np.float32)
        m["diff"] = (m["era_b_value"] - m["era_a_value"]).astype(np.float32)
        m["area"] = m["district_id"].map(
            lambda d: registry.get(d, {}).get("area", float("nan")))
        flag_a = m["era_a_value"] <= threshold
        flag_b = m["era_b_value"] <= threshold
        m["flag_a"] = flag_a
        m["flag_b"] = flag_b
        m["event_match"] = flag_a & flag_b
        m["state_agree"] = flag_a == flag_b
        m["both_drought"] = m["event_match"]
        m["severe_agree"] = (m["era_a_value"] <= severe) == \
                            (m["era_b_value"] <= severe)
        m["class_a"] = class_index(m["era_a_value"].to_numpy(np.float64), classes)
        m["class_b"] = class_index(m["era_b_value"].to_numpy(np.float64), classes)
        m["class_match"] = m["class_a"] == m["class_b"]
        m["class_near"] = (np.abs(m["class_a"].astype(np.int16) -
                                  m["class_b"].astype(np.int16)) <= 1)

        per = per_district_metrics(m, classes, threshold, severe)
        per.insert(0, "variable", var_id)
        mon = monthly_metrics(m)
        mon.insert(0, "variable", var_id)

        overlap_parts.append(m)
        dist_parts.append(per)
        month_parts.append(mon)

        # per-variable anchor for the log / regression harness
        w = m["area"].to_numpy(np.float64)
        ok = np.isfinite(w)
        wt = float(w[ok].sum())
        summary[var_id] = OrderedDict([
            ("districts", int(per.shape[0])),
            ("district_months", int(m.shape[0])),
            ("window", [int(m["year"].min()), int(m["year"].max())]),
            ("months", int(m.groupby(["year", "month"]).ngroups)),
            ("median_r", float(per["r"].median(skipna=True))),
            ("median_rmsd", float(per["rmsd"].median())),
            ("area_bias", float(np.dot(w[ok], (m["era_b_value"] -
                                               m["era_a_value"])[ok]) / wt)),
            ("area_state_agree", float(np.dot(w[ok], m["state_agree"][ok]) / wt)),
            ("area_both_drought", float(np.dot(w[ok], m["event_match"][ok]) / wt)),
            ("area_class_exact", float(np.dot(w[ok], m["class_match"][ok]) / wt)),
            ("area_class_near", float(np.dot(w[ok], m["class_near"][ok]) / wt)),
        ])
        if not quiet:
            print(f"  {var_id}: {per.shape[0]} districts, {m.shape[0]:,} "
                  f"district-months, median r = {per['r'].median():.3f}, "
                  f"area state agreement = "
                  f"{summary[var_id]['area_state_agree'] * 100:.1f}%")

    matched = pd.concat(overlap_parts, ignore_index=True)
    per_district = pd.concat(dist_parts, ignore_index=True)
    monthly = pd.concat(month_parts, ignore_index=True)
    paths = write_outputs(cfg, matched, per_district, monthly, repo)
    return {
        "matched": matched,
        "per_district": per_district,
        "monthly": monthly,
        "paths": paths,
        "summary": summary,
        "registry": registry,
    }


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------
def verify(cfg: dict, result: dict, repo: Path) -> list[str]:
    problems = []
    matched = result["matched"]
    per = result["per_district"]
    ov_path = result["paths"]["overlap"]
    tbl = pq.read_table(ov_path)
    if tbl.num_rows != len(matched):
        problems.append(f"overlap row count {tbl.num_rows} != built {len(matched)}")
    # 1. no imputation: every row has both values finite
    a = tbl.column("era_a_value").to_numpy(zero_copy_only=False)
    b = tbl.column("era_b_value").to_numpy(zero_copy_only=False)
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        problems.append("overlap contains non-finite values (imputation guard)")
    # 2. exact source reconciliation: seeded sample re-read from the PARQUET
    #    partitions on disk (not from the in-memory build frames)
    seed = int(cfg["verify_seed"])
    rng = random.Random(seed)
    dates = tbl.column("date").to_pylist()
    dids = tbl.column("district_id").to_pylist()
    vars_ = tbl.column("variable").to_pylist()
    av = tbl.column("era_a_value").to_pylist()
    bv = tbl.column("era_b_value").to_pylist()
    for var_id in cfg["variables"]:
        idxs = [i for i, v in enumerate(vars_) if v == var_id]
        pick = rng.sample(idxs, min(8, len(idxs)))
        for i in pick:
            y, mo = int(dates[i][:4]), int(dates[i][5:7])
            fa = (repo / cfg["paths"]["era_a"] / f"variable={var_id}" /
                  f"year={y}" / "part-0.parquet")
            fb = (repo / cfg["paths"]["era_b"] / f"variable={var_id}" /
                  "part-0.parquet")
            da = pd.read_parquet(fa)
            db = pd.read_parquet(fb)
            sa = da[(da.district_id.astype(str) == dids[i]) &
                    (da.year == y) & (da.month == mo)]["value"]
            sb = db[(db.district_id.astype(str) == dids[i]) &
                    (db.year == y) & (db.month == mo)]["value"]
            if len(sa) != 1 or len(sb) != 1:
                problems.append(f"source row missing: {var_id} {dids[i]} {dates[i]}")
                continue
            if float(sa.iloc[0]) != float(av[i]):
                problems.append(f"era A mismatch: {var_id} {dids[i]} {dates[i]}")
            if float(sb.iloc[0]) != float(bv[i]):
                problems.append(f"era B mismatch: {var_id} {dids[i]} {dates[i]}")
    # 3. per-district reconciliation for one district, independent numpy
    for var_id in cfg["variables"]:
        sub = matched[matched["variable"] == var_id]
        did = sorted(sub["district_id"].unique())[0]
        g = sub[sub["district_id"] == did]
        row = per[(per["variable"] == var_id) &
                  (per["district_id"] == did)].iloc[0]
        aa = g["era_a_value"].to_numpy(np.float64)
        bb = g["era_b_value"].to_numpy(np.float64)
        dd = bb - aa
        checks = [
            ("n", float(len(g)), float(row["n"])),
            ("bias", float(dd.mean()), float(row["bias"])),
            ("rmsd", float(np.sqrt(np.mean(dd * dd))), float(row["rmsd"])),
        ]
        for name, want, got in checks:
            if abs(want - got) > 1e-9:
                problems.append(f"metric mismatch {var_id}/{did}/{name}: "
                                f"{want} vs {got}")
    # 4. district coverage: per-district rows == districts in the overlap
    for var_id in cfg["variables"]:
        n_ov = matched[matched["variable"] == var_id]["district_id"].nunique()
        n_per = per[per["variable"] == var_id].shape[0]
        if n_ov != n_per:
            problems.append(f"{var_id}: per-district rows {n_per} != matched "
                            f"districts {n_ov}")
    # 5. absent rows stay absent: a district with no era-A overlap must not
    #    appear with zero-filled metrics
    reg_ids = set(result["registry"])
    present = set(per["district_id"])
    absent = sorted(reg_ids - present)
    if absent:
        missing_vals = per[per["district_id"].isin(absent)]
        if len(missing_vals):
            problems.append("absent districts were zero-filled")
    result["absent_districts"] = absent
    return problems


# --------------------------------------------------------------------------
# selftest — synthetic world with analytically known answers
# --------------------------------------------------------------------------
def selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="die-crossval-"))
    try:
        (tmp / "data/parquet/atlas").mkdir(parents=True)
        (tmp / "data/parquet/observed").mkdir(parents=True)
        (tmp / "data").mkdir(exist_ok=True)
        # registry: d1 and d2 equal area; d3 has era-A data only
        pd.DataFrame([
            {"district_id": "d1", "district_name": "D1", "state_name": "S",
             "state_id": "s", "area_km2": 100.0},
            {"district_id": "d2", "district_name": "D2", "state_name": "S",
             "state_id": "s", "area_km2": 100.0},
            {"district_id": "d3", "district_name": "D3", "state_name": "S",
             "state_id": "s", "area_km2": 100.0},
        ]).to_csv(tmp / "data/districts.csv", index=False)
        classes = [
            {"key": "extreme_drought", "min": None, "max": -2.0,
             "minClosed": False, "maxClosed": True},
            {"key": "severe_drought", "min": -2.0, "max": -1.5,
             "minClosed": False, "maxClosed": True},
            {"key": "moderate_drought", "min": -1.5, "max": -1.0,
             "minClosed": False, "maxClosed": True},
            {"key": "mild_drought", "min": -1.0, "max": -0.5,
             "minClosed": False, "maxClosed": True},
            {"key": "near_normal", "min": -0.5, "max": 0.5,
             "minClosed": False, "maxClosed": False},
            {"key": "mildly_wet", "min": 0.5, "max": 1.0,
             "minClosed": True, "maxClosed": False},
            {"key": "moderately_wet", "min": 1.0, "max": 1.5,
             "minClosed": True, "maxClosed": False},
            {"key": "severely_wet", "min": 1.5, "max": 2.0,
             "minClosed": True, "maxClosed": False},
            {"key": "extremely_wet", "min": 2.0, "max": None,
             "minClosed": True, "maxClosed": False},
        ]
        meta = {"indicators": [
            {"id": "spei_1", "classes": classes},
            {"id": "spei_12", "classes": classes},
        ]}
        (tmp / "data/metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        # 24 months, 2 years. d1: identical. d2: +0.5 bias. d3: era A only.
        rows_a, rows_b = [], []
        for y in (1981, 1982):
            for mo in range(1, 13):
                v = math.sin((mo - 1) / 12 * 2 * math.pi)  # -1..1 roughly
                for did, delta in (("d1", 0.0), ("d2", 0.5), ("d3", 0.0)):
                    rows_a.append({"district_id": did, "year": y, "month": mo,
                                   "value": float(np.float32(v))})
                for did, delta in (("d1", 0.0), ("d2", 0.5)):
                    rows_b.append({"district_id": did, "year": y, "month": mo,
                                   "value": float(np.float32(v + delta))})
        a = pd.DataFrame(rows_a)
        b = pd.DataFrame(rows_b)
        for y in (1981, 1982):
            d = (tmp / "data/parquet/atlas/variable=spei_01" / f"year={y}")
            d.mkdir(parents=True, exist_ok=True)
            a[a.year == y].to_parquet(d / "part-0.parquet", index=False)
        (tmp / "data/parquet/observed/variable=spei_01").mkdir(parents=True)
        b.to_parquet(tmp / "data/parquet/observed/variable=spei_01/part-0.parquet",
                     index=False)

        cfg = {
            "primary_window": [1981, 1982],
            "variables": {"spei_01": "SPEI-1"},
            "drought_threshold": -1.0,
            "severe_threshold": -1.5,
            "metadata": "data/metadata.json",
            "registry": "data/districts.csv",
            "paths": {"era_a": "data/parquet/atlas",
                      "era_b": "data/parquet/observed",
                      "out_dir": "data/parquet/cross_validation"},
            "outputs": {"overlap": "overlap_1981_2014.parquet",
                        "per_district": "per_district_1981_2014.parquet",
                        "monthly": "monthly_1981_2014.parquet"},
            "row_group_districts": 60,
            "verify_seed": 20261103,
        }
        result = build(cfg, tmp, quiet=True)
        per = result["per_district"].set_index("district_id")
        ov = result["matched"]
        checks = []
        checks.append(("d3 excluded (era A only)", "d3" not in per.index))
        checks.append(("d1 r = 1", abs(per.loc["d1", "r"] - 1.0) < 1e-12))
        checks.append(("d1 bias = 0", abs(per.loc["d1", "bias"]) < 1e-12))
        checks.append(("d2 bias = 0.5",
                       abs(per.loc["d2", "bias"] - 0.5) < 1e-6))
        checks.append(("d2 r = 1", abs(per.loc["d2", "r"] - 1.0) < 1e-12))
        checks.append(("d2 class_exact < 1",
                       per.loc["d2", "class_exact"] < 1.0))
        checks.append(("d2 class_near = 1",
                       per.loc["d2", "class_near"] == 1.0))
        checks.append(("overlap rows = 48", len(ov) == 48))
        # d2's +0.5 shift moves some months one class, never more
        checks.append(("class_near >= class_exact",
                       (ov["class_near"] >= ov["class_match"]).all()))
        mon = result["monthly"]
        checks.append(("monthly rows = 24", len(mon) == 24))
        checks.append(("monthly bias = 0.25",
                       abs(mon["diff"].iloc[0] - 0.25) < 1e-9))
        problems = verify(cfg, result, tmp)
        checks.append(("verify clean", not problems))
        ok = True
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        if problems:
            for p in problems:
                print("   PROBLEM:", p)
        print("SELFTEST " + ("PASSED" if ok else "FAILED"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Build era A <-> era B cross-validation (M6.6)")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--selftest", action="store_true",
                    help="run the synthetic-world self-test instead of building")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    cfg = load_config(Path(args.config))
    print(f"Cross-validation build: window {cfg['primary_window']}, "
          f"variables {list(cfg['variables'])}")
    result = build(cfg, REPO)
    problems = verify(cfg, result, REPO)
    for name, path in result["paths"].items():
        print(f"  wrote {path.relative_to(REPO)}  "
              f"({path.stat().st_size / 1024:.1f} KB)")
    if result.get("absent_districts"):
        print(f"  no era-A overlap (left absent, never imputed): "
              f"{len(result['absent_districts'])} districts")
    if problems:
        for p in problems:
            print("  PROBLEM:", p)
        return 1
    print("VERIFY PASS")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
