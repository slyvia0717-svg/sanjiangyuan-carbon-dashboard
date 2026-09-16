from __future__ import annotations

import csv
import json
from pathlib import Path

import joblib
import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from scipy.ndimage import uniform_filter
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score, precision_recall_fscore_support


ROOT = Path(__file__).resolve().parents[1]
IN_DIR = ROOT / "outputs/clcd_clipped"
FEAT_DIR = ROOT / "outputs/ml_prediction/features"
OUT = ROOT / "outputs/ml_prediction"
OUT.mkdir(parents=True, exist_ok=True)
YEARS = [2005, 2010, 2015, 2020, 2025]
CLASSES = np.arange(1, 10, dtype=np.uint8)
RNG = np.random.default_rng(20260915)


def load_float(name: str) -> np.ndarray:
    with rasterio.open(FEAT_DIR / name) as src:
        a = src.read(1).astype("float32")
        return np.where(a == src.nodata, np.nan, a)


def make_features(cur: np.ndarray, prev: np.ndarray, dem: np.ndarray,
                  slope: np.ndarray, aspect: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    valid = (cur > 0) & np.isfinite(dem)
    rows, cols = np.indices(cur.shape)
    parts = [
        cur.astype("float32"), prev.astype("float32"), (cur != prev).astype("float32"),
        dem / 7000.0, slope / 45.0,
        np.sin(np.radians(aspect)), np.cos(np.radians(aspect)),
        rows.astype("float32") / cur.shape[0], cols.astype("float32") / cur.shape[1],
    ]
    for size in (3, 11):
        denom = uniform_filter(valid.astype("float32"), size=size, mode="constant", cval=0.0)
        for cls in CLASSES:
            num = uniform_filter((cur == cls).astype("float32"), size=size, mode="constant", cval=0.0)
            parts.append(np.divide(num, denom, out=np.zeros_like(num), where=denom > 0))
    x = np.column_stack([p[valid] for p in parts]).astype("float32")
    return x, valid


def write_lulc(path: Path, arr: np.ndarray, profile: dict, tags: dict) -> None:
    p = profile.copy()
    p.update(driver="GTiff", dtype="uint8", count=1, nodata=0, compress="DEFLATE",
             tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(arr.astype("uint8"), 1)
        dst.update_tags(**tags)


# Aggregate each 30 m categorical raster to the common 300 m grid using GDAL's mode.
with rasterio.open(FEAT_DIR / "copernicus_dem_300m_clcd_grid.tif") as grid:
    profile = grid.profile.copy()
    shape = (grid.height, grid.width)

lulc: dict[int, np.ndarray] = {}
for year in YEARS:
    with rasterio.open(IN_DIR / f"CLCD_{year}_sanjiangyuan.tif") as src:
        a = src.read(1, out_shape=shape, resampling=Resampling.mode).astype("uint8")
    lulc[year] = a
    write_lulc(FEAT_DIR / f"lulc_{year}_300m_mode.tif", a, profile,
               {"source": f"CLCD {year}", "aggregation": "10x10 mode from 30 m"})

dem = load_float("copernicus_dem_300m_clcd_grid.tif")
slope = load_float("slope_degrees_300m_clcd_grid.tif")
aspect = load_float("aspect_degrees_300m_clcd_grid.tif")

# Natural-frequency stratified sample: retain all rare transitions and cap only
# abundant origin/destination pairs. Sample weights restore their population share.
train_x, train_y, train_w = [], [], []
transition_rows = []
for i, (start, end) in enumerate(zip(YEARS[:3], YEARS[1:4])):
    prev = lulc[YEARS[i - 1]] if i > 0 else lulc[start]
    x, valid = make_features(lulc[start], prev, dem, slope, aspect)
    y = lulc[end][valid]
    origin = lulc[start][valid]
    for a in CLASSES:
        for b in CLASSES:
            idx = np.flatnonzero((origin == a) & (y == b))
            n = len(idx)
            if n == 0:
                continue
            cap = 60000 if a == b else 40000
            take = min(n, cap)
            chosen = RNG.choice(idx, size=take, replace=False) if take < n else idx
            train_x.append(x[chosen]); train_y.append(y[chosen])
            train_w.append(np.full(take, n / take, dtype="float32"))
            transition_rows.append([start, end, int(a), int(b), n, take])

X = np.concatenate(train_x)
y = np.concatenate(train_y)
w = np.concatenate(train_w)
model = ExtraTreesClassifier(
    n_estimators=180, max_features="sqrt", min_samples_leaf=3,
    n_jobs=-1, random_state=20260915, class_weight=None,
)
model.fit(X, y, sample_weight=w)
joblib.dump(model, OUT / "lulc_extratrees_model.joblib", compress=3)

# Mean historical change rate for each origin class.  Tree classifiers tend to
# suppress rare changes; spatial allocation therefore ranks change probability
# and applies only the historically observed quota, separately by origin class.
origin_change_rates = {}
for cls in CLASSES:
    rates = []
    for start, end in zip(YEARS[:3], YEARS[1:4]):
        m = lulc[start] == cls
        rates.append(float(np.mean(lulc[end][m] != cls)) if np.any(m) else 0.0)
    origin_change_rates[int(cls)] = float(np.mean(rates))


def quota_predict(x: np.ndarray, origin: np.ndarray) -> np.ndarray:
    proba = model.predict_proba(x).astype("float32")
    labels = model.classes_.astype("uint8")
    result = origin.copy().astype("uint8")
    for cls in CLASSES:
        idx = np.flatnonzero(origin == cls)
        if len(idx) == 0:
            continue
        same_col = int(np.flatnonzero(labels == cls)[0])
        change_score = 1.0 - proba[idx, same_col]
        n_change = int(round(len(idx) * origin_change_rates[int(cls)]))
        if n_change == 0:
            continue
        selected = idx[np.argpartition(change_score, -n_change)[-n_change:]]
        alt = proba[selected].copy()
        alt[:, same_col] = -1.0
        result[selected] = labels[np.argmax(alt, axis=1)]
    return result

# Temporal holdout: only information available by 2020 is used to predict 2025.
Xv, valid_v = make_features(lulc[2020], lulc[2015], dem, slope, aspect)
base = lulc[2020][valid_v]
truth = lulc[2025][valid_v]
pred = quota_predict(Xv, base)
changed_true = truth != base
changed_pred = pred != base

def metrics(p: np.ndarray) -> dict:
    bp, br, bf, _ = precision_recall_fscore_support(
        changed_true, p != base, average="binary", zero_division=0
    )
    return {
        "overall_accuracy": float(accuracy_score(truth, p)),
        "kappa": float(cohen_kappa_score(truth, p)),
        "macro_f1": float(f1_score(truth, p, average="macro", zero_division=0)),
        "binary_change_precision": float(bp),
        "binary_change_recall": float(br),
        "binary_change_f1": float(bf),
        "true_change_rate": float(changed_true.mean()),
        "predicted_change_rate": float((p != base).mean()),
        "destination_accuracy_on_true_changed_pixels": float((p[changed_true] == truth[changed_true]).mean()),
    }

validation = {"model": metrics(pred), "persistence_baseline": metrics(base)}
pred_map = np.zeros(shape, dtype="uint8"); pred_map[valid_v] = pred
write_lulc(OUT / "validation_prediction_2025_300m.tif", pred_map, profile,
           {"model": "ExtraTrees", "training_periods": "2005-2010;2010-2015;2015-2020"})

# Recursive business-as-usual forecasts. The 2035 step uses 2025 as its previous state.
forecast = {}
cur, prev = lulc[2025].copy(), lulc[2020]
for year in (2030, 2035):
    xf, vf = make_features(cur, prev, dem, slope, aspect)
    nxt = np.zeros(shape, dtype="uint8")
    nxt[vf] = quota_predict(xf, cur[vf])
    forecast[year] = nxt
    write_lulc(OUT / f"lulc_forecast_{year}_bau_300m.tif", nxt, profile,
               {"scenario": "business_as_usual", "model": "ExtraTrees",
                "validated_on": "2020-2025"})
    prev, cur = cur, nxt

with (OUT / "training_transition_sample_counts.csv").open("w", newline="", encoding="utf-8-sig") as f:
    wr = csv.writer(f); wr.writerow(["start_year", "end_year", "origin", "destination", "population_n", "sample_n"])
    wr.writerows(transition_rows)

summary = {
    "model": "ExtraTreesClassifier",
    "analysis_resolution_m": 300,
    "training_rows": int(len(y)),
    "training_periods": [[2005, 2010], [2010, 2015], [2015, 2020]],
    "validation_period": [2020, 2025],
    "validation": validation,
    "forecast_years": [2030, 2035],
    "historical_origin_change_rates": origin_change_rates,
    "feature_count": int(X.shape[1]),
    "features": ["current_lulc", "previous_lulc", "recent_change", "elevation", "slope",
                 "aspect_sin", "aspect_cos", "row", "column",
                 "3x3 class proportions (1-9)", "11x11 class proportions (1-9)"],
    "scope_note": "Exploratory BAU forecast; climate and accessibility drivers are not yet included.",
}
(OUT / "model_validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
