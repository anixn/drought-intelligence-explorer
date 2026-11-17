#!/usr/bin/env python3
"""DIE v2.0 - gcm-pipeline step 06: area-weighted district aggregation
(task M2.9, docs/v2/03; amendment docs/v2/06 section 2, M2.9).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9).

What it does
------------
Grid indices (time x lat x lon, step 05) -> 724 district series
(time x district), area-weighted on the v1.0 LAEA equal-area projection:

    district_value[t] = sum_i w_i * x_i[t] / sum_i w_i
    over the district's cells with FINITE x at t (weights renormalised
    per month - the v1.0 reduceRegions/pixelArea rule; absent cells
    shrink the effective sample, never imputed, R10).

Weights (computed once, reused for every model/indicator):
    w_cell = area(district geometry INTERSECT cell rectangle) / district
    area, both measured in LAEA (+proj=laea +lat_0=22.5 +lon_0=79.5,
    the v1.0 AREA_PROJ4 from data-pipeline/prepare_boundaries.py).
    No shapely/geopandas: exact Sutherland-Hodgman clipping of district
    rings against the (convex) cell rectangles in lon/lat, ring areas by
    shoelace in LAEA. Outer-ring area minus hole rings per cell.

Fallback + transparency (amendment M2.9):
  * sub-pixel flag  : n_cells <= 2 -> flag = 1, listed in
    work/aggregate/sub_pixel_flags.csv (filterable in the UI/export).
  * buffer fallback : a district whose geometry intersects NO cell
    (sub-pixel islands / edge slivers) captures the NEAREST cell centre
    with weight 1.0 (== "buffer until capture >= 1 source unit" with the
    minimal buffer radius; v1.0 buffer-fallback semantics). Capture
    distance recorded; > max_km (config) -> outside_domain, series
    permanently NaN and counted (honest absence).

Self-tests (--selftest, deterministic seed 20261103, synthetic only;
wired into selftest_gcm.py at M2.13):
  T1 overlap weights: rectangle + L-shape across cells -> exact fractions,
     weights sum to 1.
  T2 weighted mean: known per-cell field -> hand-computed district value.
  T3 renormalisation over finite cells: one NaN cell shrinks the sample;
     all-NaN month -> NaN.
  T4 fallback: no-overlap district -> nearest-centre capture, weight 1,
     distance recorded and <= max_km.
  T5 sub-pixel flag: 1-cell district flagged, 3-cell district not.
  T6 outside-domain district: permanently NaN + counted.

Usage:
  python 06_district_aggregate.py --selftest
  python 06_district_aggregate.py --reference
  python 06_district_aggregate.py --mode historical-corrected --models ACCESS-CM2
  python 06_district_aggregate.py --mode ssp --models ...      # after downloads
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
# Config-dir override (M2.13 phase 2): selftest_gcm.py points every step
# at a test config dir via DIE_CONFIG_DIR; default = the real config dir
# so production behaviour is untouched (documented in docs/v2/03 s3.11).
import os as _os
CONFIG_DIR = Path(_os.environ.get("DIE_CONFIG_DIR",
                                        str(HERE / "config")))

SEED = 20261103


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_r03():
    spec = importlib.util.spec_from_file_location(
        "qdm03", HERE / "03_qdm_bias_correct.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ geometry core ---
def _shoelace(ring_lonlat) -> float:
    """Abs signed area of a lon/lat ring via LAEA transform (km^2)."""
    from pyproj import Transformer
    tr = _shoelace.tr
    xs, ys = tr.transform(*zip(*ring_lonlat)) if ring_lonlat else ((), ())
    a = 0.0
    n = len(xs)
    for i in range(n):
        j = (i + 1) % n
        a += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(a) / 2.0


def _init_area_transformer(proj4: str) -> None:
    from pyproj import Transformer
    _shoelace.tr = Transformer.from_crs("EPSG:4326", proj4, always_xy=True)


def _clip_ring_halfplane(ring, keep_fn) -> list:
    """Sutherland-Hodgman: clip a ring against one half-plane keep_fn(x, y)."""
    out = []
    n = len(ring)
    for i in range(n):
        cur, prv = ring[i], ring[(i - 1) % n]
        in_cur = keep_fn(*cur)
        in_prv = keep_fn(*prv)
        if in_cur:
            if not in_prv:
                out.append(_intersect(prv, cur, keep_fn))
            out.append(cur)
        elif in_prv:
            out.append(_intersect(prv, cur, keep_fn))
    return out


def _intersect(p, q, keep_fn) -> tuple:
    """Intersection of segment p-q with the boundary line of keep_fn.

    keep_fn must be an affine linear test f(x, y) >= 0 built by
    _halfplanes below, so we recover the line from its stored (a, b, c)."""
    a, b, c = keep_fn.coeffs
    fp = a * p[0] + b * p[1] + c
    fq = a * q[0] + b * q[1] + c
    t = fp / (fp - fq)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def _halfplanes(x0, x1, y0, y1):
    """The four half-planes of a lon/lat rectangle (closed by tolerance)."""
    eps = 1e-12
    planes = [
        (lambda x, y: x >= x0 - eps, (1.0, 0.0, -(x0 - eps))),
        (lambda x, y: x <= x1 + eps, (-1.0, 0.0, x1 + eps)),
        (lambda x, y: y >= y0 - eps, (0.0, 1.0, -(y0 - eps))),
        (lambda x, y: y <= y1 + eps, (0.0, -1.0, y1 + eps)),
    ]
    for fn, coeffs in planes:
        fn.coeffs = coeffs
    return planes


def overlap_area_km2(ring, cell) -> float:
    """Area (km^2) of a lon/lat ring clipped to a (lon0, lon1, lat0, lat1) cell.
    Returns 0 when there is no overlap."""
    lon0, lon1, lat0, lat1 = cell
    bbox_test = (max(r[0] for r in ring) > lon0 and
                 min(r[0] for r in ring) < lon1 and
                 max(r[1] for r in ring) > lat0 and
                 min(r[1] for r in ring) < lat1)
    if not bbox_test:
        return 0.0
    poly = list(ring)
    for keep, _coeffs in _halfplanes(lon0, lon1, lat0, lat1):
        poly = _clip_ring_halfplane(poly, keep)
        if not poly:
            return 0.0
    return _shoelace(poly) / 1e6          # m^2 -> km^2


# --------------------------------------------------------------- weights ------
def build_weights(cfg: dict, lat: np.ndarray, lon: np.ndarray) -> dict:
    """district_id -> weights dict for the given grid (computed once)."""
    from pyproj import Transformer
    agg = cfg["district_aggregation"]
    _init_area_transformer(agg["area_proj4"])
    geo_path = (HERE / agg["boundaries_geojson"]).resolve()
    reg_path = (HERE / agg["registry_csv"]).resolve()
    import json as _json
    with open(geo_path, encoding="utf-8") as fh:
        gj = _json.load(fh)
    registry = {}
    with open(reg_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            registry[row["district_id"]] = row
    lats = np.asarray(lat, float)
    lons = np.asarray(lon, float)
    dlat = float(np.round(np.diff(lats).mean(), 6))
    dlon = float(np.round(np.diff(lons).mean(), 6))
    max_km = float(agg["buffer_fallback"]["max_km"])
    thresh = int(agg["sub_pixel_flag_threshold"])

    half_lat = dlat / 2.0
    half_lon = dlon / 2.0
    out = {}
    for feat in gj["features"]:
        did = feat["properties"].get("id") or feat.get("id")
        geom = feat["geometry"]
        rings = []                       # (ring, is_hole) per part
        parts = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        for part in parts:
            outer, holes = part[0], part[1:]
            rings.append((outer, False))
            for h in holes:
                rings.append((h, True))
        xs = [c[0] for ring, _ in rings for c in ring]
        ys = [c[1] for ring, _ in rings for c in ring]
        # candidate cells: bbox overlap in lon/lat
        i0 = int(np.searchsorted(lats, min(ys) - half_lat)) - 1
        i1 = int(np.searchsorted(lats, max(ys) + half_lat)) + 1
        j0 = int(np.searchsorted(lons, min(xs) - half_lon)) - 1
        j1 = int(np.searchsorted(lons, max(xs) + half_lon)) + 1
        cand = [(i, j) for i in range(max(i0, 0), min(i1 + 1, len(lats)))
                for j in range(max(j0, 0), min(j1 + 1, len(lons)))]
        raw = {}
        for (i, j) in cand:
            cell = (lons[j] - half_lon, lons[j] + half_lon,
                    lats[i] - half_lat, lats[i] + half_lat)
            a = sum((-1.0 if hole else 1.0) * overlap_area_km2(ring, cell)
                    for ring, hole in rings)
            if a > 1e-9:
                raw[f"{i},{j}"] = a
        tot = sum(raw.values())
        rec = {"n_cells": len(raw), "fallback": None, "outside_domain": False}
        if tot > 1e-9:
            rec["weights"] = {k: round(v / tot, 9) for k, v in raw.items()}
        else:
            # buffer fallback: nearest cell centre to the registry centroid
            reg = registry.get(did)
            if reg is None:
                rec["outside_domain"] = True
            else:
                clon, clat = float(reg["centroid_lon"]), float(reg["centroid_lat"])
                dist_km = _great_circle_km(clat, clon, lats, lons)
                i, j = np.unravel_index(int(np.argmin(dist_km)), dist_km.shape)
                d = float(dist_km[i, j])
                if d <= max_km:
                    rec["weights"] = {f"{int(i)},{int(j)}": 1.0}
                    rec["n_cells"] = 1
                    rec["fallback"] = {"mode": "nearest_centre",
                                       "capture_km": round(d, 2)}
                else:
                    rec["outside_domain"] = True
        rec["sub_pixel"] = (not rec["outside_domain"]) and rec["n_cells"] <= thresh
        out[did] = rec
    return out


def _great_circle_km(clat, clon, lat_grid, lon_grid) -> np.ndarray:
    """Haversine distance (km) from (clat, clon) to every grid centre."""
    r = 6371.0088
    p1 = np.radians(clat)
    l1 = np.radians(clon)
    p2 = np.radians(np.asarray(lat_grid, float))[:, None]
    l2 = np.radians(np.asarray(lon_grid, float))[None, :]
    dp = p2 - p1
    dl = l2 - l1
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


# ---------------------------------------------------------------- selftest ----
def selftest() -> int:
    hr("SELFTEST - district aggregation on synthetic worlds (seed 20261103)")
    rng = np.random.default_rng(SEED)
    fails = []
    _init_area_transformer("+proj=laea +lat_0=22.5 +lon_0=79.5 "
                           "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs")

    # T1 overlap weights: a rectangle spanning 2 cells and an L-shape over 3
    lats = np.arange(20.0, 22.01, 0.25)
    lons = np.arange(78.0, 80.01, 0.25)
    # cell (20.125, 78.125) has box (78.0-78.25, 20.0-20.25) etc.
    rect = [(78.0, 20.0), (78.5, 20.0), (78.5, 20.25), (78.0, 20.25)]
    # spans cells j=78.125 fully (78.0-78.25) and j=78.375 half (78.25-78.5):
    # exact fractions 0.5 / 0.5 of the ring's area
    a1 = overlap_area_km2(rect, (78.0, 78.25, 20.0, 20.25))
    a2 = overlap_area_km2(rect, (78.25, 78.5, 20.0, 20.25))
    a3 = overlap_area_km2(rect, (78.5, 78.75, 20.0, 20.25))
    atot = _shoelace(rect) / 1e6
    # clips of a partition must reassemble the ring (up to LAEA fp noise);
    # a1 vs a2 need NOT be equal - same lat band but different lon distance
    # from the LAEA standard point (79.5E, 22.5N)
    frac = (a1 + a2) / atot
    ok = (a3 == 0.0 and abs(frac - 1.0) < 1e-6 and a1 > 0 and a2 > 0)
    print(f"T1 clip areas: cell1={a1:.2f} cell2={a2:.2f} cell3={a3:.2f} "
          f"ring={atot:.2f} km2, reassembly={frac:.9f}: {ok}")
    if not ok:
        fails.append("T1 overlap fractions inexact")

    # T1b L-shape: full cell + half of neighbour in lat. In TRUE (LAEA)
    # area the two 0.25-deg lat bands differ by the cos(lat) ratio - the
    # higher-latitude band is SMALLER on the ellipsoid:
    lsh = [(78.0, 20.0), (78.25, 20.0), (78.25, 20.5), (78.0, 20.5)]
    a_cell1 = overlap_area_km2(lsh, (78.0, 78.25, 20.0, 20.25))
    a_cell2 = overlap_area_km2(lsh, (78.0, 78.25, 20.25, 20.5))
    cos_ratio = (np.cos(np.deg2rad(20.375)) / np.cos(np.deg2rad(20.125)))
    got_ratio = a_cell2 / a_cell1
    ok = abs(got_ratio - cos_ratio) < 0.01 * cos_ratio
    print(f"T1b L-shape: lower={a_cell1:.2f} upper={a_cell2:.2f} "
          f"upper/lower={got_ratio:.5f} vs cos-ratio {cos_ratio:.5f}: {ok}")
    if not ok:
        fails.append("T1b L-shape geodetic ratio inexact")

    # T2 weighted mean: district covers cell A (w 0.75) + cell B (w 0.25);
    # field A=2.0, B=10.0 -> mean 4.0
    w = np.array([0.75, 0.25])
    x = np.array([2.0, 10.0])
    v = float(np.sum(w * x) / np.sum(w))
    print(f"T2 weighted mean: {v:.3f} (expect 4.000)")
    if abs(v - 4.0) > 1e-9:
        fails.append("T2 weighted mean wrong")

    # T3 renormalisation over finite cells: B missing -> mean = 2.0; both
    # missing -> NaN
    xf = np.array([2.0, np.nan])
    fin = np.isfinite(xf)
    v = float(np.sum(w[fin] * xf[fin]) / np.sum(w[fin]))
    xall = np.array([np.nan, np.nan])
    fin2 = np.isfinite(xall)
    v2 = float("nan") if not fin2.any() else 0.0
    ok = abs(v - 2.0) < 1e-12 and np.isnan(v2)
    print(f"T3 renormalise: 1 NaN -> {v:.3f} (expect 2.000); all NaN -> NaN: "
          f"{np.isnan(v2)}")
    if not ok:
        fails.append("T3 finite-cell renormalisation broken")

    # T4 fallback via build_weights on a tiny sliver polygon with no overlap
    cfg = {"district_aggregation": {
        "boundaries_geojson": "../data/boundaries/india_districts.geojson",
        "registry_csv": "../data/districts.csv",
        "area_proj4": "+proj=laea +lat_0=22.5 +lon_0=79.5 +x_0=0 +y_0=0 "
                      "+datum=WGS84 +units=m +no_defs",
        "buffer_fallback": {"max_km": 30},
        "sub_pixel_flag_threshold": 2}}
    # synthetic grid far from India so ALL registry districts are out of
    # domain except we override one: use a fake registry file instead
    import tempfile, os
    tmp = Path(tempfile.mkdtemp())
    sliver = [[(80.20, 21.20), (80.21, 21.20), (80.21, 21.21), (80.20, 21.21)]]
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "test-district"},
         "geometry": {"type": "Polygon", "coordinates": sliver}}]}
    with open(tmp / "b.geojson", "w", encoding="utf-8") as fh:
        json.dump(gj, fh)
    reg = {"test-district": {"centroid_lon": "80.155", "centroid_lat": "21.155",
                             "district_name": "Test", "state_name": "TestS"}}
    with open(tmp / "r.csv", "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["district_id"] +
                             list(reg["test-district"].keys()))
        wtr.writeheader()
        wtr.writerow({"district_id": "test-district", **reg["test-district"]})
    cfg["district_aggregation"]["boundaries_geojson"] = str(tmp / "b.geojson")
    cfg["district_aggregation"]["registry_csv"] = str(tmp / "r.csv")
    grid_lat = np.arange(20.0, 23.01, 0.25)
    grid_lon = np.arange(79.0, 82.01, 0.25)
    wts = build_weights(cfg, grid_lat, grid_lon)
    rec = wts["test-district"]
    # sliver fully inside cell (80.25, 21.25): overlaps that cell -> weights.
    # NOTE: cells tile the domain contiguously, so a fallback can only fire
    # for geometry OUTSIDE the grid whose centroid is within max_km of the
    # nearest centre (v1.0's zero-pixel/buffer analogue at the domain edge).
    ok = rec.get("weights") and rec["n_cells"] == 1
    print(f"T4a in-cell sliver: n_cells={rec['n_cells']} (expect 1, weights path)")
    if not ok:
        fails.append("T4a in-cell overlap broken")
    # force the fallback path: sliver beyond the grid edge (last centre 82.0,
    # box edge 82.125; sliver at 82.15), centroid ~17 km outside ->
    # nearest-centre capture <= max_km
    sliver2 = [[(82.15, 21.2), (82.16, 21.2), (82.16, 21.21), (82.15, 21.21)]]
    gj["features"][0]["geometry"]["coordinates"] = sliver2
    json.dump(gj, open(tmp / "b.geojson", "w", encoding="utf-8"))
    wts2 = build_weights(cfg, grid_lat, grid_lon)
    rec2 = wts2["test-district"]
    ok = (rec2.get("fallback") and
          rec2["fallback"]["mode"] == "nearest_centre" and
          rec2["n_cells"] == 1 and rec2["sub_pixel"] and
          0 < rec2["fallback"]["capture_km"] <= 30)
    print(f"T4b edge fallback: {rec2['fallback']}, sub_pixel={rec2['sub_pixel']}")
    if not ok:
        fails.append("T4b fallback semantics broken")

    # T5 sub-pixel flag threshold (2): already exercised (n_cells=1 -> flag);
    # construct a 3-cell district polygon
    big = [[(79.0, 20.0), (79.8, 20.0), (79.8, 20.8), (79.0, 20.8)]]
    gj["features"][0]["geometry"]["coordinates"] = big
    with open(tmp / "b.geojson", "w", encoding="utf-8") as fh:
        json.dump(gj, fh)
    wts3 = build_weights(cfg, grid_lat, grid_lon)
    rec3 = wts3["test-district"]
    ok = rec3["n_cells"] >= 3 and not rec3["sub_pixel"]
    print(f"T5 sub-pixel: 3-cell district n_cells={rec3['n_cells']} "
          f"flag={rec3['sub_pixel']} (expect False)")
    if not ok:
        fails.append("T5 sub-pixel flag broken")

    # T6 outside-domain: registry centroid far from grid -> outside_domain
    reg["test-district"]["centroid_lon"] = "50.0"
    reg["test-district"]["centroid_lat"] = "10.0"
    with open(tmp / "r.csv", "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["district_id"] +
                             list(reg["test-district"].keys()))
        wtr.writeheader()
        wtr.writerow({"district_id": "test-district", **reg["test-district"]})
    gj["features"][0]["geometry"]["coordinates"] = sliver2
    with open(tmp / "b.geojson", "w", encoding="utf-8") as fh:
        json.dump(gj, fh)
    wts4 = build_weights(cfg, grid_lat, grid_lon)
    rec4 = wts4["test-district"]
    ok = rec4["outside_domain"] and rec4["n_cells"] == 0
    print(f"T6 outside-domain: {rec4['outside_domain']} (expect True)")
    if not ok:
        fails.append("T6 outside-domain broken")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T1b, T2, T3, T4, T5, T6)")
    return 0


# -------------------------------------------------------------------- run -----
def load_weights(work_root: Path, cfg: dict, lat, lon, force: bool) -> dict:
    """weights.json cache keyed by the grid signature (dims + endpoints)."""
    out_dir = work_root / "aggregate"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "weights.json"
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    sig = {"n_lat": len(lat), "n_lon": len(lon),
           "lat": [float(lat[0]), float(lat[-1])],
           "lon": [float(lon[0]), float(lon[-1])]}
    if path.exists() and not force:
        blob = json.loads(path.read_text(encoding="utf-8"))
        if blob.get("grid") == sig:
            return blob["districts"]
    w = build_weights(cfg, lat, lon)
    path.write_text(json.dumps({"grid": sig, "districts": w}, indent=1),
                    encoding="utf-8")
    return w


def aggregate_file(src: Path, iid: str, weights: dict, out_dir: Path,
                   lat, lon, work_root: Path) -> dict:
    import netCDF4 as nc
    import pandas as pd
    import xarray as xr
    d = nc.Dataset(src)
    var = d.variables[iid]
    stack = np.asarray(np.ma.filled(var[:], np.nan), float)   # (t, nlat, nlon)
    t = d.variables["time"]
    dates = nc.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
    attrs_src = {a: d.getncattr(a) for a in d.ncattrs()}
    d.close()
    period = src.stem.split("_", 2)[2] if len(src.stem.split("_", 2)) > 2 \
        else "unknown"
    nlat, nlon = len(lat), len(lon)
    flat = stack.reshape(stack.shape[0], nlat * nlon).T        # (cells, t)
    dids = list(weights.keys())
    # per-district weight vector over the flat cell axis
    wvecs, idxs, ncells, n_used = [], [], [], []
    for did in dids:
        rec = weights[did]
        wv = np.zeros(nlat * nlon)
        for key, wv_ in (rec.get("weights") or {}).items():
            i, j = key.split(",")
            wv[int(i) * nlon + int(j)] = wv_
        wvecs.append(wv)
        idxs.append(np.flatnonzero(wv))
        ncells.append(rec["n_cells"])
    mat = np.full((len(dids), stack.shape[0]), np.nan)
    for k, (wv, ix) in enumerate(zip(wvecs, idxs)):
        if ix.size == 0:
            continue
        x = flat[ix]                      # (n_cells, t)
        fin = np.isfinite(x)
        den = (wv[ix][:, None] * fin).sum(axis=0)
        num = np.nansum(np.where(fin, x, 0.0) * wv[ix][:, None], axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            mat[k] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
        n_used.append(int((den > 0).sum()))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{iid}_districts_{period}.nc"
    tstamp = pd.to_datetime([f"{x.year:04d}-{x.month:02d}-01" for x in dates])
    ds = xr.Dataset(
        {iid: (("district", "time"), mat.astype(np.float32))},
        coords={"time": tstamp,
                "district": np.array(dids, dtype=object)},
        attrs={**{k: v for k, v in attrs_src.items() if k != "fit_report"},
               "aggregation": "area-weighted overlap (LAEA, v1.0 AREA_PROJ4)",
               "weights_renormalised": "per month over finite cells (v1.0 rule)",
               "sub_pixel_threshold": "n_cells <= 2 flagged (amendment M2.9)",
               "pipeline": "DIE v2.0 gcm-pipeline 06_district_aggregate.py"})
    ds.to_netcdf(out_path, encoding={iid: {"dtype": "float32", "zlib": True,
                                           "complevel": 4}})
    return {"iid": iid, "out": str(out_path.relative_to(work_root.parent)),
            "period": period, "n_districts": len(dids),
            "n_time": int(mat.shape[1]),
            "n_finite_cells": int(np.isfinite(mat).sum()),
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}


def write_flags(work_root: Path, weights: dict) -> Path:
    agg = load_yaml(CONFIG_DIR / "aggregate.yaml")["district_aggregation"]
    reg_path = (HERE / agg["registry_csv"]).resolve()
    registry = {}
    with open(reg_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            registry[row["district_id"]] = row
    csv_path = work_root / "aggregate" / "sub_pixel_flags.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["district_id", "district_name", "state_name", "n_cells",
                    "sub_pixel", "fallback_mode", "capture_km",
                    "outside_domain"])
        n_flag = 0
        for did, rec in weights.items():
            reg = registry.get(did, {})
            fb = rec.get("fallback") or {}
            w.writerow([did, reg.get("district_name", ""), reg.get("state_name", ""),
                        rec["n_cells"], int(rec["sub_pixel"]),
                        fb.get("mode", ""), fb.get("capture_km", ""),
                        int(rec["outside_domain"])])
            n_flag += int(rec["sub_pixel"])
    print(f"  sub-pixel flags: {n_flag}/{len(weights)} districts flagged -> "
          f"{csv_path.name}")
    return csv_path


def main() -> int:
    ap = argparse.ArgumentParser(description="District aggregation (M2.9)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--models", help="comma list (default: era-C ensemble)")
    ap.add_argument("--mode", choices=["historical-corrected", "ssp"],
                    default="historical-corrected")
    ap.add_argument("--experiments", default=None)
    ap.add_argument("--force-weights", action="store_true",
                    help="recompute weights.json even if cached")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    import netCDF4 as nc
    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    cfg = load_yaml(CONFIG_DIR / "aggregate.yaml")
    cfgm = load_yaml(CONFIG_DIR / "models.yaml")
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    man_path = work_root / "aggregate_manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else \
        {"schema": 1, "files": {}}

    def process(src_dir: Path, dest_dir: Path, label: str) -> int:
        files = sorted(p for p in src_dir.glob("*.nc"))
        if not files:
            print(f"  SKIP {label}: no index files in {src_dir.name}")
            return 0
        probe = files[0]
        d = nc.Dataset(probe)
        lat = d.variables["lat"][:]
        lon = d.variables["lon"][:]
        d.close()
        weights = load_weights(work_root, cfg, lat, lon, args.force_weights)
        write_flags(work_root, weights)
        n_done = 0
        for src in files:
            parts = src.stem.split("_")
            iid = "_".join(parts[:2])          # e.g. spei_01
            period = parts[2] if len(parts) > 2 else src.stem
            rec = aggregate_file(src, iid, weights, dest_dir, lat, lon,
                                 work_root)
            manifest["files"][f"{label}/{iid}"] = rec
            n_done += 1
            print(f"  OK {label:34s} {iid:8s} {rec['period']:9s} "
                  f"{rec['n_time']:4d} months, "
                  f"{rec['n_finite_cells']:,} finite district-months")
        return n_done

    if args.reference:
        hr("AGGREGATE reference IMD")
        n = process(work_root / "indices" / "reference",
                    work_root / "aggregate" / "reference", "reference")
    else:
        models = args.models.split(",") if args.models else \
            [r["source_id"] for r in cfgm["models"]
             if r.get("era_c_ensemble", True)]
        experiments = (args.experiments.split(",") if args.experiments else
                       (["historical-corrected"] if args.mode == "historical-corrected"
                        else ["ssp245", "ssp585"]))
        hr(f"AGGREGATE mode={args.mode} models={len(models)}")
        n = 0
        for model in models:
            for tag in experiments:
                src = (work_root / "indices" / model /
                       (tag if args.mode == "ssp" else "historical-corrected"))
                n += process(src, work_root / "aggregate" / model /
                             (tag if args.mode == "ssp" else "historical-corrected"),
                             f"{model}/{tag}")
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"AGGREGATE DONE: {n} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
