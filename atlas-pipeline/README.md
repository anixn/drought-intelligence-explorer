# atlas-pipeline — era A (Drought Atlas of India) ingestion

Era A is the Atlas *reconstruction* record (SPEI at 1/4/12-month scales,
0.05°, 1901-01 → 2025-12). It is **never spliced** with era B (observed,
1981–2025) or era C (projections) — every surface is era-labelled (R2).
Era A lands on the **platform's 724-district v1.0 fabric** (OD4), not the
Atlas's own 742-polygon fabric.

## Source

- **Drought Atlas of India, 1901–2025** (v2), Zenodo DOI
  [10.5281/zenodo.20368514](https://zenodo.org/records/20368514), CC-BY-4.0
  (stated on the record page only — no LICENCE file ships in the archive).
- Owner-local archive root: `D:/Websites/die-data/DroughtAtlas_v2`
  (`config/atlas.yaml → atlas.local_root`). The archive is **read-only**
  for these scripts; nothing is ever deleted until the trim policy fires
  (`config/atlas.yaml → keep / delete_after_ingest`).

## Workflow (run in this order)

| Step | Script | What it does | Output |
|---|---|---|---|
| 0 | `00_verify_atlas.py` | M6.1 source gate: structure, series, boundaries, grid, provenance, sizes (V1–V6) | `work/atlas_source_report.json` |
| 1 | `01_crosswalk.py` | Area weights: 724 district polygons × 0.05° lattice (imports the proven `gcm-pipeline/06` clipping machinery) | `work/crosswalk/weights.json` + summary + manifest |
| 2 | `02_atlas_to_district.py` | Stream both grid roots → weighted aggregation → era-A Parquet + built-in QA (national vs Atlas India file, per-district-month round-trip recomputation) | `work/atlas_store/atlas/variable=*/year=*` + `work/ingest/ingest_manifest.json` |
| 3 | *(after verification)* promotion | Copy `work/atlas_store/atlas/` → `data/parquet/atlas/`, catalog + metadata era-A block | `data/parquet/atlas/` |

Each script has `--selftest` (synthetic, deterministic); run it before the
real thing. The real runs are build-time ETL over local files — they are
safe to run from the repo root with the canonical Python:

```
C:\Users\deshm\miniconda3\envs\drought\python.exe atlas-pipeline\01_crosswalk.py
C:\Users\deshm\miniconda3\envs\drought\python.exe atlas-pipeline\02_atlas_to_district.py
```

## Facts locked by the M6.1 gate (do not re-derive)

- SPEI-**1/4/12 only** — the Atlas has **no** SPEI-3 or SPEI-6.
- Period 1901-01..2025-12 (1,500 months), NaN tokens in place (R10).
- The grid ships in **two disjoint sibling folders** (`Gridded_SPEI` +
  `DroughtAtlas_v2/Gridded_SPEI`); both are required.
- Atlas fabric: 742 district polygons / 732 series / 11 DISPUTED
  no-LGD polygons; 4,723 taluka polygons / 4,639 series. The name fields
  are partially corrupted and `DISTRICT_L` is not a bijection — the
  crosswalk is **geometric**, never name/code-based.
- The shipped cell set (115,394 files) **omits all six island districts**
  (Nicobars, North/Middle Andaman, South Andaman, Diu, Lakshadweep, Mahe):
  era A honestly carries no data for them (`outside_domain`,
  `no_shipped_cells`). The lattice has 338,720 positions; 3,119 dead
  weights on unshipped cells were dropped and re-normalised.
- Crosswalk QA (prototype): conservation Σ-overlap/polygon-area median
  1.000000203 (max 1.0005); vs registry area median 1.000001 (max 1.0019);
  Nicobars flagged (its polygon extends south of the lattice).
- National QA: grid-weighted national series vs the Atlas's own India file
  gives r = 0.980 / 0.992 / 0.999 (spei 1/4/12) with mean bias ≤ 0.026 z;
  the sd_ratio ≈ 0.39–0.50 is the expected mean-of-standardised effect —
  the Atlas's national series is standardised at national level (sd
  0.996), ours is the area-weighted mean of district z-scores. r is the
  meaningful check, never an identity claim.
- The readme is stale (claims 1901–2020 + a PNG atlas; the files run to
  2025-12 and contain no PNGs).

## Trim policy (after the ingest verifies)

KEEP both grid roots + district/taluka boundary shapefiles + readme.
DELETE only afterwards (Owner-executed, with before/after sizes recorded):
`Z-score/`, `STATE_BOUNDARY.*`, `India_Country_Boundary.*`,
`latlon_India_0.05degree.csv`. Nothing is deleted today.
