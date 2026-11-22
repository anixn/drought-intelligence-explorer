#!/usr/bin/env python3
"""DIE v2.0 gcm-pipeline — raw NetCDF health scan.

Opens every raw year file under paths.yaml raw_root + raw_root_ssp and
reads a small slice; any file that raises (truncated download, corrupt
HDF, bad structure) is reported. The inventory gate (01) only sees
filenames — this catches byte-level corruption that would otherwise fail
deep in the chain (e.g. step 02 at NorESM2-MM 2022).

Usage:  python scan_nc_health.py [--root-sub Hist|SSP|both] [--var pr]
Writes: work/nc_health.json + a console list of bad files. Exit 1 if any
file is unreadable.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def check_file(path: Path, var: str) -> dict:
    """Open the file and read one variable value + 3 time values. A file
    that raises anywhere (open, structure, HDF b-tree, decode) is bad."""
    import netCDF4 as nc
    d = None
    try:
        d = nc.Dataset(path)
        if var in d.variables:
            _ = d.variables[var][0, 0, 0]
        else:
            _ = d.variables["tasmax" if var == "pet" else var][:1]
        _ = d.variables["time"][:3]
        return {"ok": True}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if d is not None:
            d.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--root-sub", default="both",
                    choices=["Hist", "SSP", "both"])
    args = ap.parse_args()

    paths = load_yaml(HERE / "config" / "paths.yaml")
    roots = {"Hist": Path(paths["raw_root"]),
             "SSP": Path(paths.get("raw_root_ssp", ""))}
    if args.root_sub != "both":
        roots = {k: v for k, v in roots.items() if k == args.root_sub}

    bad, total, t0 = [], 0, time.time()
    for sub, root in roots.items():
        if not root or not Path(root).exists():
            print(f"skip root {sub}: {root} (missing)")
            continue
        for var_dir in sorted(Path(root).iterdir()):
            if not var_dir.is_dir():
                continue
            files = sorted(var_dir.glob("*.nc"))
            print(f"[{sub}/{var_dir.name}] {len(files)} files", flush=True)
            for f in files:
                total += 1
                r = check_file(f, var_dir.name)
                if not r["ok"]:
                    bad.append({"root": sub, "file": str(f),
                                "bytes": f.stat().st_size,
                                "error": r["error"]})
                    print(f"  BAD: {f.name} ({f.stat().st_size} B) "
                          f"- {r['error']}", flush=True)

    out = HERE / "work" / "nc_health.json"
    out.write_text(json.dumps({
        "scanned": total, "bad": bad, "seconds": round(time.time() - t0, 1)},
        indent=2), encoding="utf-8")
    print(f"\nSCANNED {total} files in {time.time() - t0:.0f}s - "
          f"{len(bad)} unreadable -> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
