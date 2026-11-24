# Scientific Data submission checklist

## Completed in this package

- [x] Version pinned to DIE v2.0.0 and snapshot `v2026.09`.
- [x] Current software and dataset DOIs used throughout.
- [x] Era-B total updated to **3,780,163** valid district-month values.
- [x] Current propagation result used: **r = 0.8716, n = 547, 95% CI [0.8356, 0.8999]**.
- [x] Current national check used: **4 of 547 months** at or below −1.00, one qualifying event.
- [x] Current Marathwada values used: SPI-3 −0.97125; VCI 13.5 and 8.375.
- [x] IMD benchmark included with real measured values and PET/resolution caveats.
- [x] Era-A–era-B overlap included with the 1981–2014 window and six island districts absent.
- [x] CMIP6 release gates included, including reported-only SSP overlap diagnostics.
- [x] Eight-model published ensemble stated correctly; 24 listed and 22 processed candidates distinguished.
- [x] Era-C archive described as 19,904 files / 900.1 MB ZIP; no false per-file manifest claim.
- [x] Title is 74 characters; abstract is 164 words.
- [x] Required Scientific Data headings are present and ordered.
- [x] Data Overview is one paragraph with two figures.
- [x] No Results, Discussion, Conclusions, worked-example or Reuse Potential headings.
- [x] 8 figures and 10 tables; all figures are separate PDF and 300-dpi PNG files.
- [x] Roboto Regular/Bold used in every figure; 10 pt minimum enforced by the builder.
- [x] 34 embedded numerical references, all cited, ordered by first appearance.
- [x] No internal `\ref`/`\label` links and no external `.bib`/`.bbl` dependency.
- [x] Manuscript compiles with no undefined citations and no overfull horizontal boxes.
- [x] Publication figure checksums: 13 inputs and 16 figure files pass.
- [x] Manuscript structure checker: 32/32 pass.
- [x] Pipeline self-test: 82 assertions pass.
- [x] Shipped-data regression: 735 values pass.
- [x] Reality checks: pass after correcting the artifact's version metadata to 2.0.0.
- [x] Published-claim reproduction: 5 artifacts pass.
- [x] Status contract: pass.
- [x] CMIP6 orchestrator: 9/9 suites pass when run without the concurrent pipeline-self-test directory race.
- [x] Paper-claim verifier: 6/6 experiments pass after updating the Benjamini--Hochberg expectation to the v2.0.0 record (415 uncorrected, 354 after FDR).
- [x] Atlas source-gate self-test: T1--T4 pass.
- [x] Cross-validation self-test: 17/17 assertions pass with UTF-8 console output.
- [x] Incremental Parquet converter self-test: 4/4 pass.

## Owner actions before submission

- [ ] Resolve the boundary-source licence with the maintainers, or explicitly approve the separable-layer fallback for final publication.
- [ ] Complete one internal scientific review and one language/copy-edit review.
- [ ] Confirm the author-contribution, competing-interests and no-external-funding declarations in the submission system.
- [ ] Prepare the covering letter and reviewer suggestions in the submission system.
- [ ] Upload `manuscript.pdf` for first review. For revision/final typesetting, upload `manuscript.tex` as the Article file and the eight figure PDFs separately.
- [ ] Refresh the EarthArXiv preprint only after the Scientific Data version is frozen.

## Notes for the editor/reviewer

- The earlier v1.0.0 resource is cited and the new v2.0.0 contribution is identified explicitly.
- Raw IMD and CMIP6 inputs are not redistributed; derived DIE products carry CC BY 4.0 and source terms remain separate.
- The IMD benchmark uses its computed 1981–2025 comparison window; the manuscript does not relabel it as the 1981–2014 cross-era window.
- Projections are simulations, agreement is a model count, and eras are never silently spliced.
