from __future__ import annotations

import glob
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import reproject


ROOT = Path(__file__).resolve().parents[1]
CLCD = ROOT / "outputs/clcd_clipped/CLCD_2025_sanjiangyuan.tif"
TILES = sorted(glob.glob(str(ROOT / "work/dem_tiles/*.tif")))
OUT = ROOT / "outputs/ml_prediction/features"
OUT.mkdir(parents=True, exist_ok=True)


def write_float(path: Path, array: np.ndarray, profile: dict) -> None:
    p = profile.copy()
    p.update(
        driver="GTiff", dtype="float32", count=1, nodata=-9999.0,
        compress="DEFLATE", predictor=3, tiled=True, blockxsize=256,
        blockysize=256, BIGTIFF="IF_SAFER",
    )
    data = np.where(np.isfinite(array), array, p["nodata"]).astype("float32")
    with rasterio.open(path, "w", **p) as dst:
        dst.write(data, 1)
        dst.update_tags(
            source="Copernicus DEM GLO-30 (2021 release)",
            processing="bilinear reprojection to CLCD-aligned 300 m analysis grid",
        )


with rasterio.open(CLCD) as ref:
    factor = 10
    width = math.ceil(ref.width / factor)
    height = math.ceil(ref.height / factor)
    transform = ref.transform * Affine.scale(factor, factor)
    profile = ref.profile.copy()
    profile.update(width=width, height=height, transform=transform, crs=ref.crs)
    # Nearest-neighbour mask is sufficient because all final ML comparisons use
    # this same grid and the CLCD data have already been boundary-clipped.
    lulc_mask = ref.read(1, out_shape=(height, width), resampling=Resampling.nearest) != ref.nodata

dem = np.full((height, width), np.nan, dtype="float32")
for tile_path in TILES:
    with rasterio.open(tile_path) as src:
        reproject(
            source=rasterio.band(src, 1), destination=dem,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=transform, dst_crs=profile["crs"],
            src_nodata=src.nodata, dst_nodata=np.nan,
            resampling=Resampling.bilinear, init_dest_nodata=False,
        )

dem[~lulc_mask] = np.nan
valid = np.isfinite(dem)
if not np.all(valid[lulc_mask]):
    raise RuntimeError(f"DEM gaps inside analysis mask: {np.sum(lulc_mask & ~valid):,} pixels")

# In the equal-area projected grid both axes have 300 m spacing.
filled = np.where(valid, dem, 0.0)
gy, gx = np.gradient(filled, 300.0, 300.0)
slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")
aspect = np.mod(np.degrees(np.arctan2(-gx, gy)), 360.0).astype("float32")
for arr in (slope, aspect):
    arr[~valid] = np.nan

write_float(OUT / "copernicus_dem_300m_clcd_grid.tif", dem, profile)
write_float(OUT / "slope_degrees_300m_clcd_grid.tif", slope, profile)
write_float(OUT / "aspect_degrees_300m_clcd_grid.tif", aspect, profile)

summary = {
    "dem_source": "Copernicus DEM GLO-30 Public, 2021 release",
    "input_tile_count": len(TILES),
    "analysis_resolution_m": 300,
    "grid_width": width,
    "grid_height": height,
    "valid_pixels": int(valid.sum()),
    "elevation_m_min": float(np.nanmin(dem)),
    "elevation_m_max": float(np.nanmax(dem)),
    "elevation_m_mean": float(np.nanmean(dem)),
    "slope_deg_mean": float(np.nanmean(slope)),
    "slope_deg_p95": float(np.nanpercentile(slope, 95)),
}
(OUT / "terrain_feature_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
