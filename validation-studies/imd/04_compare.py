"""M4.3 - comparison framework: era B vs IMD, by timescale, season and region.

Metrics (same definitions as the era A<->B cross-validation, so the two
validation studies are readable side by side):

  r          Pearson correlation of the matched monthly district series
  bias       mean(IMD - era B) in indicator units (z)
  RMSD       root-mean-square of the same difference
  state      share of months on the same side of the -1.00 truncation
  class      McKee exact / within-one-class agreement
  event      Jaccard overlap of drought-flagged months

Aggregates are reported two ways: the unweighted district median (robust) and
the area-weighted mean (what a national statement should use). Districts with
no matched pair are absent, never zero-filled.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

INDICATORS = {  # imd file suffix -> era-B csv
    "spi_01": "spi_01.csv",
    "spi_03": "spi_03.csv",
    "spi_06": "spi_06.csv",
    "spi_12": "spi_12.csv",
    "spei_03": "spei_03.csv",
    "spei_12": "spei_12.csv",
}


def load_pair(cfg, key, ids, months):
    imd_path = Path(cfg["_work"]) / f"imd_{key}.csv"
    die_path = C.REPO / "data" / "drought" / INDICATORS[key]
    if not imd_path.exists() or not die_path.exists():
        return None, None
    imd = C.read_die_matrix(imd_path, ids, months)
    die = C.read_die_matrix(die_path, ids, months)
    return imd, die


def seasonal_metrics(imd, die, months, season_months, area):
    rows = []
    idx = [i for i, (_y, m) in enumerate(months) if m in season_months]
    for d in range(imd.shape[0]):
        a = imd[d, idx]
        b = die[d, idx]
        a2, b2 = C.finite_pair(a, b)
        if a2.size < 3:
            rows.append((d, a2.size, None, None, None, None, None, None))
            continue
        r = C.pearson(a, b)
        bias, rmsd = C.bias_rmsd(a, b)
        state = C.state_agreement(a, b)
        exact, near = C.class_agreement(a, b)
        ev = C.event_match(a, b)
        rows.append((d, a2.size, r, bias, rmsd, state, exact, ev))
    df = pd.DataFrame(rows, columns=["d", "n", "r", "bias", "rmsd", "state",
                                     "class_exact", "event"])
    df["area"] = area
    return df


def summarise(df: pd.DataFrame, min_pairs: int) -> dict:
    ok = df["n"] >= min_pairs
    out = {"districts": int(ok.sum()), "pairs": int(df.loc[ok, "n"].sum())}
    for col in ("r", "bias", "rmsd", "state", "class_exact", "event"):
        v = df.loc[ok, col].astype(float)
        w = df.loc[ok, "area"].astype(float)
        vv = v[np.isfinite(v)]
        if vv.empty:
            out[col] = {"median": None, "weighted": None}
            continue
        ww = w[np.isfinite(v)]
        out[col] = {
            "median": float(np.median(vv)),
            "weighted": float(np.average(vv, weights=ww)) if ww.sum() > 0 else None,
        }
    return out


def national_series(imd, die, area):
    """Area-weighted national monthly series for both records (diagnostic)."""
    w = area.copy()

    def weighted_mean(mat):
        num = np.nansum(mat * w[:, None], axis=0)
        den = (np.isfinite(mat) * w[:, None]).sum(axis=0)
        out = np.full(num.shape, np.nan)
        np.divide(num, den, out=out, where=den > 0)
        return out

    return weighted_mean(imd), weighted_mean(die)


def main() -> int:
    cfg = C.load_config()
    reg = pd.read_csv(C.REPO / cfg["fabric"]["districts_csv"], dtype={"district_id": str})
    ids = reg["district_id"].tolist()
    area = reg["area_km2"].to_numpy(float)
    states = reg["state_name"].tolist()
    y0, y1 = cfg["study"]["period"]
    months = C.month_grid(y0, y1)
    seasons = cfg["comparison"]["seasons"]
    min_pairs = int(cfg["comparison"]["min_pairs"])

    report = {"schema": "die-imd-comparison/1.0", "period": [y0, y1],
              "indicators": {}, "national": {}, "notes": [
                  "bias is mean(IMD - era B); negative means IMD is drier",
                  "state/class/event use the published McKee thresholds",
                  "districts without a matched pair are absent, never zero-filled",
              ]}
    summary_md = ["# IMD benchmark — summary", "",
                  f"Window {y0}–{y1}; IMD = independent station-interpolated reference; "
                  "era B = the shipped record.", ""]

    for key in INDICATORS:
        imd, die = load_pair(cfg, key, ids, months)
        if imd is None:
            print(f"{key}: no data (skipped)")
            continue
        fam, scale = key.split("_", 1)
        entry = {"label": f"{fam.upper()}-{int(scale)}"}
        for sname, smonths in seasons.items():
            df = seasonal_metrics(imd, die, months, smonths, area)
            entry[sname] = summarise(df, min_pairs)
            if sname == "all":
                per = df.copy()
                per["district_id"] = ids
                per["state_name"] = states
                per = per[per["n"] >= min_pairs]
                cols = ["district_id", "state_name", "n", "r", "bias", "rmsd",
                        "state", "class_exact", "event"]
                per[cols].to_csv(
                    Path(cfg["_report"]) / f"per_district_{key}.csv",
                    index=False, float_format="%.4f")
        na, nb = national_series(imd, die, area)
        report["national"][key] = {
            "r": C.pearson(na, nb),
            "bias": C.bias_rmsd(na, nb)[0],
            "rmsd": C.bias_rmsd(na, nb)[1],
            "n_months": int(np.isfinite(na).sum()),
        }
        report["indicators"][key] = entry

        s = entry["all"]
        summary_md.append(
            f"| {entry['label']} | {s['districts']} | {s['pairs']:,} | "
            f"{s['r']['median']:.3f} | {s['bias']['weighted']:+.3f} | "
            f"{s['rmsd']['weighted']:.3f} | {100*s['state']['weighted']:.1f} % | "
            f"{100*s['class_exact']['weighted']:.1f} % | {100*s['event']['weighted']:.1f} % |")
        print(f"{key}: districts {s['districts']}, median r {s['r']['median']:.3f}, "
              f"weighted bias {s['bias']['weighted']:+.3f}, "
              f"state agreement {100*s['state']['weighted']:.1f} %")

    summary_md[3:3] = [
        "| Indicator | Districts | Pairs | median r | area bias | area RMSD | state | class | event |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    (Path(cfg["_report"]) / "compare_summary.md").write_text(
        "\n".join(summary_md) + "\n", encoding="utf-8")
    C.write_json(Path(cfg["_report"]) / "validation_report.json", report)
    print("\nwrote", Path(cfg["_report"]) / "validation_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
