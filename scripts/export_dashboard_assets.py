from __future__ import annotations

import csv, json
from pathlib import Path
import numpy as np
import rasterio
from PIL import Image
from scipy.ndimage import binary_dilation, binary_erosion

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'outputs/unified_analysis'; DIST=ROOT/'dashboard/dist'; ASSET=DIST/'assets'
ASSET.mkdir(parents=True,exist_ok=True)
years=[2005,2010,2015,2020,2025,2030,2035]
colors=np.array([[0,0,0,0],[243,223,138,255],[40,122,60,255],[107,181,69,255],[183,223,109,255],[79,158,214,255],[216,242,250,255],[202,168,121,255],[215,58,50,255],[134,101,168,255]],dtype=np.uint8)

def save_rgba(a,path,width=1000):
    im=Image.fromarray(a,'RGBA'); h=round(im.height*width/im.width)
    im.resize((width,h),Image.Resampling.NEAREST).save(path,optimize=True)

for y in years:
    suf='_bau' if y>=2030 else ''
    with rasterio.open(SRC/'lulc_300m'/f'lulc_{y}{suf}_300m.tif') as s: lc=s.read(1)
    save_rgba(colors[lc],ASSET/f'lulc-{y}.png')
    with rasterio.open(SRC/'carbon_stock'/f'carbon_stock_{y}{suf}_300m.tif') as s: c=s.read(1); nd=s.nodata
    valid=c!=nd; t=np.clip(c/192.0,0,1)
    rgba=np.zeros((*c.shape,4),dtype=np.uint8)
    rgba[...,0]=(244-214*t).astype(np.uint8);rgba[...,1]=(247-118*t).astype(np.uint8);rgba[...,2]=(220-142*t).astype(np.uint8);rgba[...,3]=valid*255
    save_rgba(rgba,ASSET/f'carbon-{y}.png')

for a,b in zip(years[:-1],years[1:]):
    with rasterio.open(SRC/'carbon_change'/f'carbon_change_{a}_{b}_300m.tif') as s: d=s.read(1);nd=s.nodata
    valid=d!=nd; z=np.clip(d/190,-1,1); rgba=np.zeros((*d.shape,4),dtype=np.uint8)
    pos=np.maximum(z,0);neg=np.maximum(-z,0);rgba[...,0]=(244-188*pos).astype(np.uint8);rgba[...,1]=(240-110*neg).astype(np.uint8);rgba[...,2]=(207-105*pos-90*neg).astype(np.uint8);rgba[...,3]=valid*255
    save_rgba(rgba,ASSET/f'change-{a}-{b}.png')

with rasterio.open(SRC/'park_zones_300m.tif') as s:
    zones=s.read(1); zone_tags=s.tags()
slug_by_name={'澜沧江园区':'lancang','长江源园区':'changjiang','黄河源园区':'huanghe'}
for zone_id in (1,2,3):
    mask=zones==zone_id
    edge=binary_dilation(mask,iterations=7)^binary_erosion(mask,iterations=7)
    core=binary_dilation(mask,iterations=3)^binary_erosion(mask,iterations=3)
    rgba=np.zeros((*zones.shape,4),dtype=np.uint8)
    rgba[(zones>0)&~mask]=[5,25,31,105]
    rgba[edge]=[255,255,255,230]
    rgba[core]=[11,102,91,255]
    save_rgba(rgba,ASSET/f'park-{slug_by_name[zone_tags[f"zone_{zone_id}"]]}.png')

def rows(name):
    with (SRC/'tables'/name).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))

time=rows('carbon_timeseries_2005_2035.csv')
classes=rows('lulc_area_and_carbon_by_class.csv')
parks=rows('park_level_summary.csv')
transitions=rows('transition_carbon_contributions.csv')
for r in time:
    for k in ('year','carbon_stock_MtC','change_from_previous_MtC','change_from_2005_MtC','change_from_2025_MtC'):
        if r[k]!='':r[k]=float(r[k]) if k!='year' else int(r[k])
for r in classes:
    for k in ('year','lucode'):r[k]=int(r[k])
    for k in ('area_km2','area_percent','carbon_density_MgC_ha','carbon_stock_MtC'):r[k]=float(r[k])
for r in parks:
    r['year']=int(r['year']);r['area_km2']=float(r['area_km2']);r['carbon_stock_MtC']=float(r['carbon_stock_MtC'])
for r in transitions:
    for k in ('start_year','end_year','origin_code','destination_code'):r[k]=int(r[k])
    for k in ('area_km2','carbon_change_MtC'):r[k]=float(r[k])
transitions=[r for r in transitions if r['origin_code']!=r['destination_code']]
model=json.loads((ROOT/'outputs/ml_prediction/model_validation_summary.json').read_text())
payload={'years':years,'timeSeries':time,'classes':classes,'parks':parks,'transitions':transitions,'modelValidation':model['validation'],'meta':{'resolution':'300 m','areaKm2':123343.02,'investVersion':'3.20.2','forecastYears':[2030,2035]}}
(ASSET/'dashboard-data.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print('assets',len(list(ASSET.iterdir())))
