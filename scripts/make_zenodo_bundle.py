"""Build the Zenodo dataset archives (M7.2) from the shipped stores.

Produces four archives whose layout matches the R2 snapshot (`parquet/...`,
`drought/*.csv`) plus a checksum file and a README, so the Zenodo deposit is a
drag-and-drop of `dist/zenodo/*`.

    python scripts/make_zenodo_bundle.py --version 2.0.0 [--force]

Sizes are printed; nothing is uploaded. `dist/` is gitignored.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "dist" / "zenodo"

# (archive name, [(source dir, prefix inside the archive)])
GROUPS = [
    ("era-a-atlas", [(REPO / "data" / "parquet" / "atlas", "parquet/atlas")]),
    ("era-b-gridded", [
        (REPO / "data" / "parquet" / "observed", "parquet/observed"),
        (REPO / "data" / "drought", "drought"),
    ]),
    ("era-c-projections", [(REPO / "data" / "parquet" / "projections", "parquet/projections")]),
    ("cross-validation", [(REPO / "data" / "parquet" / "cross_validation", "parquet/cross_validation")]),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(name: str, version: str, sources, force: bool) -> Path:
    out = OUT / f"die-v{version}-{name}.zip"
    if out.exists() and not force:
        print(f"  {out.name}: exists ({out.stat().st_size / 1e6:.1f} MB), --force to rebuild")
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED,
                         allowZip64=True) as z:
        for root, prefix in sources:
            files = sorted(p for p in root.rglob("*") if p.is_file())
            for p in files:
                arc = prefix + "/" + str(p.relative_to(root)).replace("\\", "/")
                # Parquet is already compressed: storing avoids a pointless pass
                method = (zipfile.ZIP_STORED if p.suffix == ".parquet"
                          else zipfile.ZIP_DEFLATED)
                z.write(p, arc, compress_type=method)
                count += 1
    print(f"  {out.name}: {count:,} files, {out.stat().st_size / 1e6:.1f} MB")
    return out


DATASET_README = """# Drought Intelligence Explorer v2.0.0 — district drought record for India

Snapshot **v{version}** of the data behind https://drought.ankitdeshmukh.com, in
long-format Parquet. Three labelled eras; they are never spliced.

| Archive | Era | Contents | Coverage |
|---|---|---|---|
| `die-v{version}-era-a-atlas.zip` | A — reconstruction | `parquet/atlas/variable=spei_01|04|12/year=<yyyy>/` | 1901–2025 |
| `die-v{version}-era-b-gridded.zip` | B — gridded product | `parquet/observed/`, `drought/*.csv` | 1981-01 → 2026-09 |
| `die-v{version}-era-c-projections.zip` | C — projections | `parquet/projections/scenario=<s>/stat=<st>/variable=<id>/year=<yyyy>/` | 2015–2100 |
| `die-v{version}-cross-validation.zip` | A ↔ B | `parquet/cross_validation/*.parquet` | 1981–2014 |

## Schema

`district_id` (string slug, e.g. `gujarat-ahmedabad`) · `year` (int16) ·
`month` (int8, 1–12) · `value` (float32; z-score for SPI/SPEI, **percent** for
soil-moisture anomaly, 0–100 for VCI). Missing observations are **absent rows**,
never NULL and never imputed. The national pre-aggregate
(`parquet/_national_monthly.parquet`) adds `variable` and `n_districts`.

Era-C statistics are model fractions, not z-scores: `agreement_moderate`,
`agreement_severe`, `n_models`, `dir_agreement_drier`, `dir_agreement_n`, plus
`median`, `p25`, `p75` and per-model `members` (`model=<GCM>`).

## Method (short)

SPI: gamma, MLE, mixed zeros; SPEI: log-logistic, L-moments; base period
1981–2020; per-calendar-month fits with calibration gates. Events: runs ≥ 3
months below −1.00 z / −15 % / 30 % VCI, censored at record edges, broken by
missing months. Area weighting: LAEA (lat_0 22.5, lon_0 79.5). Methodology
version `research-gee-1.0.2`, pipeline `1.1.0`. Full reference:
Documentation P (SQL field guide) in the application and `docs/sql-guide.md` in
the software repository.

## Licences

Derived products: **CC-BY-4.0**. Source datasets keep their own terms — CHIRPS
(public domain), ERA5-Land (Copernicus Licence), MODIS (public domain), IMD
(Government of India, research use), Drought Atlas of India (CC-BY-4.0,
DOI 10.5281/zenodo.20368514), CMIP6 (ESGF terms).

## Verify

`SHA256SUMS.txt` lists every archive. Rebuild the checksums with
`sha256sum -c SHA256SUMS.txt`.
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="2.0.0")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    v = args.version.lstrip("v")
    print(f"Zenodo dataset bundles v{v} -> {OUT}")
    archives = [build(name, v, src, args.force) for name, src in GROUPS]
    readme = OUT / "README.md"
    readme.write_text(DATASET_README.format(version=v), encoding="utf-8")
    sums = OUT / "SHA256SUMS.txt"
    lines = [f"{sha256(p)}  {p.name}" for p in archives] + [f"{sha256(readme)}  README.md"]
    sums.write_text("\n".join(sorted(lines, key=lambda s: s.split('  ')[1])) + "\n",
                    encoding="utf-8")
    total = sum(p.stat().st_size for p in archives)
    print(f"total {total / 1e6:.1f} MB across {len(archives)} archives")
    print("wrote", sums)
    return 0


if __name__ == "__main__":
    sys.exit(main())
