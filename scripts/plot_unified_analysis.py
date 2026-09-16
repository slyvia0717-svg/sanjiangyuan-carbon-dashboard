from pathlib import Path

import csv
import matplotlib.pyplot as plt
import numpy as np
import rasterio

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'outputs/unified_analysis'; FIG=BASE/'figures'; TAB=BASE/'tables'

def read(path):
    with rasterio.open(path) as s:
        a=s.read(1).astype('float32'); nd=s.nodata
    return np.ma.masked_equal(a,nd)

fig,axes=plt.subplots(2,3,figsize=(15,8),constrained_layout=True)
stocks=[]
for year in (2005,2025,2035):
    suffix='_bau' if year>=2030 else ''
    stocks.append(read(BASE/'carbon_stock'/f'carbon_stock_{year}{suffix}_300m.tif'))
vmin=min(float(a.min()) for a in stocks);vmax=max(float(a.max()) for a in stocks)
for ax,a,year in zip(axes[0],stocks,(2005,2025,2035)):
    im=ax.imshow(a,cmap='YlGn',vmin=vmin,vmax=vmax);ax.set_title(f'{year}'+(' BAU' if year>=2030 else ' observed'));ax.axis('off')
fig.colorbar(im,ax=axes[0],shrink=.75,label='Carbon density (Mg C/ha)')
for ax,(start,end) in zip(axes[1],((2005,2025),(2025,2035),(2005,2035))):
    a=read(BASE/'carbon_change'/f'carbon_change_{start}_{end}_300m.tif')
    lim=max(abs(float(a.min())),abs(float(a.max())))
    im2=ax.imshow(a,cmap='RdYlGn',vmin=-lim,vmax=lim);ax.set_title(f'Change {start}–{end}');ax.axis('off')
fig.colorbar(im2,ax=axes[1],shrink=.75,label='Carbon-density change (Mg C/ha)')
fig.suptitle('Sanjiangyuan carbon stock and change (300 m)',fontsize=15)
fig.savefig(FIG/'carbon_maps_and_change_2005_2035.png',dpi=220,bbox_inches='tight');fig.savefig(FIG/'carbon_maps_and_change_2005_2035.pdf',bbox_inches='tight');plt.close(fig)

classes=['Forest','Shrub','Grassland','Water','Snow/Ice','Barren']
data={c:[] for c in classes};years=[]
rows=list(csv.DictReader((TAB/'lulc_area_and_carbon_by_class.csv').open(encoding='utf-8-sig')))
for year in (2005,2010,2015,2020,2025,2030,2035):
    years.append(year); subset={r['class_name']:float(r['area_km2']) for r in rows if int(r['year'])==year}
    for c in classes:data[c].append(subset.get(c,0))
fig,ax=plt.subplots(figsize=(9,5),constrained_layout=True)
for c,color in zip(classes,['#287a3c','#6bb545','#b7df6d','#4f9ed6','#d8f2fa','#caa879']):ax.plot(years,data[c],marker='o',label=c,color=color,lw=2)
ax.axvline(2025,color='#777',ls=':',lw=1);ax.set(xlabel='Year',ylabel='Area (km²)',title='Land-cover area trajectories, 2005–2035');ax.grid(alpha=.25);ax.legend(ncol=3)
fig.savefig(FIG/'lulc_area_trends_2005_2035.png',dpi=220);fig.savefig(FIG/'lulc_area_trends_2005_2035.pdf');plt.close(fig)
