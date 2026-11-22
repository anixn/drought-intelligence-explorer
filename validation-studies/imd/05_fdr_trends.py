"""M4.3 step 2 - trend-map comparison with BH-FDR (the mandatory view).

Mann-Kendall + Sen's slope on the annual mean of each district series (>= 9
valid months, the application's rule), computed independently for the IMD
benchmark and the era-B record. Benjamini-Hochberg at q = 0.05 over the district
set, because a trend map without multiple-testing control is exploratory.

Reports: how many districts trend (uncorrected vs FDR), and among districts
significant in both records, how often the sign agrees.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

INDICATORS = {"spi_03": "spi_03.csv", "spi_12": "spi_12.csv",
              "spei_12": "spei_12.csv"}


def annual_matrix(mat: np.ndarray, months: list[tuple[int, int]]):
    years = np.array([y for (y, _m) in months])
    cal = np.array([m for (_y, m) in months])
    out_years = sorted(set(years.tolist()))
    out = np.full((mat.shape[0], len(out_years)), np.nan)
    for j, y in enumerate(out_years):
        cols = np.where(years == y)[0]
        block = mat[:, cols]
        n = np.isfinite(block).sum(axis=1)
        mean = np.where(n > 0, np.nansum(block, axis=1) / np.maximum(n, 1), np.nan)
        out[:, j] = np.where(n >= 9, mean, np.nan)
    return np.asarray(out_years, float), out


def trend_table(mat, months, area):
    years, annual = annual_matrix(mat, months)
    rows = []
    for d in range(annual.shape[0]):
        x = annual[d]
        if np.isfinite(x).sum() < 10:
            rows.append((d, None, None, None))
            continue
        z, p = C.mann_kendall(x)
        slope = C.sen_slope(x, years)
        rows.append((d, z, p, slope))
    return pd.DataFrame(rows, columns=["d", "z", "p", "slope"])


def main() -> int:
    cfg = C.load_config()
    reg = pd.read_csv(C.REPO / cfg["fabric"]["districts_csv"], dtype={"district_id": str})
    ids = reg["district_id"].tolist()
    area = reg["area_km2"].to_numpy(float)
    y0, y1 = cfg["study"]["period"]
    months = C.month_grid(y0, y1)
    q = float(cfg["comparison"]["fdr_q"])

    report = {"schema": "die-imd-trends/1.0", "period": [y0, y1], "q": q,
              "annual_rule": ">= 9 valid months", "indicators": {}}

    for key, die_csv in INDICATORS.items():
        imd_path = Path(cfg["_work"]) / f"imd_{key}.csv"
        die_path = C.REPO / "data" / "drought" / die_csv
        if not imd_path.exists() or not die_path.exists():
            print(f"{key}: skipped")
            continue
        imd = C.read_die_matrix(imd_path, ids, months)
        die = C.read_die_matrix(die_path, ids, months)

        ti = trend_table(imd, months, area)
        tb = trend_table(die, months, area)
        ti["sig_raw"] = ti["p"] < 0.05
        tb["sig_raw"] = tb["p"] < 0.05
        ti["sig_fdr"] = C.bh_fdr(ti["p"].to_numpy(float), q)
        tb["sig_fdr"] = C.bh_fdr(tb["p"].to_numpy(float), q)

        both = ti["sig_fdr"] & tb["sig_fdr"]
        agree = (np.sign(ti["slope"]) == np.sign(tb["slope"])) & both
        entry = {
            "districts_testable": int(ti["p"].notna().sum()),
            "imd": {"sig_raw": int(ti["sig_raw"].sum()), "sig_fdr": int(ti["sig_fdr"].sum())},
            "era_b": {"sig_raw": int(tb["sig_raw"].sum()), "sig_fdr": int(tb["sig_fdr"].sum())},
            "both_fdr": int(both.sum()),
            "sign_agree_share_both": float(agree.sum() / both.sum()) if both.sum() else None,
            "median_slope": {
                "imd": float(np.nanmedian(ti["slope"])),
                "era_b": float(np.nanmedian(tb["slope"])),
            },
        }
        out = pd.DataFrame({
            "district_id": ids,
            "n_years_imd": ti["p"].notna(),
            "imd_z": ti["z"], "imd_p": ti["p"], "imd_slope": ti["slope"],
            "imd_sig_fdr": ti["sig_fdr"],
            "era_b_z": tb["z"], "era_b_p": tb["p"], "era_b_slope": tb["slope"],
            "era_b_sig_fdr": tb["sig_fdr"],
        })
        out.to_csv(Path(cfg["_report"]) / f"trends_{key}.csv",
                   index=False, float_format="%.5f")
        report["indicators"][key] = entry
        print(f"{key}: FDR-significant IMD {entry['imd']['sig_fdr']} / era B "
              f"{entry['era_b']['sig_fdr']} (of {entry['districts_testable']}); "
              f"sign agreement {entry['sign_agree_share_both']}")

    C.write_json(Path(cfg["_report"]) / "trend_comparison.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
