# Design review & standing design checklist

**Source:** *Answers with Receipts — a design and credibility review of the Drought Intelligence Explorer* (independent review, 19 November 2026; v2-dev @ `87e0d18`).
**Archived copy:** [`docs/v2/reference/design-review-2026-11-19.pdf`](reference/design-review-2026-11-19.pdf).
**Status:** adopted as the standing design workflow for every new surface. This file is read alongside `docs/v2/04-frontend-ui-spec.md`; where the review is a suggestion, the decision actually taken is recorded here.

> Use this file before building, and again before calling a surface done. It is deliberately short: the full argument is in the PDF, the binding rules are in the decision register (D10, D11).

---

## 1. The design position

One evidence engine, three reading depths:

| Depth | What it is | Where it lives |
|---|---|---|
| **1 — Answers** | Plain-language answer, one number, one map, receipts one click away | `#overview` "Ask the record"; `#summary`; future district pages |
| **2 — Exploration** | The analytical lenses (the existing workspaces) | `#overview`, `#historical`, `#events`, `#propagation`, `#projections`, `#summary`, `#atlas`, `#engine` |
| **3 — Evidence** | Methods, provenance, verification, downloads | Documentation & Resources (`#data`), exports, repository |

The review's core instruction is **layering, not restructuring**. The analytical depth is already strong; the missing layer is the quotable answer in front of it, and the receipt behind it.

## 2. Decision: one produced record, four lenses (D11)

The four era-B tabs are **four questions about one gridded multi-source product**, not four datasets. Consolidating them into one dense workspace would hide the distinct questions; leaving them as four peer top-level tabs made them look like four products and forced visitors to learn the internal taxonomy.

**Committed structure (M10.3c):**

| Top-level destination | Lenses beneath |
|---|---|
| **Record 1981–2025** (era B, Gridded Multi-Source Product) | Overview · Historical Analysis · Drought Events · Propagation & Relationships |
| **Projections 2015–2100** (era C) | Future Projections · Drought to 2100 |
| **Atlas 1901–2025** (era A) | — (single surface) |
| **Documentation** | — (the centre) |
| **Engine Lab** | — (single technical tool) |

Rules for future work:

1. A new **dataset or era** becomes a new top-level destination.
2. A new **question about an existing record** becomes a lens under that destination, not a new product tab.
3. Hash routes and workspace depth are preserved (R8): the change is navigation, not content.
4. The four lenses are never merged into a single view without a documented reason; they serve different questions and different methods.

## 3. Standing checklist for every new surface

An item counts as done only when every applicable line passes.

- [ ] **Quote safety.** Every finding is quotable in one sentence without editing — counts, not probabilities, for count statistics; windows attached to every change claim.
- [ ] **Provenance.** Every number carries visible provenance: era, scenario where applicable, window, baseline, sample size — chips or tooltip, not hidden in docs.
- [ ] **Quotability.** Every panel emits a share card and a copy-as-citation string with the dataset DOI and an access date.
- [ ] **Permalinks.** Every view is re-openable from its URL (state-encoding permalinks; graceful fallback for unknown parameters).
- [ ] **Honesty.** Every absence is a stated refusal, not an error: no imputation, no splicing, no fabricated pending values; no-data districts stay grey.
- [ ] **Exports.** Every exported artefact carries DOI, version and methodology string in its header or footer.
- [ ] **Verification.** Every quoted quantitative claim in the manuscript and UI is re-derivable by one command from the repository.
- [ ] **Answers first.** Every new surface opens with its answer, then its options; technique names are never the entry toll.
- [ ] **Era clarity.** Every era-facing surface states which era it draws from and links the *Why three eras?* explainer.
- [ ] **Single source.** Every change to copy derives from metadata, never hand-typed, so banners cannot drift from data.

Additional DIE-only checks: keyboard + ARIA on new controls; mobile 44 px targets; zero console errors; `data-pipeline/selftest.py` and `scripts/regression_check.py` green before commit. The landing observation must be a documented drought month (D12), with **Latest** one click away.

## 4. Review findings → DIE work map

| Review item | DIE task / decision | State |
|---|---|---|
| Depth-1 answer layer; question-first entry | M10.2 (Ask the record), M10.3c (product-first nav) | ✅ shipped |
| Product-first navigation over technique-first tabs | **D11 / M10.3c** | ✅ shipped |
| State-encoding permalinks | M10.4 | built 2026-11-21 |
| DOI in metadata, exports and citation box | M10.5 | scheduled |
| District profile pages `#/district/<id>` | M10.6 | scheduled |
| Living methodology + governance + reality-check surfaces | M10.7 | scheduled |
| Claim verifier + `reproduce_figures.py` | M10.8 | scheduled |
| Era A ↔ B cross-validation as a public trust surface | M6.6 `#crossval` (+ M6.8 seam uncertainty) | next build task |
| Era-C citation block in `metadata.json` | M10.5 | scheduled |
| README / manuscript currency sync | M7 release hygiene | scheduled |

**Not adopted:** two websites, a simplified mode, or an AI question box. They fragment the single evidence engine and violate the layering principle.

## 5. Typography note (M10.3b, revised M10.3c)

The first typography pass used Source Serif 4; the Owner judged the title cramped on paper. The display/reading voice is now **Literata** (variable optical 7–72, italic 400) — designed for screen reading, large x-height, open apertures. It holds a 19 px title and 13.5 px prose without the print-display tightness. Inter remains the UI voice; IBM Plex Mono the data voice. This reinforces the checklist: type is judged at production sizes on the real surface, not by family name.
