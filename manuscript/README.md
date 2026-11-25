# Manuscript — Drought Intelligence Explorer

This folder holds the written outputs for the platform. There are two related
manuscripts and one shared figure/verification area:

| Path | Purpose |
|---|---|
| `main.tex`, `main.pdf` | EarthArXiv preprint, manuscript version 1.3 (self-contained bibliography) |
| `main_v2.tex`, `main_v2.pdf` | Version 2 working draft (three eras, engine and projections) |
| `scientific-data/` | Scientific Data (Nature Portfolio) Data Descriptor submission package |
| `figures/` | Preprint figures and the committed reproduction artifacts under `figures/reproduced/` |

## Scientific Data submission

`scientific-data/` is the journal submission package: a 23-page Data Descriptor,
nine final-size Roboto figures (vector PDF plus 300-dpi PNG), ten tables and
three annotated live-site screenshot figures. It has its own builder, structure
checker, checksums, fonts and submission checklist. See
[`scientific-data/README.md`](scientific-data/README.md).

```bash
python manuscript/scientific-data/make_figures.py
python manuscript/scientific-data/make_figures.py --check
python manuscript/scientific-data/check_manuscript.py
latexmk -pdf manuscript/scientific-data/manuscript.tex
```

The package reads released artifacts from the repository root; it performs no
scientific processing and does not modify the preprint sources.

## Preprint (EarthArXiv v1.3)

- `main.tex` — the manuscript; self-contained (inline `thebibliography`, no `.bib` file needed)
- `figures/` — the nine figures referenced by relative path `figures/`

Compile:

```bash
tectonic main.tex        # or: latexmk -pdf main.tex
```

The document needs the `newtxtext`/`newtxmath` font bundle and `natbib`
(both are included in TeX Live, MiKTeX and the tectonic bundle). No other
files are required.

## Figures

Figure 2 (temporal coverage) is generated directly from the released
`data/metadata.json`, so the printed availability windows always match the
shipped record. Regenerate it from the repository root:

```bash
data-pipeline/.venv/Scripts/python.exe manuscript/figures/make_fig2_coverage.py
```

Figures 7-9 (platform screenshots: the Drought Events workspace, the
guidance/validation/download surfaces and the phone-sized responsive
views) are captured from the live app by a scripted Playwright session,
so they can be regenerated after any interface change:

```bash
data-pipeline/.venv/Scripts/python.exe manuscript/figures/make_platform_figures.py
```

(The script serves the repository root on a localhost port and drives
headless Chromium; it needs `playwright` with its chromium browser and
`pillow` in the pipeline environment. Desktop captures use the same
1680x1050 viewport as Figures 4-6, at twice the pixel density.)

## Consistency with the repository

- The citation metadata (`CITATION.cff`, cff-version 1.2.0, DOI
  10.5281/zenodo.24113364) is identical to the repository root's copy.
- Every quantified methodological claim in the paper (L-moment parameter
  recovery, the small-sample MLE wet bias, Gringorten tie handling,
  classification continuity, area-weighting accuracy, the
  Benjamini-Hochberg trend demonstration) is reproduced by
  `data-pipeline/verify_paper_claims.py`.
- The quoted self-test assertion count (82) matches
  `data-pipeline/selftest.py`.
- `scripts/reproduce_figures.py` writes the committed reference artifacts in
  `figures/reproduced/`; CI checks them with `--check`.

## Maintenance notes

- Figure 1 (pipeline diagram) still shows the pre-release assertion count
  ("39 assertions"); update that one label in the drawing tool to 82 the
  next time the figure is edited.
- When the EarthArXiv preprint DOI is minted, add it to the Citation
  section of the root `README.md`.
- LaTeX intermediate files (`*.aux`, `*.log`, `*.fls`, `*.fdb_latexmk`,
  `*.out`, `*.bbl`, `*.blg`) are build artifacts and are ignored; only the
  compiled PDFs are kept.
