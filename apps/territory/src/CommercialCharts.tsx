import {useState} from "react";
const sourceNames:any={chains:"Cadenas",distribution:"Distribución",closeup:"Close-Up / seguimiento"};
const metricNames:any={inventory:"Inventario",rotation:"Rotación",distribution:"Distribución",sales:"Ventas",mov:"MOV de origen"};
const unitNames:any={COP:"COP",units:"unidades",source_mov:"MOV · unidad por validar"};
export function CommercialCharts({series}:{series:any[]}){
 const [selectedSource,setSource]=useState("chains"),[selectedPeriod,setPeriod]=useState(""),[selectedMeasure,setMeasure]=useState("");
 if(!series.length)return null;
 const sources=[...new Set(series.map(r=>r.source))];
 const source=sources.includes(selectedSource)?selectedSource:sources[0];
 const scoped=series.filter(r=>r.source===source);
 const periods=[...new Set(scoped.map(r=>r.period))].sort().reverse();
 const period=periods.includes(selectedPeriod)?selectedPeriod:periods[0];
 const measures=[...new Set(scoped.filter(r=>r.period===period).map(r=>r.metric+"|"+r.unit))];
 const measure=measures.includes(selectedMeasure)?selectedMeasure:measures[0];
 const rows=scoped.filter(r=>r.period===period&&r.metric+"|"+r.unit===measure).sort((a,b)=>Math.abs(Number(b.value))-Math.abs(Number(a.value)));
 const unit=rows[0]?.unit, max=Math.max(1,...rows.map(r=>Math.abs(Number(r.value))));
 const observed=rows.reduce((a,r)=>a+r.observed,0), missing=rows.reduce((a,r)=>a+r.missing,0);
 const sum=rows.reduce((a,r)=>a+(r.value===null?0:Number(r.value)),0);
 return <section className="mg-card commercial-charts">
  <header><p className="mg-eyebrow">CORTE COMERCIAL · COMPARACIÓN DE MARCAS</p><h2>La misma medida. Un contexto claro.</h2><p>Compara dentro de una fuente y un mes. Las visitas, el dinero y las unidades mantienen sus propias escalas.</p></header>
  <div className="commercial-selects"><label>Fuente del gráfico<select value={source} onChange={e=>{setSource(e.target.value);setPeriod("");setMeasure("")}}>{sources.map(x=><option key={x} value={x}>{sourceNames[x]}</option>)}</select></label><label>Mes del corte<select value={period} onChange={e=>{setPeriod(e.target.value);setMeasure("")}}>{periods.map(x=><option key={x}>{x}</option>)}</select></label><label>Medida del gráfico<select value={measure} onChange={e=>setMeasure(e.target.value)}>{measures.map(x=>{const [m,u]=x.split("|");return <option key={x} value={x}>{metricNames[m]} · {unitNames[u]}</option>})}</select></label></div>
  <div className="commercial-totals"><div><span>Total observado</span><strong>{observed?sum.toLocaleString("es-CO"):"Sin dato"}</strong><small>{unitNames[unit]}</small></div><div><span>Registros con dato</span><strong>{observed.toLocaleString("es-CO")}</strong><small>del corte seleccionado</small></div><div><span>Valores no informados</span><strong>{missing.toLocaleString("es-CO")}</strong><small>Se excluyen de la suma; no son ceros.</small></div></div>
  <div className="commercial-bars" role="img" aria-label={"Comparación por marca: "+sourceNames[source]+", "+period+", "+measure}>{rows.map(r=><div key={r.brand}><div><b>{r.brand}</b><span>{r.value===null?"Sin dato":Number(r.value).toLocaleString("es-CO")} {unitNames[r.unit]}</span></div><div className="commercial-track"><i style={{width:(Math.abs(Number(r.value))/max*100)+"%",background:Number(r.value)<0?"#ad634d":undefined}}/></div><small>{r.observed} con dato · {r.missing} sin dato</small></div>)}</div>
  <p className="lp-meta">Valores del archivo, no existencias en vivo. El tamaño de las barras representa magnitud; los ajustes negativos conservan su signo. No mide efectos causales de las visitas.</p>
 </section>
}
