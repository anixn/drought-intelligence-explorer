#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_ranking_data.py — era-C model ranking artifact for the UI (M5.5).

Reads the step-08 validation outputs (`gcm-pipeline/work/validation/
best_subset.yaml` + `ranking.csv`, Owner-local) and emits a small
deterministic JSON (`data/ranking.json`) that `#projections` fetches
directly — no engine query needed for the ranking panel.

Contract honoured here:
  - The ranking is a MULTI-METRIC COMPOSITE (8 skill metrics, min-max
    normalised, weighted mean over indicators) — never a single-metric
    ranking (roadmap M5.5).
  - The subset (n = 8) is selected by the committed stability criterion
    (largest inter-rank composite gap + reweighting-stability order), NOT
    by a rank cutoff.
  - Source window: model historical 1981-2014 vs IMD. Weights are shipped
    verbatim. Round-trip: every ranking row is verified cell-level against
    the source CSV before the file is written.

Usage:
    python scripts/build_ranking_data.py            # build + verify
    python scripts/build_ranking_data.py --check    # verify existing only

If the Owner-local validation outputs are missing the script exits non-zero
with instructions — nothing is fabricated (R3).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = REPO / "gcm-pipeline" / "work" / "validation"
SUBSET_YAML = SRC_DIR / "best_subset.yaml"
RANKING_CSV = SRC_DIR / "ranking.csv"
OUT_JSON = REPO / "data" / "ranking.json"

METRIC_KEYS = [
    "pearson_r", "abs_bias", "rmsd", "class_agreement",
    "freq_ratio", "duration_ratio", "severity_ratio", "spatial_r",
]

# minimal flat-YAML reader for the keys this script needs (no external dep)
def _read_subset_yaml(path: pathlib.Path) -> dict:
    import yaml  # pyyaml is in the drought env (used by the gcm pipeline)
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _read_ranking_csv(path: pathlib.Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build() -> dict:
    subset = _read_subset_yaml(SUBSET_YAML)
    ranking = _read_ranking_csv(RANKING_CSV)

    subset_models = list(subset.get("subset") or [])
    if not subset_models:
        sys.exit("best_subset.yaml has no 'subset' list — refusing to emit (R3)")

    # weights: shipped verbatim (multi-metric proof)
    weights = dict(subset.get("weights_verbatim") or {})
    if not weights:
        sys.exit("best_subset.yaml has no 'weights_verbatim' — refusing (R3)")

    rows = []
    for r in ranking:
        model = r["model"]
        metrics = {}
        for k in METRIC_KEYS:
            raw = (r.get(k) or "").strip()
            if raw == "":
                metrics[k] = None      # metric not computed for this model
            else:
                metrics[k] = float(raw)
        rows.append({
            "rank": int(r["rank"]),
            "model": model,
            "composite": float(r["composite"]),
            "in_subset": model in subset_models,
            "metrics": metrics,
        })
    rows.sort(key=lambda x: x["rank"])

    doc = {
        "schema": "die-era-c-ranking/1.0",
        "source": {
            "pipeline": "gcm-pipeline 08_validate_gcm.py",
            "files": [str(SUBSET_YAML.relative_to(REPO)).replace("\\", "/"),
                      str(RANKING_CSV.relative_to(REPO)).replace("\\", "/")],
            "window": subset.get("window"),
            "n_candidates": subset.get("n_candidates"),
        },
        "method": (subset.get("method") or "").strip(),
        "criterion": {
            "rule": (subset.get("criterion_rule") or "").strip(),
            "size_range": subset.get("criterion", {}).get("size_range"),
            "stability_draws": subset.get("criterion", {}).get("stability_draws"),
            "stability_seed": subset.get("criterion", {}).get("stability_seed"),
            "core_size": subset.get("core_size"),
            "core_gap": subset.get("core_gap"),
        },
        "weights_verbatim": weights,
        "ensemble_n": len(subset_models),
        "subset": subset_models,
        "ranking": rows,
        "honesty": [
            "multi-metric composite of 8 skill metrics vs IMD (1981-2014); "
            "never a single-metric ranking",
            "subset = committed stability criterion (largest-gap core + "
            "reweighting-stability order), not a rank cutoff",
            "historical skill is not future skill; free-running model "
            "realisations are not correlated with observations (documented "
            "caveat in gcm-pipeline config/validation.yaml)",
            "composite is shown with all component metrics — disagreement "
            "between metrics is information, not noise",
        ],
    }
    return doc


def verify(doc: dict) -> list[str]:
    """Round-trip checks; returns a list of failures (empty == PASS)."""
    fails = []
    ranking = _read_ranking_csv(RANKING_CSV)
    by_model = {r["model"]: r for r in ranking}
    subset_models = set(doc["subset"])
    if len(subset_models) != doc["ensemble_n"]:
        fails.append("ensemble_n != len(subset)")
    for row in doc["ranking"]:
        src = by_model.get(row["model"])
        if src is None:
            fails.append(f"model {row['model']} not in source CSV")
            continue
        if int(src["rank"]) != row["rank"]:
            fails.append(f"{row['model']}: rank mismatch")
        if abs(float(src["composite"]) - row["composite"]) > 1e-9:
            fails.append(f"{row['model']}: composite mismatch")
        for k, v in row["metrics"].items():
            raw = (src.get(k) or "").strip()
            if v is None:
                if raw != "":
                    fails.append(f"{row['model']}.{k}: null but source has {raw}")
                continue
            if raw == "" or abs(float(raw) - v) > 1e-9:
                fails.append(f"{row['model']}.{k}: metric mismatch")
        if row["in_subset"] != (row["model"] in subset_models):
            fails.append(f"{row['model']}: in_subset flag mismatch")
    # subset membership must match the source list verbatim (order included)
    if doc["subset"] != list(_read_subset_yaml(SUBSET_YAML).get("subset") or []):
        fails.append("subset list does not match best_subset.yaml verbatim")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the existing data/ranking.json only")
    args = ap.parse_args()

    if not SUBSET_YAML.exists() or not RANKING_CSV.exists():
        sys.exit(
            "Owner-local validation outputs not found:\n"
            f"  {SUBSET_YAML}\n  {RANKING_CSV}\n"
            "Run gcm-pipeline step 08 first (Owner compute); nothing is "
            "fabricated in its absence (R3).")

    if args.check:
        doc = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    else:
        doc = build()

    fails = verify(doc)
    if fails:
        for f in fails:
            print("FAIL:", f)
        return 1
    print(f"round-trip verified: {len(doc['ranking'])} rows x "
          f"{len(METRIC_KEYS) + 2} fields, subset n={doc['ensemble_n']}")

    if args.check:
        print("CHECK PASS (existing file untouched)")
        return 0

    payload = json.dumps(doc, indent=1, ensure_ascii=False,
                         sort_keys=False) + "\n"
    data = payload.encode("utf-8")
    OUT_JSON.write_bytes(data)
    print(f"wrote {OUT_JSON.relative_to(REPO)} "
          f"({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
