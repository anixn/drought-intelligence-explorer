# Manuscript — Drought Intelligence Explorer (Data Descriptor)

LaTeX source of the platform's data-descriptor preprint (manuscript
version 1.3, prepared for [EarthArXiv](https://eartharxiv.org/)).

- `main.tex` — the manuscript; self-contained (inline `thebibliography`, no `.bib` file needed)
- `figures/` — the nine figures referenced by relative path `figures/`

## Compile

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

## Maintenance notes

- Figure 1 (pipeline diagram) still shows the pre-release assertion count
  ("39 assertions"); update that one label in the drawing tool to 82 the
  next time the figure is edited.
- When the EarthArXiv preprint DOI is minted, add it to the Citation
  section of the root `README.md`.
