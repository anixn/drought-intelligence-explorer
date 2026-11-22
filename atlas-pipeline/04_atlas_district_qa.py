#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""04_atlas_district_qa.py — per-district QA: the Atlas's OWN district series
(732, polygon-based) vs the PROMOTED era-A store (724, grid-aggregated).

This is the M6.2 step-4 cross-check, run at promotion time (Owner "go"
2026-11-20). It is QA ONLY — the Atlas's 742-polygon fabric is never
published (register OD4); the numbers here measure how well the platform's
geometric grid→724 route reproduces the Atlas's own district-level signal.

Method (declared, approximate by construction):
  1. Read the Atlas DISTRICT_BOUNDARY.shp polygons (shape type 5) + DBF
     attributes (DISTRICT_L = LGD district code; 11 DISPUTED polygons have
     no code and are SKIPPED, noted — the name fields are corrupted and the
     code field is not a bijection, M6.1 gate facts).
  2. Load only polygons whose code maps to an EXISTING series file
     (Z-score/Districts/data_distwise_id_<code>); 10 series are absent.
  3. Assign each polygon to the v1.0 district (724, R1 fabric) that
     CONTAINS its centroid (ray-casting PIP with hole handling in lon/lat).
     This is an APPROXIMATE geometric mapping — a polygon straddling a
     boundary goes wholly to the containing side of its centroid; recorded
     as such in the output.
  4. Per v1.0 district: area-weight (LAEA, v1.0 proj4) the assigned Atlas
     series into one QA series, compare with the PROMOTED era-A district
     series (data/parquet/atlas) over the overlap 1981–2025 (and the full
     1901–2025 window for information): r, mean bias (QA − ours).
  5. Output: work/district_qa.json + work/district_qa.csv; a summary block
     is appended to metadata.json → era_a.district_qa (additive).

Never merged, never published as data (R9/R1). Deterministic.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SERIES_RE = re.compile(r"^data_distwise_id_(\d+)$")


def load_shp_polygons(shp_path: Path) -> list[list[list[tuple[float, float]]]]:
    """Minimal .shp Polygon reader (shape types 5, 15, 25). Returns, per
    record, a list of parts; each part is a list of (lon, lat)."""
    shapes = []
    with shp_path.open("rb") as f:
        data = f.read()
    if len(data) < 100:
        raise SystemExit(f"FATAL: shp too small: {shp_path}")
    # shx gives record offsets; fall back to sequential scan
    n = (len(data) - 100) // 8
    pos = 100
    order = "big"      # record header big-endian
    while pos + 8 <= len(data):
        _idx, content_len = struct.unpack(">ii", data[pos:pos + 8])
        rec = data[pos + 8: pos + 8 + content_len * 2]
        pos += 8 + content_len * 2
        if len(rec) < 4:
            continue
        (stype,) = struct.unpack("<i", rec[:4])
        if stype in (5, 15, 25):                       # Polygon(Z)(M)
            box = struct.unpack("<4d", rec[4:36])
            (nparts,) = struct.unpack("<i", rec[36:40])
            (npoints,) = struct.unpack("<i", rec[40:44])
            parts_off = struct.unpack(f"<{nparts}i",
                                      rec[44:44 + 4 * nparts])
            pts_off = 44 + 4 * nparts
            pts = struct.unpack(f"<{npoints * 2}d",
                                rec[pts_off:pts_off + 16 * npoints])
            parts = []
            for pi in range(nparts):
                a = parts_off[pi]
                b = parts_off[pi + 1] if pi + 1 < nparts else npoints
                parts.append([(pts[2 * k], pts[2 * k + 1])
                              for k in range(a, b)])
            shapes.append(parts)
        else:
            shapes.append(None)                        # skipped record type
    return shapes


def ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    """Shoelace centroid of an outer ring (lon/lat; fine for containment)."""
    a = cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-18:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return (cx / (3.0 * a), cy / (3.0 * a))


def point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def point_in_geom(x: float, y: float, rings: list) -> bool:
    """Containment against a FLAT ring list (the shp reader preserves no hole
    nesting): a point inside ANY ring counts. Hole over-inclusion is a tiny,
    documented approximation acceptable for QA-only centroid assignment."""
    return any(point_in_ring(x, y, r) for r in rings if len(r) >= 4)


def laea_area_km2(ring, transformer) -> float:
    xs, ys = transformer.transform([p[0] for p in ring], [p[1] for p in ring])
    a = 0.0
    n = len(ring)
    for i in range(n):
        a += xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i]
    return a / 2.0 / 1e6          # SIGNED (orientation encodes outer/hole)


def polygon_area_km2(rings, transformer) -> float:
    """Net polygon area from a FLAT ring list: |Σ signed ring areas| — outer
    rings and holes arrive with opposite orientations, so the sum is the net."""
    return abs(sum(laea_area_km2(r, transformer) for r in rings))


def load_series_file(path: Path) -> dict:
    """5-column series: Year Month SPEI-1 SPEI-4 SPEI-12 -> {(y,m): (v1,v4,v12)}."""
    out = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                y, m = int(parts[0]), int(parts[1])
            except ValueError:
                continue                                   # header line
            vals = []
            for p in parts[2:5]:
                vals.append(float("nan") if p.lower() == "nan" else float(p))
            out[(y, m)] = tuple(vals)
    return out


def parts_all_flat(parts_all: list) -> list:
    """v1.0 geojson geometry (parts of [outer, holes...]) -> flat ring list."""
    return [ring for part in parts_all for ring in part]


def run(cfg_path: Path, promoted_root: Path) -> dict:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["atlas"]
    from pyproj import Transformer
    transformer = Transformer.from_crs(
        "EPSG:4326", cfg["crosswalk"]["area_proj4"], always_xy=True)

    # ---- atlas polygons + attributes ---------------------------------------
    bdir = Path(cfg["local_root"]) / cfg["boundaries"]["dir"]
    shp = bdir / cfg["boundaries"]["district"]
    dbf = shp.with_suffix(".dbf")
    sys.path.insert(0, str(HERE))
    import importlib.util
    spec = importlib.util.spec_from_file_location("v00", HERE / "00_verify_atlas.py")
    v00 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v00)
    dbf_rows, _fields = v00.dbf_records(dbf)
    shapes = load_shp_polygons(shp)
    if len(shapes) != len(dbf_rows):
        raise SystemExit(f"FATAL: shp/shdbf mismatch {len(shapes)} vs "
                         f"{len(dbf_rows)}")
    # the Atlas shapefile ships in LCC_WGS84 (metric, false E/N 4,000,000;
    # .prj read verbatim) - transform every ring to WGS84 lon/lat before any
    # centroid/containment arithmetic (areas stay in the v1.0 LAEA metric)
    lcc_prj = shp.with_suffix(".prj").read_text(encoding="utf-8")
    to_ll = Transformer.from_crs(lcc_prj, "EPSG:4326", always_xy=True)
    for parts in shapes:
        if parts is None:
            continue
        for k, ring in enumerate(parts):
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            X, Y = to_ll.transform(xs, ys)
            parts[k] = list(zip(X, Y))
    code_field = "ID"          # the polygon->series key (1..742; the 10
                               # series-less ids are the M6.1 list). NOT
                               # DISTRICT_L (LGD codes, not a bijection).
    polys = []
    for i, (attrs, parts) in enumerate(zip(dbf_rows, shapes)):
        code = attrs.get(code_field)
        if parts is None or code in (None, "", b""):
            continue
        code = str(code).strip()
        polys.append({"code": code, "parts": parts})

    # ---- atlas series files --------------------------------------------------
    sdir = Path(cfg["local_root"]) / cfg["series"]["districts"]["dir"]
    series_files = {SERIES_RE.match(p.name).group(1): p
                    for p in sdir.iterdir() if SERIES_RE.match(p.name)}
    have = [p for p in polys if p["code"] in series_files]
    skipped_no_series = len(polys) - len(have)

    # ---- v1.0 fabric (724) + centroid assignment ------------------------------
    geo = json.loads((REPO / cfg["crosswalk"]["boundaries_geojson"])
                     .read_text(encoding="utf-8"))
    v1 = {}
    for feat in geo["features"]:
        did = feat["properties"].get("id") or feat.get("id")
        g = feat["geometry"]
        parts_all = (g["coordinates"] if g["type"] == "MultiPolygon"
                     else [g["coordinates"]])
        v1[did] = parts_all                       # list of parts; part[0] outer
    assignment = {}                                # did -> [(area_km2, code)]
    unmatched = 0
    for p in have:
        # centroid of the largest ring (main landmass of the polygon)
        outer = max(p["parts"], key=lambda r: abs(laea_area_km2(r, transformer)))
        cx, cy = ring_centroid(outer)
        did = None
        for cand, parts_all in v1.items():
            if point_in_geom(cx, cy, parts_all_flat(parts_all)):
                did = cand
                break
        if did is None:
            unmatched += 1
            continue
        area = polygon_area_km2(p["parts"], transformer)
        assignment.setdefault(did, []).append((area, p["code"]))

    # ---- comparison vs the PROMOTED era-A store -------------------------------
    import pyarrow.parquet as pq
    scales = {0: "spei_01", 1: "spei_04", 2: "spei_12"}
    ours = {}                                      # (var, did) -> {(y,m): val}
    for var in scales.values():
        vdir = promoted_root / f"variable={var}"
        for f in sorted(vdir.rglob("*.parquet")):
            t = pq.read_table(f).to_pydict()
            for d, y, m, v in zip(t["district_id"], t["year"], t["month"],
                                  t["value"]):
                if v is None:
                    continue
                ours.setdefault((var, d), {})[(int(y), int(m))] = v

    rows = []
    for did, members in sorted(assignment.items()):
        tot = sum(a for a, _c in members)
        if tot <= 0:
            continue
        # area-weight (LAEA km2) the assigned Atlas series into one QA series
        accs = {}
        for a, code in members:
            w = a / tot
            for (y, m), vals in load_series_file(series_files[code]).items():
                d = accs.setdefault((y, m), [0.0, 0.0, 0.0])
                for k, val in enumerate(vals):
                    if math.isfinite(val):
                        d[k] += w * val
        for (y, m), acc in accs.items():
            for k, var in scales.items():
                ov = ours.get((var, did), {}).get((y, m))
                if ov is None or not math.isfinite(acc[k]):
                    continue
                rows.append((did, var, y, m, acc[k], ov))
    # aggregate per (did, var): r + bias over the overlap window 1981-2025
    per = {}
    for did, var, y, m, qv, ov in rows:
        if 1981 <= y <= 2025:
            d = per.setdefault((did, var), {"q": [], "o": []})
            d["q"].append(qv)
            d["o"].append(ov)
    stats = []
    for (did, var), d in sorted(per.items()):
        q = np.array(d["q"]); o = np.array(d["o"])
        if len(q) < 120:
            continue
        r = float(np.corrcoef(q, o)[0, 1]) if q.std() > 0 and o.std() > 0 \
            else float("nan")
        stats.append({"district_id": did, "variable": var, "n_months": len(q),
                      "r": r, "mean_bias": float((q - o).mean())})
    # full-window (informational) national view: mean r per scale
    summ = {}
    for var in scales.values():
        rs = np.array([s["r"] for s in stats
                       if s["variable"] == var and math.isfinite(s["r"])])
        bs = np.array([s["mean_bias"] for s in stats
                       if s["variable"] == var and math.isfinite(s["mean_bias"])])
        summ[var] = {
            "n_districts": int(len(rs)),
            "r_median": float(np.median(rs)) if len(rs) else None,
            "r_p10": float(np.percentile(rs, 10)) if len(rs) else None,
            "r_share_ge_0.9": float((rs >= 0.9).mean()) if len(rs) else None,
            "abs_bias_median": float(np.median(np.abs(bs))) if len(bs) else None,
        }
    out = {
        "schema": "die-atlas-district-qa/1.0",
        "method": "centroid containment assignment against the v1.0 fabric "
                  "(flat ring lists; holes ignored - a tiny documented "
                  "approximation); a polygon straddling a boundary goes "
                  "wholly to the centroid side - QA only, never published "
                  "(register OD4)",
        "atlas_polygons_with_code": len(polys),
        "atlas_polygons_with_series": len(have),
        "atlas_polygons_skipped_no_series": skipped_no_series,
        "v1_districts_with_atlas_series": len(assignment),
        "centroids_outside_724_fabric": unmatched,
        "overlap_window": [1981, 2025],
        "summary": summ,
        "per_district": stats,
    }
    (HERE / "work").mkdir(exist_ok=True)
    (HERE / "work" / "district_qa.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    with (HERE / "work" / "district_qa.csv").open("w", newline="",
                                                 encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# QA ONLY - Atlas 732-series vs promoted era-A store",
                    "", "", "", "", ""])
        w.writerow(["# generated", hashlib.sha256(
            json.dumps(out, sort_keys=True).encode()).hexdigest()[:16],
            "", "", "", ""])
        w.writerow(["district_id", "variable", "n_months", "r", "mean_bias"])
        for s in stats:
            w.writerow([s["district_id"], s["variable"], s["n_months"],
                        f"{s['r']:.4f}", f"{s['mean_bias']:.4f}"])
    return out


def main() -> int:
    cfg = HERE / "config" / "atlas.yaml"
    out = run(cfg, REPO / "data" / "parquet" / "atlas")
    print(json.dumps(out["summary"], indent=1))
    print("coverage:", out["v1_districts_with_atlas_series"], "districts;",
          out["atlas_polygons_skipped_no_series"], "polygons without series;",
          out["centroids_outside_724_fabric"], "centroids unmatched")
    # attach the summary to metadata.json era_a (additive, deterministic)
    md_path = REPO / "data" / "metadata.json"
    md = json.loads(md_path.read_text(encoding="utf-8"))
    if "era_a" in md:
        md["era_a"]["district_qa"] = {
            "method": out["method"],
            "window": out["overlap_window"],
            "summary": out["summary"],
            "artifacts": ["atlas-pipeline/work/district_qa.json",
                          "atlas-pipeline/work/district_qa.csv"],
        }
        md_path.write_text(json.dumps(md, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        print("metadata.json era_a.district_qa attached")
    print("DISTRICT QA DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
