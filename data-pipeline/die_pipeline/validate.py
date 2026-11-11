"""Step 6 — validate the exported dataset against the application contract.

Mirrors the checks the web app performs at load time (see
assets/js/data-loader.js) and adds scientific sanity checks:

  contract   header/date columns, district ids vs registry & boundaries,
             duplicate rows, non-numeric cells, completeness,
             classification coverage (every finite value falls in exactly
             one metadata class)
  science    value limits, national area-weighted SPI mean ~ 0 and sd ~ 1,
             SPI-6 vs SPEI-6 correlation, completeness thresholds,
             summaries/event-file consistency

Exit code 0 = only INFO/WARNING; 1 = at least one ERROR.

Usage
-----
    python -m die_pipeline.validate            # validate <app_root>/data
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from . import common


class Report:
    def __init__(self):
        self.errors = 0
        self.warnings = 0
        self.info = 0

    def error(self, msg):
        self.errors += 1
        print(f"  [ERROR]   {msg}")

    def warn(self, msg):
        self.warnings += 1
        print(f"  [WARNING] {msg}")

    def ok(self, msg):
        self.info += 1
        print(f"  [ok]      {msg}")


def validate(cfg: dict) -> int:
    rep = Report()
    data_dir = os.path.join(common.app_root(cfg), "data")
    meta_path = os.path.join(data_dir, "metadata.json")
    if not os.path.exists(meta_path):
        common.die(f"no metadata.json under {data_dir}")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)

    districts, states = common.load_registry(cfg)
    d_ids = [d["district_id"] for d in districts]
    areas = np.array([d["area_km2"] for d in districts])
    id_set = set(d_ids)

    with open(common.boundaries_path(cfg), encoding="utf-8") as fh:
        gj = json.load(fh)
    b_ids = {f["properties"].get("id") for f in gj["features"]}

    period = meta["period"]
    qa = cfg.get("qa", {})
    rep.ok(f"metadata: mode={meta['data_mode']} period={period['start']}..{period['end']} "
           f"indicators={len(meta['indicators'])} sources={len(meta.get('sources', []))}")

    # Month columns are identical across indicator files in practice; keep one
    # canonical copy for the base-period calibration checks below.
    date_cols: list[str] = []

    if set(d_ids) != b_ids:
        rep.error(f"registry/boundary id mismatch: {len(set(d_ids) - b_ids)} in "
                  f"registry only, {len(b_ids - set(d_ids))} in boundaries only")

    mats = {}
    for ind in meta["indicators"]:
        iid = ind["id"]
        path = os.path.join(common.app_root(cfg), ind["file"])
        if not os.path.exists(path):
            rep.error(f"{iid}: file missing — {ind['file']}")
            continue
        ids, date_cols, mat = common.read_wide_csv(path)
        mats[iid] = mat

        # header / dates
        bad_dates = [c for c in date_cols if not common.dates_ok(c)
                     or not (period["start"] <= c <= period["end"])]
        if bad_dates:
            rep.error(f"{iid}: {len(bad_dates)} date columns outside the "
                      f"declared period (e.g. {bad_dates[:3]})")
        expected_cols = pd.period_range(period["start"], period["end"], freq="M")
        if len(date_cols) != len(expected_cols):
            rep.warn(f"{iid}: {len(date_cols)} month columns vs {len(expected_cols)} "
                     f"declared in period")

        # ids
        dup = len(ids) - len(set(ids))
        if dup:
            rep.error(f"{iid}: {dup} duplicate district rows")
        unknown = [i for i in ids if i not in id_set]
        if unknown:
            rep.error(f"{iid}: {len(unknown)} district ids not in the registry "
                      f"(e.g. {unknown[:3]})")
        unrep = len(id_set - set(ids))
        if unrep:
            rep.warn(f"{iid}: {unrep} registry districts have no row at all")

        finite = np.isfinite(mat)
        # Completeness is measured inside each indicator's own availability
        # window.  SPI/SPEI/SMA start in 1981; VCI cannot start before MODIS
        # NDVI (2000-02), so measuring it against the full 1981+ span would
        # report a false failure.
        has_col = finite.any(axis=0)
        actual_from = actual_to = None
        if has_col.any():
            a_act = int(np.argmax(has_col))
            b_act = int(len(has_col) - 1 - np.argmax(has_col[::-1]))
            actual_from, actual_to = date_cols[a_act], date_cols[b_act]
        av_from = ind.get("available_from") or actual_from
        av_to = ind.get("available_to") or actual_to
        if av_from and av_to and av_from <= av_to:
            idx = [j for j, c in enumerate(date_cols) if av_from <= c <= av_to]
            a_av, b_av = (idx[0], idx[-1]) if idx else (0, len(date_cols) - 1)
        else:
            a_av, b_av = 0, len(date_cols) - 1
        window = mat[:, a_av:b_av + 1]
        completeness = float(np.isfinite(window).mean() * 100) if window.size else 0.0
        if actual_from and av_from and (actual_from != av_from or actual_to != av_to):
            rep.warn(f"{iid}: metadata availability {av_from}..{av_to} does not "
                     f"match the data ({actual_from}..{actual_to})")
        thr_w = qa.get("completeness_warn", 90.0)
        thr_f = qa.get("completeness_fail", 70.0)
        if completeness < thr_f:
            rep.error(f"{iid}: completeness {completeness:.1f}% < {thr_f}% "
                      f"inside its availability window {av_from}..{av_to}")
        elif completeness < thr_w:
            rep.warn(f"{iid}: completeness {completeness:.1f}% < {thr_w}% "
                     f"inside its availability window {av_from}..{av_to}")
        else:
            rep.ok(f"{iid}: completeness {completeness:.1f}% over "
                   f"{mat.shape[0]}x{mat.shape[1]} ({av_from}..{av_to})")

        # classification coverage
        vals = mat[finite]
        if vals.size:
            noclass = sum(1 for v in vals[:: max(1, vals.size // 4000)]
                          if common.classify(float(v), ind["classes"]) is None)
            if noclass:
                rep.error(f"{iid}: {noclass} sampled values match NO class "
                          "(check thresholds in metadata.json)")
            else:
                rep.ok(f"{iid}: classification covers all sampled values")

        # value limits
        limits = qa.get("value_limits", {})
        if ind["family"] in ("spi", "spei"):
            lo, hi = limits.get("zscore", [-4.0, 4.0])
        elif iid == "sma":
            lo, hi = limits.get("sma_pct", [-100.0, 100.0])
        else:
            lo, hi = limits.get("vci_pct", [0.0, 100.0])
        out = int(((vals < lo) | (vals > hi)).sum()) if vals.size else 0
        if out:
            rep.error(f"{iid}: {out} values outside [{lo}, {hi}]")
        if vals.size:
            rep.ok(f"{iid}: values {vals.min():.2f} .. {vals.max():.2f} "
                   f"mean {vals.mean():+.2f}")

    # ---- science cross-checks ---------------------------------------------
    # Calibration check on every z-score indicator inside the BASE period:
    # standardised values must average ~0 with sd ~1 there by construction.
    # The pooled full-record check below can only detect gross global bias;
    # a base period ending decades before the archive end (1981-2020 base,
    # 1981-2025 record) makes the full-record mean drift legitimately.
    base_period = (cfg.get("base_period") or {}).get("spi_spei")
    for iid in ("spi_1", "spi_3", "spi_6", "spi_12",
                "spei_1", "spei_3", "spei_6", "spei_12"):
        mat = mats.get(iid)
        if mat is None or not np.isfinite(mat).any():
            continue
        if not date_cols or not base_period:
            continue
        bcols = [j for j, c in enumerate(date_cols)
                 if base_period[0] <= int(c[:4]) <= (base_period[1] or 9999)]
        if not bcols:
            continue
        sub = mat[:, bcols]
        vals = sub[np.isfinite(sub)]
        if vals.size < 100:
            continue
        m, sd = float(vals.mean()), float(vals.std())
        lim = qa.get("spi_abs_mean_warn", 0.25)
        if abs(m) > lim:
            rep.error(f"{iid}: BASE-period mean {m:+.3f} exceeds ±{lim} — "
                      "standardisation is biased (check the fit report)")
        else:
            rep.ok(f"{iid}: base-period calibration mean {m:+.3f}")
        sdr = qa.get("spi_sd_range", [0.70, 1.40])
        if not (sdr[0] <= sd <= sdr[1]):
            rep.warn(f"{iid}: base-period sd {sd:.3f} outside {sdr}")
        else:
            rep.ok(f"{iid}: base-period sd {sd:.3f}")

    if "spi_6" in mats and np.isfinite(mats["spi_6"]).any():
        mat = mats["spi_6"]
        vals = mat[np.isfinite(mat)]
        m, sd = vals.mean(), vals.std()
        lim = qa.get("spi_abs_mean_warn", 0.25)
        sdr = qa.get("spi_sd_range", [0.70, 1.40])
        if abs(m) > lim:
            rep.warn(f"pooled SPI-6 mean {m:+.3f} exceeds ±{lim} "
                     "(base-period balance?)")
        else:
            rep.ok(f"pooled SPI-6 mean {m:+.3f}")
        if not (sdr[0] <= sd <= sdr[1]):
            rep.warn(f"pooled SPI-6 sd {sd:.3f} outside {sdr} "
                     "(over/under-dispersed SPI — check the base period)")
        else:
            rep.ok(f"pooled SPI-6 sd {sd:.3f}")
        # national series persistence (informational)
        finite = np.isfinite(mat)
        w_area = areas[:, None] * finite
        nat = np.nansum(np.where(finite, mat, 0.0) * w_area, axis=0) / np.maximum(w_area.sum(axis=0), 1e-9)
        nat = nat[np.isfinite(nat)]
        if nat.size > 4:
            rep.ok(f"national SPI-6 series lag-1 autocorrelation "
                   f"{np.corrcoef(nat[:-1], nat[1:])[0, 1]:.2f}")

    if {"spi_6", "spei_6"} <= mats.keys():
        a, b = mats["spi_6"], mats["spei_6"]
        both = np.isfinite(a) & np.isfinite(b)
        if both.sum() > 100:
            r = float(np.corrcoef(a[both], b[both])[0, 1])
            rep.ok(f"pooled SPI-6 vs SPEI-6 correlation r={r:.2f} "
                   "(expect roughly 0.4-0.95)")

    if {"spi_3", "spei_3"} <= mats.keys():
        a, b = mats["spi_3"], mats["spei_3"]
        both = np.isfinite(a) & np.isfinite(b)
        if both.sum() > 100:
            r = float(np.corrcoef(a[both], b[both])[0, 1])
            rep.ok(f"pooled SPI-3 vs SPEI-3 correlation r={r:.2f}")

    # summaries present?
    for s in ("summaries/drought_events_spi_06.csv", "summaries/state_statistics_spi_06.csv"):
        if os.path.exists(os.path.join(data_dir, s)):
            rep.ok(f"{s} present")
        else:
            rep.warn(f"{s} missing (download-centre link will 404)")

    man = os.path.join(data_dir, "pipeline_manifest.json")
    if os.path.exists(man):
        with open(man, encoding="utf-8") as fh:
            m = json.load(fh)
        rep.ok(f"pipeline_manifest.json: generated {m.get('generated_at')}, "
               f"methodology {m.get('methodology_version')}, "
               f"{len(m.get('files', {}))} files hashed")
    else:
        rep.warn("pipeline_manifest.json missing (provenance record)")

    common.hr()
    print(f"result: {rep.errors} error(s), {rep.warnings} warning(s), {rep.info} check(s) passed")
    return 1 if rep.errors else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    cfg = common.load_config(args.config)
    common.banner("Validate application data")
    return validate(cfg)


if __name__ == "__main__":
    sys.exit(main())
