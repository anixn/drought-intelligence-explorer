#!/usr/bin/env python3
"""Capture live Drought Intelligence Explorer windows for the manuscript figures.

The figures use the main workspace only (the left control sidebar and the
global header are excluded), which roughly doubles the rendered size of the
interface text at final figure width.

Run from the repository root, with Playwright and Chromium available:

    python manuscript/scientific-data/capture_screenshots.py

Outputs (2x device pixels) go to ``manuscript/scientific-data/screenshots/``.
The live site is used deliberately: the screenshots document the published
v2.0.0 interface, not a local working tree.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "screenshots"
BASE = "https://drought.ankitdeshmukh.com"
VIEWPORT = {"width": 1200, "height": 900}
SCALE = 2

ROUTES = {
    "overview": ("/#overview", "#mapPanel"),
    "historical": ("/#historical", "#tsPanel"),
    "events": ("/#events", "#evtTable"),
    "propagation": ("/#propagation", "#propLagChart"),
    "atlas": ("/#atlas", "#atlasMap"),
    "crossval": ("/#crossval", "#cvMap"),
    "projections": ("/#projections", "#projMap"),
    "summary": ("/#summary", "#sumMap"),
    "engine": ("/#engine", "#elSql"),
    "documentation": ("/#data", "#doc-a-about"),
    "district-profile": ("/#/district/rajasthan-jodhpur", "#dpTitle"),
    "tour": ("/tour.html", ".tour-hero"),
}

ELEMENTS = {
    "overview": ["#kpiRow", "#mapPanel", "#legendBox", "#rankPanel"],
    "historical": ["#histSummaryPanel", "#trendPanel", "#trendStats"],
    "events": ["#evtTable", "#evtTimelinePanel", "#evtDistPanel"],
    "propagation": ["#propMainPanel", "#propLagChart", "#propStats"],
    "atlas": ["#atlasControlPanel", "#atlasMapPanel", "#atlasSharePanel"],
    "crossval": ["#cvKpiPanel", "#cvMapPanel", "#cvMonthlyPanel"],
    "projections": ["#projControlPanel", "#projBandPanel", "#projMapPanel"],
    "summary": ["#sumMapPanel", "#sumStatePanel"],
    "engine": ["#elQueryPanel", "#elResultWrap", "#elStatusPanel"],
    "documentation": ["#doc-a-about", "#doc-n-status"],
    "district-profile": ["#dpHeadlinePanel", "#dpStripPanel"],
    "tour": [".tour-hero", ".tour-facts"],
}

# Optional scripted interaction before the element captures (live data states).
ACTIONS = {
    "events": """
        async () => {
          const sel = document.getElementById('evtYear');
          if (sel) {
            for (let i = 0; i < 40 && sel.options.length <= 1; i++) {
              await new Promise(r => setTimeout(r, 250));
            }
            const opt = [...sel.options].find(o => o.value === '2002' || o.textContent.trim() === '2002');
            if (opt) {
              sel.value = opt.value;
              sel.dispatchEvent(new Event('change', { bubbles: true }));
            }
          }
          await new Promise(r => setTimeout(r, 2500));
        }
    """,
    "district-profile": """
        async () => {
          for (let i = 0; i < 120; i++) {
            const strip = document.getElementById('dpStrip');
            const meta = document.getElementById('dpStripMeta');
            const chips = strip ? strip.querySelectorAll('.dp-chip').length : 0;
            const loading = meta && /loading/i.test(meta.textContent);
            if (chips >= 10 && !loading) break;
            await new Promise(r => setTimeout(r, 500));
          }
          await new Promise(r => setTimeout(r, 1500));
        }
    """,
    "engine": """
        async () => {
          const btn = document.getElementById('elInitBtn');
          if (btn) btn.click();
          for (let i = 0; i < 60; i++) {
            await new Promise(r => setTimeout(r, 500));
            const s = (document.getElementById('elStatusEngine') || {}).textContent || '';
            if (s.toLowerCase().includes('ready')) break;
          }
          const sel = document.getElementById('elPreset');
          if (sel && sel.options.length > 1) {
            sel.selectedIndex = 1;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
          }
          await new Promise(r => setTimeout(r, 800));
          const run = document.getElementById('elRunBtn');
          if (run) run.click();
          for (let i = 0; i < 60; i++) {
            await new Promise(r => setTimeout(r, 500));
            if (document.querySelectorAll('#elResultTable tbody tr').length > 0) break;
          }
        }
    """,
}


def wait_ready(page) -> None:
    if page.evaluate("() => !!document.getElementById('dateSliderLabel')"):
        page.wait_for_function(
            "() => document.getElementById('dateSliderLabel') && "
            "document.getElementById('dateSliderLabel').textContent.trim() !== '-'",
            timeout=120_000,
        )
    page.wait_for_timeout(4_500)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": BASE,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "viewport": VIEWPORT,
        "device_scale_factor": SCALE,
        "note": "Main workspace element captures; global header and left sidebar excluded.",
        "windows": {},
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, (route, selector) in ROUTES.items():
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE)
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(BASE + route, wait_until="load", timeout=120_000)
            wait_ready(page)
            try:
                page.wait_for_selector(selector, state="visible", timeout=30_000)
            except Exception:
                pass
            page.wait_for_timeout(1_200)
            action = ACTIONS.get(name)
            if action:
                page.evaluate(action)
                page.wait_for_timeout(2_000)
            main = page.locator("main")
            box = main.bounding_box()
            main.screenshot(path=str(OUT / f"{name}.png"))
            if name == "overview":
                page.locator("#map").screenshot(path=str(OUT / "overview-map.png"))
            (OUT / "elements").mkdir(exist_ok=True)
            element_boxes = {}
            for selector in ELEMENTS.get(name, []):
                try:
                    loc = page.locator(selector).first
                    eb = loc.bounding_box()
                    stem = selector.lstrip("#").replace("-", "_")
                    loc.screenshot(path=str(OUT / "elements" / f"{name}__{stem}.png"))
                    element_boxes[selector] = {k: round(v, 1) for k, v in (eb or {}).items()}
                except Exception as exc:
                    element_boxes[selector] = {"error": str(exc)[:160]}
            manifest["windows"][name] = {
                "route": route,
                "selector": selector,
                "box": {k: round(v, 1) for k, v in (box or {}).items()},
                "elements": element_boxes,
                "console_errors": errors,
            }
            print(f"captured {name} ({box['width']:.0f}x{box['height']:.0f} css)")
            page.close()
        browser.close()
    (OUT / "capture-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"PASS: {len(ROUTES)} windows captured into {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
