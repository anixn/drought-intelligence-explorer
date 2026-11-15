# DIE v2.0 — Owner Amendments Memo (for OpenCode)

*Drop this file as `docs/v2/06-amendments.md`. It adds features and task amendments on top of the v2 suite (docs 00–05). Apply the same rules as the rest of the suite: one task per session, PROGRESS.md updated every session, Owner-compute items are never assumed done, and any methodological choice gets recorded in `05-decision-register.md` (§ new rows M/N…). Nothing here overrides a committed decision (D1–D5, C1–C7); items marked **[Owner]** need sign-off before they enter the roadmap.*

---

## 1. New features (proposed backlog additions)

| ID | Feature | Tier | Worth | Effort | Depends on | Spec notes |
|---|---|---|---|---|---|---|
| **E14** | **Future drought event analytics (era C).** Run the frozen v1.0 event machinery (runs, onset/termination, duration, cumulative severity, censoring) over validated era C products; compare event frequency/duration/severity per window (2026–2040 / 2041–2060 / 2081–2100) against the observed 1981–2020 baseline per district. Surface in `#projections` as a fourth view. **[Owner: confirm Tier 1]** | 1 (candidate) | 5 | M | E05 real data | Reuses event machinery; never run on fixtures for public numbers; windows are ensemble-median-based with agreement reported alongside |
| **E15** | **People-in-drought, static exposure.** Join projected drought-month counts with Census/WorldPop district population: "X million people in moderate-or-worse drought months per year by 2050/2100". Static exposure only, clearly labelled; hazard and exposure never conflated. Minimal version of F05, promoted forward. | 2 | 4 | S | E05; population grid verified (licence) | Methodology v2 documents the population source, year and its mismatch with 724-district fabric |
| **E16** | **PET-method sensitivity study.** Hargreaves (committed) vs ERA5-Land PET vs a Penman–Monteith variant (needs `huss`, `rlds`, `sfcWind` — availability-checked in 01_inventory_check.py; run only where models supply them) on the common 1981–2020 window, subset of models (e.g. best-subset 8–12). Ships as a validation-study memo + methodology v2 uncertainty statement, quantifying the era B↔C PET seam. **[Owner: compute]** | 2 | 4 | M | M2 framework; IMD/ERA5-Land reference data | Never changes the committed default (C3); sensitivity only |
| **E17** | **Era B ↔ era C cross-validation panel.** Extend `#crossval` with corrected-model-historical (1981–2014) vs observed era B over the overlap, symmetric to the Atlas↔Observed panel (r, bias, class agreement, event match, discrepancy map). The 2025/2026 seam gets the same treatment as the 1901/1981 seam. | 2 | 4 | S | M2.8 outputs | Reuses crossval schema; add `era` column or second partition file |
| **E18** | **Flash drought + compound drought–heat detection (era B first, era C if it holds up).** Flash drought: documented rapid-intensification rate (e.g. ≥ 2 percentile-classes/month per Ford/Otkin-style definition — pick and register one). Compound: joint SPI/SPEI + Tmax extremes in the same month, with lag-0 dependence noted. Client-side where feasible; Tier 3 F08 promoted. | 2 | 4 | M | — | Definition fixed in code + methodology page before any map ships |
| **O13** | **Alternate-reference QDM sensitivity product.** Run the QDM chain with the CHIRPS/ERA5-Land alternate reference (register D) alongside the IMD-primary run; ship the divergence as a downloadable sensitivity product + one methodology paragraph. Quantifies reference-dataset uncertainty. **[Owner: compute]** | 2 | 3 | M (Owner) | M2 chain | Schema unchanged; `reference_id` column or parallel partition root |
| **O14** | **Standardisation-baseline sensitivity for era C.** Fixed 1981–2020 baseline (committed C2) vs rolling/era-specific baseline on a subset — separates climate signal from baseline-definition effect in "future drought increase" claims. | 3 | 3 | S | E14 optional | One memo section; not a UI default |
| **O15** | **ENSO/IOD conditioning panels** (= existing O07, promoted). ONI + DMI association with district drought frequency; association only, never causal; JJAS-conditioned composites. | 2 | 3 | M | index data verified | Keep out of any projection claim |

### Promotions within the existing backlog

- **O02 (Pettitt change-point) → Tier 1.** Wire into the Historical tab trend view next to Mann-Kendall; client-side, S effort.
- **O03 (BH-FDR view) → Tier 1.** District trend maps ship with the q = 0.05 FDR view as default-adjacent toggle (v1.0 demo: 382 → 324 of 724). Reviewers will not accept uncorrected district trend maps.
- **F08 flash/compound → absorbed by E18** (mark F08 "superseded by E18" in the register).

## 2. Amendments to existing tasks

| Task | Amendment |
|---|---|
| **M2.1 (`models.yaml`)** | Add a `genealogy:` field per model (CMIP6 parent/institution family) so agreement fractions can be reported family-collapsed (24 models ≠ 24 independent models). Ranking stays model-level; the genealogy view is display-only. |
| **M2.11 (`08_validate_gcm.py`)** | Add **tail checks** to the validation gate, not just pooled mean/sd: Q–Q comparison of corrected-historical vs reference, plus p90/p95 drought-tail statistics by region/season. Drought is a tail phenomenon; means can pass while tails fail. Gate fails on declared tail tolerance breach. |
| **M2.6 / M2.9** | In `06_district_aggregate.py`, publish a **sub-pixel transparency list**: every district whose aggregation rests on ≤ 2 grid cells, as a `flag` value + downloadable CSV, so users can filter them out. |
| **M5 (projections tab)** | Add the E14 event view as task M5.8 once real era C data passes the gate. |
| **M4.3 (IMD comparison)** | Already includes the FDR view — keep it mandatory, not optional. |

## 3. Process amendments (OpenCode-executable, no Owner compute)

1. **CI (GitHub Actions):** on every push, run `data-pipeline/selftest.py`, the regression harness (M1.9), and — once they exist — `selftest_gcm.py` / `selftest_atlas.py`. Gate: green CI required before merge to `v2-dev`. Cheap protection for the "frozen semantics" promise.
2. **DOI strategy:** software DOI (v2.0.0) stays one deposit; **era datasets get separate versioned Zenodo deposits** so monthly era B refreshes never invalidate era A/C citations. Record the mapping in the register and CITATION.cff.
3. **README freshness badge:** a small build script (or Action) reads `data/status.json` and renders a badge (green ≤ 45 days lag, amber beyond, red no data). Same signal as the UI currency banner, visible to repo visitors.
4. **Figure-reproduction script:** `scripts/reproduce_figures.py` regenerates manuscript v2 figures from shipped Parquet + catalog (deterministic seeds, checksummed inputs), closing the data↔paper loop before M7.
5. **Register hygiene:** append rows for E14–E18, O13–O15 and the promotions above to `02-roadmap-milestones.md` §2 and cross-reference them from `05-decision-register.md` §1/§5 (new open decisions: E14 Tier-1 confirmation, E16/E18 definitions) — via a PROGRESS.md session entry, one task per session, never a silent doc edit.

## 4. Explicit non-goals (unchanged)

Nothing here pulls hydrological modelling, operational warning, ML-without-a-question, or composite-default indices into scope; era seams still are never spliced; fixtures never ship; pending Owner runs stay marked pending, never filled with synthetic values.
