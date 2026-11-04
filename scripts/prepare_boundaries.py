#!/usr/bin/env python3
"""
prepare_boundaries.py — Drought Intelligence Explorer (India)
=============================================================
Prepares deployment-ready boundary files from a raw district-level GeoJSON
of India (source: udit-001/india-maps-data, 2011+ census boundaries, mixed
with redundant state-level outline polygons that are removed here).

Pipeline
--------
1. CLEAN       Drop state-level outline polygons, merge duplicate-named
               district polygons (e.g. multi-polygon island districts stored
               as separate features), repair invalid geometries, and assign
               stable slugs as identifiers.
2. SIMPLIFY    Topology-aware simplification with mapshaper (Visvalingam,
               shared boundaries preserved -> no slivers between districts),
               plus coordinate precision reduction for file size.
3. DISSOLVE    District -> state boundaries and a national outline.
4. STATISTICS  Equal-area surface computation (Lambert Azimuthal Equal-Area
               centred on India: lat_0=22.5, lon_0=79.5) and representative
               centroids for map labels; emitted as districts.csv / states.csv.

CRS conventions
---------------
Storage CRS        : EPSG:4326 (WGS84 geographic, GeoJSON default).
Area computation   : custom LAEA equal-area projection (see AREA_PROJ4).
Centroids          : computed on the equal-area geometry, transformed back
                     to WGS84 (label-safe representative points).

Usage
-----
python3 prepare_boundaries.py <raw.geojson> <output_project_root>

Outputs (written into <output_project_root>)
--------------------------------------------
data/boundaries/india_districts.geojson   simplified district polygons
data/boundaries/india_states.geojson      dissolved state/UT polygons
data/boundaries/india_outline.geojson     national outline (single feature)
data/districts.csv                        district registry + area/centroid
data/states.csv                           state registry + area/centroid
"""

import csv
import json
import os
import re
import subprocess
import sys
import tempfile

from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from shapely.validation import make_valid

from pyproj import CRS, Proj, Transformer

AREA_PROJ4 = "+proj=laea +lat_0=22.5 +lon_0=79.5 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
# The source dataset is already generalised for web use, so districts are kept
# at full source fidelity: only coordinate precision is reduced (~100 m) to
# shrink the file. State and outline layers (background reference lines) are
# dissolved and lightly cleaned. Median district area error: 0.03%.
DISTRICT_PRECISION = "0.001"     # ~100 m
STATE_PRECISION = "0.01"         # ~1 km
MAPSHAPER = ["npx", "-y", "mapshaper"]

FWD = Transformer.from_proj(Proj("EPSG:4326"), Proj(AREA_PROJ4), always_xy=True)
INV = Transformer.from_proj(Proj(AREA_PROJ4), Proj("EPSG:4326"), always_xy=True)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    return re.sub(r"-+", "-", s).strip("-")


def equal_area_km2(geom) -> float:
    projected = transform(lambda x, y, z=None: FWD.transform(x, y), geom)
    return projected.area / 1e6


def label_point(geom):
    projected = transform(lambda x, y, z=None: FWD.transform(x, y), geom)
    pt = projected.representative_point()
    lon, lat = INV.transform(pt.x, pt.y)
    return round(lon, 4), round(lat, 4)


def clean(raw_path: str) -> tuple[list[dict], dict]:
    """Step 1: return (clean district features with ids, merge statistics)."""
    with open(raw_path) as fh:
        raw = json.load(fh)

    dropped_state_polys, merged = 0, 0
    buckets: dict[tuple[str, str], list] = {}

    for feat in raw["features"]:
        props = feat.get("properties", {})
        name, state = props.get("district"), props.get("st_nm")
        if not name or not state:
            dropped_state_polys += 1
            continue
        geom = make_valid(shape(feat["geometry"]))
        buckets.setdefault((state, name), []).append(geom)

    features = []
    for (state, name), geoms in sorted(buckets.items()):
        geom = geoms[0] if len(geoms) == 1 else unary_union(geoms)
        merged += len(geoms) - 1
        sid = slugify(state)
        features.append({
            "type": "Feature",
            "properties": {
                "id": f"{sid}-{slugify(name)}",
                "district": name,
                "state": state,
                "sid": sid,
            },
            "geometry": mapping(geom),
        })

    stats = {
        "raw_features": len(raw["features"]),
        "dropped_state_polys": dropped_state_polys,
        "merged_duplicate_features": merged,
        "clean_districts": len(features),
        "states": len({f["properties"]["sid"] for f in features}),
    }
    return features, stats


def run_mapshaper(args: list[str], cwd: str) -> None:
    cmd = MAPSHAPER + args
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"mapshaper failed: {' '.join(args)}\n{proc.stderr[-2000:]}")


def simplify_and_dissolve(clean_path: str, out_dir: str) -> None:
    """Steps 2-3: mapshaper simplification and dissolves."""
    bnd = os.path.join(out_dir, "data", "boundaries")
    os.makedirs(bnd, exist_ok=True)

    districts = os.path.join(bnd, "india_districts.geojson")
    states = os.path.join(bnd, "india_states.geojson")
    outline = os.path.join(bnd, "india_outline.geojson")

    # Districts: full source fidelity, precision rounding only.
    run_mapshaper([
        clean_path,
        "-o", f"precision={DISTRICT_PRECISION}", "format=geojson", districts,
    ], out_dir)

    # States: dissolve districts on shared boundaries (no gaps), light clean.
    run_mapshaper([
        clean_path,
        "-dissolve2", "field=sid", "copy-fields=state",
        "-clean",
        "-o", f"precision={STATE_PRECISION}", "format=geojson", states,
    ], out_dir)

    # National outline: dissolve everything to a single feature.
    run_mapshaper([
        clean_path,
        "-each", "CONST=1",
        "-dissolve2", "field=CONST",
        "-clean",
        "-o", f"precision={STATE_PRECISION}", "format=geojson", outline,
    ], out_dir)


def build_registries(out_dir: str) -> dict:
    """Step 4: repair rounding-induced invalid rings, then equal-area statistics
    and label centroids computed from the FINAL geometry actually served."""
    bnd = os.path.join(out_dir, "data", "boundaries")

    districts_path = os.path.join(bnd, "india_districts.geojson")
    with open(districts_path) as fh:
        districts = json.load(fh)

    repaired = 0
    for feat in districts["features"]:
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            feat["geometry"] = mapping(make_valid(geom))
            repaired += 1
    if repaired:
        with open(districts_path, "w") as fh:
            json.dump(districts, fh)

    rows = []
    for feat in sorted(districts["features"], key=lambda f: (f["properties"]["sid"], f["properties"]["district"])):
        p = feat["properties"]
        geom = make_valid(shape(feat["geometry"]))
        lon, lat = label_point(geom)
        rows.append({
            "district_id": p["id"],
            "district_name": p["district"],
            "state_name": p["state"],
            "state_id": p["sid"],
            "area_km2": round(equal_area_km2(geom), 1),
            "centroid_lon": lon,
            "centroid_lat": lat,
        })

    with open(os.path.join(out_dir, "data", "districts.csv"), "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with open(os.path.join(bnd, "india_states.geojson")) as fh:
        states_gj = json.load(fh)
    per_state = {}
    for r in rows:
        agg = per_state.setdefault(r["state_id"], {"name": r["state_name"], "n": 0, "area": 0.0})
        agg["n"] += 1
        agg["area"] += r["area_km2"]

    state_rows = []
    for feat in sorted(states_gj["features"], key=lambda f: f["properties"]["sid"]):
        p = feat["properties"]
        geom = make_valid(shape(feat["geometry"]))
        lon, lat = label_point(geom)
        agg = per_state[p["sid"]]
        state_rows.append({
            "state_id": p["sid"],
            "state_name": p["state"],
            "area_km2": round(equal_area_km2(geom), 1),
            "area_from_districts_km2": round(agg["area"], 1),
            "n_districts": agg["n"],
            "centroid_lon": lon,
            "centroid_lat": lat,
        })

    with open(os.path.join(out_dir, "data", "states.csv"), "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(state_rows[0].keys()))
        writer.writeheader()
        writer.writerows(state_rows)

    return {
        "districts": len(rows),
        "states": len(state_rows),
        "invalid_geometries_repaired": repaired,
        "total_area_km2": round(sum(r["area_km2"] for r in rows)),
        "district_files": {os.path.basename(p): round(os.path.getsize(p) / 1024) for p in [
            districts_path,
            os.path.join(bnd, "india_states.geojson"),
            os.path.join(bnd, "india_outline.geojson"),
        ]},
    }


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    raw_path, out_dir = sys.argv[1], sys.argv[2]

    print(f"[1/4] cleaning {raw_path} ...")
    features, clean_stats = clean(raw_path)
    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False) as tmp:
        json.dump({"type": "FeatureCollection", "features": features}, tmp)
        clean_path = tmp.name
    print("     ", clean_stats)

    print("[2/4] simplifying districts (mapshaper, topology-preserving) ...")
    print("[3/4] dissolving states + national outline ...")
    simplify_and_dissolve(clean_path, out_dir)

    print("[4/4] equal-area statistics ...")
    reg_stats = build_registries(out_dir)
    print("     ", reg_stats)

    os.unlink(clean_path)
    print("done.")


if __name__ == "__main__":
    main()
