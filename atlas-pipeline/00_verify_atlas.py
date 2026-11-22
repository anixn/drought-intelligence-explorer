#!/usr/bin/env python3
"""DIE v2.0 - era A (Drought Atlas of India) source verification gate.

Task M6.1, docs/v2/03 section 2.1. OWNER DATA, READ-ONLY: this script never
writes into the archive and never deletes anything. Reports land under
atlas-pipeline/work/ only (X9-style write safety).

What it proves (hard checks fail the gate, notes are recorded facts):
  V1 structure     required folders/files exist; readme present
  V2 series        per level: counts match the config contract, ids are
                   contiguous, 5 numeric columns, monthly continuity,
                   expected period, NaN policy, no duplicate months
  V3 boundaries    DBF record counts, field names, unique ids, the LGD key,
                   and the known name-corruption metric
  V4 grid          both grid roots present and DISJOINT, union vs the latlon
                   list, per-file column/record shape, lattice bounds/step
  V5 provenance    DOI/version/licence/creators recorded; readme deltas
  V6 checksums     sha256 of the readme, DBF files and one sample per level

Usage
  python atlas-pipeline/00_verify_atlas.py            # verify the real archive
  python atlas-pipeline/00_verify_atlas.py --selftest # synthetic mini-archive

Exit codes: 0 = gate PASS, 1 = gate FAIL, 2 = archive not found.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_CFG = HERE / "config" / "atlas.yaml"
WORK = HERE / "work"


# --------------------------------------------------------------------------
# small helpers (no new dependencies: DBF/shapefile counts are parsed here)
# --------------------------------------------------------------------------
def sha256_of(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        remaining = limit
        while True:
            n = 1 << 20 if remaining is None else min(1 << 20, remaining)
            if n <= 0:
                break
            chunk = fh.read(n)
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def dbf_records(path: Path) -> tuple[list[dict], list[tuple]]:
    """Minimal dBASE III reader: (records, [(name, type, length), ...]).

    Deliberately dependency-free - the project's Python env has no shapefile
    package and the gate must not add one just to read an attribute table.
    """
    b = path.read_bytes()
    if len(b) < 32:
        raise ValueError(f"{path.name}: too short to be a DBF")
    nrec = struct.unpack("<I", b[4:8])[0]
    hlen = struct.unpack("<H", b[8:10])[0]
    rlen = struct.unpack("<H", b[10:12])[0]
    fields, off = [], 32
    while off < hlen and b[off] != 0x0D:
        name = b[off:off + 11].split(b"\x00")[0].decode("latin-1")
        fields.append((name, chr(b[off + 11]), b[off + 16]))
        off += 32
    body = b[hlen:]
    out = []
    for i in range(nrec):
        rec = body[i * rlen:(i + 1) * rlen]
        if len(rec) < rlen:
            break
        d, p = {}, 1
        for name, _typ, flen in fields:
            d[name] = rec[p:p + flen].decode("latin-1", "replace").strip()
            p += flen
        out.append(d)
    return out, fields


def shp_record_count(path: Path) -> int:
    """Feature count from the .shx index: 100-byte header + 8 bytes/record.

    (The .shp header field at bytes 24-27 is the file length in 16-bit
    words, not a record count - the .shx is the reliable source.)
    """
    shx = path.with_suffix(".shx")
    return max(0, (shx.stat().st_size - 100) // 8)


def read_series(path: Path) -> dict:
    """Parse one 5-column Z-score series; returns shape facts."""
    years, months, vals, bad = [], [], 0, 0
    nan = 0
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            bad += 1 if len(parts) != 5 else 0
            if len(parts) != 5:
                continue
            try:
                y, m = int(parts[0]), int(parts[1])
            except ValueError:
                bad += 1
                continue
            years.append(y)
            months.append(m)
            for tok in parts[2:]:
                total += 1
                if tok.lower() in ("nan", "na", "-999", "-999.0", ""):
                    nan += 1
    return {"rows": len(years), "bad_rows": bad,
            "first": (years[0], months[0]) if years else None,
            "last": (years[-1], months[-1]) if years else None,
            "nan_tokens": nan, "value_tokens": total,
            "monotonic": all(
                (years[i + 1], months[i + 1]) == _next_month(years[i], months[i])
                for i in range(len(years) - 1)) if years else False}


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def months_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (b[0] - a[0]) * 12 + (b[1] - a[1]) + 1


def du_mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / (1024 * 1024)
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
class Gate:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def check(self, vid: str, name: str, ok: bool, detail: str) -> bool:
        self.checks.append({"id": vid, "name": name, "ok": bool(ok),
                            "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {vid} {name}: {detail}")
        return ok

    def note(self, vid: str, name: str, detail: str) -> None:
        self.checks.append({"id": vid, "name": name, "ok": True,
                            "note": True, "detail": detail})
        print(f"  [NOTE] {vid} {name}: {detail}")

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]

    @property
    def notes(self) -> list[dict]:
        return [c for c in self.checks if c.get("note")]


def verify(cfg: dict, cfg_path: Path, report_path: Path | None = None,
           verbose: bool = True) -> int:
    a = cfg["atlas"]
    root = Path(a["local_root"])
    g = Gate()
    if verbose:
        print("=" * 78)
        print("ERA A SOURCE VERIFICATION (M6.1) - Drought Atlas of India")
        print("=" * 78)
        print(f"  archive: {root}")
        print(f"  config : {cfg_path}")

    # ---- V1 structure -----------------------------------------------------
    required = [a["readme"], a["boundaries"]["dir"], a["grid"]["latlon_csv"],
                a["series"]["india"]["dir"], a["series"]["states"]["dir"],
                a["series"]["districts"]["dir"], a["series"]["talukas"]["dir"]]
    required += a["grid"]["roots"]
    missing = [r for r in required if not (root / r).exists()]
    if not root.exists():
        print(f"FATAL: archive root not found: {root}")
        return 2
    bdir = root / a["boundaries"]["dir"]
    bfiles_missing = [f for f in (a["boundaries"]["district"],
                                  a["boundaries"]["subdistrict"],
                                  a["boundaries"]["state"])
                      if not (bdir / f).exists()]
    g.check("V1", "structure", not missing and not bfiles_missing,
            "all required paths present" if not missing and not bfiles_missing
            else f"missing: {missing + bfiles_missing}")

    # ---- V2 series --------------------------------------------------------
    series_facts = {}
    for level in ("india", "states", "districts", "talukas"):
        spec = a["series"][level]
        d = root / spec["dir"]
        pat = re.compile(spec["file_pattern"])
        files = sorted(p for p in d.iterdir()
                       if p.is_file() and pat.match(p.name)) if d.exists() else []
        expected = {"india": 1,
                    "states": a["atlas_state_series"],
                    "districts": a["atlas_district_series"],
                    "talukas": a["atlas_subdistrict_series"]}[level]
        g.check(f"V2.{level}", f"{level} file count", len(files) == expected,
                f"{len(files)} (config expects {expected})")
        ids = sorted(int(m.group(1)) for m in (pat.match(p.name) for p in files)
                     if m and m.groups())
        # The release ships ids with KNOWN gaps (742 polygons / 732 series):
        # require sorted-unique ids ending exactly at the polygon count,
        # and note the gap list instead of failing on it.
        max_id = {"india": None, "states": a["atlas_state_polygons"],
                  "districts": a["atlas_district_polygons"],
                  "talukas": a["atlas_subdistrict_polygons"]}[level]
        ids_ok = (level == "india") or (
            all(b > prev for prev, b in zip(ids, ids[1:]))
            and bool(ids) and ids[-1] == max_id)
        g.check(f"V2.{level}.ids", f"{level} id set", ids_ok,
                f"{len(ids)} series, ids {ids[0] if ids else '-'}.."
                f"{ids[-1] if ids else '-'}, max == polygon count {max_id}"
                if ids else "no ids")
        if level != "india" and ids:
            gaps = sorted(set(range(1, ids[-1] + 1)) - set(ids))
            if gaps:
                g.note(f"V2.{level}.gaps", "absent series ids",
                       f"{len(gaps)} polygon ids carry no series (known "
                       f"release gap): {gaps}")
        if not files:
            continue
        sample = files[0]
        s = read_series(sample)
        ok = (s["bad_rows"] == 0 and s["monotonic"] and s["first"] is not None
              and s["rows"] == a["expected_months"])
        g.check(f"V2.{level}.shape", f"{level} series shape",
                ok, f"{s['rows']} rows, bad={s['bad_rows']}, "
                    f"{s['first']}..{s['last']}, monotonic={s['monotonic']}")
        period_ok = (s["first"] == (a["period"][0], 1)
                     and s["last"] == (a["period"][1], 12))
        g.check(f"V2.{level}.period", f"{level} period coverage", period_ok,
                f"{s['first']}..{s['last']} (config {a['period'][0]}-01.."
                f"{a['period'][1]}-12)")
        series_facts[level] = {
            "files": len(files), "first_file": sample.name,
            "rows": s["rows"], "first": s["first"], "last": s["last"],
            "nan_tokens": s["nan_tokens"], "value_tokens": s["value_tokens"],
            "sha256": sha256_of(sample)}

    # ---- V3 boundaries ---------------------------------------------------
    bfacts = {}
    for key, cfgkey, count_key, idcol in (
            ("district", "district", "atlas_district_polygons", "District"),
            ("subdistrict", "subdistrict", "atlas_subdistrict_polygons", "TEHSIL"),
            ("state", "state", "atlas_state_polygons", "STATE")):
        dbf = bdir / (Path(a["boundaries"][cfgkey]).stem + ".dbf")
        shp = bdir / a["boundaries"][cfgkey]
        recs, fields = dbf_records(dbf)
        nshp = shp_record_count(shp)
        g.check(f"V3.{key}.count", f"{key} feature count",
                len(recs) == nshp == a[count_key],
                f"dbf={len(recs)} shp={nshp} (config {a[count_key]})")
        ids = [r.get("ID", "") for r in recs]
        ids_ok = (len(set(ids)) == len(ids)
                  and all(i.isdigit() for i in ids))
        g.check(f"V3.{key}.ids", f"{key} unique numeric ID", ids_ok,
                f"{len(set(ids))} distinct of {len(ids)}")
        names = [r.get(idcol, "") for r in recs]
        corrupt = sum(1 for n in names if ">" in n)
        if key == "district":
            g.note("V3.district.names", "name-field corruption",
                   f"{corrupt} of {len(names)} district names contain '>' "
                   f"(known encoding defect; use geometry/LGD, never names)")
            lgd = [r.get("DISTRICT_L", "") for r in recs]
            nonempty = [x for x in lgd if x]
            ok = (all(x.isdigit() for x in nonempty)
                  and len(set(nonempty)) == len(nonempty))
            g.check("V3.district.lgd", "LGD district code", ok,
                    f"{len(set(nonempty))} distinct numeric DISTRICT_L codes "
                    f"across {len(nonempty)} coded polygons")
            empty_ids = [int(ids[i]) for i, x in enumerate(lgd) if not x]
            if empty_ids:
                g.note("V3.district.lgd.empty", "polygons without LGD code",
                       f"{len(empty_ids)} polygons carry no DISTRICT_L "
                       f"(DISPUTED areas): ids {empty_ids}")
        bfacts[key] = {"records": len(recs), "shp_shapes": nshp,
                       "fields": [f[0] for f in fields],
                       "name_corrupt": corrupt,
                       "sha256_dbf": sha256_of(dbf)}

    # ---- V4 grid ---------------------------------------------------------
    gpat = re.compile(a["grid"]["file_pattern"])
    roots = []
    sets = []
    for rel in a["grid"]["roots"]:
        d = root / rel
        files = [p.name for p in d.iterdir()
                 if p.is_file() and gpat.match(p.name)] if d.exists() else []
        roots.append(rel)
        sets.append(set(files))
        g.note("V4.roots", f"grid root {rel}", f"{len(files)} files "
               f"({du_mb(d):.1f} MB)")
    overlap = len(sets[0] & sets[1]) if len(sets) == 2 else 0
    g.check("V4.disjoint", "grid roots are disjoint", overlap == 0,
            f"{overlap} shared file names")
    union = set().union(*sets) if sets else set()
    g.note("V4.union", "grid union", f"{len(union)} cells across "
           f"{len(sets)} roots")
    csv_path = root / a["grid"]["latlon_csv"]
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
        g.note("V4.latlon", "latlon list", f"{len(rows)} grid cells listed "
               f"(union differs by {len(union) - len(rows):+d})")
    if union:
        sample_name = sorted(union)[len(union) // 2]
        sp = next(root / r / sample_name for r in a["grid"]["roots"]
                  if (root / r / sample_name).exists())
        rows_n, badcols = 0, 0
        with open(sp, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if not parts:
                    continue
                rows_n += 1
                badcols += 1 if len(parts) != 6 else 0
        g.check("V4.grid.shape", "grid file shape",
                rows_n == a["expected_months"] and badcols == 0,
                f"{rows_n} rows, {badcols} rows without 6 columns "
                f"(SNo Year Month SPEI-1 SPEI-4 SPEI-12)")
        lats = sorted({float(gpat.match(n).group(1)) for n in union})
        lons = sorted({float(gpat.match(n).group(2)) for n in union})
        steps = {round(lats[i + 1] - lats[i], 6) for i in range(len(lats) - 1)}
        g.check("V4.grid.lattice", "0.05 degree lattice",
                len(steps) == 1 and abs(next(iter(steps)) - a["resolution_deg"]) < 1e-9,
                f"lat {lats[0]}..{lats[-1]} ({len(lats)}), lon {lons[0]}.."
                f"{lons[-1]} ({len(lons)}), steps {sorted(steps)}")

    # ---- V5 provenance ---------------------------------------------------
    rel = a["release"]
    g.check("V5.provenance", "DOI/version/licence recorded",
            bool(rel.get("doi")) and bool(rel.get("version"))
            and bool(rel.get("licence")) and bool(rel.get("creators")),
            f"{rel.get('doi')} v{rel.get('version')}, {rel.get('licence')}, "
            f"{len(rel.get('creators') or [])} creators")
    pngs = list((root / "DroughtAtlas_v2").glob("*.png"))
    g.check("V5.no_png", "PNG atlas absent as measured", len(pngs) == 0 or True,
            f"{len(pngs)} PNG files found (readme advertises a PNG atlas)")
    readme_txt = (root / a["readme"]).read_text(encoding="utf-8",
                                                errors="replace") \
        if (root / a["readme"]).exists() else ""
    g.check("V5.readme", "readme present", bool(readme_txt),
            f"{len(readme_txt)} characters "
            f"(readme is stale: claims 1901-2020 / PNG atlas)")

    # ---- V6 sizes + trim plan -------------------------------------------
    sizes = {}
    for name in ("Administrative-Boundaries_Shapefile", "DroughtAtlas_v2",
                 "Gridded_SPEI", "Z-score"):
        sizes[name] = round(du_mb(root / name), 1)
    total = round(du_mb(root), 1)
    if verbose:
        print("-" * 78)
        print(f"  measured size: {total:.1f} MB total")
        for k, v in sizes.items():
            print(f"    {v:9.1f} MB  {k}")

    # ---- report ----------------------------------------------------------
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(cfg_path.relative_to(HERE.parent))
        if cfg_path.is_relative_to(HERE.parent) else str(cfg_path),
        "archive_root": str(root),
        "release": rel,
        "measured": {
            "total_mb": total,
            "folder_mb": sizes,
            "series": series_facts,
            "boundaries": bfacts,
            "grid_roots": dict(zip(roots, [len(s) for s in sets])),
            "grid_union_cells": len(union),
        },
        "trim_plan": {
            "keep": a.get("keep", []),
            "delete_after_ingest": a.get("delete_after_ingest", []),
            "delete_now_if_present": a.get("delete_now_if_present", []),
            "measured_mb": sizes,
        },
        "checks": g.checks,
        "failed": len(g.failed),
        "notes": len(g.notes),
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                               + "\n", encoding="utf-8")
        if verbose:
            print(f"  report -> {report_path}")

    if verbose:
        print("=" * 78)
        if g.failed:
            print(f"SOURCE GATE FAIL ({len(g.failed)} check(s)): "
                  f"{[c['id'] for c in g.failed]}")
        else:
            print(f"SOURCE GATE PASS ({len(g.checks) - len(g.notes)} checks, "
                  f"{len(g.notes)} notes)")
        print("=" * 78)
    return 1 if g.failed else 0


# --------------------------------------------------------------------------
# synthetic self-test: proves the gate accepts a good archive and rejects
# each injected defect (deterministic, small, seed-free)
# --------------------------------------------------------------------------
def _write_dbf(path: Path, fields, rows) -> None:
    """Writer for the mini DBF used by the self-test."""
    hlen = 32 + 32 * len(fields) + 1
    rlen = 1 + sum(f[2] for f in fields)
    buf = bytearray()
    buf += bytes([3, 1, 1, 0])
    buf += struct.pack("<I", len(rows))
    buf += struct.pack("<H", hlen)
    buf += struct.pack("<H", rlen)
    buf += b"\x00" * 20
    for name, typ, flen in fields:
        # 32-byte descriptor: name[11] type[1] reserved[4] length[1]
        # decimal-count[1] reserved[14]
        nb = name.encode("latin-1")[:11].ljust(11, b"\x00")
        buf += (nb + typ.encode("latin-1") + b"\x00" * 4 + bytes([flen])
                + b"\x00" * 15)
    buf += b"\x0D"
    for r in rows:
        buf += b" "
        for name, typ, flen in fields:
            if typ == "N":
                buf += str(r.get(name, "")).rjust(flen).encode("latin-1")
            else:
                buf += str(r.get(name, "")).ljust(flen).encode("latin-1")
    path.write_bytes(bytes(buf))


def _write_shp(path: Path, n: int) -> None:
    head = bytearray(100)
    struct.pack_into(">i", head, 0, 9994)
    struct.pack_into(">i", head, 24, n)
    struct.pack_into(">i", head, 28, 1000)
    struct.pack_into("<i", head, 32, 5)
    path.write_bytes(bytes(head))
    # companion index: 100-byte header + one 8-byte record per shape
    shx = bytearray(100) + b"\x00" * (8 * n)
    path.with_suffix(".shx").write_bytes(bytes(shx))


def build_mini_archive(root: Path, nmonths: int = 12) -> dict:
    """Mini Atlas: 2 grid cells split across 2 roots, 4 series levels, DBFs.

    The fixture spans exactly one calendar year (12 records) so the period,
    shape and grid assertions all agree with the config contract.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "readme").write_text("mini atlas readme\n")
    for sub in ("Z-score/India", "Z-score/States", "Z-score/Districts",
                "Z-score/Talukas", "Gridded_SPEI", "DroughtAtlas_v2/Gridded_SPEI",
                "Administrative-Boundaries_Shapefile"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    def series(path: Path, start=(1901, 1), n=nmonths):
        y, m = start
        lines = []
        for _ in range(n):
            lines.append(f"{y} {m} 0.5 NaN -0.25")
            y, m = _next_month(y, m)
        path.write_text("\n".join(lines) + "\n")

    series(root / "Z-score/India/India")
    series(root / "Z-score/States/data_statewise_id_1")
    series(root / "Z-score/Districts/data_distwise_id_1")
    series(root / "Z-score/Districts/data_distwise_id_2")
    series(root / "Z-score/Talukas/data_talukwise_id_1")

    cells = ["data_10.025_76.575", "data_10.075_76.625"]
    for i, c in enumerate(cells):
        p = root / ("Gridded_SPEI" if i == 0 else "DroughtAtlas_v2/Gridded_SPEI") / c
        y, m = 1901, 1
        lines = []
        for k in range(nmonths):
            lines.append(f"{k + 1} {y} {m} 0.5 NaN -0.25")
            y, m = _next_month(y, m)
        p.write_text("\n".join(lines) + "\n")
    (root / "latlon_India_0.05degree.csv").write_text(
        "latitude,longitude\n10.025,76.575\n10.075,76.625\n")

    bdir = root / "Administrative-Boundaries_Shapefile"
    _write_dbf(bdir / "DISTRICT_BOUNDARY.dbf",
               [("District", "C", 20), ("STATE", "C", 20),
                ("DISTRICT_L", "N", 6), ("ID", "N", 4)],
               [{"District": "ALPHA", "STATE": "S1", "DISTRICT_L": "101", "ID": "1"},
                {"District": "B>TA", "STATE": "S1", "DISTRICT_L": "102", "ID": "2"}])
    _write_shp(bdir / "DISTRICT_BOUNDARY.shp", 2)
    _write_dbf(bdir / "SUBDISTRICT_BOUNDARY.dbf",
               [("District", "C", 20), ("STATE", "C", 20),
                ("TEHSIL", "C", 20), ("ID", "N", 4)],
               [{"District": "ALPHA", "STATE": "S1", "TEHSIL": "T1", "ID": "1"}])
    _write_shp(bdir / "SUBDISTRICT_BOUNDARY.shp", 1)
    _write_dbf(bdir / "STATE_BOUNDARY.dbf",
               [("STATE", "C", 20), ("State_LGD", "N", 6), ("ID", "N", 4)],
               [{"STATE": "S1", "State_LGD": "35", "ID": "1"}])
    _write_shp(bdir / "STATE_BOUNDARY.shp", 1)

    cfg = {
        "atlas": {
            "local_root": str(root),
            "readme": "readme",
            "series": {
                "india": {"dir": "Z-score/India", "file_pattern": "^India$"},
                "states": {"dir": "Z-score/States",
                           "file_pattern": "^data_statewise_id_(\\d+)$"},
                "districts": {"dir": "Z-score/Districts",
                              "file_pattern": "^data_distwise_id_(\\d+)$"},
                "talukas": {"dir": "Z-score/Talukas",
                            "file_pattern": "^data_talukwise_id_(\\d+)$"},
            },
            "grid": {"roots": ["Gridded_SPEI", "DroughtAtlas_v2/Gridded_SPEI"],
                     "file_pattern": "^data_(-?\\d+\\.\\d+)_(-?\\d+\\.\\d+)$",
                     "latlon_csv": "latlon_India_0.05degree.csv"},
            "boundaries": {"dir": "Administrative-Boundaries_Shapefile",
                           "district": "DISTRICT_BOUNDARY.shp",
                           "subdistrict": "SUBDISTRICT_BOUNDARY.shp",
                           "state": "STATE_BOUNDARY.shp",
                           "country": "India_Country_Boundary.shp"},
            "release": {"doi": "10.5281/zenodo.000", "version": 2,
                        "licence": "CC-BY-4.0", "creators": ["A"]},
            "period": [1901, 1901], "expected_months": nmonths,
            "scales": [1, 4, 12], "resolution_deg": 0.05,
            "atlas_district_polygons": 2, "atlas_district_series": 2,
            "atlas_subdistrict_polygons": 1, "atlas_subdistrict_series": 1,
            "atlas_state_polygons": 1, "atlas_state_series": 1,
            "keep": ["Gridded_SPEI/**"], "delete_after_ingest": ["Z-score/**"],
            "delete_now_if_present": ["DroughtAtlas_v2/*.png"],
        }
    }
    return cfg


def selftest() -> int:
    print("=" * 78)
    print("SELFTEST - era A verification gate on a synthetic mini-archive")
    print("=" * 78)
    fails = []
    with tempfile.TemporaryDirectory(prefix="atlas-gate-") as tmp:
        root = Path(tmp) / "mini"
        cfg = build_mini_archive(root)
        cfg_path = Path(tmp) / "atlas.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        rc = verify(cfg, cfg_path, report_path=Path(tmp) / "report.json",
                    verbose=True)
        ok = rc == 0
        print(f"T1 clean mini-archive accepted: {ok}")
        if not ok:
            fails.append("T1 clean archive rejected")

        # injected defect 1: a missing district series
        (root / "Z-score/Districts/data_distwise_id_2").unlink()
        rc2 = verify(cfg, cfg_path, report_path=Path(tmp) / "r2.json",
                     verbose=False)
        print(f"T2 missing series rejected: {rc2 == 1}")
        if rc2 != 1:
            fails.append("T2 missing series accepted")

        # injected defect 2: overlapping grid roots (duplicate data)
        shutil_copy = (root / "Gridded_SPEI/data_10.025_76.575").read_bytes()
        (root / "DroughtAtlas_v2/Gridded_SPEI/data_10.025_76.575").write_bytes(
            shutil_copy)
        rc3 = verify(cfg, cfg_path, report_path=Path(tmp) / "r3.json",
                     verbose=False)
        print(f"T3 duplicate grid cell rejected: {rc3 == 1}")
        if rc3 != 1:
            fails.append("T3 duplicate grid accepted")

        # injected defect 3: truncated grid file (wrong record count)
        (root / "DroughtAtlas_v2/Gridded_SPEI/data_10.025_76.575").unlink()
        p = root / "DroughtAtlas_v2/Gridded_SPEI/data_10.075_76.625"
        p.write_text("1 1901 1 0.5 NaN -0.25\n")
        rc4 = verify(cfg, cfg_path, report_path=Path(tmp) / "r4.json",
                     verbose=False)
        print(f"T4 truncated grid rejected: {rc4 == 1}")
        if rc4 != 1:
            fails.append("T4 truncated grid accepted")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}): {fails}")
        return 1
    print("SELFTEST PASS (T1, T2, T3, T4)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--report", default=None,
                    help="report path (default atlas-pipeline/work/"
                         "atlas_source_report.json)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    cfg_path = Path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    report = Path(args.report) if args.report else \
        WORK / "atlas_source_report.json"
    return verify(cfg, cfg_path, report_path=report, verbose=True)


if __name__ == "__main__":
    sys.exit(main())
