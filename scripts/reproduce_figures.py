#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reproduce_figures.py — reproduce published manuscript figures/claims from the
shipped record (task M10.8).

The manuscript's browser screenshots cannot be re-rendered headlessly, but the
*data* behind its quantitative figures and tables can, deterministically. This
script regenerates three published figures/claims and compares them with the
committed reference artifacts under manuscript/figures/reproduced/:

  1. Figure 2 — temporal coverage of the ten indicators, drawn from
     data/metadata.json as a deterministic SVG (the plotted bars are also
     written as JSON).
  2. Figure 5 — the All-India SPI-3 series: months at or below -1.00 (four of
     547 as of the 2026-09 refresh; re-derived each run), the series minimum,
     and the qualifying event count.
  3. Figure 6 — propagation: SPI-3 (lead) vs SPEI-3 (response) over All India,
     Pearson r, n and the moving-block bootstrap 95% interval
     (1,000 resamples, seed 20261103).
  Plus Table 5's external checks by hashing the committed reality-check
  artifact (scripts/verify_reality_checks.py owns those numbers).

Usage:
  python scripts/reproduce_figures.py            # write the artifacts
  python scripts/reproduce_figures.py --check    # verify against committed refs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
META = REPO / "data" / "metadata.json"
NATIONAL = REPO / "data" / "parquet" / "_national_monthly.parquet"
REALITY = REPO / "data" / "reality_checks.json"
OUT = REPO / "manuscript" / "figures" / "reproduced"

ORDER = ["spi_1", "spi_3", "spi_6", "spi_12",
         "spei_1", "spei_3", "spei_6", "spei_12", "sma", "vci"]
FAMILY_COLOR = {"spi": "#2A5F85", "spei": "#22756B",
                "land_sma": "#C87E3B", "land_vci": "#6F9E3F"}


def month_num(ym: str) -> float:
    y, m = ym.split("-")
    return int(y) + (int(m) - 1) / 12.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def national_series(var: str) -> pd.Series:
    df = pd.read_parquet(NATIONAL)
    d = df[df.variable == var].sort_values(["year", "month"])
    idx = [f"{int(r.year):04d}-{int(r.month):02d}" for r in d.itertuples(index=False)]
    return pd.Series(d.value.astype(float).to_numpy(), index=idx)


def fig2(meta: dict) -> tuple[str, dict]:
    inds = {i["id"]: i for i in meta["indicators"]}
    bars = []
    for k, iid in enumerate(ORDER):
        ind = inds[iid]
        start, end = ind["available_from"], ind["available_to"]
        color = (FAMILY_COLOR["land_sma"] if iid == "sma"
                 else FAMILY_COLOR["land_vci"] if iid == "vci"
                 else FAMILY_COLOR[ind["family"]])
        bars.append({"id": iid, "label": ind["label"] if iid not in ("sma", "vci")
                     else ("SMA" if iid == "sma" else "VCI"),
                     "start": start, "end": end, "color": color})
    data = {"figure": "fig2_coverage", "reference_period": "1981-01..2020-12",
            "vci_period": "2000-02..2025-12", "bars": bars}

    # Deterministic SVG (no font rasterisation, so byte-stable).
    W, H = 1000, 520
    L, R, T, B = 210, 40, 40, 60
    pw, ph = W - L - R, H - T - B
    x0, x1 = 1976.4, 2027.6
    def x(v): return L + (v - x0) / (x1 - x0) * pw
    def y(k): return T + (k + 0.5) / len(ORDER) * ph
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}">',
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<rect x="{x(1981.0):.2f}" y="{T}" width="{x(2021.0)-x(1981.0):.2f}" '
           f'height="{ph}" fill="#E8EEF2"/>',
           f'<text x="{x(1981.3):.2f}" y="{T+18}" font-family="sans-serif" '
           f'font-size="14" fill="#5A6B7A">Reference climatology 1981–2020 (SPI, SPEI, SMA)</text>',
           f'<rect x="{x(2000.08):.2f}" y="{T}" width="{x(2026.0)-x(2000.08):.2f}" '
           f'height="{ph}" fill="#DCEBD2" opacity="0.55"/>']
    for k, b in enumerate(bars):
        yy = y(k)
        xa, xb = x(month_num(b["start"])), x(month_num(b["end"]) + 1 / 12)
        svg.append(f'<rect x="{xa:.2f}" y="{yy-10:.2f}" width="{max(1.0, xb-xa):.2f}" '
                   f'height="20" fill="{b["color"]}"/>')
        svg.append(f'<text x="{xa-6:.2f}" y="{yy+4:.2f}" text-anchor="end" '
                   f'font-family="sans-serif" font-size="11" fill="#3B4A57">{b["start"]}</text>')
        svg.append(f'<text x="{xb+6:.2f}" y="{yy+4:.2f}" '
                   f'font-family="sans-serif" font-size="11" fill="#3B4A57">{b["end"]}</text>')
        svg.append(f'<text x="{L-14}" y="{yy+4:.2f}" text-anchor="end" '
                   f'font-family="sans-serif" font-size="13" fill="#2E2820">{b["label"]}</text>')
    for yr in range(1980, 2026, 5):
        svg.append(f'<text x="{x(yr):.2f}" y="{T+ph+24}" text-anchor="middle" '
                   f'font-family="sans-serif" font-size="12" fill="#3B4A57">{yr}</text>')
        svg.append(f'<line x1="{x(yr):.2f}" y1="{T+ph}" x2="{x(yr):.2f}" y2="{T+ph+5}" '
                   f'stroke="#9AA7B2"/>')
    svg.append(f'<text x="{x(2000.4):.2f}" y="{T+ph-8}" font-family="sans-serif" '
               f'font-size="13" fill="#4C7A2E">VCI reference period 2000–present</text>')
    svg.append('</svg>')
    return "\n".join(svg) + "\n", data


def fig5() -> dict:
    s = national_series("spi_03")
    low = [{"date": d, "value": round(float(v), 4)} for d, v in s.items() if v <= -1.0]
    # qualifying event: consecutive months at or below -1.00, min 3
    dates = list(s.index)
    vals = s.to_numpy(float)
    events = []
    start = -1
    for j in range(len(vals) + 1):
        inrun = j < len(vals) and math.isfinite(vals[j]) and vals[j] <= -1.0
        if inrun and start < 0:
            start = j
        if not inrun and start >= 0:
            if j - start >= 3:
                events.append({"start": dates[start], "end": dates[j - 1],
                               "months": j - start})
            start = -1
    imin = int(np.argmin(vals))
    return {
        "figure": "fig5_historical",
        "series": "All-India SPI-3 (area-weighted national monthly)",
        "n_months": int(len(s)),
        "n_at_or_below_minus1": len(low),
        "months": low,
        "minimum": {"date": dates[imin], "value": round(float(vals[imin]), 4)},
        "qualifying_events": events,
        "n_qualifying_events": len(events),
    }


def fig6() -> dict:
    a = national_series("spi_03")
    b = national_series("spei_03")
    d = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    x = d.a.to_numpy(float)
    y = d.b.to_numpy(float)
    n = len(x)
    r = float(np.corrcoef(x, y)[0, 1])
    blk = max(4, min(24, int(round(n ** (1 / 3)))))
    rng = np.random.default_rng(20261103)
    nblocks = int(np.ceil(n / blk))
    boot = []
    for _ in range(1000):
        starts = rng.integers(0, n - blk + 1, nblocks)
        idx = np.concatenate([np.arange(st, st + blk) for st in starts])[:n]
        boot.append(float(np.corrcoef(x[idx], y[idx])[0, 1]))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {
        "figure": "fig6_propagation",
        "pair": ["spi_03", "spei_03"],
        "n": n,
        "r": round(r, 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "bootstrap": {"resamples": 1000, "block": blk, "seed": 20261103},
    }


def table5() -> dict:
    rc = json.loads(REALITY.read_text(encoding="utf-8"))
    return {
        "figure": "table5_reality",
        "artifact": "data/reality_checks.json",
        "sha256": sha256(REALITY),
        "checks": [c["id"] for c in rc.get("checks", [])],
    }


def artifacts() -> dict:
    meta = json.loads(META.read_text(encoding="utf-8"))
    svg, cov = fig2(meta)
    return {
        "fig2_coverage.svg": svg,
        "fig2_coverage.json": json.dumps(cov, indent=2, ensure_ascii=False) + "\n",
        "fig5_historical.json": json.dumps(fig5(), indent=2, ensure_ascii=False) + "\n",
        "fig6_propagation.json": json.dumps(fig6(), indent=2, ensure_ascii=False) + "\n",
        "table5_reality.json": json.dumps(table5(), indent=2, ensure_ascii=False) + "\n",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Reproduce published figures (M10.8)")
    ap.add_argument("--check", action="store_true",
                    help="verify against committed reference artifacts")
    args = ap.parse_args()
    out = artifacts()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.check:
        bad = []
        for name, text in out.items():
            p = OUT / name
            if not p.exists():
                bad.append(f"missing {name}")
            elif p.read_text(encoding="utf-8") != text:
                bad.append(f"drift {name}")
        if bad:
            print("REPRODUCE FIGURES: FAIL")
            for b in bad:
                print("  " + b)
            return 1
        print(f"REPRODUCE FIGURES: PASS ({len(out)} artifacts match the shipped record)")
        return 0
    for name, text in out.items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(out)} artifacts to {OUT.relative_to(REPO)}")
    for name in out:
        print("  " + name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
