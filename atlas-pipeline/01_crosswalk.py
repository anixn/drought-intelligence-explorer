#!/usr/bin/env python3
"""DIE v2.0 - atlas-pipeline step 01: grid-to-district crosswalk (task M6.2).

Computes, ONCE, the area weights that map the Atlas 0.05-degree lattice
(115,394 cells, two disjoint roots) onto the platform's 724-district v1.0
fabric (OD4, Owner-delegated 2026-11-18: era A lands on 724, never on the
Atlas's own 742-polygon fabric).

The weight machinery is IMPORTED from gcm-pipeline/06_district_aggregate.py
(exact Sutherland-Hodgman clipping of district rings against the cell
rectangles in the v1.0 LAEA projection; buffer fallback for sub-pixel
units) - imported, never copied, so there is one source of truth. The 06
selftest (T1-T6, wired into selftest_gcm.py) proves those primitives.

Writes ONLY under atlas-pipeline/work/ (X9-style write safety):
  work/crosswalk/weights.json            district_id -> {n_cells, weights{"i,j": w}, fallback, outside_domain, sub_pixel}
  work/crosswalk/crosswalk_summary.csv   per-district diagnostics
  work/crosswalk/crosswalk_manifest.json byte sizes + sha256 + counts

Usage:
  python atlas-pipeline/01_crosswalk.py             # build the weights
  python atlas-pipeline/01_crosswalk.py --selftest  # synthetic checks
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_CFG = HERE / "config" / "atlas.yaml"
WORK = HERE / "work"

SEED = 20261103


def load_06():
    """Import the PROVEN weight primitives from gcm-pipeline step 06."""
    src = REPO / "gcm-pipeline" / "06_district_aggregate.py"
    if not src.exists():
        raise SystemExit(f"FATAL: weight machinery not found: {src}")
    spec = importlib.util.spec_from_file_location("die_step06", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["die_step06"] = mod
    spec.loader.exec_module(mod)
    return mod


def lattice_from_cfg(cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    # accepts the full config document OR the atlas block itself
    atlas = cfg["atlas"] if "atlas" in cfg else cfg
    lat_cfg = atlas["crosswalk"]["lattice"]
    lats = np.round(np.arange(lat_cfg["lat_start"], lat_cfg["lat_end"]
                              + lat_cfg["step"] / 2, lat_cfg["step"]), 3)
    lons = np.round(np.arange(lat_cfg["lon_start"], lat_cfg["lon_end"]
                              + lat_cfg["step"] / 2, lat_cfg["step"]), 3)
    if len(lats) != lat_cfg["n_lats"] or len(lons) != lat_cfg["n_lons"]:
        raise SystemExit(
            f"FATAL: lattice size mismatch - built {len(lats)}x{len(lons)}, "
            f"config expects {lat_cfg['n_lats']}x{lat_cfg['n_lons']} "
            f"(the M6.1 gate-verified lattice)")
    return lats, lons


def build(cfg_path: Path) -> int:
    a = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["atlas"]
    step06 = load_06()
    cw = a["crosswalk"]
    lats, lons = lattice_from_cfg(a)
    print("=" * 78)
    print("ATLAS-PPIPELINE 01 - grid-to-district crosswalk (M6.2)")
    print("=" * 78)
    print(f"  lattice : {len(lats)} lats x {len(lons)} lons = "
          f"{len(lats) * len(lons)} cells @ {cw['lattice']['step']} deg")
    print(f"  fabric  : {cw['boundaries_geojson']} (724 features, v1.0)")

    # absolute paths so the imported 06 code resolves them regardless of cwd
    agg_cfg = {
        "district_aggregation": {
            "area_proj4": cw["area_proj4"],
            "boundaries_geojson": str((REPO / cw["boundaries_geojson"]).resolve()),
            "registry_csv": str((REPO / cw["registry_csv"]).resolve()),
            "sub_pixel_flag_threshold": cw["sub_pixel_flag_threshold"],
            "buffer_fallback": {"max_km": cw["buffer_fallback_max_km"]},
        }
    }
    t0 = time.time()
    weights = step06.build_weights(agg_cfg, lats, lons)

    # The lattice has 338,720 positions but the Atlas SHIPS 115,394 cell
    # files (sea cells have no file). A weight on a non-shipped cell is dead
    # weight (Yanam's polygon touches one): restrict every district's weight
    # map to the SHIPPED cell set, then re-normalise. Districts that lose
    # all weights become outside_domain with a recorded reason.
    gpat = __import__("re").compile(a["grid"]["file_pattern"])
    shipped = set()
    for rel_root in a["grid"]["roots"]:
        d = Path(a["local_root"]) / rel_root
        if d.exists():
            for nm in d.iterdir():
                m = gpat.match(nm.name)
                if m:
                    i = int(round((float(m.group(1)) - lats[0])
                                  / float(cw["lattice"]["step"])))
                    j = int(round((float(m.group(2)) - lons[0])
                                  / float(cw["lattice"]["step"])))
                    shipped.add(f"{i},{j}")
    dropped = 0
    for did, rec in weights.items():
        if rec.get("outside_domain") or not rec.get("weights"):
            continue
        kept = {k: v for k, v in rec["weights"].items() if k in shipped}
        if len(kept) != len(rec["weights"]):
            dropped += len(rec["weights"]) - len(kept)
        if kept:
            tot = sum(kept.values())
            rec["weights"] = {k: round(v / tot, 9) for k, v in kept.items()}
            rec["n_cells"] = len(kept)
            rec["sub_pixel"] = rec["n_cells"] <= cw["sub_pixel_flag_threshold"]
            rec["fallback"] = None
        else:
            rec["weights"] = {}
            rec["n_cells"] = 0
            rec["outside_domain"] = True
            rec["sub_pixel"] = False
            rec["fallback"] = {"mode": "no_shipped_cells"}
    print(f"  lattice 338,720 positions vs {len(shipped)} shipped cells: "
          f"{dropped} dead weights dropped and re-normalised")
    dt = time.time() - t0

    registry = {}
    with open(REPO / cw["registry_csv"], encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            registry[row["district_id"]] = row
    n_outside = sum(1 for r in weights.values() if r.get("outside_domain"))
    n_fallback = sum(1 for r in weights.values() if r.get("fallback"))
    n_subpixel = sum(1 for r in weights.values() if r.get("sub_pixel"))

    # ------------------------------------------------------------ QA ----
    # Proper conservation check: recompute the exact per-district total
    # overlap area (sum of clipped areas over candidate cells) and compare
    # it with (a) the polygon's own LAEA area and (b) the registry area.
    # (A weighted-average-cell-area ratio would be meaningless.)
    import json as _json
    geo_path = (REPO / cw["boundaries_geojson"]).resolve()
    with open(geo_path, encoding="utf-8") as fh:
        gj = _json.load(fh)
    half = float(cw["lattice"]["step"]) / 2.0
    rows, ratios, registry_ratios = [], [], []
    for feat in gj["features"]:
        did = feat["properties"].get("id") or feat.get("id")
        geom = feat["geometry"]
        parts = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        rings = []
        for part in parts:
            rings.append((part[0], False))
            for h in part[1:]:
                rings.append((h, True))
        xs = [c[0] for ring, _ in rings for c in ring]
        ys = [c[1] for ring, _ in rings for c in ring]
        i0 = int(np.searchsorted(lats, min(ys) - half)) - 1
        i1 = int(np.searchsorted(lats, max(ys) + half)) + 1
        j0 = int(np.searchsorted(lons, min(xs) - half)) - 1
        j1 = int(np.searchsorted(lons, max(xs) + half)) + 1
        a_sum = 0.0
        for i in range(max(i0, 0), min(i1 + 1, len(lats))):
            for j in range(max(j0, 0), min(j1 + 1, len(lons))):
                cell = (lons[j] - half, lons[j] + half,
                        lats[i] - half, lats[i] + half)
                a_sum += sum((-1.0 if hole else 1.0)
                             * step06.overlap_area_km2(ring, cell)
                             for ring, hole in rings)
        area_poly = sum((-1.0 if hole else 1.0) * step06._shoelace(ring)
                        for ring, hole in rings) / 1e6
        rec = weights.get(did, {})
        reg = registry.get(did)
        area_reg = float(reg["area_km2"]) if reg else float("nan")
        r_cons = a_sum / area_poly if area_poly > 0 else np.nan
        r_reg = a_sum / area_reg if area_reg > 0 else np.nan
        if r_cons == r_cons:
            ratios.append(r_cons)
            registry_ratios.append(r_reg)
        rows.append({
            "district_id": did,
            "n_cells": rec.get("n_cells", 0),
            "fallback": (rec.get("fallback") or {}).get("mode", ""),
            "outside_domain": int(bool(rec.get("outside_domain"))),
            "sub_pixel": int(bool(rec.get("sub_pixel"))),
            "registry_area_km2": area_reg,
            "polygon_area_laea_km2": round(area_poly, 3),
            "overlap_area_km2": round(a_sum, 3),
            "conservation_ratio": round(r_cons, 9) if r_cons == r_cons else "",
            "registry_ratio": round(r_reg, 6) if r_reg == r_reg else "",
        })
    ra = np.asarray([r for r in ratios if r == r])
    rr = np.asarray([r for r in registry_ratios if r == r])
    print(f"  weights built in {dt:.1f}s for {len(weights)} districts")
    print(f"  conservation (sum clipped areas / polygon LAEA area): "
          f"median {np.median(ra):.9f}, min {ra.min():.9f}, max {ra.max():.9f}")
    print(f"  vs registry area: median {np.median(rr):.6f}, "
          f"p05 {np.percentile(rr, 5):.6f}, max {rr.max():.6f} "
          f"(~1 expected: registry areas were built on the same LAEA)")
    print(f"  outside_domain: {n_outside}  buffer-fallback: {n_fallback}  "
          f"sub-pixel flagged: {n_subpixel}")
    tol = float(cw.get("area_tolerance_frac", 0.02))
    if rr.max() > 1 + tol or rr.min() < 1 - tol:
        bad = [rows[i]["district_id"] for i, r in enumerate(rr)
               if r > 1 + tol or r < 1 - tol]
        print(f"  WARNING: {len(bad)} districts outside the "
              f"{tol:.0%} registry-area tolerance: {bad[:10]}")

    # -------------------------------------------------------- outputs ----
    out_dir = WORK / "crosswalk"
    out_dir.mkdir(parents=True, exist_ok=True)
    wj = out_dir / "weights.json"
    payload = json.dumps(
        {"lattice": {k: cw["lattice"][k] for k in
                     ("lat_start", "lat_end", "lon_start", "lon_end",
                      "step", "n_lats", "n_lons")},
         "area_proj4": cw["area_proj4"],
         "n_districts": len(weights),
         "weights": weights},
        sort_keys=True, separators=(",", ":")) + "\n"
    data = payload.encode("utf-8")
    wj.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    with open(out_dir / "crosswalk_summary.csv", "w", newline="",
              encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    man = {
        "step": "01_crosswalk",
        "generated_from": str(cfg_path),
        "weights_sha256": sha,
        "weights_bytes": len(data),
        "n_districts": len(weights),
        "n_cells_lattice": int(len(lats) * len(lons)),
        "shipped_cells": len(shipped),
        "dead_weights_dropped": dropped,
        "outside_domain": n_outside,
        "buffer_fallback": n_fallback,
        "sub_pixel": n_subpixel,
        "conservation": {
            "ratio_vs_polygon_laea": {
                "median": float(np.median(ra)), "min": float(ra.min()),
                "max": float(ra.max())},
            "ratio_vs_registry": {
                "median": float(np.median(rr)),
                "p05": float(np.percentile(rr, 5)),
                "max": float(rr.max())},
        },
        "registry_area_tolerance": tol,
    }
    (out_dir / "crosswalk_manifest.json").write_text(
        json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {wj.relative_to(REPO)} ({len(data):,} bytes, sha256 {sha[:16]})")
    print("CROSSWALK DONE")
    return 0


# ---------------------------------------------------------------- selftest ----
def selftest() -> int:
    print("=" * 78)
    print("SELFTEST - crosswalk (synthetic; seed 20261103)")
    print("=" * 78)
    fails = []
    step06 = load_06()
    step06._init_area_transformer(
        "+proj=laea +lat_0=22.5 +lon_0=79.5 +x_0=0 +y_0=0 "
        "+datum=WGS84 +units=m +no_defs")

    # T1: the imported module is the real 06 (proven primitives present)
    ok = all(hasattr(step06, n) for n in
             ("build_weights", "overlap_area_km2", "_shoelace",
              "_clip_ring_halfplane", "_great_circle_km"))
    print(f"T1 proven 06 machinery imported: {ok}")
    if not ok:
        fails.append("T1 import")

    # T2: lattice_from_cfg honours the gate-verified counts and rejects lies
    tmp_cfg = {"atlas": {"crosswalk": {"lattice": {
        "lat_start": 8.125, "lat_end": 37.075, "lon_start": 68.225,
        "lon_end": 97.375, "step": 0.05, "n_lats": 580, "n_lons": 584}}}}
    lats, lons = lattice_from_cfg(tmp_cfg)
    ok = (len(lats) == 580 and len(lons) == 584
          and abs(float(lats[0]) - 8.125) < 1e-9
          and abs(float(lats[-1]) - 37.075) < 1e-9
          and abs(float(lons[0]) - 68.225) < 1e-9
          and abs(float(lons[-1]) - 97.375) < 1e-9)
    print(f"T2 lattice build 580x584 exact: {ok}")
    if not ok:
        fails.append("T2 lattice")
    bad = dict(tmp_cfg); bad["atlas"]["crosswalk"]["lattice"]["n_lats"] = 579
    try:
        lattice_from_cfg(bad)
        ok = False
    except SystemExit:
        ok = True
    print(f"T3 lying lattice count rejected: {ok}")
    if not ok:
        fails.append("T3 lattice guard")

    # T4: on a toy lattice, a rectangle district's weights reproduce the
    # exact fractional overlap areas (re-runs the 06 T1 semantics at 0.05 deg)
    lats_t = np.array([10.0, 10.05])
    lons_t = np.array([76.0, 76.05])
    # rectangle spanning lon 76.0..76.075 (1.5 cells), lat 10.0..10.05 (1 cell)
    rect = [(76.0, 10.0), (76.075, 10.0), (76.075, 10.05), (76.0, 10.05)]
    a_full = step06.overlap_area_km2(rect, (76.0, 76.05, 10.0, 10.05))
    a_part = step06.overlap_area_km2(rect, (76.05, 76.1, 10.0, 10.05))
    atot = step06._shoelace(rect) / 1e6
    # (1e-6 relative - the SAME tolerance the proven 06 selftest T1 uses for
    # LAEA floating-point noise on clip reassembly)
    ok = (abs((a_full + a_part) / atot - 1.0) < 1e-6
          and abs(a_full / (a_full + a_part) - 1.5 / 2.25) < 1e-6)
    print(f"T4 fractional weights: full={a_full:.6f} part={a_part:.6f} "
          f"sum/atot={(a_full + a_part) / atot:.9f}: {ok}")
    if not ok:
        fails.append("T4 fractions")

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
    return build(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
