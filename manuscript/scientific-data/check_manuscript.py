#!/usr/bin/env python3
"""Check the Scientific Data manuscript package without third-party tools."""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _find_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "data" / "metadata.json").is_file() and (candidate / "scripts").is_dir():
            return candidate
    raise RuntimeError("repository root not found (no data/metadata.json above this script)")


ROOT = _find_root(HERE)
TEX = HERE / "manuscript.tex"


def words(text: str) -> list[str]:
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}~]", " ", text)
    return re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text)


def main() -> int:
    tex = TEX.read_text(encoding="utf-8")
    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, detail: object) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    title_match = re.search(r"\{\\LARGE\\bfseries\s+(.+?)\\par\}", tex, re.S)
    title = title_match.group(1).strip() if title_match else ""
    add("title_length", bool(title) and len(title) <= 110, {"title": title, "characters": len(title), "limit": 110})
    add("title_style", bool(title) and not any(c in title for c in ":()") and "Drought Intelligence Explorer" not in title and "CMIP" not in title, title)

    abstract_match = re.search(r"\\section\*\{(?:Abstract)\}(.*?)\\section\*\{Background", tex, re.S)
    abstract = abstract_match.group(1).strip() if abstract_match else ""
    abstract_words = len(words(abstract))
    add("abstract_length", 0 < abstract_words <= 170, {"words": abstract_words, "limit": 170})
    add("abstract_no_urls", "http" not in abstract.lower() and "doi" not in abstract.lower(), "No URL or DOI in abstract")

    required = ["Background & Summary", "Methods", "Data Records", "Technical Validation", "Usage Notes", "Data Availability", "Code Availability"]
    headings = [h.replace("\\&", "&") for h in re.findall(r"\\section\*\{(.+?)\}", tex)]
    positions = []
    for h in required:
        positions.append(headings.index(h) if h in headings else -1)
    add("required_sections", all(p >= 0 for p in positions) and positions == sorted(positions), headings)
    add("data_overview_single_paragraph", headings.count("Data Overview") == 1, headings.count("Data Overview"))
    forbidden = {"Results", "Discussion", "Conclusions", "Reuse Potential", "Limitations", "Version 1.0 scope and future updates", "Version 2.0 scope and status"}
    add("no_out_of_scope_headings", not (set(headings) & forbidden), sorted(set(headings) & forbidden))

    add("no_internal_refs", not re.search(r"\\(?:ref|label|cref|Cref)\b", tex), "Free-text figure/table references only")
    add("embedded_bibliography", "\\begin{thebibliography}" in tex and "\\bibliography{" not in tex and "\\addbibresource" not in tex, "Inline thebibliography; no .bib/.bbl dependency")
    add("computer_modern", "newtx" not in tex and "lmodern" not in tex and "fontspec" not in tex, "Default Computer Modern fonts")

    bib_block = re.search(r"\\begin\{thebibliography\}\{(\d+)\}(.*?)\\end\{thebibliography\}", tex, re.S)
    bib_items = re.findall(r"\\bibitem\{([^}]+)\}", bib_block.group(2)) if bib_block else []
    declared = int(bib_block.group(1)) if bib_block else -1
    add("bibliography_count", len(bib_items) == declared, {"entries": len(bib_items), "declared": declared})

    body = tex[:bib_block.start()] if bib_block else tex
    cited: list[str] = []
    for group in re.findall(r"\\citep\{([^}]+)\}", body):
        for key in group.split(","):
            key = key.strip()
            if key and key not in cited:
                cited.append(key)
    add("citations_defined", set(cited) <= set(bib_items), sorted(set(cited) - set(bib_items)))
    add("citation_order", cited == bib_items, {"first_appearance": cited, "bibliography": bib_items})
    add("all_references_cited", set(bib_items) <= set(cited), sorted(set(bib_items) - set(cited)))

    n_figures = tex.count("\\begin{figure}")
    n_tables = tex.count("\\begin{table}")
    add("figure_count", 1 <= n_figures <= 9, n_figures)
    add("table_count", 1 <= n_tables <= 10, n_tables)
    figure_files = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    missing = [f for f in figure_files if not (HERE / "figures" / f).exists()]
    add("figure_files_exist", not missing and len(figure_files) == n_figures, {"files": figure_files, "missing": missing})
    add("figure_numbers_in_text", all((f"Fig. {i}" in tex or f"Figure {i}" in tex) for i in range(1, n_figures + 1)), n_figures)
    overview = re.search(r"\\section\*\{Data Overview\}(.*?)\\section\*\{Technical Validation\}", tex, re.S)
    overview_figures = overview.group(1).count("\\begin{figure}") if overview else 0
    add("data_overview_figure_limit", 0 <= overview_figures <= 2, overview_figures)

    stale = ["3{,}715{,}048", "0.8743", "4 of 538", "n=538", "7,965", "v2-dev", "in preparation", "24-model ensemble", "540 months"]
    found = [s for s in stale if s in tex]
    add("no_stale_claims", not found, found)
    current = ["3,780,163", "4 of 547", "0.8716", "[0.8356,0.8999]", "24445534", "24444860", "2026-09", "eight-model"]
    missing_current = [s for s in current if s not in tex]
    add("current_headline_values", not missing_current, missing_current)
    add("no_placeholders", not re.search(r"\b(?:TODO|TBD|FIXME|XXX|PENDING)\b", tex), "No drafting placeholders")

    meta = json.loads((ROOT / "data/metadata.json").read_text(encoding="utf-8"))
    status = json.loads((ROOT / "data/status.json").read_text(encoding="utf-8"))
    reality = json.loads((ROOT / "data/reality_checks.json").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "scripts/regression_baseline.json").read_text(encoding="utf-8"))
    figure_data = json.loads((HERE / "figure_data.json").read_text(encoding="utf-8"))
    valid_total = sum(v["finite"] for v in baseline["per_variable"].values())
    add("valid_value_total", valid_total == 3780163 and "3,780,163" in tex, valid_total)
    add("record_end", meta["period"]["end"] == "2026-09" and status["data"]["data_month"] == "2026-09", meta["period"]["end"])
    add("doi_contract", meta["doi"]["v2_0_0"] == "10.5281/zenodo.24444860" and meta["doi"]["dataset_v2_0_0"] == "10.5281/zenodo.24445534", meta["doi"])
    add("reality_version", reality["data_version"] == "2.0.0", reality["data_version"])
    add("figure_data_real", figure_data.get("synthetic_data") is False and len(figure_data.get("figures", {})) == n_figures, {"synthetic_data": figure_data.get("synthetic_data"), "figures": len(figure_data.get("figures", {}))})
    add("figure_typography", figure_data.get("font") == "Roboto" and figure_data.get("minimum_font_pt") == 10 and figure_data.get("width_in") == 7.2, {"font": figure_data.get("font"), "minimum_font_pt": figure_data.get("minimum_font_pt"), "width_in": figure_data.get("width_in")})
    add("roboto_files", (HERE / "fonts" / "Roboto-Regular.ttf").exists() and (HERE / "fonts" / "Roboto-Bold.ttf").exists() and (HERE / "fonts" / "OFL.txt").exists(), "Static Roboto Regular/Bold and OFL licence present")

    pdf = HERE / "manuscript.pdf"
    add("compiled_pdf", pdf.exists() and pdf.stat().st_size > 100_000, {"bytes": pdf.stat().st_size if pdf.exists() else 0})
    log = (HERE / "manuscript.log").read_text(encoding="utf-8", errors="replace") if (HERE / "manuscript.log").exists() else ""
    add("no_undefined_citations", "undefined" not in log.lower() or "Citation" not in log, "No undefined citations")
    add("no_overfull_boxes", "Overfull \\hbox" not in log, "No overfull horizontal boxes")

    passed = sum(1 for c in checks if c["pass"])
    payload = {"schema": "die-manuscript-check/1.0", "passed": passed, "total": len(checks), "checks": checks}
    (HERE / "manuscript-check.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{'PASS' if passed == len(checks) else 'FAIL'}: {passed}/{len(checks)} manuscript checks")
    for c in checks:
        if not c["pass"]:
            print(" -", c["check"], ":", c["detail"])
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
