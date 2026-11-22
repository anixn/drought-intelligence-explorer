"""M4.1 - verify the IMD archive before anything is computed from it.

Checks are deliberately boring and explicit: file presence per year, contiguous
years, grid geometry, variable name, units and the declared fill value. The
report is written to work/imd_inventory.json and is the record of what was
actually used (never "the IMD data" in the abstract).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def year_of(pattern: str, path: Path) -> int | None:
    rx = re.escape(pattern).replace(r"\{year\}", r"(\d{4})")
    m = re.match(rx, path.name)
    return int(m.group(1)) if m else None


def check_var(cfg: dict, key: str, y0: int, y1: int) -> dict:
    spec = cfg["imd"][key]
    folder = Path(cfg["imd"]["root"]) / spec["dir"]
    files = sorted(folder.glob("*.nc"))
    years = sorted(y for y in (year_of(spec["pattern"], f) for f in files) if y)
    out = {
        "key": key,
        "dir": str(folder),
        "files": len(files),
        "years": [min(years), max(years)] if years else None,
        "missing_years": [y for y in range(y0, y1 + 1) if y not in years],
        "grid_deg": spec["grid_deg"],
        "declared_var": spec["var"],
    }
    if not years:
        out["status"] = "FAIL"
        out["notes"] = ["no files found"]
        return out

    ds = xr.open_dataset(folder / spec["pattern"].format(year=years[-1]))
    var = spec["var"]
    out.update({
        "dims": list(ds[var].dims),
        "shape": list(ds[var].shape),
        "lat": [float(ds.lat.min()), float(ds.lat.max())],
        "lon": [float(ds.lon.min()), float(ds.lon.max())],
        "n_lat": int(ds.sizes.get("lat", 0)),
        "n_lon": int(ds.sizes.get("lon", 0)),
        "units": str(ds[var].attrs.get("units", "")),
        "fill": ds[var].encoding.get("_FillValue"),
    })
    dlat = float(np.diff(ds.lat.values).mean())
    dlon = float(np.diff(ds.lon.values).mean())
    out["dlat"] = round(dlat, 4)
    out["dlon"] = round(dlon, 4)
    sample = ds[var].isel(time=slice(0, 31)).values.astype("float64")
    sample = np.where(sample > 1e10, np.nan, sample)
    out["sample_min"] = float(np.nanmin(sample))
    out["sample_max"] = float(np.nanmax(sample))
    ds.close()

    notes = []
    if abs(abs(dlat) - spec["grid_deg"]) > 1e-6 or abs(abs(dlon) - spec["grid_deg"]) > 1e-6:
        notes.append(f"grid {abs(dlat):.3f}x{abs(dlon):.3f} != declared {spec['grid_deg']}")
    if out["missing_years"]:
        notes.append(f"{len(out['missing_years'])} missing year(s) in {y0}-{y1}")
    if key == "rainfall" and out["sample_min"] < 0:
        notes.append("negative rainfall in the sample window")
    if key != "rainfall" and out["sample_min"] < -60:
        notes.append("implausible temperature minimum (fill value not decoded?)")
    out["notes"] = notes
    out["status"] = "PASS" if not out["missing_years"] and not notes else "NOTES"
    return out


def main() -> int:
    cfg = C.load_config()
    y0, y1 = cfg["study"]["period"]
    temp_from = cfg["study"]["temperature_from"]
    rows = []
    report = {"schema": "die-imd-inventory/1.0",
              "study_period": [y0, y1],
              "temperature_from": temp_from,
              "variables": []}

    for key, start in (("rainfall", y0), ("tmax", temp_from), ("tmin", temp_from)):
        info = check_var(cfg, key, start, y1)
        report["variables"].append(info)
        rows.append([info["key"], str(info["files"]), str(info["years"]),
                     f"{info.get('n_lat', '?')}x{info.get('n_lon', '?')}",
                     f"{info.get('dlat', '?')} deg", info.get("units", ""),
                     info["status"], "; ".join(info.get("notes", []))[:60]])

    C.print_table(rows, ["variable", "files", "years", "grid", "step", "units", "status", "notes"])
    C.write_json(Path(cfg["_work"]) / "imd_inventory.json", report)
    print("\nwrote", Path(cfg["_work"]) / "imd_inventory.json")
    bad = [v for v in report["variables"] if v["status"] == "FAIL"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
