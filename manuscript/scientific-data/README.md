# Scientific Data submission — Drought Intelligence Explorer v2.0.0

Standalone Scientific Data (Nature Portfolio) Data Descriptor package. It lives
inside `manuscript/` alongside the EarthArXiv preprint sources and does not
modify them.

## Deliverables

- `manuscript.tex` — standalone Data Descriptor source with embedded numerical references.
- `manuscript.pdf` — compiled first-round review manuscript (23 pages at the current build).
- `figures/fig01_*.pdf` through `fig09_*.pdf` — vector publication figures.
- `figures/fig01_*.png` through `fig09_*.png` — matching 300-dpi review/preview renders.
- `screenshots/` — live-site captures used in the three annotated interface figures.
- `figure_data.json` — every plotted value, source checksum and output checksum.
- `FIGURE_SHA256SUMS.txt` — figure-file integrity manifest.
- `make_figures.py` — deterministic figure builder.
- `check_manuscript.py` and `manuscript-check.json` — journal-structure and consistency gate.
- `fonts/` — static Roboto Regular/Bold and the SIL Open Font Licence.
- `submission-checklist.md` — completed checks and remaining owner actions.

## Figure production standard

The supplied figure specification describes a different HBV/CZIPEF project. Its
hydrological figure content is not applicable here; only its transferable
production rules were used:

- Roboto Regular and Bold throughout.
- Minimum 10 pt text at final saved size.
- 7.2 inch figure width.
- White background, academic palette, vector PDF and 300-dpi PNG.
- One complete file per figure, with panel letters embedded.

The drought-specific figures were redesigned at final size rather than scaled
down from oversized canvases. Crowded model-ranking and multi-panel content was
moved into tables or separated into simpler panels.

## Rebuild

From the repository root, using a Python environment with `numpy`, `pandas`,
`pyarrow`, `pyproj`, `PyYAML` and `matplotlib`:

```bash
python manuscript/scientific-data/make_figures.py
python manuscript/scientific-data/make_figures.py --check
python manuscript/scientific-data/check_manuscript.py
latexmk -pdf manuscript/scientific-data/manuscript.tex
```

The figure builder reads only released artifacts and fails if any figure text is
below 10 pt. `--check` verifies all input and output SHA-256 values without
rebuilding.

## Version pin

The manuscript describes DIE v2.0.0 and snapshot `v2026.09`:

- Software DOI: `10.5281/zenodo.24444860`
- Dataset DOI: `10.5281/zenodo.24445534`
- Era-B record: 1981-01 to 2026-09
- Era-A record: 1901-01 to 2025-12
- Era-C scenarios: 2015-2100

The four Zenodo ZIP bundles contain the core era stores. Companion metadata,
catalogue, national aggregate, event/validation artifacts and boundary GeoJSON
remain in the repository and public snapshot, as stated in the manuscript.
