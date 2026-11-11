#!/usr/bin/env python3
"""Regenerate manuscript Figure 2 (temporal coverage) from data/metadata.json.

The figure is drawn directly from the per-indicator availability windows of
the released metadata file, so the printed start/end months always match the
shipped record (earlier drafts showed the SPI-12/SPEI-12 warm-up as 1982-01;
the first complete 12-month accumulation actually ends in 1981-12).

Run from the repository root:
    data-pipeline/.venv/Scripts/python.exe manuscript/figures/make_fig2_coverage.py
"""

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = os.path.dirname(os.path.abspath(__file__))     # manuscript/figures
ROOT = os.path.dirname(os.path.dirname(HERE))         # repository root
META = os.path.join(ROOT, "data", "metadata.json")
OUT = os.path.join(HERE, "fig2_coverage.png")


def month_num(ym: str) -> float:
    y, m = ym.split("-")
    return int(y) + (int(m) - 1) / 12.0


ORDER = ["spi_1", "spi_3", "spi_6", "spi_12",
         "spei_1", "spei_3", "spei_6", "spei_12", "sma", "vci"]
FAMILY_COLOR = {"spi": "#2A5F85", "spei": "#22756B",
                "land_sma": "#C87E3B", "land_vci": "#6F9E3F"}


def main() -> int:
    with open(META, encoding="utf-8") as fh:
        meta = json.load(fh)
    inds = {i["id"]: i for i in meta["indicators"]}

    fig, ax = plt.subplots(figsize=(16, 7.3), dpi=125)
    fig.patch.set_facecolor("white")

    # shaded reference-period bands
    ax.axvspan(month_num("1981-01"), month_num("2020-12") + 1 / 12,
               color="#E8EEF2", zorder=0)
    ax.text(month_num("1981-04"), -0.55,
            "Reference climatology 1981\u20132020 (SPI, SPEI, SMA)",
            fontsize=13.5, color="#5A6B7A")
    ax.axvspan(month_num("2000-02"), month_num("2025-12") + 1 / 12,
               color="#DCEBD2", alpha=0.55, zorder=0)

    for k, iid in enumerate(ORDER):
        ind = inds[iid]
        y = k                                        # SPI-1 on top after flip
        start, end = ind["available_from"], ind["available_to"]
        color = (FAMILY_COLOR["land_sma"] if iid == "sma"
                 else FAMILY_COLOR["land_vci"] if iid == "vci"
                 else FAMILY_COLOR[ind["family"]])
        ax.barh(y, month_num(end) + 1 / 12 - month_num(start),
                left=month_num(start), height=0.62, color=color, zorder=3)
        ax.text(month_num(start) - 0.2, y, start, ha="right", va="center",
                fontsize=11.5, color="#3B4A57")
        ax.text(month_num(end) + 1 / 12 + 0.2, y, end, ha="left",
                va="center", fontsize=11.5, color="#3B4A57")

    ax.set_yticks(range(len(ORDER)))
    short = {"sma": "SMA", "vci": "VCI"}
    ax.set_yticklabels([short.get(i, inds[i]["label"]) for i in ORDER],
                       fontsize=13.5)
    ax.set_xlim(1976.4, 2027.6)
    ax.set_ylim(-1.5, 10.3)
    ax.invert_yaxis()
    ax.set_xticks(range(1980, 2026, 5))
    ax.tick_params(axis="x", labelsize=13, colors="#3B4A57")
    ax.set_xlabel("Observation month", fontsize=14.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9AA7B2")

    ax.text(month_num("2000-06"), 9.75,
            "VCI reference period 2000\u2013present",
            fontsize=13.5, color="#4C7A2E")

    ax.legend(handles=[
        Patch(facecolor=FAMILY_COLOR["spi"], label="Meteorological (SPI)"),
        Patch(facecolor=FAMILY_COLOR["spei"], label="Water balance (SPEI)"),
        Patch(facecolor=FAMILY_COLOR["land_sma"], label="Land surface (SMA)"),
        Patch(facecolor=FAMILY_COLOR["land_vci"], label="Land surface (VCI)"),
    ], loc="lower left", bbox_to_anchor=(0.03, 0.075), ncol=2, fontsize=11,
        handlelength=1.6, columnspacing=1.6, frameon=False)

    fig.tight_layout()
    fig.savefig(OUT, facecolor="white")
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
