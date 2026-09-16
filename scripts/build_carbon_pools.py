import csv, json
from pathlib import Path

OUT=Path('outputs/carbon_parameters'); OUT.mkdir(parents=True,exist_ok=True)
names={1:'耕地',2:'森林',3:'灌木',4:'草地',5:'水体',6:'冰雪',7:'裸地',8:'不透水面',9:'湿地'}
# Main parameters in t C/ha. Direct Sanjiangyuan values are used where available.
baseline={
 1:(1.02,6.15,90.48,3.30),  # negligible mapped area; alpine-grass proxy
 2:(11.08,30.30,143.82,6.71),
 3:(1.49,21.10,98.18,3.67),
 4:(1.02,6.15,90.48,3.30),
 5:(0,0,0,0),                # open-water column only; sediments excluded
 6:(0,0,0,0),                # permanent snow/ice; no transferable terrestrial pool
 7:(0.34,0,28.44,0),         # values from source's combined snow/ice/bare class assigned to bare land
 8:(0,0,0,0),
 9:(1.02,6.15,117.27,3.30),  # grass biomass proxy + regional-study aquatic/wet-soil value
}
scenarios={
 'baseline_terrestrial':baseline,
 'include_lake_sediment':{**baseline,5:(0,0,117.27,0)},
 'literal_combined_class':{**baseline,5:(0,0,117.27,0),6:(0.34,0,28.44,0)},
}
notes={
 1:('proxy','CLCD mapped area is negligible; grassland proxy avoids an unsupported high cropland value.'),
 2:('direct','Direct Sanjiangyuan National Park InVEST parameter.'),3:('direct','Direct Sanjiangyuan National Park InVEST parameter.'),4:('direct','Direct Sanjiangyuan National Park InVEST parameter.'),
 5:('decision','Baseline excludes sediment because CLCD water pixels describe surface water, while InVEST terrestrial carbon pools do not model sediment depth or burial.'),
 6:('split','Set to zero; the source combined snow/ice/bare value is attributed to sparse/bare soil rather than glacier surfaces.'),
 7:('split','Receives the source combined snow/ice/bare parameter because it contains the residual vegetation and soil carbon.'),
 8:('proxy','Set to zero; mapped area is one 30 m pixel and has no material influence.'),
 9:('proxy','Grassland biomass plus 117.27 t C/ha soil proxy; mapped area is negligible and regional studies support wetland SOC exceeding meadow SOC.'),
}
for scenario,data in scenarios.items():
    with (OUT/f'carbon_pools_{scenario}.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['lucode','c_above','c_below','c_soil','c_dead'])
        for k in range(1,10): w.writerow([k,*data[k]])
with (OUT/'parameter_mapping.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(['lucode','clcd_class_zh','baseline_c_above','baseline_c_below','baseline_c_soil','baseline_c_dead','evidence_level','treatment_note'])
    for k in range(1,10): w.writerow([k,names[k],*baseline[k],*notes[k]])

# Quantify sensitivity using the already validated area table.
with Path('outputs/clcd_clipped/clcd_area_by_class.csv').open(encoding='utf-8-sig') as f: rr=list(csv.DictReader(f))
area={(int(r['year']),int(r['class_value'])):float(r['area_km2']) for r in rr if int(r['class_value'])>0}
res=[]
for sn,data in scenarios.items():
    for year in [2005,2010,2015,2020,2025]:
        total=sum(area.get((year,k),0)*100*sum(data[k]) for k in range(1,10))
        res.append({'scenario':sn,'year':year,'carbon_stock_tC':round(total,3),'carbon_stock_MtC':round(total/1e6,6)})
with (OUT/'scenario_sensitivity_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=res[0].keys()); w.writeheader(); w.writerows(res)

method='''# 三江源 CLCD—InVEST 碳库参数说明

单位统一为 t C/ha（与 Mg C/ha 数值相同）。主来源为直接研究三江源国家公园、采用 CLCD 与 InVEST 四碳库框架的 2024 年研究。森林、灌木、草地直接采用其表 1；合并的“冰雪及裸地”被拆分处理。

## 关键决策

1. **冰雪与裸地拆分**：永久冰雪设为四碳库均为 0；原研究合并类别中的 0.34（地上）和 28.44（土壤）全部赋给裸地。理由是这些碳来自稀疏植被、裸土或冻土，而不是冰雪表面。另提供 `literal_combined_class` 情景，保留原论文把相同参数用于冰雪的做法，供敏感性比较。
2. **水体底泥碳**：主情景把水体四碳库设为 0。青藏高原湖泊沉积物确实是重要碳库，但沉积库存取决于岩芯深度和累积时间，不能用一个表面水体像元直接代表；InVEST Carbon 也不模拟沉积埋藏过程。`include_lake_sediment` 情景单独采用原研究的 117.27 t C/ha，用来量化这一假设的影响。
3. **湿地**：采用草地生物量参数，并以 117.27 t C/ha 作为土壤代理。区域观测表明高寒湿地 SOC 高于草甸。CLCD 中湿地面积不足 0.001%，因此该代理不会实质改变区域总量，但保留以满足类别完整性。
4. **耕地与不透水面**：两类在裁剪区中分别只有约 0.005 km² 和 0.0009 km²。耕地用草地代理，不透水面设 0，并标为低置信度；二者对总量影响可忽略。

## 推荐用法

正式主结果使用 `carbon_pools_baseline_terrestrial.csv`。把 `include_lake_sediment` 作为水体底泥敏感性结果；把 `literal_combined_class` 作为复现原论文合并类别逻辑的上界检查。不要把湖泊沉积物库存变化解释为 5 年期净碳汇。

## 来源

- 直接参数：*Estimation of carbon stock and economic value of Sanjiangyuan National Park, China*（Ecological Indicators, 2024），Table 1。
- 水体处理依据：青藏高原 24 个湖泊岩芯研究显示沉积碳库存与长期埋藏率高度依赖时间尺度和区域条件，不能直接等同于水面 LULC 的固定土壤碳。
- 湿地判断依据：三江源高寒湿地—草甸转换研究显示湿地土壤 SOC 与 SOC 密度显著高于草甸。
- 格式要求：InVEST Carbon Storage and Sequestration 用户指南；每个 LULC 代码必须有完整的 `c_above/c_below/c_soil/c_dead` 数值。
'''
(OUT/'README_carbon_parameters.md').write_text(method,encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
