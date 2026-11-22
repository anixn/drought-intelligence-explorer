# IMD benchmark validation memo

**Status:** computed from the Owner's local IMD archive by `validation-studies/imd/` (tasks M4.1–M4.4). Every number below is read from the JSON artifacts written by the same run; nothing is hand-entered. This is the M4 exit-gate memo with real numbers.

**Comparison window:** 1981–2025. **Standardisation base:** 1981–2020 (identical to era B).

## Findings at a glance

- **Correlation.** Median district-level r ranges **0.60–0.71** across the 6 indicators (national area-weighted series: **0.73–0.86**).
- **Bias.** Area-weighted mean difference (IMD − era B) stays within **-0.038 to +0.002 z** — i.e. no systematic wet or dry offset at district scale; the sign drifts slightly negative at longer accumulation windows.
- **Drought state.** Districts agree on which side of the −1.00 truncation in **82.2–86.9 %** of months; exact nine-class agreement is **31.7–36.5 %**, which is the expected ceiling for a nine-bin scheme dominated by the near-normal class (the UI reports state and within-one-class for that reason).

- **Trend detection differs while direction does not.** With BH-FDR at q = 0.05, era B flags more districts than IMD (e.g. SPI-3: 324 vs 155), yet among districts significant in both, the slope sign agrees in **89.3 %**. A longer, smoother input series (and, for SPEI, a different PET) raises detection power without contradicting the direction.

## 1. Inputs actually used

| Variable | Files | Years | Grid | Units | Status | Notes |
|---|---|---|---|---|---|---|
| rainfall | 125 | 1901–2025 | 129×135 @ 0.25° | mm/day | PASS | — |
| tmax | 75 | 1951–2025 | 31×31 @ 1.0° | degC | PASS | — |
| tmin | 75 | 1951–2025 | 31×31 @ 1.0° | degC | PASS | — |

**Product note (X8 / OD3):** the IMD temperature archive on this machine is the **1.0° daily** product (1951–2025), not 0.25°. Temperature-based results are therefore restricted to 1951 onward and inherit the 1° resolution; pre-1951 temperature reasoning must use the era-A reconstruction, never an extrapolated IMD series.

## 2. District aggregation

Fractional area weights: each grid cell is split into 8×8 sub-cells, a district's weight in a cell is its covered share × cos(latitude), and the district series is the weighted mean of finite cells only. Ocean cells carry no district weight.

| Variable | Grid | Months | Districts covered | Median cells per district | Range |
|---|---|---|---|---|---|
| rainfall | 129×135 | 540 | 722 | 11 | 1–299 |
| tmax | 31×31 | 540 | 717 | 2 | 1–29 |
| tmin | 31×31 | 540 | 717 | 2 | 1–29 |

Districts with no intersecting cell (reported, never filled with a national average): **rainfall** — lakshadweep-lakshadweep, puducherry-mahe; **tmax** — dadra-and-nagar-haveli-and-daman-and-diu-daman, dadra-and-nagar-haveli-and-daman-and-diu-diu, lakshadweep-lakshadweep, puducherry-mahe, puducherry-yanam, tamil-nadu-chennai, west-bengal-kolkata; **tmin** — dadra-and-nagar-haveli-and-daman-and-diu-daman, dadra-and-nagar-haveli-and-daman-and-diu-diu, lakshadweep-lakshadweep, puducherry-mahe, puducherry-yanam, tamil-nadu-chennai, west-bengal-kolkata.

## 3. Agreement with the era-B record

Bias is `mean(IMD − era B)` in z units: a negative bias means the IMD reference is **drier** than the shipped record. “Area” means area-weighted over districts; the median is the unweighted district median (robust to small districts).

| Indicator | Districts | Pairs | median r | area bias | area RMSD | state | class | event |
|---|---|---|---|---|---|---|---|---|
| SPI-1 | 719 | 388,260 | 0.675 | +0.002 | 0.800 | 86.9 % | 36.5 % | 33.2 % |
| SPI-3 | 719 | 386,822 | 0.659 | -0.018 | 0.844 | 83.9 % | 33.7 % | 32.5 % |
| SPI-6 | 719 | 384,665 | 0.643 | -0.027 | 0.862 | 83.4 % | 33.0 % | 31.8 % |
| SPI-12 | 719 | 380,351 | 0.604 | -0.030 | 0.891 | 82.2 % | 31.7 % | 29.4 % |
| SPEI-3 | 714 | 384,068 | 0.714 | -0.028 | 0.760 | 84.9 % | 35.6 % | 36.2 % |
| SPEI-12 | 714 | 377,624 | 0.647 | -0.038 | 0.807 | 84.3 % | 32.7 % | 34.7 % |

### Seasonal breakdown (area-weighted)

| Indicator | Season | median r | area bias | state | class |
|---|---|---|---|---|---|
| SPI-1 | all | 0.675 | +0.002 | 86.9 % | 36.5 % |
| SPI-1 | jjas | 0.678 | -0.019 | 85.3 % | 36.6 % |
| SPI-1 | ondj | 0.681 | +0.015 | 88.3 % | 37.2 % |
| SPI-3 | all | 0.659 | -0.018 | 83.9 % | 33.7 % |
| SPI-3 | jjas | 0.623 | -0.025 | 83.2 % | 32.7 % |
| SPI-3 | ondj | 0.694 | -0.017 | 84.8 % | 35.8 % |
| SPI-6 | all | 0.643 | -0.027 | 83.4 % | 33.0 % |
| SPI-6 | jjas | 0.608 | -0.027 | 82.9 % | 31.8 % |
| SPI-6 | ondj | 0.615 | -0.026 | 83.0 % | 33.2 % |
| SPI-12 | all | 0.604 | -0.030 | 82.2 % | 31.7 % |
| SPI-12 | jjas | 0.612 | -0.031 | 82.6 % | 32.6 % |
| SPI-12 | ondj | 0.601 | -0.029 | 81.7 % | 31.3 % |
| SPEI-3 | all | 0.714 | -0.028 | 84.9 % | 35.6 % |
| SPEI-3 | jjas | 0.676 | -0.021 | 84.5 % | 34.0 % |
| SPEI-3 | ondj | 0.742 | -0.023 | 86.2 % | 37.5 % |
| SPEI-12 | all | 0.647 | -0.038 | 84.3 % | 32.7 % |
| SPEI-12 | jjas | 0.656 | -0.037 | 84.6 % | 33.2 % |
| SPEI-12 | ondj | 0.642 | -0.038 | 84.0 % | 32.4 % |

### National monthly series (area-weighted, diagnostic)

| Indicator | r | bias | RMSD | months |
|---|---|---|---|---|
| SPI-1 | 0.864 | +0.002 | 0.243 | 540 |
| SPI-3 | 0.824 | -0.018 | 0.276 | 538 |
| SPI-6 | 0.786 | -0.027 | 0.307 | 535 |
| SPI-12 | 0.730 | -0.030 | 0.356 | 529 |
| SPEI-3 | 0.838 | -0.028 | 0.293 | 538 |
| SPEI-12 | 0.777 | -0.038 | 0.358 | 529 |

## 4. Trend maps (Mann–Kendall + Sen, BH-FDR q = 0.05)

Annual means require ≥ 9 valid months (the application's rule). FDR control is applied within each record.

| Indicator | Testable | IMD sig (raw) | IMD sig (FDR) | era B sig (raw) | era B sig (FDR) | both FDR | sign agreement |
|---|---|---|---|---|---|---|---|
| SPI-3 | 719 | 261 | 155 | 382 | 324 | 75 | 89.3 % |
| SPI-12 | 719 | 317 | 239 | 445 | 397 | 115 | 83.5 % |
| SPEI-12 | 714 | 293 | 191 | 521 | 505 | 105 | 84.8 % |

## 5. What this does and does not show

1. **What it shows.** Where the CHIRPS/ERA5-Land-based record and the independent station-interpolated IMD reference agree — in correlation, in drought state, in class and in trend direction — and where they do not. Discrepancies are listed above rather than smoothed away.
2. **SPI is the clean comparison.** Both sides use the same rainfall-only estimator and the same 1981–2020 base, so a difference is a difference in the rainfall input and its spatial aggregation.
3. **SPEI carries a method difference.** Era B uses ERA5-Land PET; the IMD benchmark uses Hargreaves–Samani PET on 1° IMD temperatures. A SPEI difference therefore mixes rainfall and PET-method effects and is reported for completeness, not as a like-for-like test.
4. **Resolution.** Rainfall is 0.25°, temperature 1.0°, aggregated to districts with fractional area weights. A district smaller than a cell is represented by that cell's coverage; small-district metrics are noisier than large-district metrics. The 1° temperature grid gives most districts only one or two cells, so PET — and therefore every SPEI number — is coarse by construction; SPI is the benchmark's primary result.
5. **No operational claim.** These are research comparisons; neither record is an official drought declaration.

## 6. Reproduction

```bash
python validation-studies/imd/00_verify_imd.py
python validation-studies/imd/01_imd_monthly.py
python validation-studies/imd/02_districts.py
python validation-studies/imd/03_indicators.py
python validation-studies/imd/04_compare.py
python validation-studies/imd/05_fdr_trends.py
python validation-studies/imd/99_memo.py
```

Inputs: the Owner's local IMD archive (not committed). Outputs: `report/validation_report.json`, `report/per_district_*.csv`, `report/trends_*.csv`, `report/trend_comparison.json`, this memo.
