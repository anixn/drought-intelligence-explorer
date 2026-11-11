"""Google Earth Engine route — steps 1-3 replaced by server-side extraction.

The reference pipeline (download -> prepare_rasters -> zonal_stats) is
replaced here by Earth Engine compositing and area-weighted district
aggregation. The output is deliberately identical to ``zonal_stats.py``:

    <processed>/series/{precip,pet,soil,ndvi}.csv
        district_id, district_name, state_name, date, mean,
        valid_pixel_count, total_pixel_count

Steps 4-6 (``indicators.py``, ``export_app.py``, ``validate.py``) are then
run unchanged, so every file under ``data/`` keeps the same schema and the
same scientific definitions.

Why not compute SPI/SPEI in Earth Engine?
-----------------------------------------
SPI and SPEI need a per-district, per-calendar-month gamma / log-logistic
maximum-likelihood fit over a 30-year base period and an inverse-normal
transform. Earth Engine has no gamma/log-logistic MLE reducer and the fit
is a small, well-tested client-side operation in ``indicators.py``. GEE is
therefore used for what it is good at (petabyte-scale monthly compositing
and zonal statistics); the statistical transforms stay in the reference
Python code.

Datasets used (see ``config.yaml`` -> ``gee.datasets``):
    precipitation  UCSB-CHG/CHIRPS/DAILY              mm/day -> mm/month
    PET            ECMWF/ERA5_LAND/MONTHLY_AGGR       m/month -> mm/month
    soil moisture  ECMWF/ERA5_LAND/MONTHLY_AGGR       layers 1-3 -> % vol.
    NDVI           MODIS/061/MOD13A3                  scale 0.0001

Note: the Earth Engine CHIRPS asset is currently the v2.0 Final product.
The local download route in this repository targets CHIRPS v3.0. Do not mix
the two versions inside one climatology; the GEE metadata block records
which version was used.

Usage
-----
    python -m die_pipeline.gee_export --project ee-yourproject --end 2025-12
    python -m die_pipeline.gee_export --project ee-yourproject \
        --start 2000-01 --end 2025-12 --vars precip ndvi

By default the extraction is followed automatically by the indicator
computation, the application export and validation, so a single run
writes everything the dashboard reads (data/drought/*.csv,
data/summaries/*.csv, data/metadata.json). Pass --no-postprocess to stop
after the series files. The orchestrator offers the same chain:

    python run.py gee --project ee-yourproject --end 2025-12
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
from datetime import date, datetime, timezone

from . import common

VAR_ORDER = ("precip", "pet", "soil", "ndvi")

CHUNK_HEADER = [
    "district_id", "district_name", "state_name", "date", "mean",
    "valid_pixel_count", "total_pixel_count",
]

# Defaults mirror config.yaml -> gee.datasets. They are merged with the YAML
# so the module also works with an older config file.
DEFAULTS = {
    "precip": {
        "id": "UCSB-CHG/CHIRPS/DAILY",
        "band": "precipitation",
        "monthly": "sum",           # daily mm/day summed over the month
        "scale": 1.0,
        "abs": False,
    },
    "pet": {
        "id": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
        "band": "potential_evaporation_sum",
        "monthly": "first",         # one monthly-aggregate image per month
        "scale": 1000.0,            # m/month -> mm/month
        "abs": True,                # ECMWF sign convention: upward = negative
    },
    "soil": {
        "id": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
        "bands": [
            "volumetric_soil_water_layer_1",
            "volumetric_soil_water_layer_2",
            "volumetric_soil_water_layer_3",
        ],
        "monthly": "first",
        "scale": 100.0,             # m3/m3 -> % volumetric
        "abs": False,
    },
    "ndvi": {
        "id": "MODIS/061/MOD13A3",
        "band": "NDVI",
        "monthly": "first",
        "mosaic": True,            # MOD13A3 is tiled: mosaic the ~16-17
                                    # sinusoidal granules into one India image
        "scale": 0.0001,
        "abs": False,
        "start": "2000-02",         # first MOD13A3 month
    },
}


# ---------------------------------------------------------------------------#
# small helpers
# ---------------------------------------------------------------------------#

def _month_after(ym: str) -> str:
    """'2025-12' -> '2026-01'."""
    y, m = map(int, ym.split("-"))
    m += 1
    if m == 13:
        m, y = 1, y + 1
    return f"{y:04d}-{m:02d}"


def _month_tag(ym: str) -> str:
    """Band-name-safe tag: '1981-01' -> 'm198101'."""
    return "m" + ym.replace("-", "")


def _chunks(seq: list[str], size: int):
    size = max(1, int(size))
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _num(value):
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None       # drop NaN


def _specs(cfg: dict) -> dict:
    """Merge config.yaml overrides with the module defaults."""
    gee = cfg.get("gee") or {}
    overrides = gee.get("datasets") or {}
    out = {}
    for var in VAR_ORDER:
        spec = dict(DEFAULTS[var])
        spec.update(overrides.get(var) or {})
        lo, hi = cfg["variables"][var]["valid_range"]
        spec["valid_range"] = (float(lo), float(hi))
        out[var] = spec
    return out


def _var_months(var: str, spec: dict, start: str, end: str) -> list[str]:
    first = max(start, spec.get("start", start))
    if first > end:
        return []
    return [common.ym(t) for t in common.month_range(first, end)]


# ---------------------------------------------------------------------------#
# Earth Engine initialisation and boundaries
# ---------------------------------------------------------------------------#

def _init_ee(cfg: dict, project: str | None):
    try:
        import ee
    except ImportError:
        common.die(
            "earthengine-api is not installed. Activate the pipeline venv and "
            "run: pip install earthengine-api"
        )

    project = project or os.environ.get("EE_PROJECT") or (cfg.get("gee") or {}).get("project")
    if not project:
        common.die(
            "No Earth Engine project. Set gee.project in data-pipeline/config.yaml, "
            "pass --project, or export EE_PROJECT=<google-cloud-project-id>."
        )
    try:
        ee.Initialize(project=project)
    except Exception as exc:                              # noqa: BLE001
        common.die(
            "Earth Engine initialisation failed:\n"
            f"  {exc}\n\n"
            "One-time setup:\n"
            "  1. earthengine authenticate\n"
            "  2. create/select a Google Cloud project with the Earth Engine API enabled\n"
            "  3. pass --project <project-id> (or set gee.project in config.yaml)\n"
            "See data-pipeline/docs/gee-update-guide.md."
        )
    return ee


def _property_fields(ee, fc):
    """Find the name of the id/name/state properties in an asset."""
    try:
        keys = set(fc.first().toDictionary().keys().getInfo() or [])
    except Exception as exc:                              # noqa: BLE001
        common.die(f"could not inspect the boundary asset properties: {exc}")
    id_field = "district_id" if "district_id" in keys else ("id" if "id" in keys else None)
    if not id_field:
        common.die("boundary asset has neither a 'district_id' nor an 'id' property")
    return {
        "id": id_field,
        "name": "district_name" if "district_name" in keys else (
            "district" if "district" in keys else None),
        "state": "state_name" if "state_name" in keys else (
            "state" if "state" in keys else None),
    }


def _load_fc(ee, cfg: dict, asset: str | None):
    if asset:
        print(f"  boundaries: GEE asset {asset}")
        fc = ee.FeatureCollection(asset)
        fields = _property_fields(ee, fc)
        return fc, fields

    path = common.boundaries_path(cfg)
    with open(path, encoding="utf-8") as fh:
        gj = json.load(fh)
    features = []
    for f in gj.get("features", []):
        props = f.get("properties") or {}
        did = props.get("id")
        if not did:
            continue
        features.append(ee.Feature(ee.Geometry(f["geometry"]), {
            "district_id": did,
            "district_name": props.get("district") or did,
            "state_name": props.get("state") or "",
        }))
    if not features:
        common.die(f"no usable features in {path}")
    print(f"  boundaries: local GeoJSON {path} ({len(features)} features)")
    return ee.FeatureCollection(features), {
        "id": "district_id", "name": "district_name", "state": "state_name"}


def _upload_boundary(ee, fc, asset_id: str) -> None:
    if not asset_id.startswith("projects/"):
        common.die("--boundary-asset must look like "
                   "projects/<project>/assets/<name>")
    print(f"  uploading boundaries to {asset_id} (one-off, a few minutes) ...")
    task = ee.batch.Export.table.toAsset(
        collection=fc,
        description="die_india_districts_724",
        assetId=asset_id,
    )
    task.start()
    last = None
    while True:
        status = task.status()
        state = status.get("state")
        if state != last:
            print(f"    task {status.get('id', '')}: {state}")
            last = state
        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(15)
    if state != "COMPLETED":
        common.die(f"boundary asset export ended {state}: "
                   f"{status.get('error_message', 'no message')}\n"
                   "Upload data/boundaries/india_districts.geojson manually via "
                   "the Code Editor Assets tab if the task cannot be created.")


# ---------------------------------------------------------------------------#
# GEE images
# ---------------------------------------------------------------------------#

def _month_image_counts(ee, collection_id: str, start: str, end: str) -> dict[str, int]:
    """Number of images per YYYY-MM month present in the GEE collection.

    For a daily collection (CHIRPS) this is the number of published days in
    the month; for monthly-aggregate collections (ERA5-Land, MOD13A3) it is
    the number of granules covering the month (>= 1 = published).
    """
    col = ee.ImageCollection(collection_id).filterDate(
        f"{start}-01", f"{_month_after(end)}-01")
    times = col.aggregate_array("system:time_start").getInfo() or []
    counts: dict[str, int] = {}
    for t in times:
        if t is None:
            continue
        dt = datetime.fromtimestamp(float(t) / 1000.0, tz=timezone.utc)
        k = f"{dt.year:04d}-{dt.month:02d}"
        counts[k] = counts.get(k, 0) + 1
    return counts


def _gate_months(months_all: list[str], counts: dict[str, int],
                 day_gate: bool) -> tuple[list[str], list[str], list[str]]:
    """Split requested months into (extractable, short, missing).

    ``day_gate=True`` applies to daily collections that are summed per month
    (CHIRPS): a partially published month would be summed over its available
    days and read as a false drought (audit F2), so it is only extractable
    when every day of the month is published. Monthly-aggregate collections
    need a single image per month.
    """
    extractable: list[str] = []
    short: list[str] = []
    missing: list[str] = []
    for m in months_all:
        c = counts.get(m, 0)
        y, mo = int(m[:4]), int(m[5:7])
        n_days = common.days_in_month((y, mo))
        if c == 0:
            missing.append(m)
        elif day_gate and c < n_days:
            short.append(m)
        else:
            extractable.append(m)
    return extractable, short, missing


def _monthly_image(ee, spec: dict, ym: str):
    """One physical monthly image in the source's native projection."""
    col = ee.ImageCollection(spec["id"]).filterDate(
        f"{ym}-01", f"{_month_after(ym)}-01")

    if spec.get("monthly", "first") == "sum":
        img = col.select(spec["band"]).sum()
    elif spec.get("mosaic", False):
        # Tiled collections (MODIS sinusoidal tiles: ~16-17 granules cover
        # India per month) deliver the region as SEPARATE images. Taking
        # ``col.first()`` would rasterise one tile only and mask the rest of
        # the country to no-data. ``mosaic()`` composites the tiles, then
        # ``max`` reduces any same-day overlap to a single value.
        img = col.select(spec["band"]).mosaic()
    else:
        img = ee.Image(col.first())
    if spec.get("bands"):
        img = img.select(spec["bands"]).reduce(ee.Reducer.mean())
    else:
        img = img.select(spec["band"])

    if spec.get("abs"):
        img = img.abs()
    scale = float(spec.get("scale", 1.0))
    if scale != 1.0:
        img = img.multiply(scale)

    lo, hi = spec["valid_range"]
    img = img.updateMask(img.gte(lo).And(img.lte(hi)))
    return img.rename("value")


def _stats_image(ee, img):
    """Four bands needed for an area-weighted district mean.

    v = value x pixel area      (masked where the value is invalid)
    w = pixel area              (masked where the value is invalid)
    n = 1 where valid, 0 else   (valid pixel count)
    t = 1 everywhere            (total pixel count in the polygon)

    ``ee.Image.pixelArea()`` is used rather than a hand-made cos(latitude)
    weight, so the same code is correct for the geographic CHIRPS/ERA5 grids
    and for the equal-area sinusoidal MODIS grid.
    """
    area = ee.Image.pixelArea()
    valid = img.mask()                 # 0/1 image in the value image's projection
    v = img.multiply(area).rename("v")
    w = valid.multiply(area).rename("w")
    n = valid.rename("n")
    # Derive the "all pixels" band from the mask so it inherits the value
    # image's projection.  ee.Image.constant(1) would default to a 1-degree
    # grid, which would make total_pixel_count meaningless and stop the
    # sub-pixel fallback from ever triggering.
    t = valid.multiply(0).add(1).rename("t")
    return v.addBands([w, n, t])


def _stack_months(ee, spec: dict, months: list[str]):
    images = []
    for ym in months:
        img = _monthly_image(ee, spec, ym)
        stats = _stats_image(ee, img)
        tag = _month_tag(ym)
        images.append(stats.rename([f"{tag}_v", f"{tag}_w",
                                    f"{tag}_n", f"{tag}_t"]))
    stack = images[0]
    for extra in images[1:]:
        stack = stack.addBands(extra)
    return stack


def _native_projection(ee, spec: dict):
    """CRS + affine transform of the source dataset's native grid.

    Derived images (``ImageCollection.sum()``, ``mask()`` etc.) do not carry
    projection metadata, so ``reduceRegions`` would silently fall back to the
    default 1-degree grid.  The grid is therefore read from the first raw
    image and handed to ``reduceRegions`` explicitly.
    """
    try:
        proj = ee.Image(ee.ImageCollection(spec["id"]).first()).projection().getInfo()
    except Exception as exc:                              # noqa: BLE001
        common.die(f"could not read the native projection of {spec['id']}: {exc}")
    return proj["crs"], proj["transform"]


def _reduce(ee, fc, stack, tile_scale: int, crs: str, transform: list):
    """reduceRegions on the native grid, geometries stripped."""
    return stack.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.sum(),
        crs=crs,
        crsTransform=transform,
        tileScale=int(tile_scale),
    ).map(lambda f: ee.Feature(None, f.toDictionary()))


# ---------------------------------------------------------------------------#
# parsing / checkpoints
# ---------------------------------------------------------------------------#

def _prop(props: dict, key: str):
    """GEE returns ``<band>`` (current API); older builds append ``_sum``."""
    if key in props:
        return props[key]
    return props.get(key + "_sum")


def _parse_features(info: dict, months: list[str], fields: dict) -> list[dict]:
    rows = []
    id_field = fields.get("id") or "district_id"
    name_field = fields.get("name")
    state_field = fields.get("state")
    for feature in info.get("features", []):
        props = feature.get("properties") or {}
        did = props.get(id_field)
        if not did:
            continue
        dname = (props.get(name_field) if name_field else None) or did
        sname = (props.get(state_field) if state_field else None) or ""
        for ym in months:
            tag = _month_tag(ym)
            v = _num(_prop(props, f"{tag}_v"))
            w = _num(_prop(props, f"{tag}_w"))
            n = _num(_prop(props, f"{tag}_n"))
            t = _num(_prop(props, f"{tag}_t"))
            mean = v / w if (v is not None and w is not None and w > 0) else None
            # reduceRegions weights each pixel by the fraction of its area
            # inside the polygon, so n/t are fractional effective counts.
            # The reference zonal_stats writes integer counts; round them, and
            # never let a real (non-null) mean carry a zero count.
            vcount = int(round(n)) if n is not None else 0
            tcount = int(round(t)) if t is not None else 0
            if mean is not None:
                tcount = max(tcount, 1)
                vcount = max(min(vcount, tcount), 1)
            else:
                vcount = min(vcount, tcount)
            rows.append({
                "district_id": did,
                "district_name": dname,
                "state_name": sname,
                "date": ym,
                "mean": mean,
                "valid_pixel_count": vcount,
                "total_pixel_count": tcount,
            })
    return rows


def _write_rows(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CHUNK_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row[k] is None else row[k])
                             for k in CHUNK_HEADER})


def _fallback_fc(ee, fc, rows: list[dict], buffer_m: float, fields: dict):
    """Districts with no valid pixel need an all-touched-style fallback.

    ``reduceRegions`` weights pixels by the fraction of their area inside the
    polygon, so partially covered districts already get a value.  What can
    still come back empty is a district whose only overlapping pixels are
    masked (tiny islands, coastal slivers).  Buffer those geometries by about
    one pixel and reduce again; the values are then the nearest valid source
    pixels, the same intent as ``all_touched=True`` in the raster pipeline.
    """
    zero_ids = sorted({r["district_id"] for r in rows if r["mean"] is None})
    if not zero_ids or not buffer_m:
        return None, zero_ids
    ids = ee.List(zero_ids)
    id_field = fields.get("id") or "district_id"
    small = fc.filter(ee.Filter.inList(id_field, ids))
    small = small.map(lambda f: f.setGeometry(f.geometry().buffer(float(buffer_m))))
    return small, zero_ids


def _process_chunk(ee, cfg, var, spec, fc, fields, months, chunk_dir,
                   tile_scale, buffer_m, force, crs, transform,
                   buffered_out: set | None = None) -> str:
    path = os.path.join(chunk_dir, f"{months[0]}__{months[-1]}.csv")
    if os.path.exists(path) and not force:
        # A chunk written by an older build may use the old ``Mon-YY`` date
        # labels.  ``_assemble`` now normalises those, but a stale chunk can
        # also be truncated or belong to another window, so only reuse it when
        # its months match this request exactly.
        try:
            import pandas as pd
            cached = pd.read_csv(path, usecols=["date"])
            cached_dates = set(cached["date"].astype(str))
            if cached_dates == set(months):
                print(f"    {var} {months[0]}..{months[-1]}: cached")
                return path
            print(f"    {var} {months[0]}..{months[-1]}: cached chunk has "
                  f"unexpected dates — re-extracting")
        except Exception:                                 # noqa: BLE001
            print(f"    {var} {months[0]}..{months[-1]}: cached chunk unreadable"
                  f" — re-extracting")

    try:
        stack = _stack_months(ee, spec, months)
        info = _reduce(ee, fc, stack, tile_scale, crs, transform).getInfo()
        rows = _parse_features(info, months, fields)

        small, zero_ids = _fallback_fc(ee, fc, rows, buffer_m, fields)
        if small is not None:
            sinfo = _reduce(ee, small, stack, tile_scale, crs, transform).getInfo()
            fallback = _parse_features(sinfo, months, fields)
            by_key = {(r["district_id"], r["date"]): r for r in rows}
            for r in fallback:
                if r["district_id"] not in zero_ids:
                    continue
                old = by_key.get((r["district_id"], r["date"]))
                if old is not None and old["mean"] is None:
                    old.update(r)
            print(f"    {var} {months[0]}..{months[-1]}: "
                  f"{len(zero_ids)} district(s) without valid pixels buffered")
            if buffered_out is not None:
                buffered_out.update(zero_ids)

        _write_rows(path, rows)
        print(f"    {var} {months[0]}..{months[-1]}: {len(rows)} rows")
        return path

    except Exception as exc:                              # noqa: BLE001
        if len(months) <= 1:
            raise
        mid = len(months) // 2
        print(f"    {var} {months[0]}..{months[-1]} failed ({exc}); "
              f"splitting into {len(months[:mid])}+{len(months[mid:])} months")
        _process_chunk(ee, cfg, var, spec, fc, fields, months[:mid], chunk_dir,
                       tile_scale, buffer_m, force, crs, transform, buffered_out)
        _process_chunk(ee, cfg, var, spec, fc, fields, months[mid:], chunk_dir,
                       tile_scale, buffer_m, force, crs, transform, buffered_out)
        return ""


def _assemble(cfg: dict, var: str, chunk_dir: str, allowed_months: list[str]) -> str:
    files = sorted(glob.glob(os.path.join(chunk_dir, "*.csv")))
    if not files:
        print(f"  {var}: no chunks to assemble")
        return ""
    import pandas as pd

    frames = []
    for path in files:
        df = pd.read_csv(path)
        if not df.empty:
            frames.append(df)
    if not frames:
        print(f"  {var}: chunks are empty")
        return ""

    df = pd.concat(frames, ignore_index=True)
    raw = df["date"].astype(str).str.strip()
    # Chunks written before the date-format fix use ``Feb-00`` labels. Normalise
    # them to the app's ``YYYY-MM`` contract instead of silently dropping the
    # rows (this previously lost the first 12 MODIS months).
    iso = raw.str.match(r"^\d{4}-\d{2}$")
    legacy = pd.to_datetime(raw.where(~iso), format="%b-%y", errors="coerce")
    df["date"] = raw.where(iso, legacy.dt.strftime("%Y-%m"))
    df = df[df["date"].notna() & df["date"].isin(set(allowed_months))]
    df = df.drop_duplicates(subset=["district_id", "date"], keep="last")
    for col in ("valid_pixel_count", "total_pixel_count"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["mean"] = pd.to_numeric(df["mean"], errors="coerce")
    df = df[["district_id", "district_name", "state_name", "date", "mean",
             "valid_pixel_count", "total_pixel_count"]]

    out = common.processed_file(cfg, "series", f"{var}.csv")
    df.to_csv(out, index=False)
    finite = int(df["mean"].notna().sum())
    print(f"  {var}: {df['district_id'].nunique()} districts x "
          f"{df['date'].nunique()} months, {finite} valid district-months "
          f"-> {out}")
    return out


# ---------------------------------------------------------------------------#
# main entry point
# ---------------------------------------------------------------------------#

def run(cfg: dict, project: str | None = None, start: str | None = None,
        end: str | None = None, vars: list[str] | None = None,
        chunk_months: int | None = None, boundary_asset: str | None = None,
        upload_boundary: bool = False, force: bool = False,
        postprocess: bool = True) -> int:
    gee = cfg.get("gee") or {}
    end = end or gee.get("end") or "2025-12"
    start = start or cfg["history"]["start"]
    chunk_months = int(chunk_months or gee.get("chunk_months", 12))
    tile_scale = int(gee.get("tile_scale", 4))
    buffers = gee.get("buffer_m") or {}

    common.banner(f"Google Earth Engine extraction — {start} .. {end}")
    ee = _init_ee(cfg, project)
    specs = _specs(cfg)
    run_t0 = time.time()

    asset = boundary_asset or gee.get("boundary_asset")
    if upload_boundary:
        if not asset:
            common.die("--upload-boundary needs --boundary-asset "
                       "projects/<project>/assets/<name>")
        # The asset does not exist yet on the first run, so always upload the
        # local GeoJSON, then switch to the asset for the extraction.
        local_fc, _local_fields = _load_fc(ee, cfg, None)
        _upload_boundary(ee, local_fc, asset)
        fc, fields = _load_fc(ee, cfg, asset)
    else:
        fc, fields = _load_fc(ee, cfg, asset)

    var_list = [v for v in (vars or VAR_ORDER) if v in specs]
    unknown = sorted(set(vars or []) - set(specs))
    if unknown:
        common.die(f"unknown variable(s): {', '.join(unknown)}")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": project or os.environ.get("EE_PROJECT") or gee.get("project"),
        "start": start,
        "end": end,
        "chunk_months": chunk_months,
        "tile_scale": tile_scale,
        "boundary_asset": asset,
        "datasets": {v: specs[v] for v in var_list},
        "variables": {},
    }

    for var in var_list:
        spec = specs[var]
        months_all = _var_months(var, spec, start, end)
        if not months_all:
            print(f"  {var}: no months in {start}..{end} — skipped")
            continue

        print(f"\n  {var}: {spec['id']}")
        try:
            counts = _month_image_counts(ee, spec["id"],
                                         months_all[0], months_all[-1])
        except Exception as exc:                          # noqa: BLE001
            common.die(f"could not inspect {spec['id']}: {exc}")

        # Audit F2: gate months by published day count, not image presence.
        # A partially published month in a daily collection would otherwise be
        # summed over its available days and read as a nationwide drought.
        day_gate = spec.get("monthly", "first") == "sum"
        months, short, missing = _gate_months(months_all, counts, day_gate)
        if missing:
            print(f"    {len(missing)} month(s) not yet in GEE "
                  f"({missing[0]}..{missing[-1]}) — skipped")
        if short:
            print(f"    {len(short)} partially published month(s) "
                  f"({short[0]}..{short[-1]}) — skipped until every day of "
                  "the month is on the server")
        if not months:
            print("    no extractable months — skipped")
            continue

        chunk_dir = common.processed_dir(cfg, "gee_chunks", var)
        if force:
            for old in glob.glob(os.path.join(chunk_dir, "*.csv")):
                os.remove(old)
            print("    --force: cleared cached chunks")

        crs, transform = _native_projection(ee, spec)
        print(f"    grid: {crs} {transform}")

        buffer_m = float(buffers.get(var, 0) or 0)
        buffered_var: set[str] = set()
        var_t0 = time.time()
        for chunk in _chunks(months, chunk_months):
            _process_chunk(ee, cfg, var, spec, fc, fields, chunk, chunk_dir,
                           tile_scale, buffer_m, force, crs, transform,
                           buffered_out=buffered_var)

        _assemble(cfg, var, chunk_dir, months_all)
        meta["variables"][var] = {
            "available_months": len(months),
            "missing_months": len(missing),
            "short_months": short,
            "day_gate": day_gate,
            "month_image_counts": {m: counts.get(m, 0) for m in months_all},
            "first": months[0],
            "last": months[-1],
            "requested_first": months_all[0],
            "requested_last": months_all[-1],
            "native_crs": crs,
            "native_transform": transform,
            "buffered_districts": sorted(buffered_var),
            "runtime_s": round(time.time() - var_t0, 1),
        }

    meta["runtime_s"] = round(time.time() - run_t0, 1)
    meta_path = os.path.join(common.processed_dir(cfg, "gee_chunks"), "_meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"\n  GEE run metadata: {meta_path}")

    if postprocess:
        # One command -> a complete, dashboard-ready data/ folder. The app
        # reads <app_root>/data/{drought,summaries}/*.csv + metadata.json, so
        # the indicator computation, export and validation are chained here
        # instead of leaving half-processed output on disk. (run.py's
        # ``gee`` command performs this same chain; module users get it too.)
        from . import indicators, export_app, validate
        print("\n  Next steps run automatically: indicators -> export -> validate")
        indicators.compute(cfg)
        export_app.run(cfg)
        rc = validate.validate(cfg)
        print(f"\nGEE build finished; dashboard data written to "
              f"{os.path.join(common.app_root(cfg), 'data')}"
              + ("" if rc == 0 else " (validation reported errors — see above)"))
        return rc
    print("  Next: python run.py gee --skip-extract  (indicators -> export -> validate)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--project", default=None,
                    help="Google Cloud project id with Earth Engine enabled")
    ap.add_argument("--start", default=None, help="YYYY-MM (default: history.start)")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: gee.end or 2025-12)")
    ap.add_argument("--vars", nargs="+", default=None, choices=list(VAR_ORDER))
    ap.add_argument("--chunk-months", type=int, default=None)
    ap.add_argument("--boundary-asset", default=None,
                    help="projects/<project>/assets/<name>")
    ap.add_argument("--upload-boundary", action="store_true",
                    help="create the boundary asset from the local GeoJSON first")
    ap.add_argument("--force", action="store_true",
                    help="recompute cached chunks")
    ap.add_argument("--no-postprocess", action="store_true",
                    help="only extract series; skip indicators/export/validate")
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    return run(cfg, project=args.project, start=args.start, end=args.end,
               vars=args.vars, chunk_months=args.chunk_months,
               boundary_asset=args.boundary_asset,
               upload_boundary=args.upload_boundary, force=args.force,
               postprocess=not args.no_postprocess)


if __name__ == "__main__":
    sys.exit(main())
