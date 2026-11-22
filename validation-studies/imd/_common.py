"""Shared helpers for the IMD benchmark validation study (M4, docs/v2/03 §5).

The study compares the era-B record (CHIRPS/ERA5-Land/MODIS, district level)
against an independent station-interpolated reference (IMD) computed with the
*same* indicator machinery. Nothing here invents data: every number comes from
the Owner's local IMD archive or from the shipped era-B matrices.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load_config(path: Path | None = None) -> dict:
    cfg = yaml.safe_load((path or (HERE / "config.yaml")).read_text(encoding="utf-8"))
    cfg["_repo"] = str(REPO)
    cfg["_here"] = str(HERE)
    cfg["_work"] = str(REPO / cfg["outputs"]["work"])
    cfg["_report"] = str(REPO / cfg["outputs"]["report"])
    Path(cfg["_work"]).mkdir(parents=True, exist_ok=True)
    Path(cfg["_report"]).mkdir(parents=True, exist_ok=True)
    return cfg


# --------------------------------------------------------------- calendars --

def month_grid(y0: int, y1: int) -> list[tuple[int, int]]:
    return [(y, m) for y in range(y0, y1 + 1) for m in range(1, 13)]


def month_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def matrix_to_frame(values: np.ndarray, ids: list[str],
                    months: list[tuple[int, int]]) -> pd.DataFrame:
    """district x month matrix -> the app's wide CSV layout."""
    return pd.DataFrame(values, index=ids,
                        columns=[month_key(y, m) for (y, m) in months])


def frame_to_matrix(df: pd.DataFrame, ids: list[str],
                    months: list[tuple[int, int]]) -> np.ndarray:
    cols = [month_key(y, m) for (y, m) in months]
    sub = df.reindex(ids)
    return sub[cols].to_numpy(dtype=float, na_value=np.nan)


def read_die_matrix(path: Path, ids: list[str],
                    months: list[tuple[int, int]]) -> np.ndarray:
    df = pd.read_csv(path, dtype={"district_id": str})
    return frame_to_matrix(df.set_index("district_id"), ids, months)


def finite_pair(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(a) & np.isfinite(b)
    return a[ok], b[ok]


# ------------------------------------------------------------------ metrics --

def pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = finite_pair(np.asarray(a, float), np.asarray(b, float))
    if a.size < 3:
        return None
    sa, sb = float(np.std(a)), float(np.std(b))
    if sa == 0.0 or sb == 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def bias_rmsd(a: np.ndarray, b: np.ndarray) -> tuple[float | None, float | None]:
    a, b = finite_pair(np.asarray(a, float), np.asarray(b, float))
    if a.size == 0:
        return None, None
    d = a - b
    return float(np.mean(d)), float(math.sqrt(float(np.mean(d * d))))


def classify(z: np.ndarray, thresholds=(-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0)) -> np.ndarray:
    """McKee nine-class index; NaN stays -1 (no class)."""
    z = np.asarray(z, float)
    out = np.full(z.shape, -1, dtype=np.int8)
    ok = np.isfinite(z)
    out[ok] = np.searchsorted(np.asarray(thresholds), z[ok], side="left")
    return out


def class_agreement(za: np.ndarray, zb: np.ndarray) -> tuple[float | None, float | None]:
    a, b = finite_pair(np.asarray(za, float), np.asarray(zb, float))
    if a.size == 0:
        return None, None
    ca, cb = classify(a), classify(b)
    return float(np.mean(ca == cb)), float(np.mean(np.abs(ca - cb) <= 1))


def state_agreement(za: np.ndarray, zb: np.ndarray, tau: float = -1.0) -> float | None:
    a, b = finite_pair(np.asarray(za, float), np.asarray(zb, float))
    if a.size == 0:
        return None
    return float(np.mean((a <= tau) == (b <= tau)))


def event_match(za: np.ndarray, zb: np.ndarray, tau: float = -1.0) -> float | None:
    """Share of months where both records flag drought (Jaccard-style recall)."""
    a, b = finite_pair(np.asarray(za, float), np.asarray(zb, float))
    if a.size == 0:
        return None
    fa, fb = a <= tau, b <= tau
    union = int((fa | fb).sum())
    if union == 0:
        return 1.0
    return float((fa & fb).sum() / union)


# ------------------------------------------------------------- trend tooling --

def mann_kendall(x: np.ndarray) -> tuple[float, float]:
    """Two-sided MK z and p, tie-corrected (no serial-correlation correction)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 10:
        return float("nan"), float("nan")
    s = 0.0
    for k in range(n - 1):
        s += float(np.sum(np.sign(x[k + 1:] - x[k])))
    _, counts = np.unique(x, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - float(np.sum(counts * (counts - 1) * (2 * counts + 5)))) / 18.0
    if var <= 0:
        return float("nan"), float("nan")
    if s > 0:
        z = (s - 1) / math.sqrt(var)
    elif s < 0:
        z = (s + 1) / math.sqrt(var)
    else:
        z = 0.0
    from scipy import stats as st
    p = 2.0 * (1.0 - st.norm.cdf(abs(z)))
    return float(z), float(p)


def sen_slope(x: np.ndarray, years: np.ndarray) -> float:
    x = np.asarray(x, float)
    years = np.asarray(years, float)
    ok = np.isfinite(x)
    x, years = x[ok], years[ok]
    n = x.size
    if n < 2:
        return float("nan")
    slopes = []
    for i in range(n - 1):
        slopes.extend((x[i + 1:] - x[i]) / (years[i + 1:] - years[i]))
    return float(np.median(slopes)) if slopes else float("nan")


def bh_fdr(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(p.shape, dtype=bool)
    if ok.sum() == 0:
        return out
    pv = p[ok]
    order = np.argsort(pv)
    m = pv.size
    ranked = pv[order]
    passed = ranked <= (np.arange(1, m + 1) / m) * q
    if not passed.any():
        return out
    k = int(np.max(np.where(passed)[0]))
    keep = np.zeros(m, dtype=bool)
    keep[order[: k + 1]] = True
    out[ok] = keep
    return out


# ----------------------------------------------------------- area weighting --

def build_weights(geojson_path: Path, ids: list[str], lat: np.ndarray,
                  lon: np.ndarray, supersample: int = 4):
    """Fractional district coverage of each grid cell.

    A district's weight in a cell is the share of that cell covered by the
    district, estimated by rasterising all 724 polygons on a supersampled grid
    (supersample x supersample sub-cells per cell) and multiplying by cos(lat)
    so a 0.25 deg cell has an equal-area weight (the same principle as the
    application's LAEA weighting).

    Returns (weights, coverage):
      weights  float32 [n_districts, n_lat, n_lon], rows normalised per district
      coverage float32 [n_districts] share of the district's cells with weight
    """
    import rasterio.features
    from rasterio.transform import from_origin

    geo = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    id_set = set(ids)
    shapes = []
    for feat in geo["features"]:
        did = feat["properties"].get("id")
        if did not in id_set:
            continue
        shapes.append((feat["geometry"], ids.index(did) + 1))

    dlat = float(lat[1] - lat[0])
    dlon = float(lon[1] - lon[0])
    ny, nx = lat.size, lon.size
    ss = max(1, int(supersample))
    height, width = ny * ss, nx * ss
    transform = from_origin(float(lon[0] - dlon / 2), float(lat[-1] + dlat / 2),
                            dlon / ss, dlat / ss)
    raster = rasterio.features.rasterize(
        shapes, out_shape=(height, width), transform=transform,
        fill=0, dtype="int32", all_touched=False)

    # subsample fraction per target cell
    sub = raster.reshape(ny, ss, nx, ss)
    # raster rows run north -> south; flip to the dataset's ascending latitude
    sub = sub[::-1]
    cell_area = np.cos(np.deg2rad(lat))[:, None]

    n = len(ids)
    weights = np.zeros((n, ny, nx), dtype=np.float32)
    coverage = np.zeros(n, dtype=np.float32)
    for k in range(1, n + 1):
        frac = np.mean(sub == k, axis=(1, 3)).astype(np.float64)   # [ny, nx]
        w = frac * cell_area
        total = w.sum()
        if total <= 0:
            continue
        weights[k - 1] = (w / total).astype(np.float32)
        coverage[k - 1] = float(np.count_nonzero(frac) / max(1, np.count_nonzero(cell_area)))
    return weights, coverage


def aggregate(weights: np.ndarray, field: np.ndarray) -> np.ndarray:
    """weights [d, lat, lon] x field [t, lat, lon] -> district series [d, t]."""
    t = field.shape[0]
    out = np.full((weights.shape[0], t), np.nan, dtype=np.float32)
    for i in range(weights.shape[0]):
        w = weights[i].reshape(-1)
        idx = np.where(w > 0)[0]
        if idx.size == 0:
            continue
        ww = w[idx]
        vals = field.reshape(t, -1)[:, idx]
        ok = np.isfinite(vals)
        num = np.where(ok, vals, 0.0) @ ww
        den = ok @ ww
        with np.errstate(invalid="ignore", divide="ignore"):
            out[i] = np.where(den > 0, num / den, np.nan)
    return out


def hargreaves_pet(tmax: np.ndarray, tmin: np.ndarray, lat: np.ndarray,
                   months: list[tuple[int, int]]) -> np.ndarray:
    """Hargreaves-Samani PET (mm/month) from monthly tmax/tmin and latitude.

    Ra is the standard extraterrestrial radiation for the 15th of each month;
    the formula and the 0.0023/17.8 constants are Hargreaves & Samani (1985),
    the same method the era-C chain applies to the IMD reference.
    """
    lat = np.asarray(lat, float)[:, None]
    out = np.full((len(months),) + tmax.shape[1:], np.nan, dtype=np.float32)
    gsc = 0.0820                                # MJ m-2 min-1
    for k, (_y, m) in enumerate(months):
        doy = 15 + sum(31 if mm in (1, 3, 5, 7, 8, 10, 12)
                       else 30 if mm in (4, 6, 9, 11) else 28 for mm in range(1, m))
        phi = np.deg2rad(lat)
        dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
        dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
        ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
        ra = (24 * 60 / np.pi) * gsc * dr * (
            ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))
        ra_mm = ra * 0.408
        tr = np.asarray(tmax[k], float) - np.asarray(tmin[k], float)
        tr = np.where(tr > 0, tr, np.nan)
        tmean = (np.asarray(tmax[k], float) + np.asarray(tmin[k], float)) / 2.0
        days = 31 if m in (1, 3, 5, 7, 8, 10, 12) else 30 if m in (4, 6, 9, 11) else 28
        pet = 0.0023 * ra_mm * (tmean + 17.8) * np.sqrt(tr)
        out[k] = np.where(np.isfinite(pet), pet * days, np.nan)
    return out


# --------------------------------------------------------------------- io --

def write_json(path: str | Path, obj) -> None:
    def default(o):
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"not JSON serialisable: {type(o)}")

    Path(path).write_text(
        json.dumps(obj, indent=1, ensure_ascii=False, default=default) + "\n",
        encoding="utf-8")


def print_table(rows: list[list[str]], header: list[str]) -> None:
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    line = "  ".join(str(h).ljust(w) for h, w in zip(header, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
