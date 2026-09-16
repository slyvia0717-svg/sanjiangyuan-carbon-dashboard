from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "outputs/ml_prediction"
OUT = ROOT / "outputs/unified_analysis"
LULC_OUT = OUT / "lulc_300m"
STACK_OUT = OUT / "invest_datastacks"
LULC_OUT.mkdir(parents=True, exist_ok=True)
STACK_OUT.mkdir(parents=True, exist_ok=True)

inputs = {
    2005: SRC / "features/lulc_2005_300m_mode.tif",
    2010: SRC / "features/lulc_2010_300m_mode.tif",
    2015: SRC / "features/lulc_2015_300m_mode.tif",
    2020: SRC / "features/lulc_2020_300m_mode.tif",
    2025: SRC / "features/lulc_2025_300m_mode.tif",
    2030: SRC / "lulc_forecast_2030_bau_300m.tif",
    2035: SRC / "lulc_forecast_2035_bau_300m.tif",
}
with rasterio.open(SRC / "features/copernicus_dem_300m_clcd_grid.tif") as d:
    common_mask = d.read(1) != d.nodata
    reference = (d.crs, d.transform, d.width, d.height)

qa = {"resolution_m": 300, "expected_valid_pixels": int(common_mask.sum()), "years": {}}
for year, path in inputs.items():
    with rasterio.open(path) as src:
        arr = src.read(1).astype("uint8")
        profile = src.profile.copy()
        actual = (src.crs, src.transform, src.width, src.height)
    if actual != reference:
        raise RuntimeError(f"Grid mismatch for {year}: {path}")
    arr[~common_mask] = 0
    values, counts = np.unique(arr[arr > 0], return_counts=True)
    if not set(values.tolist()).issubset(set(range(1, 10))):
        raise RuntimeError(f"Unexpected LULC class in {year}: {values}")
    out_path = LULC_OUT / f"lulc_{year}{'_bau' if year >= 2030 else ''}_300m.tif"
    profile.update(dtype="uint8", nodata=0, compress="DEFLATE", tiled=True,
                   blockxsize=256, blockysize=256)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr, 1)
        dst.update_tags(year=year, period_type="BAU forecast" if year >= 2030 else "observed",
                        aggregation="10x10 mode from 30m CLCD" if year <= 2025 else "ML prediction")
    qa["years"][str(year)] = {
        "valid_pixels": int(np.sum(arr > 0)),
        "area_km2": float(np.sum(arr > 0) * 0.09),
        "classes": {str(int(v)): int(c) for v, c in zip(values, counts)},
    }
    workspace = OUT / "invest_300m" / f"run_{year}"
    stack = {
        "args": {
            "workspace_dir": str(workspace),
            "results_suffix": str(year),
            "lulc_bas_path": str(out_path),
            "carbon_pools_path": str(ROOT / "outputs/carbon_parameters/carbon_pools_baseline_terrestrial.csv"),
            "calc_sequestration": False,
            "do_valuation": False,
            "n_workers": -1,
        },
        "model_name": "natcap.invest.carbon",
        "invest_version": "3.20.2",
    }
    (STACK_OUT / f"carbon_{year}.json").write_text(json.dumps(stack, indent=2), encoding="utf-8")

(OUT / "qa").mkdir(exist_ok=True)
(OUT / "qa/input_grid_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(qa, ensure_ascii=False, indent=2))
