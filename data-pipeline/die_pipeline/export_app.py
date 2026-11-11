"""Step 5 — export the application data contract.

Writes into <app_root>/data/:

    drought/<indicator>.csv   wide matrices (district rows x month columns)
    metadata.json             provenance/period switched to research mode
    summaries/*.csv           precomputed SPI-6 event and state statistics
                              (reproducibility cross-checks)
    pipeline_manifest.json    run parameters + SHA-256 checksums

The exporter uses the existing metadata.json as a *template* so indicator
labels, tooltips, class thresholds and palettes are preserved; only
data-dependent fields (period, reference period, provenance, sources,
last_updated, data_mode) are rewritten. Classification thresholds remain
the single source of truth in metadata.json.

Usage
-----
    python -m die_pipeline.export_app            # normal run
    python -m die_pipeline.export_app --dry-run  # report only, write nothing
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from . import common


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------#
# matrices
# ---------------------------------------------------------------------------#

def build_matrix(cfg: dict, iid: str, districts: list[dict],
                 months) -> np.ndarray:
    src = common.processed_file(cfg, "indicators", f"{iid}.csv")
    if not os.path.exists(src):
        common.die(f"indicator output missing: {src} — run indicators first")
    try:
        df = pd.read_csv(src)
    except Exception:
        df = pd.DataFrame(columns=["district_id", "date", "value"])
    df["date"] = df["date"].astype(str)
    id_pos = {d["district_id"]: i for i, d in enumerate(districts)}
    ym_pos = {common.ym(t): j for j, t in enumerate(months)}
    mat = np.full((len(districts), len(months)), np.nan)
    for r in df.itertuples(index=False):
        i, j = id_pos.get(r.district_id), ym_pos.get(r.date)
        if i is not None and j is not None and np.isfinite(r.value):
            mat[i, j] = float(r.value)
    return mat


def annotate_availability(ind: dict, mat: np.ndarray, date_cols: list[str]) -> None:
    """Record the first/last month with any valid value for one indicator.

    SPI/SPEI/SMA cover the full 1981+ archive; VCI starts with MODIS NDVI
    (2000-02).  The app needs this per-indicator window to label and clamp its
    analysis instead of treating the shorter record as missing data.
    """
    has = np.isfinite(mat).any(axis=0)
    idx = np.where(has)[0]
    if idx.size:
        a, b = int(idx[0]), int(idx[-1])
        sub = mat[:, a:b + 1]
        ind["available_from"] = date_cols[a]
        ind["available_to"] = date_cols[b]
        ind["available_months"] = b - a + 1
        ind["completeness_pct"] = round(
            float(np.isfinite(sub).mean() * 100), 2)
        if a > 0:
            ind["availability_note"] = (
                f"Source record begins {date_cols[a]}; "
                f"{a} month(s) before this are not available.")
    else:
        ind["available_from"] = None
        ind["available_to"] = None
        ind["available_months"] = 0
        ind["completeness_pct"] = 0.0
        ind["availability_note"] = "No valid values in the export period."


# ---------------------------------------------------------------------------#
# metadata
# ---------------------------------------------------------------------------#

def build_metadata(cfg: dict, template: dict | None, indicators: list[dict],
                   months, n_states: int, n_districts: int) -> dict:
    today = date.today().isoformat()
    am = cfg["app_metadata"]
    bp = cfg["base_period"]

    def bp_text(key):
        b = bp[key]
        return f"{b[0]}-{b[1] if b[1] is not None else 'present'}"

    reference_period = (f"SPI/SPEI and SMA climatology {bp_text('spi_spei')}; "
                        f"VCI {bp_text('vci')} (per-calendar-month fitting; see methodology)")

    meta = dict(template) if template else {}
    meta.update({
        "application": "Drought Intelligence Explorer",
        "region": cfg["region"]["name"],
        "data_mode": am["data_mode"],
        "data_provenance": am["data_provenance"].strip(),
        "last_updated": today,
        "methodology_version": am["methodology_version"],
        "random_seed": None,
        "period": {"start": common.ym(months[0]), "end": common.ym(months[-1]),
                   "n_months": len(months)},
        "temporal_resolution": "monthly",
        "spatial_units": (f"administrative districts ({n_states} states/union "
                          f"territories, {n_districts} units as supplied)"),
        "spatial_resolution": "district-level aggregation (simplified boundary "
                              "geometry served for visualisation)",
        "crs": "EPSG:4326 (WGS84) geographic coordinates, GeoJSON default",
        "area_method": template.get("area_method") if template else (
            "Precomputed equal-area statistics (Lambert Azimuthal Equal-Area "
            "centred at 22.5N, 79.5E). Areas are never derived from degree-"
            "coordinate arithmetic."),
        "reference_period": reference_period,
        "indicators": indicators,
        "sources": [dict(s, access_date=today) for s in am["sources"]],
        "citation": (template or {}).get(
            "citation",
            "Deshmukh, A. (2026). Drought Intelligence Explorer: An Interactive "
            "Geospatial Platform for Drought Monitoring and Analysis in India "
            "[computer software]. https://ankitdeshmukh.com/"),
        "disclaimer": am["disclaimer"].strip(),
    })
    for key in ("aggregation", "events", "seasons"):
        if template and key in template:
            meta[key] = template[key]
    return meta


def build_indicator_specs(cfg: dict, template: dict | None) -> list[dict]:
    """Template indicator entries with refreshed reference_period/file."""
    specs = template["indicators"] if template else common.default_indicator_specs()
    bp = cfg["base_period"]
    out = []
    for ind in specs:
        ind = dict(ind)
        iid = ind["id"]
        kind = next((s["kind"] for s in cfg["indicators"] if s["id"] == iid), None)
        if kind is None:
            common.die(f"indicator '{iid}' exists in metadata.json but not in "
                       "config.yaml indicators — add it there or remove it from "
                       "the template metadata")
        b = bp["spi_spei"] if kind in ("spi", "spei") else bp["sma"] if kind == "sma" else bp["vci"]
        end_y = b[1] if b[1] is not None else "present"
        ind["file"] = f"data/drought/{common.INDICATOR_FILES[iid]}"
        ind["reference_period"] = f"{b[0]}-{end_y} (research climatology)"
        out.append(ind)
    return out


# ---------------------------------------------------------------------------#
# summaries (reproducibility cross-checks)
# ---------------------------------------------------------------------------#

def write_summaries(cfg: dict, districts: list[dict], states: list[dict],
                    date_cols: list[str], spi6: np.ndarray, dry: bool) -> int:
    summ = common.app_data_dir(cfg, "summaries")
    d_ids = [d["district_id"] for d in districts]
    d_names = [d["district_name"] for d in districts]
    d_state_names = [d["state_name"] for d in districts]
    d_states = [d["state_id"] for d in districts]
    areas = np.array([d["area_km2"] for d in districts])
    T = len(date_cols)

    n_events = 0
    if not dry:
        with open(os.path.join(summ, "drought_events_spi_06.csv"), "w",
                  newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["district_id", "district_name", "state_name", "indicator",
                        "event_start", "event_end", "duration_months",
                        "severity", "mean_intensity", "min_value"])
            for i in range(len(districts)):
                series = spi6[i]
                t = 0
                while t < T:
                    if np.isfinite(series[t]) and series[t] <= -1.0:
                        t2 = t
                        while t2 < T and np.isfinite(series[t2]) and series[t2] <= -1.0:
                            t2 += 1
                        dur = t2 - t
                        if dur >= 3:
                            seg = series[t:t2]
                            sev = float(np.sum(-1.0 - seg))
                            w.writerow([d_ids[i], d_names[i], d_state_names[i], "spi_6",
                                        date_cols[t], date_cols[t2 - 1], dur,
                                        round(sev, 2), round(sev / dur, 2),
                                        round(float(seg.min()), 2)])
                            n_events += 1
                        t = t2
                    else:
                        t += 1

    if not dry:
        with open(os.path.join(summ, "state_statistics_spi_06.csv"), "w",
                  newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["state_id", "state_name", "indicator", "mean", "drought_months",
                        "affected_area_pct_mean", "severe_area_pct_mean",
                        "completeness_pct"])
            for s in [st["state_id"] for st in states]:
                idx = [i for i in range(len(districts)) if d_states[i] == s]
                if not idx:
                    continue
                sub = spi6[idx]
                areas_s = areas[idx]
                finite = np.isfinite(sub)
                if finite.any():
                    # Audit F3: the state mean and the drought-month regional
                    # series must be area-weighted like every other regional
                    # summary (the manuscript promises unweighted means are
                    # never used for regional statistics).
                    w2d = np.where(finite, areas_s[:, None], 0.0)
                    wsum_m = w2d.sum(axis=0)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        region = (np.nansum(np.where(finite, sub, 0.0) * w2d,
                                            axis=0) / wsum_m)
                    region = np.where(wsum_m > 0, region, np.nan)
                    drought_months = int(np.sum(np.isfinite(region)
                                                & (region <= -1.0)))
                    if np.isfinite(region).any():
                        mean_v = float(np.nanmean(region))
                    else:
                        mean_v = np.nan
                    drought_area = (np.where(sub <= -0.5, 1, 0) * finite * areas_s[:, None]).sum(axis=0) / areas_s.sum()
                    severe_area = (np.where(sub <= -1.5, 1, 0) * finite * areas_s[:, None]).sum(axis=0) / areas_s.sum()
                    aff, sev = drought_area.mean() * 100, severe_area.mean() * 100
                    comp = finite.sum() / sub.size * 100
                    w.writerow([s, d_state_names[idx[0]], "spi_6",
                                round(float(mean_v), 3) if np.isfinite(mean_v) else "",
                                drought_months, round(float(aff), 2),
                                round(float(sev), 2), round(float(comp), 2)])
                else:
                    w.writerow([s, d_state_names[idx[0]], "spi_6", "", 0, "", "", 0.0])
    return n_events


# ---------------------------------------------------------------------------#
# main
# ---------------------------------------------------------------------------#

def run(cfg: dict, dry: bool = False) -> int:
    districts, states = common.load_registry(cfg)
    template = common.load_app_metadata(cfg)
    specs = build_indicator_specs(cfg, template)

    # export window
    end = cfg["export"]["period_end"]
    if end is None:
        latest = "0000-00"
        for ind in specs:
            p = common.processed_file(cfg, "indicators", f"{ind['id']}.csv")
            if os.path.exists(p):
                try:
                    d = pd.read_csv(p, usecols=["date"])
                    if len(d):
                        latest = max(latest, str(d["date"].max()))
                except Exception:
                    pass
        end = latest
    months = common.month_range(cfg["export"]["period_start"], end)
    date_cols = [common.ym(t) for t in months]
    if len(months) < 2:
        common.die(
            f"export period is empty ({cfg['export']['period_start']} .. {end}). "
            "No indicator produced any values — typically the source archive "
            "is missing (check `python run.py status`) or shorter than "
            "min_base_years. Aborting BEFORE any application file is "
            "overwritten.")

    common.banner(f"Export application data — {len(districts)} districts x "
                  f"{len(months)} months ({date_cols[0]} .. {date_cols[-1]})")

    drought_dir = common.app_data_dir(cfg, "drought")
    mats = {}
    for ind in specs:
        iid = ind["id"]
        mat = build_matrix(cfg, iid, districts, months)
        mats[iid] = mat
        annotate_availability(ind, mat, date_cols)
        if not dry:
            path = os.path.join(drought_dir, common.INDICATOR_FILES[iid])
            common.write_wide_csv(path, districts, date_cols, mat,
                                  common.indicator_decimals(iid))
        finite = mat[np.isfinite(mat)]
        spec = ind
        print(f"  {iid:8s} {os.path.basename(common.INDICATOR_FILES[iid]):18s} "
              f"available={spec['available_from']}..{spec['available_to']} "
              f"completeness={spec['completeness_pct']:5.1f}%  "
              + (f"mean={finite.mean():+.2f} sd={finite.std():.2f}" if finite.size else "ALL MISSING"))

    if "spi_6" in mats:
        n_events = write_summaries(cfg, districts, states, date_cols,
                                   mats["spi_6"], dry)
    else:
        # Audit F10: summaries are SPI-6 cross-checks by design; skip them
        # with a warning instead of crashing when spi_6 is not configured.
        print("  WARNING: spi_6 is not configured — summaries cross-check "
              "files skipped")
        n_events = 0

    meta = build_metadata(cfg, template, specs, months,
                          len(states), len(districts))
    if not dry:
        with open(os.path.join(common.app_data_dir(cfg), "metadata.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

    # ---- manifest (provenance) --------------------------------------------
    if not dry:
        manifest = {
            "generated_at": date.today().isoformat(),
            "pipeline_version": "1.1.0",
            "methodology_version": meta["methodology_version"],
            "period": meta["period"],
            "base_periods": cfg["base_period"],
            "indicator_availability": {
                i["id"]: {"from": i.get("available_from"),
                          "to": i.get("available_to"),
                          "months": i.get("available_months")}
                for i in specs},
            "min_base_years": cfg.get("min_base_years", 20),
            "sources": meta["sources"],
            "files": {},
        }
        for iid, mat in mats.items():
            p = os.path.join(drought_dir, common.INDICATOR_FILES[iid])
            spec = next(s for s in specs if s["id"] == iid)
            a, b = spec["available_from"], spec["available_to"]
            manifest["files"][f"data/drought/{common.INDICATOR_FILES[iid]}"] = {
                "sha256": _sha256(p), "bytes": os.path.getsize(p),
                "districts": mat.shape[0], "months": mat.shape[1],
                "available_from": a, "available_to": b,
                "available_months": spec["available_months"],
                "completeness_pct": spec["completeness_pct"]}
        for extra in ("metadata.json",
                      "summaries/drought_events_spi_06.csv",
                      "summaries/state_statistics_spi_06.csv"):
            p = os.path.join(common.app_data_dir(cfg), extra)
            if os.path.exists(p):
                manifest["files"][f"data/{extra}"] = {
                    "sha256": _sha256(p), "bytes": os.path.getsize(p)}
        with open(os.path.join(common.app_data_dir(cfg), "pipeline_manifest.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)

    # ---- verification summary ----------------------------------------------
    common.hr()
    areas = np.array([d["area_km2"] for d in districts])
    for iid, mat in mats.items():
        finite = np.isfinite(mat)
        if finite.any():
            w_area = areas[:, None] * finite
            nat = np.nansum(np.where(finite, mat, 0.0) * w_area, axis=0) / np.maximum(w_area.sum(axis=0), 1e-9)
            nat = nat[np.isfinite(nat)]
            lag1 = (np.corrcoef(nat[:-1], nat[1:])[0, 1]
                    if nat.size > 3 else float("nan"))
            print(f"  {iid:8s} national area-weighted mean={nat.mean():+.2f} "
                  f"lag1={lag1:.2f}")
    print(f"  SPI-6 drought events (<= -1.0, >= 3 months): {n_events}")
    print(f"  total registry area: {areas.sum():,.0f} km2")
    if dry:
        print("  (dry run — nothing written)")
    else:
        print("  written: data/drought/*.csv, data/metadata.json, "
              "data/summaries/*.csv, data/pipeline_manifest.json")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    cfg = common.load_config(args.config)
    return run(cfg, dry=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
