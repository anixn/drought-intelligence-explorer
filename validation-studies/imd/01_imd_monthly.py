"""M4.2 step 1 - IMD daily grids -> monthly totals / means.

Rainfall is accumulated (mm/month; a partial month keeps `min_count=1` so a
missing day yields NaN rather than a too-dry total). Temperature is averaged
(degC/month). Nothing is interpolated or gap-filled: missing days stay missing
and the district aggregation ignores NaN cells (never a zero).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def monthly(cfg: dict, key: str) -> dict:
    spec = cfg["imd"][key]
    folder = Path(cfg["imd"]["root"]) / spec["dir"]
    var = spec["var"]
    y0, y1 = cfg["study"]["period"]
    if key != "rainfall":
        y0 = max(y0, cfg["study"]["temperature_from"])

    chunks = []
    months: list[tuple[int, int]] = []
    for year in range(y0, y1 + 1):
        path = folder / spec["pattern"].format(year=year)
        if not path.exists():
            print(f"  {key}: missing {year}, leaving a gap")
            continue
        ds = xr.open_dataset(path)
        da = ds[var].astype("float64")
        if "time" in da.dims:
            if key == "rainfall":
                m = da.resample(time="MS").sum(min_count=1, skipna=True)
            else:
                m = da.resample(time="MS").mean(skipna=True)
            # drop the raw fill value if it survived decoding
            if key == "rainfall":
                m = m.where(m >= 0)
            else:
                m = m.where(m < 90)
            chunks.append(m.load())
            months.extend((int(t.dt.year), int(t.dt.month)) for t in m.time)
        ds.close()

    if not chunks:
        raise SystemExit(f"no monthly data for {key}")

    arr = xr.concat(chunks, dim="time")
    arr = arr.transpose("time", "lat", "lon")
    data = arr.values.astype("float32")
    lat = arr.lat.values.astype("float64")
    lon = arr.lon.values.astype("float64")

    out = Path(cfg["_work"]) / f"imd_monthly_{key}.npz"
    np.savez_compressed(out, data=data, lat=lat, lon=lon,
                        years=np.array([y for y, _ in months]),
                        months=np.array([m for _, m in months]))
    finite = float(np.mean(np.isfinite(data))) if data.size else 0.0
    print(f"  {key}: {data.shape[0]} months x {data.shape[1]} x {data.shape[2]} "
          f"({finite:.1%} finite) -> {out.name}")
    return {"key": key, "months": int(data.shape[0]), "shape": list(data.shape),
            "first": C.month_key(*months[0]), "last": C.month_key(*months[-1]),
            "finite_share": finite}


def main() -> int:
    cfg = C.load_config()
    report = {"schema": "die-imd-monthly/1.0", "steps": []}
    print("IMD daily -> monthly")
    for key in ("rainfall", "tmax", "tmin"):
        report["steps"].append(monthly(cfg, key))
    C.write_json(Path(cfg["_work"]) / "imd_monthly_report.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
