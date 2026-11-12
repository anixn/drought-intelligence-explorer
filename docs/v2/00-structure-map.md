# 00 — Structure Map: Where Every File Goes in Your Existing v1.0.0 Repo

*Read this together with `AGENTS.md` §5 (target layout). This file answers two questions concretely: **where each kit file goes** in the existing Drought Intelligence Explorer v1.0.0 repository, and **how to run everything** (install, daily OpenCode loop, dev server, pipelines, deploy). One-time install: run `install_v2_kit.sh` from the kit — it performs every step below automatically.*

---

## 1. The annotated tree — your v1 structure, unchanged unless marked NEW

```
drought-intelligence-explorer/          ← your existing repo (branch: v2-dev after install)
│
├── AGENTS.md                            NEW  ← copy from kit ROOT (NOT into docs/)
├── PROGRESS.md                          NEW  ← copy from kit ROOT (NOT into docs/)
│
├── index.html                           existing v1 shell — never rewritten; new tabs added at M5/M6
├── CNAME                                existing (drought.ankitdeshmukh.com) — untouched
├── CITATION.cff / LICENSE / README.md   existing — versioned forward at M7
│
├── assets/
│   ├── css/                             existing (style.css, leaflet.css) — untouched
│   └── js/
│       ├── app.js                       existing (hash router, orchestration) — untouched
│       ├── data-loader.js               existing (PapaParse wide-CSV loader) — stays as fallback
│       ├── telemetry.js                 existing — untouched
│       ├── leaflet.js, papaparse.min.js, plotly-cartesian.min.js, html2canvas.min.js
│       │                                existing vendored libs — untouched
│       └── ducklab.js                   NEW (M1.6) — DuckDB-WASM engine service
│
├── data/
│   ├── metadata.json                    existing contract — EXTENDED only (era blocks, availability windows)
│   ├── pipeline_manifest.json           existing — EXTENDED (checksums, bias-correction block)
│   ├── drought/
│   │   └── spi_*.csv, spei_*.csv, soil_moisture.csv, vci.csv
│   │                                    existing wide CSVs — KEPT, kept in sync, permanent fallback
│   ├── districts.csv / boundaries GeoJSON  existing registry + geometry — untouched
│   ├── status.json                      NEW (M3) — freshness status for the banner
│   ├── parquet/                         NEW (M1.3+) — created by scripts, never by hand
│   │   ├── catalog.json                 exact-path manifest (UI source of truth)
│   │   ├── observed/variable=<id>/part-0.parquet
│   │   ├── atlas/variable=<id>/year=<yyyy>/part-0.parquet          (M6)
│   │   ├── projections/scenario=<s>/stat=<st>/variable=<id>/year=<yyyy>/…  (M5)
│   │   ├── cross_validation/overlap_1981_2020.parquet              (M6)
│   │   └── _national_monthly.parquet    pre-aggregate (~42 KB)
│   ├── fixtures/                        NEW (M5 dev only) — SYNTHETIC, never shipped
│   └── geo/*.pmtiles                    NEW (M6) — PMTiles geometry
│
├── data-pipeline/                       existing v1 pipeline — semantics FROZEN
│   ├── run.py / selftest.py / config.yaml / prepare_boundaries.py / …
│   └── (monthly-increment mode added at M3 — extends run.py, never forks it)
│
├── gcm-pipeline/                        NEW (M2) — era C chain, built by OpenCode:
│   ├── config/models.yaml               ← YOU fill the final 24 models (task M2.1)
│   ├── config/reference.yaml            IMD primary reference (already specified)
│   ├── config/paths.yaml                raw/ work/ out/ roots (gitignored)
│   ├── 00_download_cmip6.py … 09_export_parquet.py
│   ├── selftest_gcm.py                  synthetic 3-model world — OpenCode's proof, no real compute
│   ├── README.md                        YOUR runbook (env, order, checkpoints)
│   └── work/ out/                       gitignored intermediates + validated outputs
│
├── atlas-pipeline/                      NEW (M6) — era A ingestion (config/, 00–03, selftest_atlas.py)
├── validation-studies/                  NEW (M4/M6) — imd/ (00–05) and crossval/
├── scripts/                             NEW (M1.3+) — build-time converters:
│   ├── convert_to_parquet.py            wide CSV → long Parquet + catalog.json generator
│   └── (PMTiles builder at M6)
│
├── server.py                            NEW (M1.2) — Range-capable dev server (use this, not http.server)
│
├── docs/
│   ├── user-guide.md, methodology.md, data-sources.md   existing v1 docs — untouched
│   └── v2/                              NEW ← the six kit docs land here:
│       ├── 00-structure-map.md          this file
│       ├── 01-vision-scope.md
│       ├── 02-roadmap-milestones.md
│       ├── 03-scientific-pipelines.md
│       ├── 04-frontend-ui-spec.md
│       └── 05-decision-register.md
│
└── manuscript/                          existing (main.tex v1.3) — v2 outline drafted at M7
```

**Placement rules (the two people most often get wrong):**

1. `AGENTS.md` and `PROGRESS.md` go at the **repository root** — OpenCode auto-loads `AGENTS.md` from the repo root and expects `PROGRESS.md` next to it. Only the six numbered docs go into `docs/v2/`.
2. Everything under `data/parquet/`, `data/fixtures/`, and every pipeline `work/`/`out/` directory is **generated, never hand-made**. If a task requires new data, OpenCode writes a script that produces it; you run the script (or OpenCode does, when it's not owner-compute).

## 2. One-time install

**Option A — the installer (recommended):**

```bash
cd /path/to/drought-intelligence-explorer
bash /path/to/die-v2-opencode-docs/install_v2_kit.sh .            # docs only
bash /path/to/die-v2-opencode-docs/install_v2_kit.sh . --skeleton # + create the NEW dirs above
```

What it does, in order: verifies the repo (checks `index.html` + `data/metadata.json`) → creates/uses branch `v2-dev` and tags `v2-base` (v1.0.0 snapshot) → copies `AGENTS.md`, `PROGRESS.md` to root → copies the six docs to `docs/v2/` → (`--skeleton`) creates `scripts/`, `gcm-pipeline/config/`, `atlas-pipeline/`, `validation-studies/`, `data/parquet/`, `data/fixtures/`, `data/geo/` → prints next steps. Re-running is safe (it overwrites kit-managed files only).

**Option B — manual (same result):**

```bash
cd /path/to/drought-intelligence-explorer
git checkout master && git pull
git checkout -b v2-dev && git tag v2-base
cp /path/to/kit/AGENTS.md AGENTS.md
cp /path/to/kit/PROGRESS.md PROGRESS.md
mkdir -p docs/v2 && cp /path/to/kit/docs/*.md docs/v2/
git add AGENTS.md PROGRESS.md docs/v2 && git commit -m "M1.1: install DIE v2.0 documentation suite"
```

## 3. How to run — the daily loop

### 3.1 With OpenCode (the intended workflow)

```bash
cd /path/to/drought-intelligence-explorer
opencode
```

OpenCode auto-reads `AGENTS.md`, then `PROGRESS.md`, then resumes the recorded next task. Prompts that work well:

| You say | OpenCode does |
|---|---|
| "Read AGENTS.md and PROGRESS.md, continue the DIE v2 roadmap from the next recommended task." | executes one task (e.g. M1.3), verifies, updates PROGRESS.md |
| "Do task M2.3 exactly as specified in docs/v2/02 and 03." | builds that one script + its checks |
| "Show me the current milestone status." | summarises the tracker, no code changes |

Rules the docs enforce (so you don't have to remember): one task per session; nothing from the roadmap implemented ahead of order; owner-compute items never faked; every session ends with `PROGRESS.md` updated and a commit on `v2-dev` (e.g. `M1.4: round-trip verified`).

### 3.2 Locally in a browser

- **Today (v1.0 content):** `python3 -m http.server 8000` is fine.
- **From M1.2 onward (Parquet engine):** use the Range-capable server — `python3 server.py` → http://localhost:8000. A non-Range server silently breaks DuckDB byte-range reads (measured pitfall, docs/v2/04 §3.3).
- Sanity checks after any UI task: cycle `#overview`, `#historical`, `#events`, `#propagation`, docs centre; zero console errors; narrow window for mobile drawer; Engine Lab at `#engine` once M1.7 lands.

### 3.3 Pipelines — what YOU run, and when

| When | Command | Notes |
|---|---|---|
| Any time (safety net) | `cd data-pipeline && python selftest.py` | 82 assertions must stay green |
| Monthly era B refresh (from M3) | `python run.py gee --project <GCP_PROJECT> --end YYYY-MM` → `run.py update` → `run.py indicators` → `run.py export` → `run.py validate` → `run.py status` | new months flow into CSVs + Parquet + `data/status.json`; banner picks it up |
| Era C GCM chain (after M2 handoff — **not before PROGRESS.md says M2.14 is done**) | per `gcm-pipeline/README.md`: `python selftest_gcm.py` first (synthetic), then `00_download_cmip6.py` per model/scenario, `01_inventory_check.py`, then 02→09 in order | downloads are resumable; record progress in PROGRESS.md |
| IMD validation study (after M4.1 scripts exist) | per `validation-studies/imd/README.md` | numbers feed the validation memo |
| Atlas ingestion (after M6 verification gate) | per `atlas-pipeline/README.md` | only after licence/variables verification (OD4) |

**Sequencing guard:** the GCM scripts do not exist yet — OpenCode builds them at milestone M2. Do not run anything under `gcm-pipeline/` until the tracker shows M2 complete. Everything you must execute is gated in `PROGRESS.md` §6 (Dependencies and unresolved issues).

### 3.4 Deploy / what goes live

- **GitHub Pages currently serves `master` = live v1.0.0.** Keep it that way: `v2-dev` is your working branch, tested locally.
- At the **M7 release gate** (definition of done in `docs/v2/01` §6): merge `v2-dev` → `master`, tag `v2.0.0`, update CITATION.cff, mint the Zenodo DOI, update the version-history panel. The live site then becomes v2.0.0 with all three eras.
- Optional early preview: point GitHub Pages at a `v2-preview` branch while developing — acceptable, but remember fixtures/synthetic data must never appear there (register any preview decision in PROGRESS.md).

## 4. Quick reference

| Thing | Where |
|---|---|
| What to build next | `PROGRESS.md` → "Next recommended task" |
| Full task tables + gates | `docs/v2/02-roadmap-milestones.md` |
| Pipeline specs (GEE/GCM/Atlas/IMD) | `docs/v2/03-scientific-pipelines.md` |
| UI/engine specs + pitfalls | `docs/v2/04-frontend-ui-spec.md` |
| "Which choice applies when docs disagree" | `docs/v2/05-decision-register.md` |
| v1.0 facts to cite, not re-derive | `AGENTS.md` §7 |
| Verification before "done" | `AGENTS.md` §9 |
