# atlas-pipeline/validation/district_qa/ — committed per-district QA evidence (M6.2b)

This directory is the **committed snapshot** of the per-district QA
cross-check run at promotion time (2026-11-20, Owner "go"), mirroring the
`gcm-pipeline/validation/` evidence pattern. The source artifacts live under
`work/` (gitignored per X9-style convention); the Atlas `Z-score/` series the
QA read are **trimmed from the Owner's local archive after this snapshot**
(config/atlas.yaml → delete_after_ingest), so this directory is the durable
record.

| File | What it is |
|---|---|
| `district_qa.json` | Full per-district QA (`die-atlas-district-qa/1.0`): method declaration (centroid containment, holes ignored, QA-only), coverage counts, per-(district, variable) r / mean_bias over the 1981–2025 overlap, per-scale summary. |
| `district_qa.csv` | Flat per-(district, variable) table with a `#` provenance header (content hash prefix). |

## Headline (710 matched districts, overlap 1981–2025)

| Scale | r median | r p10 | share ≥ 0.9 | median \|bias\| |
|---|---|---|---|---|
| SPEI-1 | 0.9962 | 0.988 | 99.4 % | 0.010 z |
| SPEI-4 | 0.9985 | 0.992 | 99.4 % | 0.020 z |
| SPEI-12 | 0.9989 | 0.996 | 99.4 % | 0.030 z |

Reading: the platform's geometric grid→724 route reproduces the Atlas's OWN
polygon-averaged district series almost exactly. The method is approximate
by construction (centroid assignment; a polygon straddling a boundary goes
wholly to the centroid side; holes ignored) and is QA ONLY — the Atlas's
742-polygon fabric is never published (register OD4). Coverage deltas:
10 polygons without series and 2 unmatched centroids are the documented
M6.1 fabric anomalies.

Reproducibility: `python atlas-pipeline/04_atlas_district_qa.py` re-runs
against the local archive — AFTER the trim it needs the `Z-score/Districts`
series and will report their absence loudly (the QA was run pre-trim by
design; re-verification would require re-acquiring the release from Zenodo,
DOI 10.5281/zenodo.20368514).
