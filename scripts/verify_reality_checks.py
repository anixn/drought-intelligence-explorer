#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_reality_checks.py — re-derive the platform's external reality checks
(task M10.7).

The three boxes on the Documentation > Reality checks surface are computed
from the shipped district matrices (never hand-typed), so a reader can re-run
one command and compare:

  1. Rajasthan, July-September 2002 — every Rajasthan district at or below
     -1.00 SPI-3 in each month (the documented 2002 monsoon failure).
  2. All-India SPI-3 - months at or below -1.00 across the full national
     record (547 months as of the 2026-09 refresh; the count is re-derived
     from the shipped series, never hand-typed)
     (the two deepest national rainfall deficits).
  3. Marathwada 2015-16 — rainfall deficit in Jul-Sep 2015 followed by severe
     vegetation stress in Nov 2015 - Jan 2016 (why the platform shows more
     than one indicator family).

Output: data/reality_checks.json (deterministic bytes: no timestamp).

Usage:
  python scripts/verify_reality_checks.py          # write the JSON
  python scripts/verify_reality_checks.py --check  # verify the committed JSON
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CSV_DIR = REPO / "data" / "drought"
REGISTRY = REPO / "data" / "districts.csv"
META = REPO / "data" / "metadata.json"
NATIONAL = REPO / "data" / "parquet" / "_national_monthly.parquet"
OUT = REPO / "data" / "reality_checks.json"

MARATHWADA = [
    "maharashtra-aurangabad", "maharashtra-jalna", "maharashtra-parbhani",
    "maharashtra-hingoli", "maharashtra-nanded", "maharashtra-latur",
    "maharashtra-osmanabad", "maharashtra-beed",
]


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(CSV_DIR / name, dtype={"district_id": str})


def month(frame: pd.DataFrame, ym: str, ids: list[str] | None = None) -> pd.Series:
    f = frame if ids is None else frame[frame.district_id.isin(ids)]
    if ym not in f.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(f[ym], errors="coerce").dropna()


def fmean(values) -> float:
    vals = [float(v) for v in values if math.isfinite(float(v))]
    return math.fsum(vals) / len(vals) if vals else float("nan")


def fmt_low_months(low: list[dict]) -> str:
    """Render the drought months as prose ("July 1987 and July–September 2002")
    without hard-coding them: the record moves with every monthly refresh, and
    a stale count or month list in the claim is exactly the drift this artifact
    exists to prevent."""
    names = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]
    groups: list[list[tuple[int, int]]] = []
    for s in low:
        y, m = (int(x) for x in s["date"].split("-"))
        if groups:
            py, pm = groups[-1][-1]
            if (y * 12 + m) - (py * 12 + pm) == 1:
                groups[-1].append((y, m))
                continue
        groups.append([(y, m)])

    def one(g):
        y0, m0 = g[0]
        y1, m1 = g[-1]
        if len(g) == 1:
            return f"{names[m0 - 1]} {y0}"
        if y0 == y1:
            return f"{names[m0 - 1]}–{names[m1 - 1]} {y1}"
        return f"{names[m0 - 1]} {y0}–{names[m1 - 1]} {y1}"

    parts = [one(g) for g in groups]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def build() -> dict:
    meta = json.loads(META.read_text(encoding="utf-8"))
    reg = pd.read_csv(REGISTRY, dtype={"district_id": str}).set_index("district_id")
    spi3 = load_csv("spi_03.csv")
    vci = load_csv("vci.csv")

    # ---- 1. Rajasthan 2002 -------------------------------------------------
    raj = spi3[spi3.state_name == "Rajasthan"]
    raj_ids = raj.district_id.tolist()
    raj_w = reg.loc[raj_ids, "area_km2"].to_numpy()
    months = []
    for ym in ("2002-07", "2002-08", "2002-09"):
        v = pd.to_numeric(raj[ym], errors="coerce")
        finite = v.dropna()
        w = raj_w[v.notna().to_numpy()]
        months.append({
            "date": ym,
            "n": int(finite.size),
            "n_drought": int((finite <= -1.0).sum()),
            "all_in_drought": bool(finite.size and (finite <= -1.0).all()),
            "mean_area_weighted": float(math.fsum(w * finite.to_numpy()) / math.fsum(w)) if finite.size else None,
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
        })

    # ---- 2. All-India SPI-3 ------------------------------------------------
    nat = pd.read_parquet(NATIONAL)
    nat = nat[nat.variable == "spi_03"].sort_values(["year", "month"])
    series = [
        {"date": f"{int(r.year):04d}-{int(r.month):02d}", "value": float(r.value)}
        for r in nat.itertuples(index=False)
        if r.value is not None and math.isfinite(float(r.value))
    ]
    low = [s for s in series if s["value"] <= -1.0]

    # ---- 3. Marathwada 2015-16 --------------------------------------------
    sep = month(spi3, "2015-09", MARATHWADA)
    nov = month(vci, "2015-11", MARATHWADA)
    jan = month(vci, "2016-01", MARATHWADA)
    mar = {
        "districts": len(MARATHWADA),
        "spi3_2015_09": {
            "n": int(sep.size), "mean": fmean(sep),
            "share_le_minus1": float((sep <= -1.0).mean()) if sep.size else None,
        },
        "vci_2015_11": {
            "n": int(nov.size), "mean": fmean(nov),
            "share_below_30": float((nov < 30).mean()) if nov.size else None,
        },
        "vci_2016_01": {
            "n": int(jan.size), "mean": fmean(jan),
            "share_below_30": float((jan < 30).mean()) if jan.size else None,
        },
    }

    checks = [
        {
            "id": "rajasthan-2002",
            "title": "Rajasthan, July–September 2002",
            "claim": "Every Rajasthan district was in drought through the 2002 "
                     "monsoon failure.",
            "window": "2002-07 to 2002-09",
            "indicator": "spi_03",
            "threshold": -1.0,
            "numbers": {
                "districts": len(raj_ids),
                "months": months,
            },
            "checked_against": "Documented 2002 all-India monsoon failure "
                               "(Gadgil & Gadgil 2006; Mallya et al. 2016)",
            "source": "data/drought/spi_03.csv; data/districts.csv",
        },
        {
            "id": "all-india-spi3",
            "title": f"All-India SPI-3, {series[0]['date'][:4]}–{series[-1]['date'][:4]}",
            "claim": "The national area-weighted SPI-3 fell to or below −1.00 in "
                     f"only {'four' if len(low) == 4 else len(low)} months of the "
                     f"{len(series)}-month record — {fmt_low_months(low)}.",
            "window": f"{series[0]['date']} to {series[-1]['date']}",
            "indicator": "spi_03",
            "threshold": -1.0,
            "numbers": {
                "n_months": len(series),
                "n_at_or_below": len(low),
                "months": low,
            },
            "checked_against": "The two deepest national rainfall deficits of "
                               "the CHIRPS record",
            "source": "data/parquet/_national_monthly.parquet",
        },
        {
            "id": "marathwada-2015",
            "title": "Marathwada, 2015–16",
            "claim": "The 2015 rainfall deficit was followed by severe vegetation "
                     "stress two to four months later, which is why the platform "
                     "shows more than one indicator family.",
            "window": "2015-09 to 2016-01",
            "indicators": ["spi_03", "vci"],
            "numbers": mar,
            "checked_against": "Documented 2015–16 Marathwada drought",
            "source": "data/drought/spi_03.csv; data/drought/vci.csv",
        },
    ]

    return {
        "schema": "die-reality-checks/1.0",
        "data_version": meta.get("version"),
        "methodology_version": meta.get("methodology_version"),
        "generated_by": "scripts/verify_reality_checks.py",
        "checks": checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-derive the reality checks (M10.7)")
    ap.add_argument("--check", action="store_true",
                    help="verify the committed JSON instead of writing it")
    args = ap.parse_args()
    out = build()
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists():
            print("REALITY CHECKS: missing", OUT)
            return 1
        old = OUT.read_text(encoding="utf-8")
        if old != text:
            print("REALITY CHECKS: drift — recompute and review, then re-run without --check")
            return 1
        print("REALITY CHECKS: PASS (committed JSON matches the shipped record)")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size} bytes)")
    for c in out["checks"]:
        print(f"  {c['id']}: {c['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
