# Suggestion triage — external review of 2026-11-21

*Doc 8 of the v2 suite (advisory). Status: triage complete, no code implemented from this review.*

An external model review (`suggestion_20261121.md`, 8 items, "concrete code actions") was supplied by the Owner with the instruction: **treat it as suggestions, decide what serves the community, finish the dashboard first, refine later.** This document records the decisions so the same proposals are not re-litigated each session.

## Criterion

A suggestion is adopted only when it makes the **published scientific record easier to use or harder to misread** without violating the project rules:

- **R1** — v1.0 validated behaviour and the published data palette are preserved;
- **R2/R10** — eras are never spliced, missing data is never imputed, every statistic carries its sample size;
- **R8** — stable hash routes and keyboard/ARIA behaviour are maintained;
- **R9** — no impact or causal claim is implied by a colour or a generated sentence.

Dashboard completion (M6/M9/M10) takes priority over refinement. Nothing in this review blocks a milestone.

## Decisions at a glance

| # | Suggestion | Decision | Revisit when |
|---|---|---|---|
| 1 | Collapse 9 tabs into 5 + "More analysis" dropdown | **Reject — superseded** | never (D11 is the committed IA) |
| 2 | Colourblind-safe palette toggle that recolours severity classes | **Reject recolouring; adopt a CVD audit** | post-release accessibility audit |
| 3 | 3-step guided first-run tour (overlay + tooltip) | **Defer** | after release, with real user testing |
| 4 | Auto-generated "insight sentence" strip | **Reject — superseded and unsound as written** | never as written |
| 5 | KPI cards show completeness + freshness | **Partially already served; defer the remainder** | when a real per-KPI coverage field exists |
| 6 | Plain-language impact descriptions in the map legend | **Defer (wording risk)** | after a documented copy review |
| 7 | Mobile KPI-first layout with collapsible (max-height) charts | **Reject the mechanism; keep the mobile goal** | next dedicated mobile pass |
| 8 | Small accessibility wins (skip link, focus ring, reduced motion, aria-live) | **Already present — no change** | if a real gap is demonstrated |

## Why, item by item

### 1. Tab collapse / "More analysis" dropdown — rejected

The premise (nine competing top-level tabs) was true before **D11 product-first navigation** (2026-11-20). The shipped IA already groups the analytics under their product: top row = Record / Projections / Atlas / Documentation / Engine Lab; Record lenses = Overview / Historical / Events / Propagation / **Cross-validation**. The dropdown proposal would:

- hide whole products behind a menu (worse discoverability for first-time users, the community this review is trying to help);
- regress the accessible `role="tablist"` lens strip (roving tabindex, arrow-key navigation verified);
- duplicate a problem that no longer exists.

`feat/nav-grouping` is therefore closed as superseded. No code change.

### 2. Colourblind-safe palette toggle — recolouring rejected, audit adopted

The proposal replaces the **published data colours** with CSS variables. That is a direct R1 conflict: the v1.0 nine-class palette is part of the validated, published product, is already luminance-ordered, and every map/chart/table/CSV colour reference assumes it. A silent alternate palette would make a colour quoted in a report ambiguous — exactly the failure mode R1 guards against.

The accessibility concern behind it is legitimate. The correct response is an **audit**, not a second palette:

- the app never encodes class by colour alone (class names, tooltips, legends, tables and CSV all carry the label);
- an audit should check contrast of every class chip/label pairing (the `DIE.inkOn()` work already fixed the mid-tone chips to ≥ 4.5:1) and simulate deuteranopia/protanopia for adjacent classes;
- if the audit finds a genuine ambiguity, the fix is a **redundant encoding** (pattern/label), not a change to the published palette.

Scheduled post-release. No code change now.

### 3. Guided first-run tour — deferred

A modal overlay with 3 stops is a large, high-risk UI surface (focus trapping, `aria-live` vs `role="dialog"`, mobile positioning, interruption on every first visit) for a problem the current build already addresses: the "Ask the record" band routes the four first questions, the receipts line explains era/product/window/baseline/n, and every workspace has a written intro. Adding a tour before the dashboard is finished would be refinement ahead of completion, and would need real user testing to avoid becoming a nuisance. Deferred; revisit with community feedback after release.

### 4. Auto-generated insight sentence — rejected as written

Two problems:

1. **Superseded.** The intent (a one-line plain summary of what the user is looking at) is already served by the Depth-1 "Ask the record" band plus the receipts/evidence line.
2. **Unsound as written.** `droughtMonths / (years × 12)` treats missing months as non-drought, which is exactly the imputation-by-denominator that R10 forbids; "longest continuous event" cannot be read off a month count (it needs the frozen runs analysis with censoring); and a sentence with no sample size or era label invites quoting a number that cannot be defended.

If a narrative layer is ever added, it must be computed from the same validated analytics, must print n and the window, and must never claim impacts. No code change.

### 5. KPI completeness + freshness — mostly already served

- Freshness is in the topbar on every surface (`UPDATED`, `AVAILABILITY`).
- Sample size and window are in the receipts line under the KPI row (`era · product · window · baseline · n`) and in each surface's notes.
- The v1.0 KPI cards are validated published behaviour; adding a per-card "92 % data coverage" badge requires a **real** per-KPI coverage definition, not a decorative number.

Deferred remainder: if a genuine per-KPI coverage field is added to the metadata contract, show it next to the figure with its definition. No fabricated percentages.

### 6. Plain-language legend descriptions — deferred, wording risk

Useful for non-specialists, but the sample copy ("Crops failing, drinking-water shortages") is an **impact claim** that a standardised drought index cannot support (R9). Plain-language lines would also compete with the scientific class names in limited legend space.

Adoptable form, after a documented copy review: keep the class names as the primary label, add a second line that describes the **index condition only** (e.g. "standardised index ≤ −2.0; far below the reference climatology"), never a sectoral impact. Deferred until the dashboard is complete.

### 7. Mobile KPI-first + collapsible charts — mechanism rejected, goal kept

The goal is right; the mechanism is harmful:

- `max-height: 240px` with hidden overflow **clips the chart** rather than making it responsive: axes, legends and annotations disappear, and Plotly cannot resize into a clipped box reliably.
- The app already ships responsive chart heights and a single-column panel grid below 760 px; what is missing is a **device pass** (touch targets, sticky-nav behaviour, table scrolling), not clipped charts.

Next dedicated mobile pass: test on real narrow viewports, verify 44 px targets, tab-bar scrolling and table overflow. Deferred.

### 8. Small accessibility wins — already implemented

Verified in the current build:

| Proposal | Current state |
|---|---|
| Skip-to-content link | present (`a.skip-link` → `#workspace`), visible on focus |
| Visible focus ring | `:focus-visible` rules for buttons, selects, tabs, switch, segmented controls |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` blocks across the stylesheet |
| `aria-live` on KPI updates | topbar status and sidebar badge are polite live regions |

The one item deliberately **not** adopted is a blanket `aria-live` on the KPI grid: KPIs are recomputed on every slider tick, and a live region there would read constantly while the user drags, which degrades the experience for screen-reader users. If announcement is needed, it must be a targeted, debounced message on explicit actions (tab entry, district selection), not on every render.

Lighthouse on the new `#crossval` surface: **Accessibility 100 / Best Practices 100** (SEO 75 is the pre-existing crawlable-anchor rule for hash links).

## Net result

- **Adopted now:** nothing — dashboard completion first.
- **Adopted later (tracked):** CVD/contrast audit of the published palette (item 2), real per-KPI coverage display (item 5), index-only plain-language legend line after copy review (item 6), dedicated mobile device pass (item 7).
- **Rejected:** tab dropdown (superseded by D11), palette recolouring (R1), auto-insight sentences (R10/R9), chart clipping (hides data), blanket KPI live region (noise).

All deferred items are recorded in `PROGRESS.md` → "Dependencies and unresolved issues" and do not block M6/M9/M10.
