# IMD benchmark validation study (M4, docs/v2/03 §5)

Independent, quantitative comparison of the era-B record against **IMD gridded
observations**, with the discrepancies published. This is the v1.0 manuscript's
top roadmap item and the answer to "how do we know the CHIRPS-based SPI is right
for India?" — IMD is station-interpolated national data, so it shares none of
the inputs that drive the shipped record.

## Inputs (Owner-local, not committed)

| Variable | Product | Resolution | Years |
|---|---|---|---|
| rainfall | IMD daily gridded rain (Pai et al. 2014 lineage) | 0.25° | 1901–2025 |
| tmax / tmin | IMD daily gridded temperature (Srivastava et al. 2009 lineage) | **1.0°** | 1951–2025 |

The temperature product's actual resolution (1.0°, not 0.25°) is verified by
`00_verify_imd.py` and recorded — register OD3 asked for exactly that check.
It is the binding constraint on any temperature-based statement: nothing is
extrapolated before 1951 (X8).

## Pipeline

| Script | Task | Output |
|---|---|---|
| `00_verify_imd.py` | M4.1 — inventory, years, grid, units, fill values | `work/imd_inventory.json` |
| `01_imd_monthly.py` | daily → monthly totals (rain) / means (temperature) | `work/imd_monthly_*.npz` |
| `02_districts.py` | fractional area weights, grid → 724 districts | `work/imd_district_*.csv` |
| `03_indicators.py` | IMD-SPI / IMD-SPEI with the **era-B code** (`die_pipeline.indicators`) | `work/imd_spi_*.csv`, `work/imd_spei_*.csv` |
| `04_compare.py` | M4.3 — r, bias, RMSD, state/class/event agreement, by season and nationally | `report/validation_report.json`, `report/per_district_*.csv` |
| `05_fdr_trends.py` | M4.3 — MK + Sen + BH-FDR trend maps for both records | `report/trend_comparison.json`, `report/trends_*.csv` |
| `99_memo.py` | M4.4 — memo + a slim JSON for the dashboard | `report/validation-memo.md`, `data/imd_validation.json` |

Run in order (each step is idempotent; weights are cached in `work/`):

```bash
python validation-studies/imd/00_verify_imd.py
python validation-studies/imd/01_imd_monthly.py
python validation-studies/imd/02_districts.py
python validation-studies/imd/03_indicators.py
python validation-studies/imd/04_compare.py
python validation-studies/imd/05_fdr_trends.py
python validation-studies/imd/99_memo.py
```

## Method choices that matter

1. **Same indicator machinery, different input.** SPI/SPEI are computed by
   importing `data-pipeline/die_pipeline/indicators.py` — same gamma (MLE) and
   log-logistic (L-moment) estimators, same mixed-zero handling, same 1981–2020
   base, same calibration gates, same Gringorten fallback. A difference is a
   difference in the data, not in the code.
2. **Two comparisons, two confidence levels.** SPI is the like-for-like test
   (rainfall only). SPEI mixes a rainfall difference with a PET-method
   difference (era B: ERA5-Land PET; benchmark: Hargreaves–Samani on 1° IMD
   temperature) and is reported as such.
3. **Fractional area weights.** 8×8 sub-cells per grid cell give each district
   a covered share × cos(latitude) weight; ocean cells carry no weight and a
   district with no covered cell is reported as absent, never filled.
4. **No fabrication.** Missing days/months stay missing; the memo marks any step
   that has not run instead of printing a placeholder.

## Reading the results

`report/validation-memo.md` is the M4 exit-gate memo: inputs actually used,
district coverage, agreement tables (overall, seasonal, national), trend-map
comparison, and the explicit "what this does and does not show" section. The
dashboard renders a summary in Documentation **D · Validation & data quality**
from `data/imd_validation.json`.
