# Drought Intelligence Explorer v2.0.0 — release notes

**Date:** 2026-11-22 · **Data snapshot:** `v2026.09` · **Methodology:** `research-gee-1.0.2` · **Pipeline:** `1.1.0`
**Live:** https://drought.ankitdeshmukh.com · **Data host:** https://data.ankitdeshmukh.com/v2026.09/

## What v2.0.0 is

One queryable drought record for India, presented as **three labelled eras that are never spliced**, with the same statistical interrogation layer over all of them:

- **Era A — Drought Atlas of India reconstruction** (SPEI-1/4/12, 1901–2025), ingested from the 0.05° Atlas grid onto the 724-district fabric.
- **Era B — gridded multi-source product** (SPI-1/3/6/12, SPEI-1/3/6/12, soil-moisture anomaly, VCI), **1981-01 → 2026-09**, from CHIRPS v2.0, ERA5-Land and MODIS MOD13A3. Each indicator family reads its own source; they are never blended.
- **Era C — 24 bias-corrected CMIP6 models** (QDM against IMD 0.25° rainfall and temperature), SSP2-4.5 and SSP5-8.5, **2015–2100**, with ensemble median, 25th/75th percentiles, model-agreement fractions and per-model members. Simulations, never forecasts.

## Highlights since v1.0.0

**Science**
- Era A ingestion, promotion and per-district QA (median r 0.996–0.999 against the Atlas's own district series).
- Era A ↔ era B cross-validation over 1981–2014 (718 districts, median r 0.717/0.667, area bias +0.044/+0.008 z, state agreement 83.6/82.9 %) and the X7 seam uncertainty (`sd_diff`, SPEI-12 median 0.78 z).
- Era C chain: 24 GCMs, QDM bias correction, Hargreaves PET, ensemble statistics, validation gate.
- **Independent IMD benchmark** (new in this release): 719 districts × 540 months; median district r 0.60–0.71 (national series 0.73–0.86), area-weighted bias −0.038…+0.002 z, drought-state agreement 82.2–86.9 %; trend detection differs while direction agrees (83–89 % sign agreement among districts significant in both). Memo: `validation-studies/imd/report/validation-memo.md`.

**Application**
- Product-first navigation: `Record · Projections · Atlas · Engine Lab`, with the analytical lenses beneath; help and reference in the topbar.
- **Guided tour** (`tour.html`), delayed hover/focus explainers on every product, lens and utility, and per-product rail consoles.
- **Engine Lab**: SQL over the published Parquet store in the browser (DuckDB-WASM), with presets, arbitrary queries, byte/request counters and CSV export.
- District profiles (`#/district/<id>`), state-encoding permalinks with malformed-hash hardening, share card and PNG export with citation strip.
- Mobile and WCAG pass: 44 px targets, two-row status on phones, contrast fixes, keyboard operability.

**Documentation**
- Documentation A–P: About, data sources, methodology, validation (including the IMD benchmark), uncertainty, reproducibility, downloads and citation, version history, user guide, glossary, living methodology, governance and licences, reality checks, data status, and the **SQL field reference (P)** with copy-paste recipes.
- Every headline surface links "How this is made" to its method anchor.

**Data delivery**
- Bulk data moved out of git to an **immutable Cloudflare R2 snapshot** (`v2026.09`), read over HTTP Range requests; the repository keeps a ~200-byte pointer (`data/data-source.json`). Monthly refreshes are now kilobyte-scale commits instead of ~13 MB of permanent history.

## Data coverage

| Era | Indicator | From | To |
|---|---|---|---|
| B | SPI-1 | 1981-01 | 2026-09 |
| B | SPI-3 / SPI-6 / SPI-12 | 1981-03 / 06 / 12 | 2026-09 |
| B | SPEI-1/3/6/12 | 1981 (after warm-up) | 2026-09 |
| B | Soil-moisture anomaly | 1981-01 | 2026-09 |
| B | VCI | 2000-02 | 2026-09 |
| A | SPEI-1/4/12 | 1901-01 | 2025-12 |
| C | SPI/SPEI 1/3/6/12 | 2015 | 2100 |

549 months of era B; 724 districts; data month **2026-09** (53-day lag at release, amber by design).

## Compatibility and known limitations

- v1.0.0 URL hashes still work (`#overview`, `#historical`, `#events`, `#propagation`, `#data`); new hashes: `#atlas`, `#projections`, `#summary`, `#crossval`, `#engine`, `#/district/<id>`.
- The v2.0.0 **software DOI is minted by the GitHub–Zenodo integration when this release is published**; until then the interface and `CITATION.cff` show the concept DOI `10.5281/zenodo.24113363` and an explicit "pending" note. The dataset record is a separate Zenodo deposit (see the release assets / repository README).
- IMD temperature is the **1.0°** product (1951–2025); every temperature-based comparison is bounded at 1951 and inherits that resolution.
- Era C 2015–2025 holds free-running model realisations, not observations; the overlap with era B is cross-validation material only.
- GitHub Pages caps sites at 1 GB, which is why the data are hosted on R2.

## Verification at release

`data-pipeline/selftest.py` PASS · `scripts/regression_check.py` PASS (735 values) · reality checks PASS · reproduced figures PASS (Fig 5 = 4 of 547 months, Fig 6 r = 0.8716, n = 547) · `build_status.py --check` PASS · R2 `verify_r2.py` 6/6 · all routes at desktop and 390 px with zero console errors, zero overflow · Lighthouse Accessibility 1.00 on the main surfaces.

## Citation

```
Deshmukh, A. (2026). Drought Intelligence Explorer: a multi-era district drought
record and analytics platform for India (Version 2.0.0) [Software].
Zenodo. https://doi.org/10.5281/zenodo.24444860
```

Concept DOI (always latest): https://doi.org/10.5281/zenodo.24113363 · v1.0.0: https://doi.org/10.5281/zenodo.24113364

Data: *Drought Intelligence Explorer v2.0.0 — district drought record for India (1901–2100)*, snapshot v2026.09, CC-BY-4.0 (dataset DOI pending; archived at https://data.ankitdeshmukh.com/v2026.09/).
