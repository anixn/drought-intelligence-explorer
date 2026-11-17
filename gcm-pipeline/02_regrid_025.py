#!/usr/bin/env python3
"""DIE v2.0 — gcm-pipeline step 02: regrid to the common 0.25° grid
(task M2.5, docs/v2/03 §3.4).

OWNER-EXECUTION SCRIPT (R4). Writes ONLY under gcm-pipeline/work/ (X9
convention, docs/v2/06 §5) — never data/, never out/. Resumable + idempotent:
existing verified outputs are skipped.

Reality of the raw store (verified 2026-11-16 on ACCESS-CM2): the Owner's
R-generated year files are ALREADY at 0.25° (ACCESS-CM2 day data regridded
upstream), cropped to ~6.9-37.1N / 68.1-97.4E, with NaN marking cells outside
the cropped/valid region (~1/3 of cells in the sample). The pipeline therefore
handles BOTH cases generically: native-resolution source grids (this step
regrids) and any NaN/missing pattern (handled honestly below).

What it does, per (model, experiment, variable), from the raw yearly files:
  1. Monthly aggregation on the SOURCE grid, native calendar, per-cell
     nanmean over days (cells with no valid days stay NaN — R10):
       pr      : daily flux (kg m-2 s-1) -> monthly MEAN RATE (mm/day).
                 Regridding operates on the intensive rate, NOT the monthly
                 total (totals are extensive; conservative remapping of a
                 total is wrong). The monthly total is reconstructed AFTER
                 remapping: total = rate_remapped * days_in_month(source
                 calendar — 360_day / noleap / standard all handled).
       tasmax  : daily K -> monthly mean -> °C.
       tasmin  : daily K -> monthly mean -> °C.
  2. Regrid each monthly field to the 0.25° target grid (reference.yaml):
       pr      : first-order conservative remap (spherical-area overlap
                 weights; flux-consistent), VALIDITY-MASKED: target values
                 renormalise over the FINITE source cells they overlap (the
                 v1.0 area-weighted rule); target cells with no finite source
                 overlap are NaN (absent, never 0).
       tasmax/tasmin : masked bilinear interpolation — bracketing source
                 cells that are finite are renormalised (same rule); target
                 centres beyond the source centre range take the nearest
                 VALID source value (constant edge extension, counted); all
                 four brackets NaN -> target NaN.
  3. Calendar harmonisation: monthly values are labelled by (year, month) and
     written on the standard proleptic-Gregorian axis — the native calendar
     (360_day/365_day/standard) is preserved INSIDE the days_in_month used
     for totals and recorded in the output attributes.
  4. Verification (gate, §3.4): per month, the covered-area-weighted domain
     mean of the pr MEAN RATE equals the source mean restricted to the
     target domain and the finite mask (exact invariant; selftest T1d/T1e);
     results recorded in regrid_manifest.json.

Output: work/regrid/<model>/<experiment>/<variable>_<start>-<end>.nc
        (monthly time axis, float32, source calendar + regrid metadata in
        global attributes). Manifest: work/regrid_manifest.json (SHA-256).

Self-tests (--selftest, deterministic, synthetic only — also wired into
selftest_gcm.py at M2.13):
  T1a/T1b conservation (aligned domain, uniform + random fields, exact);
  T1c fast factorised weights == direct reference build;
  T1d buffered-domain invariant (source larger than target, exact);
  T1e NaN-hole invariant (random field with 30 % NaN holes, exact);
  T2 masked bilinear: linear field reproduced exactly where all brackets
     finite; NaN holes renormalised (never fabricated);
  T3 units: kg m-2 s-1 -> mm/day factor 86400.

Usage:
  python 02_regrid_025.py --selftest
  python 02_regrid_025.py --dry-run                       # plan only
  python 02_regrid_025.py --models ACCESS-CM2             # one model, historical
  python 02_regrid_025.py                                 # all models, downloaded experiments
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
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

KG_M2_S_TO_MM_DAY = 86400.0
KELVIN_OFFSET = 273.15
CONSERVATION_GATE = 1e-9


def hr(title: str = "") -> None:
    if title:
        print("=" * 78)
        print(title)
        print("=" * 78)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def target_grid(ref: dict) -> dict:
    g = ref["target_grid"]
    res = float(g["res_deg"])
    n_lon = int(round((g["lon_max"] - g["lon_min"]) / res))
    n_lat = int(round((g["lat_max"] - g["lat_min"]) / res))
    return {
        "res": res, "n_lon": n_lon, "n_lat": n_lat,
        "lon_edges": np.linspace(g["lon_min"], g["lon_max"], n_lon + 1),
        "lat_edges": np.linspace(g["lat_min"], g["lat_max"], n_lat + 1),
        "lon_centres": g["lon_min"] + res / 2 + res * np.arange(n_lon),
        "lat_centres": g["lat_min"] + res / 2 + res * np.arange(n_lat),
    }


# ------------------------------------------------------------- grid weights ---
def _edges_from_centres(c: np.ndarray) -> np.ndarray:
    """Cell edges as midpoints between centres, extended half a step at the
    domain ends (regular-grid assumption; non-uniform spacing supported)."""
    e = np.empty(len(c) + 1)
    e[1:-1] = (c[:-1] + c[1:]) / 2.0
    e[0] = c[0] - (c[1] - c[0]) / 2.0
    e[-1] = c[-1] + (c[-1] - c[-2]) / 2.0
    return e


def _overlap_1d(a_edges: np.ndarray, b_edges: np.ndarray) -> np.ndarray:
    """Pairwise overlap lengths: out[i, j] = overlap(a_cell_i, b_cell_j)."""
    lo = np.maximum(a_edges[:-1][:, None], b_edges[:-1][None, :])
    hi = np.minimum(a_edges[1:][:, None], b_edges[1:][None, :])
    return np.clip(hi - lo, 0.0, None)


def lat_overlap_spherical(t_edges: np.ndarray, s_edges: np.ndarray) -> np.ndarray:
    """Pairwise ∫sin(φ)dφ over the latitude overlap of each (target, source)
    cell pair — the spherical-area weight factor. Returns (n_t, n_s)."""
    a_lo, a_hi = t_edges[:-1][:, None], t_edges[1:][:, None]
    b_lo, b_hi = s_edges[:-1][None, :], s_edges[1:][None, :]
    lo = np.maximum(a_lo, b_lo)
    hi = np.minimum(a_hi, b_hi)
    return np.where(hi > lo,
                    np.sin(np.deg2rad(hi)) - np.sin(np.deg2rad(lo)), 0.0)


def conservative_weights(src_lat: np.ndarray, src_lon: np.ndarray, tgt: dict):
    """First-order conservative weight matrix for rectangular (1D-monotonic)
    regular grids. Exact factorisation: w(t, s) = latOv_sph * lonOv.
    Returns (A, row_sums) with A target-major sparse (n_t, n_s)."""
    import scipy.sparse as sp
    s_lat_e = _edges_from_centres(np.asarray(src_lat, float))
    s_lon_e = _edges_from_centres(np.asarray(src_lon, float))
    latOv = lat_overlap_spherical(tgt["lat_edges"], s_lat_e)   # (n_tlat, n_slat)
    lonOv = _overlap_1d(tgt["lon_edges"], s_lon_e)             # (n_tlon, n_slon)
    n_tlat, n_tlon = tgt["n_lat"], tgt["n_lon"]
    n_slat, n_slon = len(src_lat), len(src_lon)
    A = sp.lil_matrix((n_tlat * n_tlon, n_slat * n_slon))
    lat_nz = latOv > 0
    lon_nz = lonOv > 0
    for ti in range(n_tlat):
        slats = np.where(lat_nz[ti])[0]
        if not len(slats):
            continue
        for tj in range(n_tlon):
            slons = np.where(lon_nz[tj])[0]
            if not len(slons):
                continue
            Wsub = np.outer(latOv[ti, slats], lonOv[tj, slons])
            ii, jj = np.where(Wsub > 0)
            A[ti * n_tlon + tj, slats[ii] * n_slon + slons[jj]] = Wsub[ii, jj]
    A = A.tocsr()
    row_sums = np.asarray(A.sum(axis=1)).ravel()
    return A, row_sums


def conservative_weights_reference(src_lat: np.ndarray, src_lon: np.ndarray,
                                   tgt: dict):
    """Same weights built WITHOUT the factorisation — each (t, s) pair from
    its own lon/lat interval overlaps. Small grids only (selftest T1c)."""
    import scipy.sparse as sp
    s_lat_e = _edges_from_centres(np.asarray(src_lat, float))
    s_lon_e = _edges_from_centres(np.asarray(src_lon, float))
    n_tlat, n_tlon = tgt["n_lat"], tgt["n_lon"]
    n_slat, n_slon = len(src_lat), len(src_lon)
    rows, cols, vals = [], [], []
    for ti in range(n_tlat):
        t_lo_lat, t_hi_lat = tgt["lat_edges"][ti], tgt["lat_edges"][ti + 1]
        for tj in range(n_tlon):
            t_lo_lon, t_hi_lon = tgt["lon_edges"][tj], tgt["lon_edges"][tj + 1]
            for si in range(n_slat):
                lo_lat = max(t_lo_lat, s_lat_e[si])
                hi_lat = min(t_hi_lat, s_lat_e[si + 1])
                if hi_lat <= lo_lat:
                    continue
                d_sin = np.sin(np.deg2rad(hi_lat)) - np.sin(np.deg2rad(lo_lat))
                if d_sin <= 0:
                    continue
                for sj in range(n_slon):
                    lo_lon = max(t_lo_lon, s_lon_e[sj])
                    hi_lon = min(t_hi_lon, s_lon_e[sj + 1])
                    if hi_lon <= lo_lon:
                        continue
                    rows.append(ti * n_tlon + tj)
                    cols.append(si * n_slon + sj)
                    vals.append(float(d_sin * (hi_lon - lo_lon)))
    A = sp.csr_matrix((vals, (rows, cols)),
                      shape=(n_tlat * n_tlon, n_slat * n_slon))
    row_sums = np.asarray(A.sum(axis=1)).ravel()
    return A, row_sums


def conservative_apply(A: np.ndarray, row_sums: np.ndarray, field: np.ndarray,
                       shape_t: tuple):
    """Validity-masked conservative remap of ONE 2-D field.

    Target values renormalise over the FINITE source cells they overlap
    (the v1.0 area-weighted rule); target cells with no finite source
    overlap are NaN (absent, never 0).

    Exact invariant (selftests T1d/T1e): the covered-area-weighted mean of
    the output equals the source mean restricted to the target domain AND
    the finite mask — source cells weighted by their overlap with the
    target domain (col_sums, masked by finiteness), target cells weighted
    by the covered area (row_eff).
    Returns (remapped_2d, row_eff, cons_rel) — cons_rel = |invariant breach|.
    """
    import scipy.sparse as sp
    valid = np.isfinite(field).ravel()
    v = np.where(valid, field.ravel(), 0.0)
    Wv = A @ sp.diags(valid.astype(float))          # finite-masked weights
    row_eff = np.asarray(Wv.sum(axis=1)).ravel()
    col_eff = np.asarray(Wv.sum(axis=0)).ravel()    # = valid_s * col_sums
    num = Wv @ v
    out = np.where(row_eff > 0, num / np.where(row_eff > 0, row_eff, 1.0), np.nan)
    covered = row_eff > 0
    src_res_mean = float((v * col_eff).sum() / col_eff.sum())
    out_mean = float((out[covered] * row_eff[covered]).sum() / row_eff[covered].sum())
    cons_rel = abs(out_mean - src_res_mean) / max(abs(src_res_mean), 1e-12)
    return out.reshape(shape_t), row_eff, cons_rel


def spherical_area_weights(lat_edges: np.ndarray, n_lon: int) -> np.ndarray:
    """(n_lat, n_lon) area weights ∝ Δsin(lat) for domain-mean comparisons."""
    w = np.sin(np.deg2rad(lat_edges[1:])) - np.sin(np.deg2rad(lat_edges[:-1]))
    return np.outer(w, np.ones(n_lon))


# ------------------------------------------------------- masked bilinear ------
def bilinear_masked(src_lat: np.ndarray, src_lon: np.ndarray, field: np.ndarray,
                    tgt: dict) -> tuple:
    """Masked bilinear interpolation onto the target centres.

    - finite bracketing source cells are renormalised (v1.0 rule);
    - target centres beyond the source centre range take the nearest VALID
      source value (constant edge extension, counted);
    - a target cell with NO finite bracket is NaN (absent, never imputed).
    Returns (out_2d, n_edge_extended, n_all_nan, n_renorm)."""
    n_tlat, n_tlon = tgt["n_lat"], tgt["n_lon"]
    lat_t, lon_t = tgt["lat_centres"], tgt["lon_centres"]
    out = np.full((n_tlat, n_tlon), np.nan)
    n_ext = n_nan = n_ren = 0
    lat_s = np.asarray(src_lat, float)
    lon_s = np.asarray(src_lon, float)
    # bracket indices (source grid assumed monotonic ascending; verified by caller)
    ii = np.clip(np.searchsorted(lat_s, lat_t) - 1, 0, len(lat_s) - 2)
    jj = np.clip(np.searchsorted(lon_s, lon_t) - 1, 0, len(lon_s) - 2)
    ty = (lat_t - lat_s[ii]) / (lat_s[ii + 1] - lat_s[ii])
    tx = (lon_t - lon_s[jj]) / (lon_s[jj + 1] - lon_s[jj])
    for a in range(n_tlat):
        i0, i1 = ii[a], ii[a] + 1
        for b in range(n_tlon):
            j0, j1 = jj[b], jj[b] + 1
            w = {(i0, j0): (1 - ty[a]) * (1 - tx[b]), (i0, j1): (1 - ty[a]) * tx[b],
                 (i1, j0): ty[a] * (1 - tx[b]), (i1, j1): ty[a] * tx[b]}
            num = den = 0.0
            for (i, j), wij in w.items():
                v = field[i, j]
                if np.isfinite(v):
                    num += wij * v
                    den += wij
            if den > 0:
                if den < 0.999999:
                    n_ren += 1
                out[a, b] = num / den
            else:
                n_nan += 1
    # edge extension: centres outside the source centre range -> nearest VALID
    # source value (constant extension along the clamped bracket)
    for a in range(n_tlat):
        if lat_t[a] < lat_s[0] or lat_t[a] > lat_s[-1]:
            for b in range(n_tlon):
                if np.isnan(out[a, b]):
                    i = 0 if lat_t[a] < lat_s[0] else len(lat_s) - 1
                    col = field[i, jj[b]:jj[b] + 2]
                    valid = col[np.isfinite(col)]
                    if len(valid):
                        out[a, b] = float(valid[0])
                        n_ext += 1
        for b in range(n_tlon):
            if lon_t[b] < lon_s[0] or lon_t[b] > lon_s[-1]:
                if np.isnan(out[a, b]):
                    j = 0 if lon_t[b] < lon_s[0] else len(lon_s) - 1
                    row = field[ii[a]:ii[a] + 2, j]
                    valid = row[np.isfinite(row)]
                    if len(valid):
                        out[a, b] = float(valid[0])
                        n_ext += 1
    return out, n_ext, n_nan, n_ren


# --------------------------------------------------------------- self-tests ---
def selftest() -> int:
    hr("SELFTEST — synthetic grids (deterministic; no real data)")
    ref = load_yaml(CONFIG_DIR / "reference.yaml")
    tgt = target_grid(ref)
    fails = []
    rng = np.random.default_rng(20261103)

    # T1a/T1b — conservation over a source domain whose edges EXACTLY bound
    # the target (full coverage): domain means must match to float precision.
    src_lat = np.arange(6.5, 38.0, 1.0)                  # edges exactly 6..38
    src_lon = np.arange(67.5, 99.0, 1.0)                 # edges exactly 67..99
    A, rs = conservative_weights(src_lat, src_lon, tgt)
    src_area = spherical_area_weights(_edges_from_centres(src_lat), len(src_lon))
    t_area = spherical_area_weights(tgt["lat_edges"], tgt["n_lon"])
    for name, field in (("T1a uniform", np.full((len(src_lat), len(src_lon)), 3.17)),
                        ("T1b random ", rng.random((len(src_lat), len(src_lon))) * 50.0)):
        out, _, rel = conservative_apply(A, rs, field, (tgt["n_lat"], tgt["n_lon"]))
        src_mean = float((field * src_area).sum() / src_area.sum())
        out_mean = float((out * t_area).sum() / t_area.sum())
        rel_direct = abs(out_mean - src_mean) / abs(src_mean)
        print(f"{name}: src={src_mean:.12f} remapped={out_mean:.12f} rel={rel_direct:.3e} "
              f"(invariant rel={rel:.3e})")
        if rel > CONSERVATION_GATE or rel_direct > CONSERVATION_GATE:
            fails.append(f"{name.strip()} conservation beyond 1e-9")

    # T1c — fast factorised weights == direct reference build
    tgt_small = {"n_lon": 6, "n_lat": 6,
                 "lon_edges": np.arange(60.0, 67.0), "lat_edges": np.arange(10.0, 17.0),
                 "lon_centres": np.arange(60.5, 66.6, 1.0),
                 "lat_centres": np.arange(10.5, 16.6, 1.0)}
    A_f, _ = conservative_weights(src_lat, src_lon, tgt_small)
    A_s, _ = conservative_weights_reference(src_lat, src_lon, tgt_small)
    diff = (A_f - A_s).tocoo()
    dmax = float(np.abs(diff.data).max()) if diff.nnz else 0.0
    print(f"T1c fast-vs-reference weight matrices: max|diff| = {dmax:.3e}")
    if dmax > 1e-12:
        fails.append("T1c fast weights disagree with reference build")

    # T1d — buffered domain (production case): restricted-mean invariant exact
    src_lat_w = np.arange(5.0, 40.0, 1.0)
    src_lon_w = np.arange(60.0, 105.0, 1.0)
    A_w, rs_w = conservative_weights(src_lat_w, src_lon_w, tgt)
    field_w = rng.random((len(src_lat_w), len(src_lon_w))) * 50.0
    out_w, _, rel_d = conservative_apply(A_w, rs_w, field_w,
                                         (tgt["n_lat"], tgt["n_lon"]))
    print(f"T1d buffered : invariant rel = {rel_d:.3e}")
    if rel_d > CONSERVATION_GATE:
        fails.append("T1d buffered-domain invariant beyond 1e-9")

    # T1e — NaN holes (~30 % of source cells NaN): invariant still exact with
    # the valid-mask renormalisation; zero-coverage target cells are NaN.
    field_e = field_w.copy()
    holes = rng.random(field_e.shape) < 0.30
    field_e[holes] = np.nan
    out_e, rs_e, rel_e = conservative_apply(A_w, rs_w, field_e,
                                            (tgt["n_lat"], tgt["n_lon"]))
    n_nan_cells = int(np.isnan(out_e).sum())
    print(f"T1e nan-holes: invariant rel = {rel_e:.3e}, "
          f"zero-coverage target cells = {n_nan_cells} (absent, not 0)")
    if rel_e > CONSERVATION_GATE:
        fails.append("T1e NaN-hole invariant beyond 1e-9")
    if n_nan_cells == 0:
        fails.append("T1e expected some zero-coverage target cells")

    # T2 — masked bilinear: linear field exact where all brackets finite;
    # NaN hole cells renormalised from finite neighbours (never fabricated);
    # outside-range centres take the nearest valid source value.
    b, c, a = 0.7, -1.3, 5.0
    field3 = a + b * src_lon_w[None, :] + c * src_lat_w[:, None]
    hole = (17, 22)                                     # one interior hole
    field3[hole] = np.nan
    out3, n_ext, n_allnan, n_ren = bilinear_masked(src_lat_w, src_lon_w, field3, tgt)
    lon_g, lat_g = np.meshgrid(tgt["lon_centres"], tgt["lat_centres"])
    exact = a + b * lon_g + c * lat_g
    interior = ((lat_g > src_lat_w.min()) & (lat_g < src_lat_w.max())
                & (lon_g > src_lon_w.min()) & (lon_g < src_lon_w.max()))
    # cells whose 4 brackets exclude the hole reproduce the field exactly
    src_hole_box = (abs(lat_g - src_lat_w[hole[0]]) < 1.0) & (abs(lon_g - src_lon_w[hole[1]]) < 1.0)
    clean = interior & ~src_hole_box
    err = float(np.abs(out3 - exact)[clean].max())
    # renormalised cells stay finite and inside the local range
    ren_ok = bool(np.all(np.isfinite(out3[src_hole_box])))
    print(f"T2 bilinear: max clean interior error = {err:.3e}; "
          f"renormalised cells finite: {ren_ok}; edge-extended = {n_ext}; "
          f"all-NaN = {n_allnan}; renormalised = {n_ren}")
    if err > 1e-8:
        fails.append("T2 bilinear linear-field error")
    if not ren_ok:
        fails.append("T2 renormalised cells not finite")

    # T3 — unit factor
    print(f"T3 units: 1 kg m-2 s-1 = {KG_M2_S_TO_MM_DAY} mm/day")
    if KG_M2_S_TO_MM_DAY != 86400.0:
        fails.append("T3 unit factor")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1a, T1b, T1c, T1d, T1e, T2, T3)")
    return 0


# ------------------------------------------------------------------ regrid ---
def read_year_file(path: Path, var: str):
    """Yearly raw file -> (lat, lon, {(y, m): 2-D monthly field}, {(y, m): days},
    calendar). Fields prepared for regridding:
      pr  : monthly mean RATE in mm/day (intensive; total reconstructed later)
      tas*: monthly mean in K (converted to °C after remap)

    Read with netCDF4 + cftime directly (the Owner's R-generated files carry
    unnamed dims in xarray's view; netCDF4 exposes the named dims and the
    native calendar cleanly). Missing values (mask/fill/NaN) -> NaN (R10)."""
    import cftime
    import netCDF4 as nc
    d = nc.Dataset(path)
    try:
        v = d.variables[var]
        raw = np.ma.filled(np.ma.asarray(v[:]), np.nan).astype(np.float64)
        dims = v.dimensions                             # e.g. ('time','lat','lon')
        lat_name = next(n for n in ("lat", "latitude") if n in d.variables)
        lon_name = next(n for n in ("lon", "longitude") if n in d.variables)
        t_ax, lat_ax, lon_ax = dims.index("time"), dims.index(lat_name), dims.index(lon_name)
        if (t_ax, lat_ax, lon_ax) != (0, 1, 2):
            raw = np.transpose(raw, (t_ax, lat_ax, lon_ax))
        lat = np.asarray(d.variables[lat_name][:], float)
        lon = np.asarray(d.variables[lon_name][:], float)
        tv = d.variables["time"]
        cal = getattr(tv, "calendar", "standard")
        dates = cftime.num2date(tv[:], units=tv.units, calendar=cal)
        groups = {}
        for i, t in enumerate(dates):
            groups.setdefault((t.year, t.month), []).append(i)
        monthly, days = {}, {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)  # all-NaN slices
            for (y, m), idx in groups.items():
                block = raw[idx]
                days[(y, m)] = len(idx)
                if var == "pr":
                    with np.errstate(invalid="ignore"):
                        monthly[(y, m)] = np.nanmean(block, axis=0) * KG_M2_S_TO_MM_DAY
                else:
                    with np.errstate(invalid="ignore"):
                        monthly[(y, m)] = np.nanmean(block, axis=0)
        return lat, lon, monthly, days, cal
    finally:
        d.close()


def _assert_ascending(lat: np.ndarray, lon: np.ndarray, model: str) -> None:
    if not (np.all(np.diff(lat) > 0) and np.all(np.diff(lon) > 0)):
        raise ValueError(f"{model}: source lat/lon not strictly ascending — "
                         "descending/curvilinear grids need a regrid-rule update")


def regrid_model_var(model: str, exp: str, var: str, raw_root: Path,
                     work_root: Path, tgt: dict, years: range) -> dict:
    cfg = load_yaml(CONFIG_DIR / "models.yaml")
    row = next(r for r in cfg["models"] if r["source_id"] == model)
    variant, grid = row.get("variant"), row.get("grid_label")
    files = [raw_root / var / f"{var}_day_{model}_{exp}_{variant}_{grid}_{y}_v2.0.nc"
             for y in years]
    files = [f for f in files if f.exists()]
    if not files:
        return {"model": model, "exp": exp, "var": var, "status": "no-input",
                "detail": f"no raw year files in {years.start}-{years.stop - 1}"}
    weights = None
    months_out, time_labels = [], []
    cal_seen = set()
    stats = {"edge_extended": 0, "all_nan": 0, "renormalised": 0, "zero_cov": 0}
    cons_rels = []
    t0 = time.time()
    for f in files:
        lat, lon, monthly, days, cal = read_year_file(f, var)
        cal_seen.add(cal)
        _assert_ascending(lat, lon, model)
        if weights is None:
            A, row_sums = conservative_weights(lat, lon, tgt)
            weights = (A, row_sums)
        A, row_sums = weights
        shape_t = (tgt["n_lat"], tgt["n_lon"])
        for (y, m) in sorted(monthly):
            field = monthly[(y, m)]
            if var == "pr":
                remapped, row_eff, rel = conservative_apply(A, row_sums, field, shape_t)
                cons_rels.append(rel)
                stats["zero_cov"] += int(np.isnan(remapped).sum())
                total = remapped * days[(y, m)]           # reconstruct monthly total
                total[np.isnan(remapped)] = np.nan
                months_out.append(total)
            else:
                remapped, n_ext, n_nan, n_ren = bilinear_masked(lat, lon, field, tgt)
                stats["edge_extended"] += n_ext
                stats["all_nan"] += n_nan
                stats["renormalised"] += n_ren
                months_out.append(remapped - KELVIN_OFFSET)
            time_labels.append((y, m))
    import pandas as pd
    import xarray as xr
    out_dir = work_root / "regrid" / model / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    period = f"{time_labels[0][0]}-{time_labels[-1][0]}"
    out_path = out_dir / f"{var}_{period}.nc"
    tstamp = pd.to_datetime([f"{y:04d}-{m:02d}-01" for (y, m) in time_labels])
    data = np.stack(months_out).astype(np.float32)
    attrs = {
        "source_id": model, "experiment_id": exp, "variable_id": var,
        "variant": variant, "grid_label": grid,
        "source_calendars": ",".join(sorted(cal_seen)),
        "regrid_method": "conservative(spherical-area, 0.25deg, validity-masked)"
        if var == "pr" else "bilinear(masked, nearest-valid edge extension, 0.25deg)",
        "pr_units_note": "mm/month; rate remapped conservatively over finite source "
                         "cells (v1.0 renormalisation), total reconstructed with "
                         "source-calendar days_in_month" if var == "pr"
        else "degC monthly means",
        "absent_cells_note": "NaN = no finite source data that month (absent row "
                             "semantics, R10) — never zero-filled",
        "pipeline": "DIE v2.0 gcm-pipeline 02_regrid_025.py",
    }
    if var == "pr":
        cons_max = max(cons_rels) if cons_rels else None
        attrs["conservation_max_rel"] = cons_max
        attrs["zero_coverage_cells"] = stats["zero_cov"]
    else:
        cons_max = None
        attrs["edge_extended_cells"] = stats["edge_extended"]
        attrs["all_nan_cells"] = stats["all_nan"]
        attrs["renormalised_bracket_cells"] = stats["renormalised"]
    ds_out = xr.Dataset(
        {var: (("time", "lat", "lon"), data)},
        coords={"time": tstamp, "lat": tgt["lat_centres"], "lon": tgt["lon_centres"]},
        attrs=attrs)
    enc = {var: {"dtype": "float32", "zlib": True, "complevel": 4}}
    ds_out.to_netcdf(out_path, encoding=enc)
    return {"model": model, "exp": exp, "var": var, "status": "ok",
            "out": str(out_path.relative_to(work_root)), "n_months": len(months_out),
            "period": period, "calendars": sorted(cal_seen),
            "conservation_max_rel": cons_max, "conservation_gate": CONSERVATION_GATE,
            "stats": stats, "seconds": round(time.time() - t0, 1),
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}


def main() -> int:
    ap = argparse.ArgumentParser(description="regrid to 0.25° (M2.5)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="plan only, writes work/test-output/")
    ap.add_argument("--models", help="comma list (default: all config models)")
    ap.add_argument("--variables", default="pr,tasmax,tasmin")
    ap.add_argument("--experiments", default="historical")
    ap.add_argument("--force", action="store_true", help="recompute existing outputs")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    paths = load_yaml(CONFIG_DIR / "paths.yaml")
    ref = load_yaml(CONFIG_DIR / "reference.yaml")
    cfg = load_yaml(CONFIG_DIR / "models.yaml")
    raw_root = Path(paths["raw_root"])
    work_root = (HERE / paths.get("work_root", "work")).resolve()
    (work_root / "test-output").mkdir(parents=True, exist_ok=True)
    tgt = target_grid(ref)
    models = args.models.split(",") if args.models else [r["source_id"] for r in cfg["models"]]
    variables = args.variables.split(",")

    man_path = work_root / "regrid_manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else \
        {"schema": 1, "files": {}}

    if args.dry_run:
        plan = []
        for model in models:
            row = next((r for r in cfg["models"] if r["source_id"] == model), None)
            if row is None:
                continue
            for var in variables:
                for exp in args.experiments.split(","):
                    yrs = row.get(exp) or {}
                    have = sum(1 for y in range(int(yrs.get("start", 0)),
                                                int(yrs.get("end", -1)) + 1)
                               if (raw_root / var /
                                   f"{var}_day_{model}_{exp}_{row.get('variant')}_"
                                   f"{row.get('grid_label')}_{y}_v2.0.nc").exists())
                    plan.append({"model": model, "exp": exp, "var": var,
                                 "year_files_on_disk": have})
        out = work_root / "test-output" / "regrid_plan.json"
        out.write_text(json.dumps({"schema": 1, "plan": plan}, indent=2))
        hr(f"DRY-RUN — {len(plan)} (model, exp, var) chunks -> {out.name}")
        for p in plan:
            print(f"  {p['model']:18s} {p['exp']:10s} {p['var']:7s} "
                  f"{p['year_files_on_disk']:4d} year files on disk")
        return 0

    hr(f"REGRID — target {tgt['n_lat']}x{tgt['n_lon']} @ {tgt['res']}° "
       f"({tgt['lat_centres'][0]}..{tgt['lat_centres'][-1]}N, "
       f"{tgt['lon_centres'][0]}..{tgt['lon_centres'][-1]}E)")
    report = []
    n_ok = n_skip = n_fail = 0
    for model in models:
        row = next((r for r in cfg["models"] if r["source_id"] == model), None)
        if row is None:
            print(f"  SKIP {model}: not in models.yaml")
            continue
        for var in variables:
            for exp in args.experiments.split(","):
                yrs = row.get(exp) or {}
                years = range(int(yrs.get("start", 1981)), int(yrs.get("end", 2014)) + 1)
                existing = [k for k in manifest["files"]
                            if k.startswith(f"{model}/{exp}/{var}_")]
                if existing and not args.force:
                    rec = manifest["files"][existing[0]]
                    p = work_root / rec["out"]
                    if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == rec["sha256"]:
                        print(f"  SKIP {model}/{exp}/{var}: verified output exists")
                        n_skip += 1
                        continue
                try:
                    rec = regrid_model_var(model, exp, var, raw_root, work_root, tgt, years)
                except Exception as e:              # noqa: BLE001 — record & continue
                    print(f"  FAIL {model}/{exp}/{var}: {e}")
                    report.append({"model": model, "exp": exp, "var": var,
                                   "status": "error", "detail": str(e)})
                    n_fail += 1
                    continue
                if rec["status"] == "ok":
                    manifest["files"][f"{model}/{exp}/{var}_{rec['period']}"] = rec
                    n_ok += 1
                    cons = rec["conservation_max_rel"]
                    gate_ok = cons is None or cons <= CONSERVATION_GATE
                    st = rec["stats"]
                    print(f"  OK {model:18s} {exp:10s} {var:7s} {rec['n_months']:4d} months "
                          f"cal={','.join(rec['calendars'])} "
                          f"consRel={'-' if cons is None else format(cons, '.2e')} "
                          f"ext={st['edge_extended']} nan={st['all_nan']} "
                          f"ren={st['renormalised']} zeroCov={st['zero_cov']} "
                          f"{rec['seconds']}s "
                          f"{'GATE-PASS' if gate_ok else 'GATE-FAIL'}")
                    if not gate_ok:
                        n_fail += 1
                else:
                    print(f"  -- {model:18s} {exp:10s} {var:7s}: {rec['status']}")
                report.append(rec)
    man_path.write_text(json.dumps({"schema": 1, "files": manifest["files"],
                                    "last_report": report}, indent=2))
    print(f"REGRID DONE: {n_ok} ok, {n_skip} skipped, {n_fail} failed/gate-breached")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
