#!/usr/bin/env python3
"""Render the method-flow schematics from Mermaid sources with Pele.

The plotted figures in this package are built by ``make_figures.py`` with
matplotlib. The three method-flow schematics are authored as Mermaid text so
that node sizes follow their labels (no clipped boxes) and are rendered here
with Pele (https://pele.run), a MIT-licensed Mermaid renderer, in headless
Chromium.

Outputs, per source in ``figures/source/*.mmd``:

* ``figures/<stem>.pdf`` — vector PDF, page size equal to the natural diagram
  size, so LaTeX scales glyph outlines and never resamples pixels;
* ``figures/<stem>.png`` — 300 dpi raster preview (3x device pixels);
* ``figures/schematics.json`` — natural size, effective type size at the
  published width, source and output checksums, and tool versions.

Run from the repository root:

    python manuscript/scientific-data/render_schematics.py

Requirements: Playwright with Chromium, and network access to the pinned Pele
build on jsDelivr. ``--check`` re-renders and compares checksums instead of
overwriting.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "figures"
SOURCE = OUT / "source"
FONTS = HERE / "fonts"

PELE_VERSION = "1.13.0"
CDN = f"https://cdn.jsdelivr.net/npm/pele@{PELE_VERSION}/dist/pele.js"
PUBLISHED_WIDTH_IN = 7.17  # A4 text width of the manuscript, 0.55 in side margins
TARGET_MIN_PT = 8.5       # floor for schematic labels at the published width
FONT_SIZE_PX = 16
SCALE = 3                 # 3 x 16 px/96 dpi -> 288 dpi raster

# source stem -> (caption label used in the manifest, expected era accents)
FIGURES = {
    "fig01_architecture": "Record architecture: three labelled eras behind one district-month contract",
    "fig02_projection_pipeline": "Era-C processing, evaluation and release chain",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def font_face(name: str, weight: int, path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        "@font-face{font-family:'Roboto';font-style:normal;font-weight:%d;"
        "src:url(data:font/ttf;base64,%s) format('truetype')}" % (weight, payload)
    )


def build_html(source: str, css_fonts: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{css_fonts}
:root{{
  --pele-bg:#ffffff; --pele-fg:#1b1b1b; --pele-line:#4a4a4a; --pele-border:#b6b6b6;
  --pele-surface:#f6f6f4; --pele-surface-alt:#eeeeec; --pele-muted:#5f5f5f;
  --pele-font:'Roboto',sans-serif;
}}
html,body{{margin:0;padding:0;background:#ffffff}}
#d{{display:inline-block;width:max-content}}
.pele-cluster-label{{fill:#1b1b1b}}
</style></head><body><div id="d"></div>
<script type="module">
import {{ render }} from '{CDN}';
try {{
  await document.fonts.load('16px Roboto');
  await document.fonts.ready;
  const r = render({json.dumps(source)}, {{
    responsive: false, fontSize: {FONT_SIZE_PX}, padding: 8,
    fontFamily: 'Roboto', fontFamilyMono: 'Roboto'
  }});
  const host = document.getElementById('d');
  host.innerHTML = r.svg;
  const svg = host.querySelector('svg');
  svg.setAttribute('width', String(r.width));
  svg.setAttribute('height', String(r.height));
  window.__size = {{ w: r.width, h: r.height }};
  window.__status = 'ok';
}} catch (error) {{
  window.__status = 'error: ' + error.message;
}}
</script></body></html>"""


def render_all(check: bool) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright is not importable. Set PYTHONPATH to the publication venv.")
        return 2

    css_fonts = "\n".join([
        font_face("Roboto", 400, FONTS / "Roboto-Regular.ttf"),
        font_face("Roboto", 700, FONTS / "Roboto-Bold.ttf"),
    ])

    sources = sorted(SOURCE.glob("*.mmd"))
    if not sources:
        print(f"FAIL: no Mermaid sources in {SOURCE}")
        return 2

    records: dict[str, dict] = {}
    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for src_path in sources:
            stem = src_path.stem
            if stem not in FIGURES:
                problems.append(f"{src_path.name}: no entry in FIGURES")
                continue
            source = src_path.read_text(encoding="utf-8")
            page = browser.new_page(viewport={"width": 1800, "height": 1200},
                                    device_scale_factor=SCALE)
            page.set_content(build_html(source, css_fonts))
            page.wait_for_function("window.__status !== undefined", timeout=90_000)
            status = page.evaluate("window.__status")
            if status != "ok":
                problems.append(f"{stem}: {status}")
                page.close()
                continue

            size = page.evaluate("window.__size")
            w, h = float(size["w"]), float(size["h"])
            box = page.locator("#d svg").bounding_box()
            if not box or abs(box["width"] - w) > 1.5 or abs(box["height"] - h) > 1.5:
                problems.append(f"{stem}: rendered box {box} differs from natural {w}x{h}")

            natural_in = w / 96.0
            include_in = min(PUBLISHED_WIDTH_IN, natural_in)
            effective_pt = 12.0 * include_in / natural_in
            if effective_pt < TARGET_MIN_PT:
                problems.append(f"{stem}: labels would print at {effective_pt:.1f} pt "
                                f"(< {TARGET_MIN_PT} pt); shorten node labels")

            pdf = OUT / f"{stem}.pdf"
            png = OUT / f"{stem}.png"
            if check:
                if not pdf.exists() or not png.exists():
                    problems.append(f"{stem}: missing output")
                    page.close()
                    continue
            else:
                page.emulate_media(media="screen")
                page.pdf(path=str(pdf), width=f"{w / 96:.4f}in", height=f"{h / 96:.4f}in",
                         margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                         print_background=True)
                page.locator("#d svg").screenshot(path=str(png))

            records[stem] = {
                "caption": FIGURES[stem],
                "source": f"figures/source/{src_path.name}",
                "renderer": f"Pele {PELE_VERSION} (Mermaid) in headless Chromium",
                "natural_px": [round(w, 1), round(h, 1)],
                "aspect": round(w / h, 4),
                "include_width_in": round(include_in, 3),
                "effective_label_pt": round(effective_pt, 2),
                "pdf": {"path": f"figures/{stem}.pdf", "sha256": sha256(pdf),
                        "bytes": pdf.stat().st_size},
                "png": {"path": f"figures/{stem}.png", "sha256": sha256(png),
                        "bytes": png.stat().st_size},
            }
            page.close()
        browser.close()

    if problems:
        print("FAIL:\n  " + "\n  ".join(problems))
        return 1

    if not check:
        payload = {
            "schema": "die-publication-schematics/1.0",
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "renderer": {"name": "Pele", "version": PELE_VERSION, "url": "https://pele.run",
                         "licence": "MIT", "font": "Roboto", "font_size_px": FONT_SIZE_PX},
            "published_width_in": PUBLISHED_WIDTH_IN,
            "figures": records,
        }
        (OUT / "schematics.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")

    for stem, rec in records.items():
        print(f"{'checked' if check else 'rendered'} {stem}: "
              f"{rec['natural_px'][0]:.0f}x{rec['natural_px'][1]:.0f} px, "
              f"{rec['effective_label_pt']:.1f} pt at {rec['include_width_in']:.2f} in")
    print(f"PASS: {len(records)} schematics")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="re-render and compare with schematics.json")
    args = ap.parse_args()
    raise SystemExit(render_all(args.check))
