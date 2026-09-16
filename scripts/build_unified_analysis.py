from __future__ import annotations

import csv
import json
import math
import struct
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs/unified_analysis"
LULC_DIR = BASE / "lulc_300m"
INVEST_DIR = BASE / "invest_300m"
CARBON_DIR = BASE / "carbon_stock"
CHANGE_DIR = BASE / "carbon_change"
TABLE_DIR = BASE / "tables"
FIG_DIR = BASE / "figures"
QA_DIR = BASE / "qa"
for d in (CARBON_DIR, CHANGE_DIR, TABLE_DIR, FIG_DIR, QA_DIR): d.mkdir(parents=True, exist_ok=True)

YEARS = [2005, 2010, 2015, 2020, 2025, 2030, 2035]
CLASS_NAMES = {1:"Cropland",2:"Forest",3:"Shrub",4:"Grassland",5:"Water",6:"Snow/Ice",7:"Barren",8:"Impervious",9:"Wetland"}
pool = {}
with (ROOT / "outputs/carbon_parameters/carbon_pools_baseline_terrestrial.csv").open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f): pool[int(r["lucode"])] = sum(float(r[k]) for k in ("c_above","c_below","c_soil","c_dead"))

def lulc_path(year): return LULC_DIR / f"lulc_{year}{'_bau' if year >= 2030 else ''}_300m.tif"
def invest_path(year): return INVEST_DIR / f"run_{year}" / f"c_storage_bas_{year}.tif"

lulc, carbon = {}, {}
qa_rows, class_rows, time_rows = [], [], []
for year in YEARS:
    with rasterio.open(lulc_path(year)) as src:
        lc = src.read(1); profile = src.profile.copy()
    with rasterio.open(invest_path(year)) as src:
        c = src.read(1).astype("float32"); cprof = src.profile.copy()
    valid = lc > 0
    expected = np.full(lc.shape, -1.0, dtype="float32")
    for cls, density in pool.items(): expected[lc == cls] = density
    mask_match = np.array_equal(c != cprof["nodata"], valid)
    maxdiff = float(np.max(np.abs(c[valid] - expected[valid])))
    qa_rows.append([year, int(valid.sum()), valid.sum()*0.09, mask_match, maxdiff])
    if not mask_match or maxdiff > 1e-4: raise RuntimeError(f"InVEST QA failed for {year}")
    lulc[year], carbon[year] = lc, c
    outprof = cprof.copy(); outprof.update(compress="DEFLATE", predictor=3)
    with rasterio.open(CARBON_DIR / f"carbon_stock_{year}{'_bau' if year >= 2030 else ''}_300m.tif", "w", **outprof) as dst:
        dst.write(c, 1); dst.update_tags(units="Mg C/ha", source="InVEST 3.20.2",
            period_type="BAU forecast" if year >= 2030 else "observed")
    total = float(c[valid].sum(dtype="float64") * 9 / 1e6)
    time_rows.append([year, "BAU forecast" if year >= 2030 else "observed", total])
    for cls in range(1,10):
        m = lc == cls; n = int(m.sum())
        class_rows.append([year, "BAU forecast" if year >= 2030 else "observed", cls,
            CLASS_NAMES[cls], n*0.09, n/int(valid.sum())*100, pool[cls], n*9*pool[cls]/1e6])

with (QA_DIR / "invest_pixelwise_qa.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow(["year","valid_pixels","area_km2","mask_exact_match","max_abs_difference_MgC_ha"]); w.writerows(qa_rows)

base2005=time_rows[0][2]; base2025=time_rows[4][2]
with (TABLE_DIR / "carbon_timeseries_2005_2035.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow(["year","period_type","carbon_stock_MtC","change_from_previous_MtC","change_from_2005_MtC","change_from_2025_MtC"])
    for i,(year,typ,total) in enumerate(time_rows):
        w.writerow([year,typ,total,"" if i==0 else total-time_rows[i-1][2],total-base2005,total-base2025])
with (TABLE_DIR / "lulc_area_and_carbon_by_class.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow(["year","period_type","lucode","class_name","area_km2","area_percent","carbon_density_MgC_ha","carbon_stock_MtC"]); w.writerows(class_rows)

pairs = list(zip(YEARS[:-1], YEARS[1:])) + [(2005,2025),(2025,2035),(2005,2035)]
transition_rows=[]; change_summary=[]
for start,end in pairs:
    valid=(lulc[start]>0)&(lulc[end]>0)
    delta=np.full(lulc[start].shape,-9999.0,dtype="float32")
    delta[valid]=carbon[end][valid]-carbon[start][valid]
    p=profile.copy(); p.update(dtype="float32",nodata=-9999.0,compress="DEFLATE",predictor=3)
    with rasterio.open(CHANGE_DIR/f"carbon_change_{start}_{end}_300m.tif","w",**p) as dst:
        dst.write(delta,1); dst.update_tags(units="Mg C/ha",start_year=start,end_year=end)
    change_summary.append([start,end,float(delta[valid].sum(dtype="float64")*9/1e6),int(np.sum(delta[valid]>0)),int(np.sum(delta[valid]<0)),int(np.sum(delta[valid]==0))])
    for a in range(1,10):
        for b in range(1,10):
            n=int(np.sum((lulc[start]==a)&(lulc[end]==b)))
            if n:
                transition_rows.append([start,end,a,CLASS_NAMES[a],b,CLASS_NAMES[b],n*0.09,(pool[b]-pool[a])*n*9/1e6])
with (TABLE_DIR/"carbon_change_summary.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow(["start_year","end_year","carbon_change_MtC","gain_pixels","loss_pixels","stable_pixels"]);w.writerows(change_summary)
with (TABLE_DIR/"transition_carbon_contributions.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f);w.writerow(["start_year","end_year","origin_code","origin_name","destination_code","destination_name","area_km2","carbon_change_MtC"]);w.writerows(transition_rows)

# Minimal shapefile polygon reader for park-level summaries.
def read_rings(path: Path):
    b=path.read_bytes(); recs=[]; pos=100
    while pos+8<=len(b):
        _,words=struct.unpack_from('>2i',b,pos);pos+=8;data=b[pos:pos+words*2];pos+=words*2
        st=struct.unpack_from('<i',data,0)[0]
        if st==0: continue
        nparts,npts=struct.unpack_from('<2i',data,36);parts=list(struct.unpack_from('<'+str(nparts)+'i',data,44));off=44+4*nparts
        pts=[tuple(x) for x in struct.iter_unpack('<2d',data[off:off+16*npts])]
        recs.extend([pts[s:(parts[i+1] if i+1<nparts else npts)] for i,s in enumerate(parts)])
    return recs
def signed_area(r): return .5*sum(r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1] for i in range(len(r)-1))
def inside(pt,ring):
    x,y=pt;v=False
    for i in range(len(ring)-1):
        x1,y1=ring[i];x2,y2=ring[i+1]
        if ((y1>y)!=(y2>y)) and x<(x2-x1)*(y-y1)/(y2-y1)+x1:v=not v
    return v
def polygons(rings):
    outer=[r for r in rings if signed_area(r)<0];holes=[r for r in rings if signed_area(r)>=0]; result=[[r] for r in outer]
    for h in holes:
        cand=[(abs(signed_area(o)),i) for i,o in enumerate(outer) if inside(h[0],o)]
        if cand: result[min(cand)[1]].append(h)
    return result

park_rows=[]; bdir=ROOT/"work/boundary_raw/园区边界矢量数据"
target_crs=profile["crs"]
park_shapes=[]; park_names=[]
for shp in sorted(bdir.glob("*.shp")):
    source_crs=CRS.from_wkt(shp.with_suffix('.prj').read_text(encoding='utf-8'))
    tr=Transformer.from_crs(source_crs,target_crs,always_xy=True)
    geoms=[]
    for poly in polygons(read_rings(shp)):
        coords=[[[*tr.transform(x,y)] for x,y in ring] for ring in poly]
        geoms.append({"type":"Polygon","coordinates":coords})
    park_names.append(shp.stem)
    park_shapes.extend((g,len(park_names)) for g in geoms)
zones=rasterize(park_shapes,out_shape=lulc[2005].shape,transform=profile["transform"],fill=0,dtype="uint8")
# Pixel-center rasterization leaves a narrow boundary fringe relative to the
# CLCD common mask. Assign those fringe cells to the nearest park so the three
# park summaries exactly reconcile to the whole-study total.
common=lulc[2005]>0
missing=common&(zones==0)
if np.any(missing):
    _,nearest=distance_transform_edt(zones==0,return_indices=True)
    zones[missing]=zones[nearest[0][missing],nearest[1][missing]]
zones[~common]=0
zp=profile.copy();zp.update(dtype="uint8",nodata=0,compress="DEFLATE")
with rasterio.open(BASE/"park_zones_300m.tif","w",**zp) as dst:
    dst.write(zones,1);dst.update_tags(**{f"zone_{i+1}":n for i,n in enumerate(park_names)},method="polygon rasterization; boundary fringe assigned to nearest park")
for zone_id,park_name in enumerate(park_names,1):
    pmask=zones==zone_id
    for year in YEARS:
        m=pmask&(lulc[year]>0)
        park_rows.append([park_name,year,"BAU forecast" if year>=2030 else "observed",int(m.sum())*0.09,float(carbon[year][m].sum(dtype="float64")*9/1e6)])
with (TABLE_DIR/"park_level_summary.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f);w.writerow(["park","year","period_type","area_km2","carbon_stock_MtC"]);w.writerows(park_rows)

# Compact dashboard-ready figures.
plt.rcParams.update({"font.size":10})
fig,ax=plt.subplots(figsize=(8,4.7),constrained_layout=True)
xs=[r[0] for r in time_rows];ys=[r[2] for r in time_rows]
ax.plot(xs[:5],ys[:5],marker='o',label='Observed',color='#176c55',lw=2)
ax.plot(xs[4:],ys[4:],marker='o',label='BAU forecast',color='#d07a22',lw=2,ls='--')
ax.axvline(2025,color='#777',lw=1,ls=':');ax.set(xlabel='Year',ylabel='Carbon stock (Mt C)',title='Sanjiangyuan carbon stock, 2005–2035 (300 m)');ax.grid(alpha=.25);ax.legend()
fig.savefig(FIG_DIR/'carbon_timeseries_2005_2035.png',dpi=220);fig.savefig(FIG_DIR/'carbon_timeseries_2005_2035.pdf');plt.close(fig)

summary={"invest_version":"3.20.2","resolution_m":300,"valid_area_km2":qa_rows[0][2],"years":YEARS,
 "all_invest_pixelwise_checks_passed":True,"carbon_stock_MtC":{str(r[0]):r[2] for r in time_rows},
 "change_2025_2035_MtC":time_rows[-1][2]-base2025,"interpretation":"2030 and 2035 are exploratory BAU forecasts."}
(BASE/'analysis_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(BASE/'README_unified_analysis.md').write_text("""# 三江源2005—2035统一分析（300米）

七期土地覆盖已统一至同一300米网格和共同掩膜。2005—2025为历史观测，2030和2035为机器学习BAU情景预测。七期均使用InVEST 3.20.2与同一套基准碳库参数正式计算，并与独立碳密度映射逐像元复核。

`lulc_300m/`保存七期土地覆盖；`carbon_stock/`保存正式InVEST碳储量；`carbon_change/`保存相邻期及关键长期变化；`tables/`是Dashboard直接使用的标准化数据；`qa/`保存网格和逐像元复核记录。

预测未加入气候、道路与居民点变量，应表述为“历史土地覆盖转移、地形和邻域特征驱动的探索性BAU情景”，不可解释为确定性未来。
""",encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
