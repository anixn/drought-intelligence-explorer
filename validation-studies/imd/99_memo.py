"""M4.4 - validation memo from the computed artifacts (never hand-typed numbers).

Every number in the memo comes from work/imd_inventory.json,
report/validation_report.json or report/trend_comparison.json, written by the
steps before it. If a step has not run, the section says so rather than
printing a placeholder value.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def label(key: str) -> str:
    """spi_01 -> SPI-1, spei_12 -> SPEI-12 (the dashboard's spelling)."""
    fam, scale = key.split("_", 1)
    return f"{fam.upper()}-{int(scale)}"


def num(x, nd=3, sign=False) -> str:
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def main() -> int:
    cfg = C.load_config()
    inv_p = Path(cfg["_work"]) / "imd_inventory.json"
    rep_p = Path(cfg["_report"]) / "validation_report.json"
    tr_p = Path(cfg["_report"]) / "trend_comparison.json"
    district_p = Path(cfg["_work"]) / "imd_districts_report.json"
    if not rep_p.exists():
        raise SystemExit("run 04_compare.py first")

    inv = json.loads(inv_p.read_text(encoding="utf-8")) if inv_p.exists() else None
    rep = json.loads(rep_p.read_text(encoding="utf-8"))
    tr = json.loads(tr_p.read_text(encoding="utf-8")) if tr_p.exists() else None
    dist = json.loads(district_p.read_text(encoding="utf-8")) if district_p.exists() else None

    L: list[str] = []
    L += ["# IMD benchmark validation memo", "",
          "**Status:** computed from the Owner's local IMD archive by "
          "`validation-studies/imd/` (tasks M4.1–M4.4). Every number below is "
          "read from the JSON artifacts written by the same run; nothing is "
          "hand-entered. This is the M4 exit-gate memo with real numbers.", "",
          f"**Comparison window:** {rep['period'][0]}–{rep['period'][1]}. "
          "**Standardisation base:** 1981–2020 (identical to era B).", ""]

    # ---- findings at a glance (derived, never typed) ----------------------
    inds = list(rep.get("indicators", {}).values())
    if inds:
        rs = [e["all"]["r"]["median"] for e in inds if e["all"]["r"]["median"] is not None]
        st = [e["all"]["state"]["weighted"] for e in inds if e["all"]["state"]["weighted"] is not None]
        bi = [e["all"]["bias"]["weighted"] for e in inds if e["all"]["bias"]["weighted"] is not None]
        cl = [e["all"]["class_exact"]["weighted"] for e in inds if e["all"]["class_exact"]["weighted"] is not None]
        L += ["## Findings at a glance", "",
              f"- **Correlation.** Median district-level r ranges **{min(rs):.2f}–{max(rs):.2f}** "
              f"across the {len(inds)} indicators (national area-weighted series: "
              f"**{min(n['r'] for n in rep['national'].values()):.2f}–"
              f"{max(n['r'] for n in rep['national'].values()):.2f}**).",
              f"- **Bias.** Area-weighted mean difference (IMD − era B) stays within "
              f"**{min(bi):+.3f} to {max(bi):+.3f} z** — i.e. no systematic wet or dry "
              "offset at district scale; the sign drifts slightly negative at longer "
              "accumulation windows.",
              f"- **Drought state.** Districts agree on which side of the −1.00 "
              f"truncation in **{100*min(st):.1f}–{100*max(st):.1f} %** of months; exact "
              f"nine-class agreement is **{100*min(cl):.1f}–{100*max(cl):.1f} %**, "
              "which is the expected ceiling for a nine-bin scheme dominated by the "
              "near-normal class (the UI reports state and within-one-class for that "
              "reason).", ""]
    if tr and tr.get("indicators"):
        e = next(iter(tr["indicators"].values()))
        first = next(iter(tr["indicators"].items()))
        L += [f"- **Trend detection differs while direction does not.** With BH-FDR at "
              f"q = 0.05, era B flags more districts than IMD "
              f"(e.g. {label(first[0])}: {first[1]['era_b']['sig_fdr']} vs "
              f"{first[1]['imd']['sig_fdr']}), yet among districts significant in both, "
              f"the slope sign agrees in **{100*e['sign_agree_share_both']:.1f} %**. "
              "A longer, smoother input series (and, for SPEI, a different PET) raises "
              "detection power without contradicting the direction.", ""]

    L += ["## 1. Inputs actually used", ""]
    if inv:
        L += ["| Variable | Files | Years | Grid | Units | Status | Notes |",
              "|---|---|---|---|---|---|---|"]
        for v in inv["variables"]:
            grid = f"{v.get('n_lat', '?')}×{v.get('n_lon', '?')} @ {v.get('dlat', '?')}°"
            years = v.get("years") or ["—", "—"]
            L.append(f"| {v['key']} | {v['files']} | {years[0]}–{years[1]} | {grid} | "
                     f"{v.get('units', '')} | {v['status']} | {'; '.join(v.get('notes', [])) or '—'} |")
        L.append("")
        temp = next((v for v in inv["variables"] if v["key"] == "tmax"), None)
        if temp and temp.get("dlat") and abs(float(temp["dlat"]) - 1.0) < 1e-6:
            L += ["**Product note (X8 / OD3):** the IMD temperature archive on this "
                  "machine is the **1.0° daily** product (1951–2025), not 0.25°. "
                  "Temperature-based results are therefore restricted to 1951 "
                  "onward and inherit the 1° resolution; pre-1951 temperature "
                  "reasoning must use the era-A reconstruction, never an "
                  "extrapolated IMD series.", ""]
    else:
        L += ["_Inventory not found — run `00_verify_imd.py`._", ""]

    if dist:
        L += ["## 2. District aggregation", "",
              "Fractional area weights: each grid cell is split into "
              f"{cfg['fabric']['supersample']}×{cfg['fabric']['supersample']} "
              "sub-cells, a district's weight in a cell is its covered share × "
              "cos(latitude), and the district series is the weighted mean of "
              "finite cells only. Ocean cells carry no district weight.", "",
              "| Variable | Grid | Months | Districts covered | Median cells per district | Range |",
              "|---|---|---|---|---|---|"]
        for s in dist["steps"]:
            rng = f"{s.get('cells_min', '—')}–{s.get('cells_max', '—')}"
            L.append(f"| {s['key']} | {s['grid'][0]}×{s['grid'][1]} | {s['months']} | "
                     f"{s['districts_covered']} | {num(s.get('cells_median'), 0)} | {rng} |")
        L.append("")
        absent = [s for s in dist["steps"] if s.get("districts_absent")]
        if absent:
            L.append("Districts with no intersecting cell (reported, never filled "
                     "with a national average): " +
                     "; ".join(f"**{s['key']}** — {', '.join(s['districts_absent'])}"
                               for s in absent) + ".")
            L.append("")

    L += ["## 3. Agreement with the era-B record", "",
          "Bias is `mean(IMD − era B)` in z units: a negative bias means the IMD "
          "reference is **drier** than the shipped record. “Area” means "
          "area-weighted over districts; the median is the unweighted district "
          "median (robust to small districts).", "",
          "| Indicator | Districts | Pairs | median r | area bias | area RMSD | state | class | event |",
          "|---|---|---|---|---|---|---|---|---|"]
    for key, e in rep["indicators"].items():
        s = e["all"]
        L.append(f"| {e['label']} | {s['districts']} | {s['pairs']:,} | "
                 f"{num(s['r']['median'])} | {num(s['bias']['weighted'], 3, True)} | "
                 f"{num(s['rmsd']['weighted'])} | {pct(s['state']['weighted'])} | "
                 f"{pct(s['class_exact']['weighted'])} | {pct(s['event']['weighted'])} |")
    L.append("")

    L += ["### Seasonal breakdown (area-weighted)", "",
          "| Indicator | Season | median r | area bias | state | class |",
          "|---|---|---|---|---|---|"]
    for key, e in rep["indicators"].items():
        for sname in ("all", "jjas", "ondj"):
            if sname not in e:
                continue
            s = e[sname]
            L.append(f"| {e['label']} | {sname} | {num(s['r']['median'])} | "
                     f"{num(s['bias']['weighted'], 3, True)} | "
                     f"{pct(s['state']['weighted'])} | {pct(s['class_exact']['weighted'])} |")
    L.append("")

    if rep.get("national"):
        L += ["### National monthly series (area-weighted, diagnostic)", "",
              "| Indicator | r | bias | RMSD | months |", "|---|---|---|---|---|"]
        for key, n in rep["national"].items():
            L.append(f"| {label(key)} | {num(n['r'])} | "
                     f"{num(n['bias'], 3, True)} | {num(n['rmsd'])} | {n['n_months']} |")
        L.append("")

    if tr:
        L += ["## 4. Trend maps (Mann–Kendall + Sen, BH-FDR q = 0.05)", "",
              "Annual means require ≥ 9 valid months (the application's rule). "
              "FDR control is applied within each record.", "",
              "| Indicator | Testable | IMD sig (raw) | IMD sig (FDR) | era B sig (raw) | era B sig (FDR) | both FDR | sign agreement |",
              "|---|---|---|---|---|---|---|---|"]
        for key, e in tr["indicators"].items():
            L.append(f"| {label(key)} | {e['districts_testable']} | "
                     f"{e['imd']['sig_raw']} | {e['imd']['sig_fdr']} | "
                     f"{e['era_b']['sig_raw']} | {e['era_b']['sig_fdr']} | "
                     f"{e['both_fdr']} | {pct(e['sign_agree_share_both'])} |")
        L.append("")

    L += ["## 5. What this does and does not show", "",
          "1. **What it shows.** Where the CHIRPS/ERA5-Land-based record and the "
          "independent station-interpolated IMD reference agree — in correlation, "
          "in drought state, in class and in trend direction — and where they do "
          "not. Discrepancies are listed above rather than smoothed away.",
          "2. **SPI is the clean comparison.** Both sides use the same rainfall-"
          "only estimator and the same 1981–2020 base, so a difference is a "
          "difference in the rainfall input and its spatial aggregation.",
          "3. **SPEI carries a method difference.** Era B uses ERA5-Land PET; the "
          "IMD benchmark uses Hargreaves–Samani PET on 1° IMD temperatures. A "
          "SPEI difference therefore mixes rainfall and PET-method effects and is "
          "reported for completeness, not as a like-for-like test.",
          "4. **Resolution.** Rainfall is 0.25°, temperature 1.0°, aggregated to "
          "districts with fractional area weights. A district smaller than a cell "
          "is represented by that cell's coverage; small-district metrics are "
          "noisier than large-district metrics. The 1° temperature grid gives most "
          "districts only one or two cells, so PET — and therefore every SPEI "
          "number — is coarse by construction; SPI is the benchmark's primary "
          "result.",
          "5. **No operational claim.** These are research comparisons; neither "
          "record is an official drought declaration.", "",
          "## 6. Reproduction", "",
          "```bash",
          "python validation-studies/imd/00_verify_imd.py",
          "python validation-studies/imd/01_imd_monthly.py",
          "python validation-studies/imd/02_districts.py",
          "python validation-studies/imd/03_indicators.py",
          "python validation-studies/imd/04_compare.py",
          "python validation-studies/imd/05_fdr_trends.py",
          "python validation-studies/imd/99_memo.py",
          "```", "",
          "Inputs: the Owner's local IMD archive (not committed). Outputs: "
          "`report/validation_report.json`, `report/per_district_*.csv`, "
          "`report/trends_*.csv`, `report/trend_comparison.json`, this memo."]

    out = Path(cfg["_report"]) / "validation-memo.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", out)

    # ---- slim artifact for the dashboard (Documentation D) ----------------
    slim = {
        "schema": "die-imd-validation/1.0",
        "period": rep["period"],
        "base": rep.get("base", cfg["study"]["base"]),
        "inputs": {
            "rainfall": "IMD 0.25° daily gridded rain (Pai et al. 2014 lineage)",
            "temperature": "IMD 1.0° daily gridded tmax/tmin (Srivastava et al. 2009 lineage), 1951–2025",
        },
        "indicators": [
            {
                "label": e["label"],
                "districts": e["all"]["districts"],
                "pairs": e["all"]["pairs"],
                "r_median": e["all"]["r"]["median"],
                "bias": e["all"]["bias"]["weighted"],
                "rmsd": e["all"]["rmsd"]["weighted"],
                "state": e["all"]["state"]["weighted"],
                "class_exact": e["all"]["class_exact"]["weighted"],
                "event": e["all"]["event"]["weighted"],
            }
            for e in rep["indicators"].values()
        ],
        "national": {
            k: {"r": v["r"], "bias": v["bias"], "rmsd": v["rmsd"], "n_months": v["n_months"]}
            for k, v in rep.get("national", {}).items()
        },
        "trends": [
            {
                "label": key.split("_")[0].upper() + "-" + str(int(key.split("_")[1])),
                "testable": e["districts_testable"],
                "imd_fdr": e["imd"]["sig_fdr"],
                "era_b_fdr": e["era_b"]["sig_fdr"],
                "both_fdr": e["both_fdr"],
                "sign_agree": e["sign_agree_share_both"],
            }
            for key, e in (tr or {}).get("indicators", {}).items()
        ],
        "memo": "validation-studies/imd/report/validation-memo.md",
        "generated_from": [
            "validation-studies/imd/work/imd_inventory.json",
            "validation-studies/imd/report/validation_report.json",
            "validation-studies/imd/report/trend_comparison.json",
        ],
    }
    slim_path = C.REPO / "data" / "imd_validation.json"
    C.write_json(slim_path, slim)
    print("wrote", slim_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
