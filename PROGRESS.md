# PROGRESS.md — DIE v2.0 Persistent Tracker

> **OpenCode rule:** read this file first every session (after `AGENTS.md`), resume at "Next recommended task", and **update this file at the end of every substantial session** (status flag, session log entry, task states, files, decisions). Append to the session log — never rewrite history. The Owner appends compute results (GEE runs, GCM downloads, data acquisitions) when they complete.

---

## 1. Status flag

```
┌─────────────────────────────────────────────────────────────────────────┐
│ STATUS:        ACTIVE — M1/M2 configs · Next: M1.3                      │
│ PHASE:         M1 — engine, era-B Parquet, regression harness           │
│ ROADMAP:       ██░░░░░░░░  ~11%  (M0–M1.2 + M2.1–M2.2 done)             │
│ LAST SESSION:  2026-11-14 (Session 3 — env setup, M1.2, M2.1–M2.2)      │
│ BLOCKERS:      none blocking M1; owner actions pending for M2/M4/M6     │
│ BRANCH:        v2-dev (from master @ f3f773a; tag v2-base)              │
└─────────────────────────────────────────────────────────────────────────┘
```

Milestone board: **M0 ✅ · M1 ⬜ (M1.1–M1.2 ✅) · M2 ⬜ (M2.1–M2.2 ✅) · M3 ⬜ · M4 ⬜ · M5 ⬜ · M6 ⬜ · M7 ⬜ · M8+ ⬜** (definitions: `docs/v2/02-roadmap-milestones.md`).

## 2. Current phase

**M0 is complete** (this documentation suite). The next phase is **M1 — Foundation: engine, era-B Parquet, regression harness** (tasks M1.1–M1.10, `docs/v2/02` §3). M2 (GCM framework handoff) is independent of most of M1 and is the critical path for the Owner's compute start — begin M2 as soon as M1.2 (repo skeleton) lands.

## 3. Completed tasks

| Task | Date | Output |
|---|---|---|
| M0.1 | 2026-11-12 | Examined DIE v1.0.0 (live site, repo, manuscript, data contract) — audit facts recorded in AGENTS.md §7 |
| M0.2 | 2026-11-12 | v2.0 documentation suite written: AGENTS.md, docs/01–05, this tracker; all cross-document conflicts arbitrated (docs/v2/05 §4) |
| M0.3 | 2026-11-12 | Decision register committed (D1–D5, C1–C7, resolutions A–M, open decisions OD1–OD8, assumptions AS1–AS6) |
| M1.1 | 2026-11-12 | Suite installed into the repo (AGENTS.md, PROGRESS.md, docs/v2/00–05); branch `v2-dev` created from `master` @ `f3f773a`; tag `v2-base` = `f3f773a`; suite commit `a2d28f9`; repo audit recorded (§3 note below); `data-pipeline/selftest.py` passes on the branch (baseline green) |
| M1.2 | 2026-11-14 | Directory skeleton per AGENTS.md §5 (`data/parquet`, `data/geo`, `data/fixtures`, `scripts/`, `gcm-pipeline/{config,work,out}`, `atlas-pipeline/`, `validation-studies/`, `.gitkeep` placeholders; `work/`+`out/` contents gitignored) + Range-capable `server.py` at repo root. Commit `3342d4d` |
| M2.1 | 2026-11-14 | `gcm-pipeline/config/models.yaml`: selection criteria + download-policy comments, **pre-filled with the Owner's 24 models** from `download.R` (2026-10-30), status `provisional-owner-review` (OD1 = Owner confirms). Known gaps encoded (1981–1984 fill; CESM2/IITM-ESM tasmax/tasmin). Commit `cf46021` |
| M2.2 | 2026-11-14 | `gcm-pipeline/config/reference.yaml` per register resolutions D/C1/C2/C3/C7 (IMD primary + paths + citations + licence-verify flags, 0.25° grid, calibration 1981–2020, era C 2026–2100, PET seam, per-era bounds) and `gcm-pipeline/config/paths.yaml` with verified data root `D:/Websites/die-data/`. Commit `cf46021` |

**M1.1 repo audit (read-only, 2026-11-12):** `assets/js/` = analytics.js (40 KB), app.js (123 KB), charts.js (31 KB), data-loader.js (18 KB), filters.js (19 KB), map.js (20 KB), stats.js (12 KB), telemetry.js (9 KB); `assets/css/` = style.css (87 KB), leaflet.css (14 KB); `assets/vendor/` is empty (third-party libs load via CDN in `index.html`). `data/drought/` = 10 wide CSVs, 18.4 MB total. `data-pipeline/` entry points: `run.py`, `selftest.py` (82 assertions, PASS on branch), `config.yaml`, `prepare_boundaries.py`, `verify_paper_claims.py`, `requirements.txt`. Conda: `drought` env (`C:\Users\deshm\miniconda3\envs\drought\python.exe`) is the Python for pipeline work; `python` is not on PATH.

**M1.2 environment audit (2026-11-14, PC #2 — read-only findings recorded here for future sessions):**
- **Canonical Python:** `C:\Users\deshm\miniconda3\envs\drought\python.exe` (3.12.16) — the conda `drought` env EXISTS on this PC with numpy/pandas/scipy/pyyaml/requests/rasterio/netCDF4 preinstalled. `pyarrow` 26.0.1 installed into it this session. Conda is NOT on PATH; invoke by full path (no `conda run`).
- **PROJ/GDAL gotcha:** PostGIS (PostgreSQL 16) sets global `PROJ_LIB`/`GDAL_DATA` env vars pointing at unusable locations, which breaks rasterio ("Cannot find proj.db") in every env on this machine. **Fix per run:** `$env:PROJ_LIB='C:\Users\deshm\miniconda3\envs\drought\Lib\site-packages\rasterio\proj_data'; $env:GDAL_DATA='C:\Users\deshm\miniconda3\envs\drought\Lib\site-packages\rasterio\gdal_data'` before invoking the pipeline. Record in the M2.14 runbook.
- **Baseline re-verified on this PC:** `data-pipeline/selftest.py` → SELF-TEST PASSED (with the PROJ fix).
- **Data root verified:** `D:\Websites\die-data\cmip6\{outdir,outdir_1,download.R,India_Shp,...}` (main historical download = outdir with pr/tasmax/tasmin subfolders; outdir_1 = 1981–1984 gap fill in progress) and `D:\Websites\die-data\imd\{pr,tmax,tmin}` — **pr = 125 files, 1901–2025** (`IMD_rain_YYYY.nc`), **tmax/tmin = 1951–2025** (`IMD_tmax/tmin_YYYY.nc`). The pr record starting 1901 is richer than the session-2 audit note (1951–2025); calibration 1981–2020 unaffected. Corrected facts written into `gcm-pipeline/config/paths.yaml`.
- `server.py` verified: 206 byte-exact ranges, HEAD, 416 with `Content-Range`, 404, suffix/mid/open-end ranges, MIME overrides, keep-alive across request types — all pass on one session.

## 4. In progress

None (Session 0 ended after documentation).

## 5. Pending (next up)

| Order | Task | Milestone | Depends on | Notes |
|---|---|---|---|---|
| 1 | ~~M1.1~~ ✅ · ~~M1.2~~ ✅ · ~~M2.1–M2.2~~ ✅ (see §3) | — | — | — |
| 2 | **M1.3** `scripts/convert_to_parquet.py` — era B wide CSVs → long Parquet (zstd, dictionary, row groups 60 districts) | M1 | M1.2 | Next task |
| 3 | M1.4–M1.5 round-trip + catalog.json generator | M1 | M1.3 | |
| 4 | M2.3–M2.14 GCM scripts 00–09 + selftest_gcm + runbook | M2 | M2.1–M2.2 ✅ | Owner's downloads start when this lands |
| 5 | M1.6–M1.8 ducklab.js engine + Engine Lab + Historical behind flag | M1 | M1.5 | Reuse `work/die-2.0` prototype if present |

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

**Session-1 additions (2026-11-12/13):**
- **OD7 resolved — Route A (raw CMIP6 + own QDM) is the committed era C route.** NEX-GDDP-CMIP6 v2 (BCSD vs GMFD, CC0, 35 models, S3 + NCCS THREDDS) was evaluated per Owner request and is documented as a **known alternative only** — not used in production, because (a) it abandons the IMD-primary QDM reference (decisions D/C1), and (b) BCSD does not preserve the precipitation change signal the way QDM does. If bandwidth/compute becomes a blocker, reopening Route B requires a register entry. Verified facts: pr = kg m⁻² s⁻¹ (×86400 → mm/day), tas = K, fill 1e20, model-varying time references/calendars, v2 files only (v1.x pr compromised in dry areas), 0.25° grid offset ~0.125° from IMD.
- **Ranking-before-SSP strategy (Owner proposal, adopted):** with historical (24 models) + IMD (1951–2025) in hand, the M2 chain runs on historical only, `08_validate_gcm.py` ranks models vs observed 1981–2014 → `best_subset.yaml` (8–12). **Owner downloads SSPs (ssp245+ssp585, 2015–2100) only for the best subset.** Consequences registered: ensemble stats computed over the subset (n shown honestly, never "24"); historical skill ≠ future skill (documented limitation); agreement layers reflect the subset.
- **Download gaps found (Owner action):** CESM2 + IITM-ESM lack tasmax/tasmin (120 files); all 24 models lack historical 1981–1984 (288 files). IMD pr/tmax/tmin 1951–2025 verified complete (75 files each).

## 9. Next recommended task

### M1.3 — `scripts/convert_to_parquet.py` (next task)

Era B wide CSVs (`data/drought/*.csv`: `district_id,district_name,state_name,1981-01,…,2025-12`) → long Parquet per AGENTS.md §5 layout: `data/parquet/observed/variable=<id>/part-0.parquet` (zstd, dictionary-encoded, row groups aligned to 60 districts). Print per-variable rows/sizes. Gate: total era B ≤ ~30 MB; per-file ≤ ~600 KB. Then M1.4 round-trip (≥ 5 random cells/variable, exact match) and M1.5 `catalog.json`.

**Environment (verified this session, PC #2):** canonical Python `C:\Users\deshm\miniconda3\envs\drought\python.exe` + pyarrow 26.0.1; set `PROJ_LIB`/`GDAL_DATA` per the §3 note before any rasterio use (not needed for pure pandas/pyarrow work). Data contract: `data/metadata.json` (v1.0) is authoritative for variable ids/units — extend, never break.

**Reminder (standing):** update this file every session; push `v2-dev` before leaving the machine; never push `master`.

## 10. Session log (append-only)

| Session | Date | Tasks | Files touched | Verification | Next |
|---|---|---|---|---|---|
| 0 | 2026-11-12 | M0.1–M0.3: v1.0.0 audit (live site, GitHub repo `anixn/drought-intelligence-explorer`, manuscript main.tex, 4 planning docs); conflict arbitration; documentation suite written | AGENTS.md, PROGRESS.md, docs/v2/01–05 (package, not yet in repo) | Suite cross-checked against the 5 uploaded sources and the live-site audit facts; all user requirements mapped to docs (§11 checklist) | M1.1 |
| 1 | 2026-11-12 | M1.1: suite installed into repo root + `docs/v2/`; `v2-dev` branched from `master` @ `f3f773a`; tag `v2-base`; read-only repo audit (assets, data, pipeline entry points); Owner's CMIP6 download state inspected (6 test files, historical-only, from 1985 — gaps noted) | AGENTS.md, PROGRESS.md, docs/v2/00–05 (committed `a2d28f9`) | `data-pipeline/selftest.py` PASS on branch; git log + tag verified | M1.2 |
| 2 | 2026-11-13 | Era C route research + decision: NEX-GDDP-CMIP6 v2 evaluated from official tech note + S3 listing (units, BCSD method, model overlap, CC0); Owner chose **Route A (raw + own QDM)** via structured question; ranking-before-SSP strategy adopted; Owner download inventory verified (CMIP6 historical 22/24 complete; IMD 1951–2025 complete; gaps listed) | PROGRESS.md (decisions, session log) | S3 bucket listing + v2 tech note extracted and cross-checked; die-data folder inventory run (file counts per model/var) | M1.2 |
| 3 | 2026-11-14 | New-PC setup + M1.2 + M2.1–M2.2: conda `drought` env located (full path, not on PATH), pyarrow 26.0.1 installed, PostGIS `PROJ_LIB`/`GDAL_DATA` conflict diagnosed + per-run fix recorded, baseline selftest re-verified PASS; M1.2 skeleton + `server.py` built and verified (206/416/404, byte-exact ranges, keep-alive; 3 zombie server processes diagnosed and killed during debugging — Windows `SO_REUSEADDR` artifacts); M2.1–M2.2 configs committed (models.yaml pre-filled with Owner's 24 from `download.R`, reference.yaml IMD-primary, paths.yaml verified layout; IMD pr found to start 1901, richer than audited) | server.py (new), gcm-pipeline/config/{models,reference,paths}.yaml (new), .gitignore, data/{parquet,geo,fixtures}/.gitkeep, scripts/.gitkeep, atlas-pipeline/.gitkeep, validation-studies/.gitkeep, gcm-pipeline/{work,out}/.gitkeep, PROGRESS.md | Selftest PASS; yaml parse check (24 models, 0 dupes, window/grid verified); 8-request server battery ALL PASS on one keep-alive session; commits `3342d4d`, `cf46021` | M1.3 |
