const state={year:2025,layer:'lulc',park:'all'};let data;
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const classColors={Cropland:'#f3df8a',Forest:'#287a3c',Shrub:'#6bb545',Grassland:'#b7df6d',Water:'#4f9ed6','Snow/Ice':'#d8f2fa',Barren:'#caa879',Impervious:'#d73a32',Wetland:'#8665a8'};
const classZh={Cropland:'耕地',Forest:'森林',Shrub:'灌丛',Grassland:'草地',Water:'水体','Snow/Ice':'冰雪',Barren:'裸地',Impervious:'不透水面',Wetland:'湿地'};
const parkSlugs={'澜沧江园区':'lancang','长江源园区':'changjiang','黄河源园区':'huanghe'};
const fmt=(v,n=1)=>Number(v).toLocaleString('zh-CN',{minimumFractionDigits:n,maximumFractionDigits:n});

fetch('./assets/dashboard-data.json').then(r=>r.json()).then(d=>{data=d;init();render()}).catch(()=>{$('#mapTitle').textContent='数据加载失败，请刷新页面'});
function init(){
  data.years.forEach((y,i)=>{const s=document.createElement('span');s.textContent=y;$('#yearTicks').append(s)});
  [...new Set(data.parks.map(d=>d.park))].forEach(p=>{const o=document.createElement('option');o.value=p;o.textContent=p;$('#parkSelect').append(o)});
  $$('.segmented button').forEach(b=>b.onclick=()=>{state.layer=b.dataset.layer;$$('.segmented button').forEach(x=>x.classList.toggle('active',x===b));renderMap()});
  $('#yearSlider').oninput=e=>{state.year=data.years[+e.target.value];render()};
  $('#parkSelect').onchange=e=>{state.park=e.target.value;render()};
}
function render(){renderMap();renderMetrics();renderCarbonChart();renderBars();renderTransitions()}
function selectedCarbon(){
  if(state.park==='all')return data.timeSeries.find(d=>d.year===state.year).carbon_stock_MtC;
  return data.parks.find(d=>d.park===state.park&&d.year===state.year).carbon_stock_MtC;
}
function selectedArea(){return state.park==='all'?data.meta.areaKm2:data.parks.find(d=>d.park===state.park&&d.year===state.year).area_km2}
function previousYear(){const i=data.years.indexOf(state.year);return i?data.years[i-1]:null}
function renderMap(){
  const forecast=state.year>=2030,b=$('#periodBadge');b.textContent=forecast?'BAU预测':'历史观测';b.className='badge '+(forecast?'forecast':'observed');
  let src,title,legend='';
  if(state.layer==='lulc'){src=`./assets/lulc-${state.year}.png`;title=`${state.year} 土地覆盖`;legend=Object.entries(classColors).map(([k,c])=>`<span><i style="background:${c}"></i>${classZh[k]}</span>`).join('')}
  else if(state.layer==='carbon'){src=`./assets/carbon-${state.year}.png`;title=`${state.year} 碳储量`;legend='<span><i style="background:#f4f7dc"></i>低</span><span><i style="background:#1e8860"></i>高 · Mg C/ha</span>'}
  else{const p=previousYear();if(!p){state.year=2010;$('#yearSlider').value=1;return render()}src=`./assets/change-${p}-${state.year}.png`;title=`${p}—${state.year} 碳变化`;legend='<span><i style="background:#c44c43"></i>碳损失</span><span><i style="background:#f5efca"></i>稳定</span><span><i style="background:#23865b"></i>碳增加</span>'}
  $('#mapTitle').textContent=title;$('#mapImage').src=src;$('#mapImage').alt=title+'地图';$('#mapLegend').innerHTML=legend;
  const overlay=$('#parkOverlay');
  if(state.park==='all'){overlay.classList.remove('active');overlay.removeAttribute('src')}
  else{overlay.src=`./assets/park-${parkSlugs[state.park]}.png`;overlay.classList.add('active')}
}
function renderMetrics(){
  const y=state.year,total=selectedCarbon(),py=previousYear();let prev=null;
  if(py)prev=state.park==='all'?data.timeSeries.find(d=>d.year===py).carbon_stock_MtC:data.parks.find(d=>d.park===state.park&&d.year===py).carbon_stock_MtC;
  $('#carbonValue').textContent=fmt(total,1);$('#carbonDelta').textContent=prev==null?'基准年份':`${total-prev>=0?'+':''}${fmt(total-prev,2)} Mt C / 上一期`;
  $('#areaValue').textContent=fmt(selectedArea(),0);
  const rows=data.classes.filter(d=>d.year===y).sort((a,b)=>b.area_km2-a.area_km2),top=rows[0];$('#dominantClass').textContent=classZh[top.class_name];$('#dominantShare').textContent=`${fmt(top.area_percent,1)}%`;$('#dominantArea').textContent=`${fmt(top.area_km2,0)} km²`;
}
function renderCarbonChart(){
  const rows=state.park==='all'?data.timeSeries:data.parks.filter(d=>d.park===state.park).map(d=>({year:d.year,carbon_stock_MtC:d.carbon_stock_MtC}));
  const svg=$('#carbonChart'),W=760,H=300,p={l:58,r:20,t:25,b:40},vals=rows.map(d=>d.carbon_stock_MtC),min=Math.min(...vals)-4,max=Math.max(...vals)+4;
  const x=y=>p.l+(y-2005)/30*(W-p.l-p.r),Y=v=>H-p.b-(v-min)/(max-min)*(H-p.t-p.b);let s='';
  for(let i=0;i<4;i++){const v=min+(max-min)*i/3,yy=Y(v);s+=`<line class="chart-grid" x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}"/><text class="chart-label" x="${p.l-9}" y="${yy+4}" text-anchor="end">${fmt(v,0)}</text>`}
  s+=`<line x1="${x(2025)}" y1="${p.t}" x2="${x(2025)}" y2="${H-p.b}" stroke="#a9b7b4" stroke-dasharray="4 4"/>`;
  const hist=rows.filter(d=>d.year<=2025),future=rows.filter(d=>d.year>=2025),pts=a=>a.map(d=>`${x(d.year)},${Y(d.carbon_stock_MtC)}`).join(' ');
  s+=`<polyline points="${pts(hist)}" fill="none" stroke="#126c62" stroke-width="4"/><polyline points="${pts(future)}" fill="none" stroke="#d8902f" stroke-width="4" stroke-dasharray="8 5"/>`;
  rows.forEach(d=>{const active=d.year===state.year;s+=`<circle data-year="${d.year}" data-value="${d.carbon_stock_MtC}" cx="${x(d.year)}" cy="${Y(d.carbon_stock_MtC)}" r="${active?7:5}" fill="${d.year<=2025?'#126c62':'#d8902f'}" stroke="white" stroke-width="2"/><text class="chart-label" x="${x(d.year)}" y="${H-16}" text-anchor="middle">${d.year}</text>`});svg.innerHTML=s;
  svg.querySelectorAll('circle').forEach(c=>{c.onmouseenter=e=>tip(e,`${c.dataset.year} · ${fmt(c.dataset.value,2)} Mt C`);c.onmouseleave=hideTip;c.onclick=()=>{state.year=+c.dataset.year;$('#yearSlider').value=data.years.indexOf(state.year);render()}})
}
function renderBars(){
  const rows=data.classes.filter(d=>d.year===state.year).sort((a,b)=>b.area_km2-a.area_km2),max=Math.max(...rows.map(d=>d.area_km2));$('#classChartTitle').textContent=`${state.year} 地类面积`;
  $('#classBars').innerHTML=rows.filter(d=>d.area_km2>0).map(d=>`<div class="bar-row"><span>${classZh[d.class_name]}</span><div class="bar-track"><div class="bar-fill" style="width:${d.area_km2/max*100}%;background:${classColors[d.class_name]}"></div></div><span class="bar-value">${fmt(d.area_km2,0)}</span></div>`).join('')
}
function renderTransitions(){
  const end=state.year===2005?2010:state.year,start=end===2010?2005:data.years[data.years.indexOf(end)-1];$('#transitionTitle').textContent=`${start}—${end} 主要转移`;
  const rows=data.transitions.filter(d=>d.start_year===start&&d.end_year===end).sort((a,b)=>Math.abs(b.carbon_change_MtC)-Math.abs(a.carbon_change_MtC)).slice(0,6);
  $('#transitionList').innerHTML=rows.map(d=>`<div class="transition-row"><b>${classZh[d.origin_name]} → ${classZh[d.destination_name]}</b><span>${fmt(d.area_km2,0)} km²</span><span class="${d.carbon_change_MtC>=0?'gain':'loss'}">${d.carbon_change_MtC>=0?'+':''}${fmt(d.carbon_change_MtC,2)} Mt C</span></div>`).join('')||'<p>该时期没有可显示的主要转移。</p>'
}
function tip(e,text){const t=$('#tooltip');t.textContent=text;t.style.left=e.clientX+'px';t.style.top=e.clientY+'px';t.style.opacity=1}function hideTip(){$('#tooltip').style.opacity=0}
