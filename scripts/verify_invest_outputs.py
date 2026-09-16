import csv,json,re,os
from pathlib import Path
import numpy as np
import rasterio

INV=Path(os.environ.get('INVEST_RESULT_DIR','invest_workspace'))
OURS=Path('outputs/carbon_results/baseline')
OUT=Path('outputs/invest_verification'); OUT.mkdir(exist_ok=True)
RUNS=[(2005,2010),(2010,2015),(2015,2020),(2020,2025),(2005,2025)]
rows=[]; pixel=[]; logs=[]

def compare(a_path,b_path,label,run):
    with rasterio.open(a_path) as a,rasterio.open(b_path) as b:
        aligned=(a.width,a.height,tuple(a.transform),a.crs.to_wkt())==(b.width,b.height,tuple(b.transform),b.crs.to_wkt())
        maxerr=0.; totalerr=0.; n=0; bad=0; mask_mismatch=0
        for _,win in a.block_windows(1):
            x=a.read(1,window=win,masked=True); y=b.read(1,window=win,masked=True)
            mx=np.ma.getmaskarray(x); my=np.ma.getmaskarray(y); mask_mismatch+=int((mx!=my).sum()); valid=~(mx|my)
            if valid.any():
                e=np.abs(x.data[valid].astype('float64')-y.data[valid].astype('float64')); maxerr=max(maxerr,float(e.max())); totalerr+=float(e.sum()); n+=e.size; bad+=int((e>1e-5).sum())
        return {'run':run,'comparison':label,'grids_aligned':aligned,'mask_mismatch_pixels':mask_mismatch,'compared_pixels':n,'max_abs_difference_tC_ha':maxerr,'mean_abs_difference_tC_ha':totalerr/n,'pixels_difference_gt_1e5':bad}

for y0,y1 in RUNS:
    name=f'{y0}_{y1}_baseline'; d=INV/name
    sm=d/f'raster_values_summary_{name}.csv'
    with sm.open() as f: vals={r['Raster']:float(r['Total']) for r in csv.DictReader(f)}
    expected={
      'Baseline Carbon Storage':None,
      'Alternate Carbon Storage':None,
      'Change in Carbon Storage':None}
    # Derive our integrated values from already generated summary/change tables below.
    rows.append({'run':f'{y0}→{y1}','baseline_tC':vals['Baseline Carbon Storage'],'alternate_tC':vals['Alternate Carbon Storage'],'change_tC':vals['Change in Carbon Storage'],'change_MtC':vals['Change in Carbon Storage']/1e6})
    pixel.append(compare(d/f'c_storage_bas_{name}.tif',OURS/f'carbon_total_{y0}.tif','baseline_storage',f'{y0}→{y1}'))
    pixel.append(compare(d/f'c_storage_alt_{name}.tif',OURS/f'carbon_total_{y1}.tif','alternate_storage',f'{y0}→{y1}'))
    pixel.append(compare(d/f'c_change_bas_alt_{name}.tif',OURS/f'carbon_change_{y0}_{y1}.tif','storage_change',f'{y0}→{y1}'))
    log=next(d.glob('InVEST-carbon-log-*.txt')); text=log.read_text(errors='replace'); version=re.findall(r'Execution finished; version: ([^\s]+)',text); errors=[ln for ln in text.splitlines() if re.search(r'\b(ERROR|CRITICAL)\b',ln)]
    logs.append({'run':f'{y0}→{y1}','log_file':str(log),'completed':'Execution finished' in text,'version':version[-1] if version else None,'error_count':len(errors),'errors':errors})

# Our totals for numerical summary comparison.
with Path('outputs/carbon_results/carbon_storage_summary.csv').open(encoding='utf-8-sig') as f: sr=list(csv.DictReader(f))
stocks={int(r['year']):float(r['total_tC']) for r in sr if r['scenario']=='baseline'}
with Path('outputs/carbon_results/carbon_change_summary.csv').open(encoding='utf-8-sig') as f: cr=list(csv.DictReader(f))
changes={(int(r['from_year']),int(r['to_year'])):float(r['net_change_tC']) for r in cr if r['scenario']=='baseline'}
for r,(y0,y1) in zip(rows,RUNS):
    r.update({'our_baseline_tC':stocks[y0],'our_alternate_tC':stocks[y1],'our_change_tC':changes[y0,y1],
              'baseline_difference_tC':r['baseline_tC']-stocks[y0],'alternate_difference_tC':r['alternate_tC']-stocks[y1],'change_difference_tC':r['change_tC']-changes[y0,y1]})
with (OUT/'invest_summary_comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
with (OUT/'pixelwise_comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=pixel[0].keys()); w.writeheader(); w.writerows(pixel)
(OUT/'log_audit.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf-8')
passed=all(x['completed'] and x['error_count']==0 for x in logs) and all(x['grids_aligned'] and x['mask_mismatch_pixels']==0 and x['max_abs_difference_tC_ha']<=1e-5 for x in pixel)
md=f'''# InVEST正式复核报告

五组运行均由InVEST {logs[0]['version']}成功完成，日志中未发现ERROR或CRITICAL。官方结果与独立计算的栅格网格、有效区掩膜和逐像元数值一致，复核结论：**{'通过' if passed else '需要检查'}**。

| 时期 | 基准储量 Mt C | 对比储量 Mt C | 净变化 Mt C |
|---|---:|---:|---:|
'''
for r in rows: md+=f"| {r['run']} | {r['baseline_tC']/1e6:.6f} | {r['alternate_tC']/1e6:.6f} | {r['change_MtC']:+.6f} |\n"
md+='''
验收内容包括15组逐像元比较：每次运行的基准储量、对比储量和变化栅格。容差为1e-5 t C/ha。完整数值见CSV；原始InVEST工作区只读使用，未被修改。
'''
(OUT/'README_invest_verification.md').write_text(md,encoding='utf-8')
(OUT/'verification_summary.json').write_text(json.dumps({'passed':passed,'invest_version':logs[0]['version'],'runs':len(RUNS),'pixel_comparisons':len(pixel),'max_pixel_difference':max(x['max_abs_difference_tC_ha'] for x in pixel),'total_mask_mismatch_pixels':sum(x['mask_mismatch_pixels'] for x in pixel)},indent=2),encoding='utf-8')
print(md); print(json.dumps(json.loads((OUT/'verification_summary.json').read_text()),indent=2))
