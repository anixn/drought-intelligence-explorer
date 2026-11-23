#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_status.py — public data-status artifact (task M3.2).

Derives `data/status.json` from the committed contract so the status panel and
the currency banner cannot drift from the data:

  * record period and current data month from `data/metadata.json` / manifest
  * lag in days against the record end (amber beyond 45 days, per M3.3)
  * per-indicator availability and completeness
  * era coverage from `data/parquet/catalog.json`
  * last run + pipeline/methodology versions from `data/pipeline_manifest.json`
  * standing verification artifacts and curated known issues

The known-issue list is intentionally small and curated (it is not data-derived);
edit it here when a blocker changes. Usage:

  python scripts/build_status.py            # write data/status.json
  python scripts/build_status.py --check    # structure/consistency checks
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
META = REPO / "data" / "metadata.json"
MANIFEST = REPO / "data" / "pipeline_manifest.json"
CATALOG = REPO / "data" / "parquet" / "catalog.json"
BASELINE = REPO / "scripts" / "regression_baseline.json"
REALITY = REPO / "data" / "reality_checks.json"
OUT = REPO / "data" / "status.json"

LAG_AMBER_DAYS = 45


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def month_end(ym: str) -> date:
    y, m = (int(x) for x in ym.split("-"))
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - timedelta(days=1)


def build(today: date | None = None) -> dict:
    meta = load(META)
    manifest = load(MANIFEST)
    catalog = load(CATALOG)
    baseline = load(BASELINE)
    reality = load(REALITY)
    today = today or date.today()

    period = meta.get("period") or manifest.get("period") or {}
    start, end = period.get("start"), period.get("end")
    lag = (today - month_end(end)).days if end else None
    lag_state = ("ok" if lag is not None and lag <= LAG_AMBER_DAYS
                 else "amber" if lag is not None else "unknown")

    indicators = []
    for ind in meta.get("indicators", []):
        indicators.append({
            "id": ind.get("id"),
            "label": ind.get("label"),
            "from": ind.get("available_from"),
            "to": ind.get("available_to"),
            "months": ind.get("available_months"),
            "completeness_pct": ind.get("completeness_pct"),
        })

    eras = {}
    for key, era in (catalog.get("eras") or {}).items():
        eras[key] = {
            "label": era.get("label"),
            "available": bool(era.get("available")),
            "years": era.get("years"),
        }

    checks = [
        {"id": "pipeline_selftest", "label": "Pipeline self-test",
         "detail": "82 assertions, seed-deterministic",
         "command": "python data-pipeline/selftest.py"},
        {"id": "regression", "label": "Shipped-data regression",
         "detail": f"{len(list(_flatten(baseline)))} baseline values, seed " +
                   str(baseline.get("seed", "-")),
         "command": "python scripts/regression_check.py"},
        {"id": "reality", "label": "Reality checks",
         "detail": f"{len(reality.get('checks', []))} external checks, re-derived",
         "command": "python scripts/verify_reality_checks.py --check"},
        {"id": "figures", "label": "Published figures",
         "detail": "Fig 2/5/6 + Table 5 reproduced from the shipped record",
         "command": "python scripts/reproduce_figures.py --check"},
        {"id": "imd_benchmark", "label": "IMD benchmark (M4)",
         "detail": "independent IMD comparison; memo + machine-readable artifact",
         "command": "python validation-studies/imd/04_compare.py"},
    ]

    issues = []
    if lag is not None and lag > LAG_AMBER_DAYS:
        issues.append({
            "id": "refresh-due", "severity": "amber",
            "text": f"Era B ends {end}; the monthly refresh is {lag} days behind "
                    f"(target ≤ {LAG_AMBER_DAYS} days).",
        })
    era_a = meta.get("era_a") or {}
    if era_a.get("missing"):
        issues.append({
            "id": "atlas-islands", "severity": "known-limitation",
            "text": era_a["missing"],
        })
    issues.append({
        "id": "preprint-drift", "severity": "info",
        "text": "A few Marathwada figures in the preprint's Table 5 differ "
                "slightly from the released matrices; the interface uses the "
                "released values (M7 sync item).",
    })

    return {
        "schema": "die-status/1.0",
        "as_of": today.isoformat(),
        "data": {
            "version": meta.get("version"),
            "methodology_version": meta.get("methodology_version"),
            "pipeline_version": manifest.get("pipeline_version"),
            "mode": meta.get("data_mode"),
            "updated": meta.get("last_updated"),
            "period": {"start": start, "end": end},
            "data_month": end,
            "lag_days": lag,
            "lag_threshold_days": LAG_AMBER_DAYS,
            "lag_status": lag_state,
            "indicators": indicators,
            "eras": eras,
        },
        "run": {
            "last_run": manifest.get("generated_at"),
            "manifest": "data/pipeline_manifest.json",
            "catalog_version": catalog.get("version"),
        },
        "verification": checks,
        "known_issues": issues,
        "links": {
            "repository": "https://github.com/anixn/drought-intelligence-explorer",
            "citation": "CITATION.cff",
            "doi_v1": "https://doi.org/10.5281/zenodo.24113364",
            "reality_checks": "data/reality_checks.json",
        },
    }


def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, prefix + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, prefix + "/" + str(i))
    else:
        yield prefix, obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Build data/status.json (M3.2)")
    ap.add_argument("--check", action="store_true",
                    help="verify the committed status matches the contract")
    args = ap.parse_args()
    out = build()
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists():
            print("STATUS: missing data/status.json")
            return 1
        old = json.loads(OUT.read_text(encoding="utf-8"))
        problems = []
        if old.get("data", {}).get("data_month") != out["data"]["data_month"]:
            problems.append("data_month differs from metadata/manifest")
        if old.get("data", {}).get("version") != out["data"]["version"]:
            problems.append("data version differs")
        if old.get("data", {}).get("pipeline_version") != out["data"].get("pipeline_version"):
            problems.append("pipeline version differs")
        if not old.get("known_issues"):
            problems.append("known_issues missing")
        if problems:
            print("STATUS: FAIL")
            for p in problems:
                print("  " + p)
            return 1
        print("STATUS: PASS (status.json matches the data contract)")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size} bytes)")
    print(f"  data {out['data']['period']['start']}..{out['data']['data_month']} "
          f"· lag {out['data']['lag_days']} d ({out['data']['lag_status']}) "
          f"· {len(out['known_issues'])} known issue(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
