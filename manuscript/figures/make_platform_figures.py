#!/usr/bin/env python3
"""Capture the live-platform screenshots for manuscript Figures 7-9.

Runs the repository's static app in a local headless Chromium (Playwright)
and captures:

    fig7_events.png    Drought Events workspace, desktop 1680x1050 @2x
                       (completes the four-workspace series of Figs. 4-6)
    fig8_guidance.png  2x2 composite: district-inspection popup, the
                       integrated "How to use" guide, the live validation
                       report and the download centre in the Documentation
                       & Resources area
    fig9_mobile.png    four phone-view panels (390x844 @3x): Overview with
                       stacked KPI cards, the interactive map, the Drought
                       Events workspace and the responsive filter drawer

Every capture is scripted, so the figure set can be regenerated after any
interface change instead of being re-photographed by hand:

    data-pipeline/.venv/Scripts/python.exe manuscript/figures/make_platform_figures.py

Requirements: playwright chromium (pip install playwright &&
playwright install chromium) and pillow, both in data-pipeline/.venv.
"""

from __future__ import annotations

import functools
import http.server
import os
import socket
import tempfile
import threading

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))      # manuscript/figures
ROOT = os.path.dirname(os.path.dirname(HERE))          # repository root

DESKTOP = {"viewport": {"width": 1680, "height": 1050}, "device_scale_factor": 2}
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 3,
         "is_mobile": True, "has_touch": True}

PANEL_W, PANEL_H, MARGIN, LABEL_H = 1600, 1000, 40, 72
PHONE_W, PHONE_H, PHONE_MARGIN, PHONE_LABEL_H = 640, 1387, 50, 72


def serve_root() -> tuple[http.server.ThreadingHTTPServer, int]:
    """Serve the repository root on an ephemeral localhost port."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):        # noqa: A003
            pass

    handler = functools.partial(Quiet, directory=ROOT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def wait_ready(page) -> None:
    """Wait until the app has loaded data and drawn map + charts."""
    page.wait_for_function(
        "() => document.getElementById('dateSliderLabel') && "
        "document.getElementById('dateSliderLabel').textContent.trim() !== '-'",
        timeout=90_000)
    # the choropleth is canvas-rendered (preferCanvas); on a view other
    # than Overview the map container is display:none, so only require it
    # to be attached
    page.wait_for_selector("#map.leaflet-container", state="attached",
                           timeout=60_000)
    page.wait_for_function(
        "() => { const c = document.querySelector('#map canvas');"
        " return c && c.width > 0; }", timeout=60_000)
    page.wait_for_selector(".js-plotly-plot .main-svg", timeout=60_000)
    page.wait_for_timeout(1_400)          # chart animation / layout settle


def shot(page, path: str) -> None:
    page.screenshot(path=path)
    print("  captured", os.path.basename(path))


def capture_desktop(base: str, tmp: str) -> dict[str, str]:
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(**DESKTOP)
        page = ctx.new_page()

        # --- Events workspace first (fresh context = All-India default;
        #     a district click below would refocus every tab) -------------
        page.goto(f"{base}/#events", wait_until="domcontentloaded")
        wait_ready(page)
        page.wait_for_function(
            "() => { const e = document.querySelector('#viewEvents');"
            " return e && getComputedStyle(e).display !== 'none'; }",
            timeout=30_000)
        page.wait_for_selector("#viewEvents .js-plotly-plot .main-svg",
                               timeout=60_000)
        page.wait_for_timeout(1_400)
        out["events"] = os.path.join(tmp, "f7_events.png")
        shot(page, out["events"])

        # --- Overview: click-to-inspect district popup --------------------
        page.goto(f"{base}/#overview", wait_until="domcontentloaded")
        wait_ready(page)
        box = page.locator("#map").bounding_box()
        page.mouse.click(box["x"] + box["width"] * 0.46,
                         box["y"] + box["height"] * 0.55)
        page.wait_for_selector(".leaflet-popup-content", timeout=15_000)
        page.wait_for_timeout(900)         # popup content / sparkline render
        out["popup"] = os.path.join(tmp, "d_popup.png")
        shot(page, out["popup"])
        page.keyboard.press("Escape")

        # --- "How to use" guide ------------------------------------------
        page.click("#guideBtn")
        page.wait_for_timeout(1_000)
        out["guide"] = os.path.join(tmp, "d_guide.png")
        shot(page, out["guide"])
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # --- Documentation & Resources -----------------------------------
        page.goto(f"{base}/#data", wait_until="domcontentloaded")
        page.wait_for_timeout(900)
        quality = page.locator("#doc-d-quality")
        quality.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        out["quality"] = os.path.join(tmp, "d_quality.png")
        shot(page, out["quality"])

        downloads = page.locator("#doc-g-downloads")
        if downloads.get_attribute("open") is None:
            downloads.locator("summary").click()
        downloads.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        out["downloads"] = os.path.join(tmp, "d_downloads.png")
        shot(page, out["downloads"])

        browser.close()
    return out


def capture_mobile(base: str, tmp: str) -> dict[str, str]:
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(**PHONE)
        page = ctx.new_page()

        page.goto(f"{base}/#overview", wait_until="domcontentloaded")
        wait_ready(page)
        page.wait_for_timeout(800)
        out["m_overview"] = os.path.join(tmp, "m_overview.png")
        shot(page, out["m_overview"])

        # scroll to the interactive map (KPI cards sit above the fold)
        page.evaluate("document.getElementById('map')"
                      ".scrollIntoView({behavior: 'instant', block: 'start'})")
        page.wait_for_timeout(1_000)
        out["m_map"] = os.path.join(tmp, "m_map.png")
        shot(page, out["m_map"])

        # open the responsive filter drawer
        page.click("#navToggle")
        page.wait_for_timeout(900)
        out["m_drawer"] = os.path.join(tmp, "m_drawer.png")
        shot(page, out["m_drawer"])
        page.click("#sidebarClose")
        page.wait_for_timeout(500)

        page.click("#tabEvents")
        page.wait_for_function(
            "() => { const e = document.querySelector('#viewEvents');"
            " return e && getComputedStyle(e).display !== 'none'; }",
            timeout=30_000)
        page.wait_for_selector("#viewEvents .js-plotly-plot .main-svg",
                               timeout=60_000)
        page.wait_for_timeout(1_200)
        out["m_events"] = os.path.join(tmp, "m_events.png")
        shot(page, out["m_events"])

        browser.close()
    return out


def _font(size: int):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose(paths: list[str], out_path: str, cols: int, panel_w: int,
            panel_h: int, margin: int, label_h: int) -> None:
    """Paste screenshots on a labelled white canvas ((a), (b), ...)."""
    n = len(paths)
    rows = (n + cols - 1) // cols
    W = cols * panel_w + (cols + 1) * margin
    H = rows * (label_h + panel_h) + (rows + 1) * margin
    canvas = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(52)
    for i, p in enumerate(paths):
        r, c = divmod(i, cols)
        x = margin + c * (panel_w + margin)
        y = margin + r * (label_h + panel_h)
        img = Image.open(p).convert("RGB")
        img = img.resize((panel_w, panel_h), Image.LANCZOS)
        draw.text((x + 6, y + 4), f"({chr(97 + i)})", fill="#222222", font=font)
        canvas.paste(img, (x, y + label_h))
        draw.rectangle([x - 1, y + label_h - 1, x + panel_w, y + label_h + panel_h],
                       outline="#B0B8C0", width=2)
    canvas.save(out_path)
    print("  composed", os.path.basename(out_path), canvas.size)


def main() -> int:
    httpd, port = serve_root()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp(prefix="die_figs_")
    try:
        print("desktop captures:")
        d = capture_desktop(base, tmp)
        print("mobile captures:")
        m = capture_mobile(base, tmp)
    finally:
        httpd.shutdown()
        httpd.server_close()

    compose([d["events"]], os.path.join(HERE, "fig7_events.png"), 1,
            PANEL_W * 2, PANEL_H * 2, 0, 0)
    compose([d["popup"], d["guide"], d["quality"], d["downloads"]],
            os.path.join(HERE, "fig8_guidance.png"), 2,
            PANEL_W, PANEL_H, MARGIN, LABEL_H)
    compose([m["m_overview"], m["m_map"], m["m_events"], m["m_drawer"]],
            os.path.join(HERE, "fig9_mobile.png"), 4,
            PHONE_W, PHONE_H, PHONE_MARGIN, PHONE_LABEL_H)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
