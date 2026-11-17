# gcm-pipeline/validation/ssp/ — committed ssp-mode gate evidence (X1)

The ssp-mode step-08 gate (`08_validate_gcm.py --mode ssp`) validates the
CORRECTED SSP record over the OBSERVED OVERLAP 2015–2020 only — months past
the overlap are never gated (no observed truth; R2/R3: projections are not
forecasts). This directory is the **committed snapshot** of the PASS run,
separate from the historical-corrected snapshot in the parent directory
(era honesty, R2 — the two gates answer different questions).

| File | What it is |
|---|---|
| `validation_report_ssp.json` | Full ssp-mode gate report (`die-gcm-validation/1.0`, `mode: ssp`): enforcing gates, reported-only sections, config verbatim. |
| `SHA256SUMS.txt` | SHA-256 of the snapshot files (committed LF bytes). |

## What the gate enforces (remediation round 1, 2026-11-17)

The first design gated overlap-window means and event ratios and failed at
38–56 % regional breaches. Measured diagnosis: breaches are free-running
REALISATION effects — per-model signed offsets have mixed signs
(spi_12 2015–2020: +0.35 … −0.29), sd ratios are inside tolerance, and
regional failures concentrate in 1-district UTs (small-sample noise).
A projection does not reproduce the actual 2015–2020 weather (R2), so the
gate was re-based onto what the record can support (same precedent as the
historical-gate remediation round 1 — see `config/validation.yaml` ssp
block for the full rationale):

1. **distribution_shape (hard)** — pooled multi-model sd_ratio vs the
   reference overlap, per (iid, season, region); national breach fails;
   regional breach fraction > 0.20 fails. Means are REPORTED next to every
   cell, never gated.
2. **seam_continuity (hard)** — corrected historical tail (3 y) vs
   corrected ssp head (3 y), per model × physical variable × scenario.
   The CMIP6 historical→ssp run is ONE continuous experiment; a stitch or
   calibration defect shows as a discontinuity far beyond the declared
   envelope (pr ratio 0.80–1.25, |Δtas| ≤ 1.0 K).

Reported-only (documented in the report): overlap means (realisation +
forced signal), drought-event statistics, dry tails with stored Q-Q pairs,
SPI–SPEI divergence, per-model signed mean offsets.

## Provenance

- Produced by `08_validate_gcm.py --mode ssp` on the real phase-2 chain
  (8-model committed subset, corrected ssp245+ssp585 2015–2050, IMD-anchored
  reference), run 2026-11-17.
- Source of the snapshot: `work/validation/validation_report_ssp.json`
  (owner-local, gitignored per X9).
- The canonical report the 09 publish gate reads is
  `work/validation/validation_report.json` (latest run; mode recorded
  inside). Publish remains Owner-gated (X1 + sign-off + regression
  `--bless`).
