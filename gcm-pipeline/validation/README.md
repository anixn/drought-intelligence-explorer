# gcm-pipeline/validation/ — committed gate evidence (M2.11)

Review finding **F4** (2026-11-17): the step-08 validation gate's PASS and the
committed subset decision were previously prose claims — the products lived
only in the owner-local `work/validation/` (gitignored, per X9). This
directory is the **committed snapshot** of the last reviewed PASS, so the
evidence is auditable from the branch.

| File | What it is |
|---|---|
| `validation_report.json` | Full step-08 gate report (`die-gcm-validation/1.0`): all 5 gate sections, per-region/season cells, Q-Q tables, config verbatim. The top-level `gates` block records the PASS/FAIL per gate. |
| `best_subset.yaml` | The committed era-C subset selected by the registered criterion (largest-gap core extended to the registered floor by reweighting-stability order — never a fixed count). |
| `ranking.csv` | Per-model ranking metrics (8 metrics × indicators) behind the subset decision. |
| `SHA256SUMS.txt` | SHA-256 of each snapshot file in two forms: the committed LF content (repo `.gitattributes` policy: `* text=auto eol=lf` — every platform checks out identical bytes) and the original as-produced CRLF copies recorded in `out/export_manifest.json` (`source_sha256`). Content identical modulo line endings. |

## Provenance

- Produced by `08_validate_gcm.py --mode historical-corrected` on the real
  phase-1 corrected record (22 models, window 1981–2014), run 2026-11-16.
- Byte-identical to the M2.12 historical-corrected export
  (`out/validation/*`, checksums cross-verified against
  `out/export_manifest.json`).
- Mode label: this is the **historical-corrected (validation-era) gate** —
  the ssp-mode gate (X1, required before any projections publish) does NOT
  exist yet and will produce its own committed snapshot when it runs.

## Refresh procedure

1. Re-run `08_validate_gcm.py --mode historical-corrected` (and, when SSP
   data lands, `--mode ssp`).
2. Review the diff of `validation_report.json` (config verbatim is embedded;
   any tolerance change must come from `config/validation.yaml`, never code).
3. Copy the new products here, regenerate `SHA256SUMS.txt`, and record the
   re-run in `PROGRESS.md` (what changed and why — e.g. a monthly refresh or
   a model-list amendment).
