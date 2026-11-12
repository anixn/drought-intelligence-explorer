# PROGRESS.md — DIE v2.0 Persistent Tracker

> **OpenCode rule:** read this file first every session (after `AGENTS.md`), resume at "Next recommended task", and **update this file at the end of every substantial session** (status flag, session log entry, task states, files, decisions). Append to the session log — never rewrite history. The Owner appends compute results (GEE runs, GCM downloads, data acquisitions) when they complete.

---

## 1. Status flag

```
┌─────────────────────────────────────────────────────────────────────────┐
│ STATUS:        ACTIVE — M1 (Foundation) · Next: M1.2                    │
│ PHASE:         M1 — engine, era-B Parquet, regression harness           │
│ ROADMAP:       ██░░░░░░░░  ~8%  (M0 + M1.1 done; M1.2–M1.10 next)       │
│ LAST SESSION:  2026-11-12 (Session 1 — M1.1 suite install + branch)     │
│ BLOCKERS:      none blocking M1; owner actions pending for M2/M4/M6     │
│ BRANCH:        v2-dev (from master @ f3f773a; tag v2-base)              │
└─────────────────────────────────────────────────────────────────────────┘
```

Milestone board: **M0 ✅ · M1 ⬜ · M2 ⬜ · M3 ⬜ · M4 ⬜ · M5 ⬜ · M6 ⬜ · M7 ⬜ · M8+ ⬜** (definitions: `docs/v2/02-roadmap-milestones.md`).

## 2. Current phase

**M0 is complete** (this documentation suite). The next phase is **M1 — Foundation: engine, era-B Parquet, regression harness** (tasks M1.1–M1.10, `docs/v2/02` §3). M2 (GCM framework handoff) is independent of most of M1 and is the critical path for the Owner's compute start — begin M2 as soon as M1.2 (repo skeleton) lands.

## 3. Completed tasks

| Task | Date | Output |
|---|---|---|
| M0.1 | 2026-11-12 | Examined DIE v1.0.0 (live site, repo, manuscript, data contract) — audit facts recorded in AGENTS.md §7 |
| M0.2 | 2026-11-12 | v2.0 documentation suite written: AGENTS.md, docs/01–05, this tracker; all cross-document conflicts arbitrated (docs/v2/05 §4) |
| M0.3 | 2026-11-12 | Decision register committed (D1–D5, C1–C7, resolutions A–M, open decisions OD1–OD8, assumptions AS1–AS6) |
| M1.1 | 2026-11-12 | Suite installed into the repo (AGENTS.md, PROGRESS.md, docs/v2/00–05); branch `v2-dev` created from `master` @ `f3f773a`; tag `v2-base` = `f3f773a`; suite commit `a2d28f9`; repo audit recorded (§3 note below); `data-pipeline/selftest.py` passes on the branch (baseline green) |

**M1.1 repo audit (read-only, 2026-11-12):** `assets/js/` = analytics.js (40 KB), app.js (123 KB), charts.js (31 KB), data-loader.js (18 KB), filters.js (19 KB), map.js (20 KB), stats.js (12 KB), telemetry.js (9 KB); `assets/css/` = style.css (87 KB), leaflet.css (14 KB); `assets/vendor/` is empty (third-party libs load via CDN in `index.html`). `data/drought/` = 10 wide CSVs, 18.4 MB total. `data-pipeline/` entry points: `run.py`, `selftest.py` (82 assertions, PASS on branch), `config.yaml`, `prepare_boundaries.py`, `verify_paper_claims.py`, `requirements.txt`. Conda: `drought` env (`C:\Users\deshm\miniconda3\envs\drought\python.exe`) is the Python for pipeline work; `python` is not on PATH.

## 4. In progress

None (Session 0 ended after documentation).

## 5. Pending (next up)

| Order | Task | Milestone | Depends on | Notes |
|---|---|---|---|---|
| 1 | ~~M1.1~~ ✅ done (see §3) | — | — | — |
| 2 | **M1.2** Directory skeleton per AGENTS.md §5 | M1 | M1.1 | Next task |
| 2 | M2.1–M2.2 GCM configs (models.yaml template, reference.yaml) | M2 | M1.2 skeleton | Enables OD1 (Owner fills 24-model list) |
| 3 | M1.3–M1.5 Parquet conversion + round-trip + catalog | M1 | M1.1 | |
| 4 | M1.6–M1.8 ducklab.js engine + Engine Lab + Historical behind flag | M1 | M1.5 | Reuse `work/die-2.0` prototype if present |
| 5 | M2.3–M2.14 GCM scripts 00–09 + selftest_gcm + runbook | M2 | M2.2 | The Owner's downloads start after this lands |

(Full task tables per milestone: `docs/v2/02-roadmap-milestones.md` §3.)

## 6. Dependencies and unresolved issues

**Owner actions pending (gates — do not fake their completion):**

| Item | Gates | Status |
|---|---|---|
| Install this suite into the repo (AGENTS.md + PROGRESS.md → root; docs → `docs/v2/`) | M1.1 | ⏳ pending |
| Fill `gcm-pipeline/config/models.yaml` with the final 24 models (OD1) | M2.1 | ⏳ pending (template delivered at M2.1) |
| CMIP6 downloads (24 models, pr/tasmax/tasmin, historical + ssp245 + ssp585) | M5 real-data gate | ⏳ not started (starts after M2 handoff) |
| IMD data acquisition (rainfall; temperature product choice OD3) | M4.1 | ⏳ pending |
| Atlas v2 verification: DOI 10.5281/zenodo.20368514, licence, variables (OD4) | M6.1 | ⏳ pending |
| Era C start-year confirmation (OD2: default 2026–2100) | M2.2 | ⏳ default adopted |
| Locate `work/die-2.0/` prototype (AS2) — reuse or rebuild | M1.6 | ⏳ to check at M1.6 |

**Open technical questions:** none beyond the register's OD1–OD8 (docs/v2/05 §5).

## 7. Files created or modified

**Session 0 (2026-11-12)** — documentation suite, all currently outside the repo (package `die-v2-opencode-docs/`), to be installed at M1.1:

| File | Purpose |
|---|---|
| `AGENTS.md` | Master persistent project instructions (session protocol, golden rules, architecture, audit facts) |
| `PROGRESS.md` | This tracker |
| `docs/v2/01-vision-scope.md` | Vision, objectives, scope/non-scope, v1.0 continuity contract, era model, definition of done |
| `docs/v2/02-roadmap-milestones.md` | Feature backlog (Tier 1/2/3), milestones M0–M8 with exit gates, owner compute register, session sizing |
| `docs/v2/03-scientific-pipelines.md` | Era A/B/C/D pipelines, GCM chain 00–09, monthly refresh, IMD study, cross-validation, QA standards, data contracts |
| `docs/v2/04-frontend-ui-spec.md` | IA evolution, era honesty UI, ducklab.js engine + 7 pitfalls, surface specs, exports, a11y, regression protection |
| `docs/v2/05-decision-register.md` | D1–D5, C1–C7, conflict resolutions A–M, open decisions, CMIP6 release gate, safeguards, assumptions |

*(Repo-side file changes are appended per session below, with task IDs.)*

## 8. Scientific decisions and assumptions (new this phase)

All committed decisions and conflict resolutions are recorded in `docs/v2/05-decision-register.md` (§1–§4, §7–§8). Highlights with direct consequences for near-term work:

- **D:** Bias-correction reference = **IMD primary** (Owner instruction), CHIRPS/ERA5-Land as alternates/cross-checks — supersedes the CHIRPS/ERA5-Land suggestion in the build spec.
- **E:** PET is **per era** (B: ERA5-Land PET frozen; C: Hargreaves identically applied) — methodology v2 must document the seam.
- **F:** SPEI fallback = **v1.0 Gringorten**, GEV optional variant only.
- **G/K:** Bounds per era — B ±4 (released), C [−5, +5] with clip counts.
- **B:** Era C = **2026–2100** (provisional default; OD2 open).
- **AS4:** Nothing in era C exists yet — OpenCode builds against labelled synthetic fixtures only.

**Assumption added this session:** none beyond AS1–AS6.

## 9. Next recommended task

### M1.1 — Install the suite and open the v2 branch (Owner + OpenCode joint, session-sized)

1. Owner (or OpenCode with repo access): copy `AGENTS.md` and `PROGRESS.md` to the repo root of `github.com/anixn/drought-intelligence-explorer`; copy `docs/0*.md` to `docs/v2/`.
2. OpenCode: `git checkout -b v2-dev && git tag v2-base` from `master` (v1.0.0). Record the tag hash here.
3. Repo audit (read-only): confirm the four workspaces load, note `assets/js/*` inventory, `data/` sizes, `data-pipeline/` entry points; append findings to §3 (completed) and §7 (files).
4. Verify all v1.0 surfaces on the branch (tabs cycled, zero console errors) → this is the M1 baseline.
5. Update this file: status flag → `ACTIVE — M1 (Foundation) · task M1.2 next`; add session log entry.

### M1.2 — Directory skeleton (next task)

Create per AGENTS.md §5: `data/parquet/`, `data/geo/`, `data/fixtures/`, `scripts/`, `gcm-pipeline/` (+ `config/`, `work/`, `out/`), `atlas-pipeline/`, `validation-studies/`, and a Range-capable `server.py`. Gate: tree matches spec. **Then M2.1–M2.2 (GCM configs) so the Owner's download handoff is not delayed.**

**Owner note recorded this session:** the Owner has begun CMIP6 downloads via an R `cmip6` route (`D:\OneDrive\Desktop\AllData\don\download_cmip6.R`) with a ~24-model list and India AOI — but so far only 6 test files have landed (INM-CM4-8 / MIROC-ES2L, historical, pr/tasmax, scattered years). Historical coverage starts at 1985 in the R script; the spec requires **1981–2014** historical (calibration 1981–2014 historical + 2015–2020 ssp), and **ssp245 + ssp585 2015–2100** are not in the download config at all. The precise download list was given to the Owner in the Session-1 chat summary; it also belongs in `gcm-pipeline/config/models.yaml` at M2.1.

## 10. Session log (append-only)

| Session | Date | Tasks | Files touched | Verification | Next |
|---|---|---|---|---|---|
| 0 | 2026-11-12 | M0.1–M0.3: v1.0.0 audit (live site, GitHub repo `anixn/drought-intelligence-explorer`, manuscript main.tex, 4 planning docs); conflict arbitration; documentation suite written | AGENTS.md, PROGRESS.md, docs/v2/01–05 (package, not yet in repo) | Suite cross-checked against the 5 uploaded sources and the live-site audit facts; all user requirements mapped to docs (§11 checklist) | M1.1 |
| 1 | 2026-11-12 | M1.1: suite installed into repo root + `docs/v2/`; `v2-dev` branched from `master` @ `f3f773a`; tag `v2-base`; read-only repo audit (assets, data, pipeline entry points); Owner's CMIP6 download state inspected (6 test files, historical-only, from 1985 — gaps noted) | AGENTS.md, PROGRESS.md, docs/v2/00–05 (committed `a2d28f9`) | `data-pipeline/selftest.py` PASS on branch; git log + tag verified | M1.2 |
