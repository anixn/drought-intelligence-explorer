# atlas-pipeline — era A (Drought Atlas of India) ingestion

Era A is the Atlas *reconstruction* record (SPEI at 1/4/12-month scales,
0.05°, 1901-01 → 2025-12). It is **never spliced** with era B (Gridded
Multi-Source Product, 1981–2025 — register D8: not labelled "observed")
or era C (projections) — every surface is era-labelled (R2).
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
| 3 | `03_atlas_promote.py` (**RUN 2026-11-20**, Owner "go") | Verify staging (375 partitions, 3,220,872 rows) → copy to `data/parquet/atlas/` → **additive** catalog merge (`gc.apply_atlas`; never the bare rebuild) → metadata `era_a` block → per-file SHA-256 in `pipeline_manifest.json` | `data/parquet/atlas/` (gitignored, Owner-local until release) + contract blocks |
| 4 | `04_atlas_district_qa.py` (**RUN 2026-11-20**) | Per-district QA cross-check: the Atlas's OWN 732 polygon series (DBF `ID` → `data_distwise_id_<ID>`; LCC_WGS84 .prj transformed to WGS84 first) centroid-assigned onto the 724 fabric (approximate, QA-only), compared with the PROMOTED store over 1981–2025 | `work/district_qa.json` + `.csv`; summary attached to `metadata.json → era_a.district_qa` |

**Per-district QA result (710 matched districts, overlap 1981–2025):**
r median **0.996 / 0.998 / 0.999** (spei 1/4/12), p10 ≥ 0.988, 99.4 % of
districts ≥ 0.9, median |bias| ≤ 0.03 z. The geometric grid→724 route
reproduces the Atlas's own polygon-averaged district series almost exactly;
the two unmatched centroids and the 10 series-less polygons are the
documented M6.1 fabric anomalies (QA-only, never published).

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

## Trim policy (AFTER the ingest verifies)

KEEP both grid roots + district/taluka boundary shapefiles + readme.
DELETE only afterwards (Owner-executed, with before/after sizes recorded):
`Z-score/`, `STATE_BOUNDARY.*`, `India_Country_Boundary.*`,
`latlon_India_0.05degree.csv`. Nothing is deleted today.

## Trim EXECUTED 2026-11-20 (Owner authorisation: "you can delete the
## unused atlas file")

`05_trim.py --apply` (keep-list protected, dry-run default, selftest PASS):
deleted `Z-score/` (255.7 MB — the QA it fed is committed at
`validation/district_qa/`), `STATE_BOUNDARY.*` (~23 MB),
`India_Country_Boundary.*` (~7 MB), `latlon_India_0.05degree.csv` (1.6 MB).
**6,685.5 → 6,398.2 MB (freed 287.3 MB)**; report `work/trim_report.json`.
Keep-list verified after the trim: `Gridded_SPEI` = 115,394 cells /
5,901.8 MB (the archive's two sibling grid halves were merged by the Owner
into one root — the union is identical and both configured roots are
handled), `DISTRICT_BOUNDARY.*` + `SUBDISTRICT_BOUNDARY.*` + readme intact.
NOTE: after the trim `04_atlas_district_qa.py` can no longer re-read the
deleted `Z-score/` series — the committed snapshot is the durable record;
re-verification would re-acquire the release from Zenodo
(DOI 10.5281/zenodo.20368514).
