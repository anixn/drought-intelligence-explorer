# gcm-pipeline — DIE v2.0 era-C processing chain (runbook)

Owner-executed scientific pipeline (AGENTS.md R4): raw CMIP6 daily → regridded
0.25° monthly → QDM bias-corrected vs IMD → PET → SPI/SPEI → district
aggregates → ensemble statistics → validation gate → export. Everything is
reproducible from this directory with the commands below.

**Write-safety convention (X9, binding):** steps 01–08 write ONLY under
`work/`. Step 09 writes `out/` (staging). Copying anything into the repo's
`data/` happens ONLY via `09_export_parquet.py --publish`, which is gated
(X1) on a PASSing ssp-mode validation report.

---

## 0. Environment

| Thing | Value |
|---|---|
| Python | `C:\Users\deshm\miniconda3\envs\drought\python.exe` (conda `drought` env, NOT on PATH) |
| PROJ/GDAL fix | PostGIS sets global `PROJ_LIB`/`GDAL_DATA` to unusable locations. Per-run fix: `$env:PROJ_LIB='C:\Users\deshm\miniconda3\envs\drought\Lib\site-packages\rasterio\proj_data'; $env:GDAL_DATA='C:\Users\deshm\miniconda3\envs\drought\Lib\site-packages\rasterio\gdal_data'` (only needed for scripts importing rasterio/pyproj: 06; `run_ssp_chain.py` and `selftest_gcm.py` apply it automatically) |
| Data roots | `paths.yaml` → `raw_root` = `D:/Websites/die-data/cmip6/Hist` (historical 1981–2014), `raw_root_ssp` = `D:/Websites/die-data/cmip6/SSP` (ssp245+ssp585 2015–2050) |
| Config dir | `config/*.yaml`; every step honours `DIE_CONFIG_DIR` (test override; default unchanged) |
| Branch/CI | `v2-dev`; `.github/workflows/ci.yml` runs `data-pipeline/selftest.py` + `scripts/regression_check.py` + `selftest_gcm.py` on every push |

Naming contract for raw files (both roots, flat per-variable layout):

```
<root>/<var>/<var>_day_<model>_<experiment>_<variant>_<grid_label>_<year>_v2.0.nc
```

## 1. Verification harness (run before trusting anything)

```
python selftest_gcm.py              # orchestrator: v1.0 harness (82) + step selftests 02–09
python selftest_gcm.py --world      # M2.13 phase 2: synthetic end-to-end world, W1–W8
python selftest_gcm.py --list       # suite list
python selftest_gcm.py --only 05,08 # subset
```

- All suites are seed-deterministic (seed 20261103) and synthetic-only — no
  real data needed, no production files touched.
- `--world` builds a 3-model mini world under `work/test-output/gcm-world/`
  (wiped and rebuilt each run) that mirrors the REAL record shape
  (historical 1981–2014 + ssp245 2015–2050) and runs the whole 02→09 chain
  through subprocesses with `DIE_CONFIG_DIR`. Assertions W1–W8: regrid
  conservation, QDM bias removal, injected drying-trend survival, reference
  standardisation, ensemble exactness, gate PASS, staging round-trip, X1
  publish refusal. The world selftest is how the framework is proven without
  production compute (docs/v2/03 §3.11).

## 2. The chain (production order)

One-shot runner (resumable — each step skips SHA-256-verified outputs):

```
python run_ssp_chain.py --upto 07            # steps 01..07, log → work/ssp_chain_log.txt
python run_ssp_chain.py --upto 09            # + 08 gate + 09 staging (never publishes)
```

Individual steps (equivalent commands):

| Step | Command | Reads → writes |
|---|---|---|
| 00 | `python 00_download_cmip6.py --audit` / `--dry-run` / (download) | ESGF/Pangeo → `raw_root*` (Owner-run) |
| 01 | `python 01_inventory_check.py` | `raw_root`+`raw_root_ssp` → `work/inventory.json`; **gate**: historical completeness, AS6 ssp seam 2015–2020, truncation notes (R3), variant/grid multiplicity hard-fail |
| 02 | `python 02_regrid_025.py --experiments historical,ssp245,ssp585` | raw daily → `work/regrid/<model>/<exp>/<var>_<y0>-<y1>.nc`; conservative (pr) / masked-bilinear (tas) remap to the 0.25° target grid; conservation gate per record |
| 03 | `python 03_qdm_bias_correct.py --prepare-reference` (once) | IMD daily → `work/reference/imd_{pr,tasmax,tasmin}_1981-2020.nc` |
| 03 | `python 03_qdm_bias_correct.py --mode historical-corrected` | regrid → `work/qdm/<model>/historical-corrected/*.nc` (QDM vs IMD 1981–2020, C2) |
| 03 | `python 03_qdm_bias_correct.py --mode ssp --experiments ssp245,ssp585` | regrid → `work/qdm/<model>/<ssp>/*.nc`; calibration baseline = hist 1981–2014 + ssp 2015–2020 (AS6) |
| 04 | `python 04_pet_hargreaves.py --reference` / `--mode historical-corrected` / `--mode ssp --experiments ssp245,ssp585` | tas → `work/pet/...` (C3: identical Hargreaves on reference and model temperature) |
| 05 | `python 05_spi_spei_compute.py --reference` / `--mode historical-corrected` / `--mode ssp --experiments ssp245,ssp585` | pr+PET → `work/indices/...` (SPI/SPEI 1/3/6/12; ssp mode stitches hist-corrected + ssp and fits on the model baseline 1981–2020 — F1 fix, seam-validated) |
| 06 | `python 06_district_aggregate.py --reference` / (same modes) | grid → `work/aggregate/...` (LAEA area-overlap weights, per-month renormalisation, buffer fallback) |
| 07 | `python 07_ensemble_stats.py --mode historical-corrected` / `--mode ssp --experiments ssp245,ssp585` | aggregates → `work/ensemble/...` (median/p25/p75/agreement/n_models — X3 honest n) |
| 08 | `python 08_validate_gcm.py --mode historical-corrected` | aggregates+ensemble → `work/validation/{validation_report.json, best_subset.yaml, ranking.csv}` — 5-gate historical-skill validation, selects the committed subset |
| 08 | `python 08_validate_gcm.py --mode ssp` | ssp aggregates+ensemble → same files (mode=ssp report) — validates the corrected SSP record over the **observed overlap 2015–2020** only (months past the overlap are never gated, R2/R3); the committed subset is NOT re-selected |
| 09 | `python 09_export_parquet.py --mode historical-corrected` | validation products → `out/validation/` (the X5/E17 export; no parquet) |
| 09 | `python 09_export_parquet.py --mode ssp` | ensemble + per-model aggregates → `out/projections/` hive staging (X9) |
| 09 | `python 09_export_parquet.py --mode ssp --publish` | staging → repo `data/parquet/projections/` + catalog/manifest/metadata era-C blocks. **Gated (X1)** on the ssp-mode 08 report having no failed gate; requires Owner sign-off + `scripts/regression_check.py --bless` (catalog fingerprints change) |

## 3. Data-flow map

```
raw_root (Hist) ─┐
                 ├─ 02 → work/regrid/<model>/<exp>/<var>_*.nc
raw_root_ssp (SSP)┘        │
IMD daily ─ 03 --prepare-reference → work/reference/imd_*.nc (1981–2020)
                           │
        03 QDM ─→ work/qdm/<model>/<tag>/        (tag = historical-corrected | ssp245 | ssp585)
        04 PET ─→ work/pet/<model>/<tag>/
        05 idx ─→ work/indices/<model>/<tag>/     (+ work/indices/reference/)
        06 agg ─→ work/aggregate/<model>/<tag>/   (+ work/aggregate/reference/)
        07 ens ─→ work/ensemble/<tag>/
        08 val ─→ work/validation/{validation_report.json, best_subset.yaml, ranking.csv}
        09 exp ─→ out/{validation/, projections/}   --publish → data/parquet/projections/
```

Period labels are derived from the data everywhere (never hard-coded): the
record ends where the download ends and every surface reports the truncation
honestly (R3). Current reality: ssp245+ssp585 end 2050 (2051–2100 pending);
`models.yaml` keeps the full 2100 contract.

## 4. Measured sizes (2026-11-17, real run)

| Item | Measured |
|---|---|
| Raw historical (24 models × 3 vars × 34 y) | 16.78 GB (`cmip6/Hist`) |
| Raw ssp (8 models × 3 vars × 2 scenarios × 36 y) | 12.64 GB (`cmip6/SSP`), 1,728 files, 0 gaps |
| World selftest tree | ~60 MB (`work/test-output/gcm-world/`, gitignored) |
| *work/ chain sizes for the ssp run* | *Owner appends after the first full ssp chain completes (docs/v2/03 §3.10: estimates → measured)* |

## 5. Key config files (all science parameters live here, never in code)

| File | Contents |
|---|---|
| `config/paths.yaml` | data roots (raw_root, raw_root_ssp), work/out roots |
| `config/models.yaml` | the 24-model list, per-model variant/grid_label (from on-disk inventory — authoritative), experiment windows, era-C ensemble flags, genealogy (OD1) |
| `config/reference.yaml` | IMD-primary reference, 0.25° target grid, calibration 1981–2020, PET seam (C3), per-era z bounds |
| `config/aggregate.yaml` | boundaries geojson + district registry paths |
| `config/ensemble.yaml` | agreement thresholds, base/windows for dir_agreement |
| `config/validation.yaml` | ALL gate tolerances (printed verbatim into the report), ranking metrics + subset criterion, ssp-mode block (overlap window 2015–2020, scenarios) |
| `config/export.yaml` | export products, hive partition layout, publish targets, X1 gate flag |

## 6. Known caveats (carry into the methodology page — F6/F8/F9 backlog)

- Ranking min-max normalisation + neutral 0.5 imputation for missing metrics (F6).
- Model z fitted on 1981–2014 vs reference z on 1981–2020: small
  standardisation offset absorbed by the declared tolerances (F8).
- Documented simplifications: Hargreaves PET from monthly-mean extremes;
  monthly-scale QDM; mask-renormalised conservative remap (F9).
- Genealogy-correlated pooling is an OPEN Owner decision (F3/OD1) — the gate
  pools models as if independent until signed otherwise.
- `dir_agreement_drier` declared in export.yaml but not yet written by 07 ssp
  mode (F10) — registered, fails loudly, never silently absent.
