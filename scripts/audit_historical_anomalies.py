import csv,json,math
from collections import Counter
from pathlib import Path
import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy import ndimage
from PIL import Image,ImageDraw,ImageFont

SRC=Path('outputs/clcd_clipped'); OUT=Path('outputs/anomaly_audit'); OUT.mkdir(exist_ok=True); FIG=OUT/'figures'; FIG.mkdir(exist_ok=True)
names={1:'耕地',2:'森林',3:'灌木',4:'草地',5:'水体',6:'冰雪',7:'裸地',8:'不透水面',9:'湿地'}
carbon={1:100.95,2:191.91,3:124.44,4:100.95,5:0,6:0,7:28.78,8:0,9:127.74}
years=[2015,2020,2025]

# Exact 30 m pixel accounting, streamed by block.
trans=Counter(); paths=Counter(); states=Counter()
files=[rasterio.open(SRC/f'CLCD_{y}_sanjiangyuan.tif') for y in years]
try:
    for _,win in files[0].block_windows(1):
        a,b,c=[s.read(1,window=win) for s in files]; valid=(a>0)&(b>0)&(c>0)
        code=a[valid].astype(np.int16)*100+b[valid].astype(np.int16)*10+c[valid]
        u,n=np.unique(code,return_counts=True); paths.update({int(x):int(y) for x,y in zip(u,n)})
        code2=a[valid].astype(np.int16)*10+b[valid]; u,n=np.unique(code2,return_counts=True); trans.update({int(x):int(y) for x,y in zip(u,n)})
        states['unchanged']+=int((valid&(a==b)&(b==c)).sum())
        states['reversal_to_2015']+=int((valid&(a!=b)&(a==c)).sum())
        states['persistent_2020']+=int((valid&(a!=b)&(b==c)).sum())
        states['continued_change']+=int((valid&(a!=b)&(b!=c)&(a!=c)).sum())
        states['changed_before_2015_or_other']+=int((valid&~((a==b)&(b==c))&~((a!=b)&(a==c))&~((a!=b)&(b==c))&~((a!=b)&(b!=c)&(a!=c))).sum())
finally:
    [s.close() for s in files]

trows=[]
for code,n in trans.items():
    a,b=divmod(code,10); delta=carbon[b]-carbon[a]
    trows.append({'from_class':a,'from_name':names[a],'to_class':b,'to_name':names[b],'pixel_count':n,'area_km2':n*0.0009,'carbon_density_change_tC_ha':delta,'carbon_contribution_tC':n*0.09*delta,'carbon_contribution_MtC':n*0.09*delta/1e6})
trows.sort(key=lambda r:r['carbon_contribution_tC'])
with (OUT/'transition_carbon_contributions_2015_2020.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=trows[0].keys()); w.writeheader(); w.writerows(trows)

prows=[]
for code,n in paths.items():
    a=code//100;b=(code//10)%10;c=code%10
    if a==b==c: typ='unchanged'
    elif a!=b and a==c: typ='reversal_to_2015'
    elif a!=b and b==c: typ='persistent_2020'
    else: typ='continued_or_other'
    prows.append({'class_2015':a,'name_2015':names[a],'class_2020':b,'name_2020':names[b],'class_2025':c,'name_2025':names[c],'path_type':typ,'pixel_count':n,'area_km2':n*0.0009})
prows.sort(key=lambda r:r['pixel_count'],reverse=True)
with (OUT/'three_year_pathways_2015_2020_2025.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=prows[0].keys()); w.writeheader(); w.writerows(prows)

# 300 m screening grid for topology/edge/patch diagnostics.
with rasterio.open(SRC/'CLCD_2015_sanjiangyuan.tif') as s:
    H=math.ceil(s.height/10); W=math.ceil(s.width/10); prof=s.profile.copy(); tr=s.transform*s.transform.scale(s.width/W,s.height/H)
    small=[]
    for y in years:
        with rasterio.open(SRC/f'CLCD_{y}_sanjiangyuan.tif') as x: small.append(x.read(1,out_shape=(H,W),resampling=Resampling.nearest))
a,b,c=small; valid=(a>0)&(b>0)&(c>0); changed=valid&(a!=b)
screen=np.zeros((H,W),dtype=np.uint8); screen[valid&(a==b)&(b==c)]=1; screen[valid&(a!=b)&(a==c)]=2; screen[valid&(a!=b)&(b==c)]=3; screen[valid&(a!=b)&(b!=c)&(a!=c)]=4
prof.update(width=W,height=H,transform=tr,dtype='uint8',nodata=0,count=1,compress='LZW')
with rasterio.open(OUT/'change_stability_screening_300m.tif','w',**prof) as d: d.write(screen,1); d.update_tags(classes='1 unchanged; 2 reversal to 2015; 3 persistent since 2020; 4 continued/other',purpose='screening only; exact areas are from 30 m rasters')

dist_boundary=ndimage.distance_transform_edt(valid)*0.3
near_boundary=valid&(dist_boundary<=1.0)
waterice=(a==5)|(a==6)|(b==5)|(b==6); dist_wi=ndimage.distance_transform_edt(~waterice)*0.3; near_wi=valid&(dist_wi<=0.6)
edge_stats={'screening_resolution_m':300,'changed_fraction_all':float(changed.sum()/valid.sum()),'changed_fraction_within_1km_boundary':float((changed&near_boundary).sum()/near_boundary.sum()),'changed_fraction_interior':float((changed&~near_boundary).sum()/(valid&~near_boundary).sum()),'share_of_changed_within_1km_boundary':float((changed&near_boundary).sum()/changed.sum()),'share_of_changed_within_600m_water_or_ice':float((changed&near_wi).sum()/changed.sum())}

# Patch screening for the six largest non-diagonal transitions at 30 m.
top=[r for r in sorted([r for r in trows if r['from_class']!=r['to_class']],key=lambda r:r['pixel_count'],reverse=True)[:6]]
patchrows=[]; structure=np.ones((3,3),dtype=np.uint8)
for r in top:
    mask=valid&(a==r['from_class'])&(b==r['to_class']); lab,n=ndimage.label(mask,structure); sizes=np.bincount(lab.ravel())[1:]; areas=sizes*0.09
    patchrows.append({'transition':f"{r['from_name']}→{r['to_name']}",'screening_patch_count':int(n),'screening_area_km2':float(mask.sum()*0.09),'median_patch_km2':float(np.median(areas)) if n else 0,'largest_patch_km2':float(areas.max()) if n else 0,'share_area_patches_ge_1km2':float(areas[areas>=1].sum()/areas.sum()) if areas.sum() else 0,'note':'patch metrics use nearest-neighbor 300 m screening grid'})
with (OUT/'patch_screening_300m.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=patchrows[0].keys()); w.writeheader(); w.writerows(patchrows)

# State summary exact.
total=sum(states.values()); srows=[]
for k,n in states.items(): srows.append({'state':k,'pixel_count':n,'area_km2':n*0.0009,'share_valid_area':n/total})
with (OUT/'change_stability_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=srows[0].keys()); w.writeheader(); w.writerows(srows)

# Simple figures.
FONT='/System/Library/Fonts/STHeiti Medium.ttc'; ft=lambda n:ImageFont.truetype(FONT,n,index=0)
colors={0:(249,249,246),1:(216,218,211),2:(224,151,61),3:(190,64,58),4:(112,74,143)}; rgb=np.empty((*screen.shape,3),dtype=np.uint8)
for k,v in colors.items(): rgb[screen==k]=v
mapim=Image.fromarray(rgb).resize((1800,round(1800*H/W)),Image.Resampling.NEAREST); im=Image.new('RGB',(1940,mapim.height+240),'white'); d=ImageDraw.Draw(im); title='2015—2025变化稳定性内部核查'; bb=d.textbbox((0,0),title,font=ft(36)); d.text(((1940-bb[2])/2,25),title,font=ft(36),fill=(35,35,35)); im.paste(mapim,(70,100)); d.rectangle((70,100,1870,100+mapim.height),outline=(60,60,60))
legend=[(1,'未变化'),(2,'2025反转回2015类别'),(3,'2020变化后保持'),(4,'持续或其他变化')]; x=160;y=im.height-85
for k,s in legend: d.rectangle((x,y,x+28,y+28),fill=colors[k]); d.text((x+40,y-1),s,font=ft(18),fill=(45,45,45)); x+=410
im.save(OUT/'figures/change_stability_map.png',dpi=(300,300),optimize=True); im.save(OUT/'figures/change_stability_map.pdf',resolution=300)

# Contribution bars: largest losses and gains.
sel=trows[:6]+trows[-6:]; Wc,Hc=1800,960; im=Image.new('RGB',(Wc,Hc),'white'); d=ImageDraw.Draw(im); title='2015—2020主要转移的碳储量贡献'; bb=d.textbbox((0,0),title,font=ft(34)); d.text(((Wc-bb[2])/2,25),title,font=ft(34),fill=(35,35,35)); cx=920; d.line((cx,110,cx,870),fill=(60,60,60),width=2); vmax=max(abs(r['carbon_contribution_MtC']) for r in sel); bh=54
for i,r in enumerate(sel):
    y=120+i*62; v=r['carbon_contribution_MtC']; length=700*abs(v)/vmax; col=(193,66,58) if v<0 else (52,138,96); d.rectangle((cx-length if v<0 else cx,y,cx if v<0 else cx+length,y+bh-8),fill=col); lab=f"{r['from_name']}→{r['to_name']}  {v:+.2f} Mt C"; tw=d.textbbox((0,0),lab,font=ft(17))[2]; d.text((cx-length-tw-12 if v<0 else cx+length+12,y+8),lab,font=ft(17),fill=(40,40,40))
im.save(OUT/'figures/transition_carbon_contributions.png',dpi=(300,300),optimize=True); im.save(OUT/'figures/transition_carbon_contributions.pdf',resolution=300)

report={'exact_30m':{'states':states,'total_valid_pixels':total,'total_valid_area_km2':total*0.0009,'reversal_share_of_2015_2020_changed':states['reversal_to_2015']/(states['reversal_to_2015']+states['persistent_2020']+states['continued_change'])},'screening_300m':edge_stats,'top_loss_transitions':trows[:8],'top_gain_transitions':list(reversed(trows[-8:])),'patch_screening':patchrows}
(OUT/'audit_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
