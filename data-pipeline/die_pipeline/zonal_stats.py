"""Step 3 — area-weighted district statistics from the prepared rasters.

For every variable (precip, pet, soil, ndvi) and every monthly GeoTIFF:

  * district mean of valid pixels, weighted by cos(latitude) of the pixel
    centre so that pixel-area differences on the lat/lon grid are accounted
    for (the grids are regular; the sinusoidal NDVI input has already been
    resampled to geographic in step 2). Weights are spherical cos-latitude
    and identical for every month; the GEE route uses ellipsoidal
    pixelArea() instead. Both are time-constant, so any sub-percent route
    difference cancels in the standardised indicators;
  * valid_pixel_count / total_pixel_count per district (the app's data
    contract carries completeness, and the guide recommends spot-checks
    against these numbers);
  * districts smaller than one pixel are re-rasterised with
    all_touched=True so that no district silently disappears.

Output: <processed>/series/<var>.csv (long format)
    district_id, district_name, state_name, date, mean,
    valid_pixel_count, total_pixel_count

Usage
-----
    python -m die_pipeline.zonal_stats [--var precip pet soil ndvi]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np

from . import common

try:
    import rasterio
    from rasterio.features import rasterize
except ImportError:            # pragma: no cover
    rasterio = None

TIF_RE = re.compile(r"^\d{4}-\d{2}$")


# ---------------------------------------------------------------------------#

def load_boundaries(cfg: dict) -> list[dict]:
    p = common.boundaries_path(cfg)
    with open(p, encoding="utf-8") as fh:
        gj = json.load(fh)
    feats = []
    for f in gj["features"]:
        props = f["properties"]
        feats.append({"id": props.get("id"), "geometry": f["geometry"],
                      "name": props.get("district"), "state": props.get("state")})
    return feats


def _labels_for_grid(cfg: dict, feats, ids_index, transform, width, height):
    """Rasterise district polygons to an int32 label array (0 = outside)."""
    shapes = [(f["geometry"], ids_index[f["id"]]) for f in feats if f["id"] in ids_index]
    labels = rasterize(shapes, out_shape=(height, width),
                       transform=transform, fill=0, dtype="int32",
                       all_touched=False)
    totals = np.bincount(labels.ravel(), minlength=len(ids_index) + 1)[1:]

    if cfg["zonal"].get("all_touched_fallback", True):
        missing = [i for i in range(1, len(ids_index) + 1) if totals[i - 1] == 0]
        if missing:
            shapes_at = []
            for f in feats:
                idx = ids_index.get(f["id"])
                if idx in missing:
                    shapes_at.append((f["geometry"], idx))
            at = rasterize(shapes_at, out_shape=(height, width),
                           transform=transform, fill=0, dtype="int32",
                           all_touched=True)
            labels = np.where(labels == 0, at, labels)
            totals = np.bincount(labels.ravel(), minlength=len(ids_index) + 1)[1:]
    return labels, totals


def run_var(cfg: dict, var: str, districts: list[dict]) -> str:
    vdir = common.processed_dir(cfg, "rasters", cfg["variables"][var]["dir"])
    files = sorted(f for f in glob.glob(os.path.join(vdir, "*.tif"))
                   if TIF_RE.match(os.path.basename(f)[:-4]))
    if not files:
        print(f"  {var}: no prepared rasters — skipped")
        return ""

    ids = [d["district_id"] for d in districts]
    ids_index = {d_id: i + 1 for i, d_id in enumerate(ids)}
    feats = load_boundaries(cfg)
    unknown = {f["id"] for f in feats} - set(ids)
    if unknown:
        print(f"  {var}: WARNING {len(unknown)} boundary ids missing from the "
              "registry (e.g. " + ", ".join(sorted(unknown)[:3]) + ") — ignored")

    area_weighted = cfg["zonal"].get("area_weighted", True)
    lo, hi = cfg["variables"][var]["valid_range"]

    grid_cache = {}
    rows = []
    for path in files:
        yms = os.path.basename(path)[:-4]
        with rasterio.open(path) as ds:
            key = (ds.width, ds.height, tuple(np.round(np.array(ds.transform)[:6], 9)))
            if key not in grid_cache:
                grid_cache[key] = _labels_for_grid(cfg, feats, ids_index,
                                                   ds.transform, ds.width, ds.height)
            labels, totals = grid_cache[key]
            arr = ds.read(1).astype(np.float32)
            row_lats = None
            if area_weighted:
                # latitude of each pixel-row centre from the affine (audit F7:
                # the pixel centre, not the row's northern edge)
                rows_n = np.arange(ds.height)
                row_lats = np.array([ds.transform * (0, r + 0.5)
                                     for r in rows_n])[:, 1]
                w_row = np.cos(np.deg2rad(row_lats))[:, None]
            else:
                w_row = np.ones((ds.height, 1), dtype=np.float32)

        valid = np.isfinite(arr) & (arr >= lo) & (arr <= hi)
        w = np.where(valid, w_row, 0.0).astype(np.float64)
        wv = np.where(valid, arr * w_row, 0.0).astype(np.float64)

        nbins = len(ids) + 1
        wsum = np.bincount(labels.ravel(), weights=w.ravel(), minlength=nbins)
        vsum = np.bincount(labels.ravel(), weights=wv.ravel(), minlength=nbins)
        nvalid = np.bincount(labels.ravel(), weights=valid.ravel().astype(np.float64),
                             minlength=nbins)

        with np.errstate(invalid="ignore", divide="ignore"):
            means = vsum[1:] / wsum[1:]
        means = np.where(wsum[1:] > 0, means, np.nan)

        for i, d in enumerate(districts):
            rows.append({
                "district_id": d["district_id"],
                "district_name": d["district_name"],
                "state_name": d["state_name"],
                "date": yms,
                "mean": float(means[i]) if np.isfinite(means[i]) else "",
                "valid_pixel_count": int(nvalid[i + 1]),
                "total_pixel_count": int(totals[i]),
            })

    out = common.processed_file(cfg, "series", f"{var}.csv")
    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    n_months = len(files)
    zero_px = int((np.asarray([r["total_pixel_count"] for r in rows[:len(districts)]]) == 0).sum())
    print(f"  {var}: {n_months} months x {len(districts)} districts -> {os.path.basename(out)}"
          + (f" ({zero_px} districts below pixel size)" if zero_px else ""))
    return out


def main(argv=None) -> int:
    if rasterio is None:
        common.die("rasterio is required (pip install rasterio)")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--var", nargs="*", default=None,
                    help="subset of variables (default: all found)")
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    districts, _states = common.load_registry(cfg)
    common.banner(f"Zonal statistics — {len(districts)} districts")

    vars_ = args.var or list(cfg["variables"].keys())
    for var in vars_:
        run_var(cfg, var, districts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
