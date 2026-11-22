"""M4.2 step 2 - IMD grids -> the 724-district fabric (fractional area weights).

Each 0.25 deg (rain) or 1 deg (temperature) cell is split into
supersample x supersample sub-cells; a district's weight in a cell is the share
of sub-cells it covers, times cos(lat) for equal area. Ocean/outside cells carry
no district weight, and a district with no covered cell is reported as absent
(never filled with a national average).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def main() -> int:
    cfg = C.load_config()
    reg = pd.read_csv(C.REPO / cfg["fabric"]["districts_csv"], dtype={"district_id": str})
    ids = reg["district_id"].tolist()
    out = {"schema": "die-imd-districts/1.0", "districts": len(ids), "steps": []}

    for key in ("rainfall", "tmax", "tmin"):
        src = Path(cfg["_work"]) / f"imd_monthly_{key}.npz"
        if not src.exists():
            print(f"  {key}: no monthly file, skipping")
            continue
        z = np.load(src)
        data, lat, lon = z["data"], z["lat"], z["lon"]
        years, months = z["years"], z["months"]
        field_months = list(zip(years.tolist(), months.tolist()))

        weights_path = Path(cfg["_work"]) / f"imd_weights_{key}.npz"
        if weights_path.exists():
            w = np.load(weights_path)
            weights, coverage = w["weights"], w["coverage"]
        else:
            weights, coverage = C.build_weights(
                C.REPO / cfg["fabric"]["boundaries"], ids, lat, lon,
                cfg["fabric"]["supersample"])
            np.savez_compressed(weights_path, weights=weights, coverage=coverage)

        series = C.aggregate(weights, data)
        frame = C.matrix_to_frame(series, ids, field_months)
        frame.insert(0, "district_id", ids)
        out_csv = Path(cfg["_work"]) / f"imd_district_{key}.csv"
        frame.to_csv(out_csv, index=False, float_format="%.4f")

        covered = int(np.count_nonzero(coverage > 0))
        cells = np.array([int(np.count_nonzero(weights[i]))
                          for i in range(weights.shape[0])], dtype=int)
        out["steps"].append({
            "key": key, "grid": [int(lat.size), int(lon.size)],
            "months": len(field_months),
            "districts_covered": covered,
            "districts_absent": [ids[i] for i in np.where(coverage <= 0)[0]],
            "cells_median": float(np.median(cells[cells > 0])) if covered else None,
            "cells_min": int(cells[cells > 0].min()) if covered else None,
            "cells_max": int(cells.max()) if covered else None,
            "file": out_csv.name,
        })
        print(f"  {key}: {covered}/{len(ids)} districts, {len(field_months)} months "
              f"-> {out_csv.name}")

    C.write_json(Path(cfg["_work"]) / "imd_districts_report.json", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
