import csv,json
from pathlib import Path
import numpy as np
import rasterio
from scipy import ndimage

ROOT=Path('outputs/anomaly_audit')
with rasterio.open(ROOT/'change_stability_screening_300m.tif') as s:
    a=s.read(1); p=s.profile.copy()
rob=a.copy(); mask=a==3; lab,n=ndimage.label(mask,np.ones((3,3),dtype=np.uint8)); sizes=np.bincount(lab.ravel()); large=np.zeros(len(sizes),dtype=bool); large[sizes>=12]=True
rob[mask]=3; rob[mask&large[lab]]=4; rob[a==4]=5
p.update(dtype='uint8',nodata=0,compress='LZW')
with rasterio.open(ROOT/'robust_change_screening_300m.tif','w',**p) as d:
    d.write(rob,1); d.update_tags(classes='1 unchanged; 2 reversal; 3 persistent patch <1 km2; 4 persistent patch >=1 km2; 5 continued/other',purpose='screening only')

with (ROOT/'three_year_pathways_2015_2020_2025.csv').open(encoding='utf-8-sig') as f: paths=list(csv.DictReader(f))
def path_area(a,b,c=None):
    return sum(float(r['area_km2']) for r in paths if int(r['class_2015'])==a and int(r['class_2020'])==b and (c is None or int(r['class_2025'])==c))
report=json.loads((ROOT/'audit_report.json').read_text())
s=report['exact_30m']['states']; total=report['exact_30m']['total_valid_pixels']; changed=s['reversal_to_2015']+s['persistent_2020']+s['continued_change']
md=f'''# 三江源2015—2020历史异常变化内部核查

## 结论

2015—2020主情景碳储量减少23.18 Mt C，其中草地转裸地贡献−28.52 Mt C，是绝对主因；裸地转草地抵消了+6.82 Mt C。不能把全部草地转裸地直接解释为永久草地退化，因为2015—2020发生变化的像元中，{s['reversal_to_2015']/changed:.1%}在2025恢复为2015类别。

## 三期稳定性

- 三期始终不变：{s['unchanged']*0.0009:,.2f} km²，占研究区{s['unchanged']/total:.1%}。
- 2025反转回2015类别：{s['reversal_to_2015']*0.0009:,.2f} km²。
- 2020变化后保持到2025：{s['persistent_2020']*0.0009:,.2f} km²。
- 连续改变为第三种类别：{s['continued_change']*0.0009:,.2f} km²。

草地→裸地共3,951.14 km²，其中2,385.70 km²保持为裸地到2025，1,548.95 km²在2025返回草地。后者应视为年际分类波动或暂时状态，不作为永久退化证据。

## 空间与斑块诊断

- 仅2.86%的变化位于研究区边界1 km范围，说明异常不主要由裁剪边界造成。
- 约20.20%的变化靠近水体或冰雪600 m范围，这部分容易受到岸线、水位和积雪年际差异影响。
- 300 m筛查尺度下，草地→裸地形成18,400个斑块，中位斑块只有0.09 km²；约25.66%的面积属于≥1 km²连续斑块。大量细碎变化不宜逐像元进行生态解释。
- 同时存在最大136.35 km²的连续草地→裸地斑块，说明结果并非全部由椒盐噪声构成，仍有需要进一步关注的持续变化区。

## 推荐口径

1. 历史总量计算仍保留原始30 m CLCD，不删除任何像元。
2. 空间解释优先采用“2020变化后持续到2025”的区域。
3. 高置信度热点再要求300 m筛查尺度连续面积≥1 km²。
4. 反转像元、湖岸/冰雪边缘和小斑块标注为低置信度，不直接称为退化或恢复。
5. 本检查属于数据内部一致性核查，不能替代独立遥感影像或实地验证。

## 文件说明

- `transition_carbon_contributions_2015_2020.csv`：各转移类型对碳变化的精确贡献。
- `three_year_pathways_2015_2020_2025.csv`：2015→2020→2025完整路径。
- `change_stability_summary.csv`：稳定、反转和持续变化面积。
- `patch_screening_300m.csv`：主要转移斑块诊断。
- `change_stability_screening_300m.tif`：变化稳定性地图。
- `robust_change_screening_300m.tif`：加入≥1 km²斑块门槛的稳健筛查图。
'''
(ROOT/'README_anomaly_audit.md').write_text(md,encoding='utf-8')
print(md)
