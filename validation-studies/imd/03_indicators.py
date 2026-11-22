"""M4.2 step 3 - IMD-SPI and IMD-SPEI with the era-B indicator machinery.

The point of the benchmark is that the *only* thing that changes is the input
data: the standardisation code, the gamma/log-logistic estimators, the mixed
zero handling, the 1981-2020 base, the per-calendar-month fits and the
calibration gates are imported from `data-pipeline/die_pipeline/indicators.py`,
not re-implemented here.

SPEI uses P - PET with a Hargreaves-Samani PET computed on the 1 deg IMD
temperature grid (documented limitation: era B's SPEI uses ERA5-Land PET, so a
SPEI difference mixes rainfall and PET-method differences - that is why SPI is
the primary benchmark and SPEI is reported with that caveat).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

sys.path.insert(0, str(C.REPO / "data-pipeline"))
from die_pipeline import indicators as I  # noqa: E402


def load_district(cfg: dict, key: str):
    path = Path(cfg["_work"]) / f"imd_district_{key}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"district_id": str}).set_index("district_id")


def grid_pet(cfg: dict, months: list[tuple[int, int]]) -> np.ndarray | None:
    """Hargreaves PET on the IMD 1 deg grid, aggregated to districts."""
    zt = Path(cfg["_work"]) / "imd_monthly_tmax.npz"
    zn = Path(cfg["_work"]) / "imd_monthly_tmin.npz"
    if not (zt.exists() and zn.exists()):
        return None
    t = np.load(zt)
    n = np.load(zn)
    if t["data"].shape != n["data"].shape:
        raise SystemExit("tmax/tmin grids differ; cannot compute PET")
    if not np.allclose(t["lat"], n["lat"]) or not np.allclose(t["lon"], n["lon"]):
        raise SystemExit("tmax/tmin coordinates differ; cannot compute PET")

    pet = C.hargreaves_pet(t["data"].astype("float64"), n["data"].astype("float64"),
                           t["lat"], months)
    w = np.load(Path(cfg["_work"]) / "imd_weights_tmax.npz")
    return C.aggregate(w["weights"], pet)


def main() -> int:
    cfg = C.load_config()
    reg = pd.read_csv(C.REPO / cfg["fabric"]["districts_csv"], dtype={"district_id": str})
    ids = reg["district_id"].tolist()
    y0, y1 = cfg["study"]["period"]
    months = C.month_grid(y0, y1)
    base = cfg["study"]["base"]
    min_years = cfg["study"]["min_base_years"]
    base_mask = I._base_cols(months, base)

    rain_df = load_district(cfg, "rainfall")
    if rain_df is None:
        raise SystemExit("run 00-02 first: no district rainfall matrix")
    rain = C.frame_to_matrix(rain_df, ids, months)
    print(f"rain matrix {rain.shape}, finite {np.isfinite(rain).mean():.1%}")

    report = {"schema": "die-imd-indicators/1.0", "base": base,
              "period": [y0, y1], "per_indicator": {}, "insufficient_base_months": []}
    written = []

    for k in cfg["indicators"]["spi"]:
        acc = I.rolling_sum(rain, int(k))
        z = I._apply_per_calendar(acc, months, base_mask, I._gamma_spi,
                                  min_years, f"imd_spi_{k}", report)
        frame = C.matrix_to_frame(z, ids, months)
        frame.insert(0, "district_id", ids)
        out = Path(cfg["_work"]) / f"imd_spi_{int(k):02d}.csv"
        frame.to_csv(out, index=False, float_format="%.6f")
        written.append(out.name)
        print(f"  SPI-{k}: {np.isfinite(z).mean():.1%} finite -> {out.name}")

    pet = grid_pet(cfg, months)
    if pet is None:
        print("  SPEI skipped: no temperature months available")
    else:
        pet_df = C.matrix_to_frame(pet, ids, months)
        pet_df.insert(0, "district_id", ids)
        (Path(cfg["_work"]) / "imd_district_pet.csv").write_text(
            pet_df.to_csv(index=False, float_format="%.4f"), encoding="utf-8")
        d = rain - pet
        print(f"  P-PET: finite {np.isfinite(d).mean():.1%}")
        for k in cfg["indicators"]["spei"]:
            acc = I.rolling_sum(d, int(k))
            z = I._apply_per_calendar(acc, months, base_mask, I._loglogistic_spei,
                                      min_years, f"imd_spei_{k}", report)
            frame = C.matrix_to_frame(z, ids, months)
            frame.insert(0, "district_id", ids)
            out = Path(cfg["_work"]) / f"imd_spei_{int(k):02d}.csv"
            frame.to_csv(out, index=False, float_format="%.6f")
            written.append(out.name)
            print(f"  SPEI-{k}: {np.isfinite(z).mean():.1%} finite -> {out.name}")

    C.write_json(Path(cfg["_work"]) / "imd_fit_report.json", report)
    print("fits:", report.get("fits"), "fallbacks:",
          report.get("calibration_fallbacks"), "empirical:",
          report.get("empirical_transforms"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
