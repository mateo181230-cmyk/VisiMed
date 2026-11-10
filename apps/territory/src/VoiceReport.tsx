import React, {useEffect,useState,useRef} from 'react';
import {api,ApiError,db,send,flush,type User} from './api';
import './voice-report.css';
import {BrowserVoice} from './BrowserVoice';
const empty={schema_version:'snc-1',products:[],referrals:null,commitments:null,not_attended_reason:null};
const status:any={achieved:'Logrado',partial:'Parcial',not_achieved:'No logrado',unknown:'No informado'};
export function VoiceReport({id,user}:{id:string,user:User}) {
 const [data,setData]=useState<any>(null),[draft,setDraft]=useState<any>(empty),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false);
 const dirtyRef=useRef(false);
 const key=user.id+':voice:'+id;
 const load=async()=>{
  try {const d=await api('/visit-reports/'+id);setData(d);await db.snapshots.put({id:key,data:d});if(!dirtyRef.current)setDraft(d.structured||empty);}
  catch(e:any){if(e instanceof ApiError){setData(null);setError(e.message);return}const cached=await db.snapshots.get(key);if(cached){setData(cached.data);if(!dirtyRef.current)setDraft(cached.data.structured||empty);setNotice('Copia del celular. Los cambios se enviarán al recuperar conexión.');}else setError(e.message);}
 };
 useEffect(()=>{load();},[id]);
 useEffect(()=>{const timer=setInterval(()=>{if(!dirtyRef.current)load();},12000);return()=>clearInterval(timer);},[id]);
 useEffect(()=>{if(dirty)db.snapshots.put({id:key+':draft',data:draft});},[draft,dirty]);
 useEffect(()=>{db.snapshots.get(key+':draft').then(x=>{if(x){setDraft(x.data);dirtyRef.current=true;setDirty(true);setNotice('Recuperamos los cambios que dejaste en este celular.');}});},[id]);
 const change=(x:any)=>{setDraft(x);dirtyRef.current=true;setDirty(true);setNotice('Cambios guardados en este celular.');};
 const product=(i:number,patch:any)=>{const old=draft.products[i].name;change({...draft,products:draft.products.map((p:any,n:number)=>n===i?{...p,...patch}:p),referrals:draft.referrals?.map((r:any)=>({...r,products:r.products?.map((n:string)=>patch.name!==undefined&&n===old?patch.name:n)}))??draft.referrals});};
 const save=async(confirm:boolean)=>{
  setError('');setBusy(true);
  try{
   const now=new Date().toISOString();const make=(type:string,payload:any)=>({event_id:crypto.randomUUID(),type,visit_id:id,device_ts:now,app_version:'voice-snc-v1',payload});
   const events=[make('snc_report_submitted',{value:JSON.stringify(draft),confirm,expected_version:data.version})];
   let device=localStorage.getItem('voice-device');if(!device){device=crypto.randomUUID();localStorage.setItem('voice-device',device);}
   const r=await send(user,'voice.report.sync',{device_id:device,sent_at:now,outbox_pending:events.length,events});
   if(r.queued){setNotice('Pendiente de sincronizar. Conservamos tu reporte y confirmación en este celular.');}
   else{await db.snapshots.delete(key+':draft');dirtyRef.current=false;setDirty(false);setNotice(confirm?'Resumen confirmado. Los campos no informados siguen visibles.':'Borrador guardado.');const d=await api('/visit-reports/'+id);setData(d);setDraft(d.structured||empty);}
  }catch(e:any){setError(e.message);}finally{setBusy(false);}
 };
 return <main className="voice-report">
  <a href={'/visitas/'+id}>← Volver a la visita</a><span className="voice-eyebrow">VISIMED · REPORTE DE VISITA</span>
  <h1>{data?.doctor||'Reporte de voz'}</h1>
  <p className="voice-intro">Una conversación de hasta 5 minutos. Revisa lo que ocurrió y completa únicamente lo que falte.</p>
  {error&&<p role="alert" className="voice-error">{error}</p>}{notice&&<p role="status" className="voice-notice">{notice}</p>}
  {!data?<button onClick={load}>Volver a cargar</button>:<>
  {user.role==='rep'&&<BrowserVoice visitId={id} confirmed={data.status==='confirmed'} enabled={!!data.visit_finished&&data.status!=='confirmed'} onSaved={load}/>}
  <div className="voice-state"><b>{data.status==='confirmed'?'Confirmado':!data.visit_finished?'Visita pendiente':'Por revisar'}</b><span>{data.duration_s!=null?`${Math.floor(data.duration_s/60)}:${String(data.duration_s%60).padStart(2,'0')} de conversación`:'Todavía no hay llamada procesada'}</span></div>
  {data.pending_since&&data.status!=="confirmed"&&<p className="voice-notice">Pendiente de completar. Tu evidencia sigue guardada; puedes continuar y confirmar sin perderla.</p>}
  {!data.visit_finished&&<p>El reporte se habilita al terminar la visita. <a href={'/visitas/'+id}>Ir a la visita</a></p>}
  {data.call_failure_reason==='provider_billing'&&<p role="alert" className="voice-error">El proveedor de voz está pendiente de habilitación por facturación. Puedes completar el reporte por escrito aquí.</p>}
  {data.call_failure_reason==='voicemail'&&<p role="status" className="voice-notice">La llamada llegó al buzón. Puedes completar esta visita aquí con «Hablar con UNO» o por escrito.</p>}
  {data.call_status==='failed'&&data.call_failure_reason!=='voicemail'&&data.call_failure_reason!=='provider_billing'&&<p role="status" className="voice-notice">La llamada telefónica no pudo completarse. Tu visita sigue guardada: usa «Hablar con UNO» en este celular o completa el informe por escrito.</p>}
  {!data.structured&&<p>Este reporte aún no tiene el detalle por producto. Puedes completarlo aquí o <a href={'/visitas/'+id}>abrir la visita original</a>.</p>}
  <fieldset disabled={!data.editable||busy}>
  <datalist id="snc-brands">{data.catalogue?.map((p:any)=><option key={p.id} value={p.name}/>)}</datalist>
  {data.brand_issues?.length>0&&<p role="alert" className="voice-error">Hay marcas sin identificar. Selecciona el nombre del catálogo antes de confirmar; el resto del relato está guardado.</p>}
  <h2>1. Productos, objetivos y resultados</h2>
  {draft.products.map((p:any,i:number)=><section className="voice-product" key={i}>
   <header><span>{p.position??"?"}</span><label>Producto presentado<input list="snc-brands" value={p.name} onChange={e=>product(i,{name:e.target.value})}/></label><button type="button" aria-label={'Quitar producto '+(i+1)} onClick={()=>change({...draft,products:draft.products.filter((_:any,n:number)=>n!==i).map((x:any,n:number)=>({...x,position:x.position==null?null:n+1}))})}>×</button></header>
   <label>Orden real<select value={p.position??""} onChange={e=>product(i,{position:e.target.value?Number(e.target.value):null})}><option value="">No confirmado</option>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n}</option>)}</select></label><label>¿Qué buscabas lograr?<textarea value={p.objective||''} onChange={e=>product(i,{objective:e.target.value||null})}/></label>
   <details><summary>Medida y plazo del objetivo</summary>{p.due_text&&<p>Plazo mencionado: {p.due_text}</p>}<label>Medida<input value={p.metric||''} onChange={e=>product(i,{metric:e.target.value||null})}/></label><div className="voice-grid"><label>Meta<input type="number" min="0" value={p.target??''} onChange={e=>product(i,{target:e.target.value===''?null:Number(e.target.value)})}/></label><label>Unidad<input value={p.unit||''} onChange={e=>product(i,{unit:e.target.value||null})}/></label><label>Fecha<input type="date" value={p.due_date||''} onChange={e=>product(i,{due_date:e.target.value||null})}/></label></div></details>
   <label>Resultado<select value={p.achievement} onChange={e=>product(i,{achievement:e.target.value})}>{Object.entries(status).map(([k,v]:any)=><option key={k} value={k}>{v}</option>)}</select></label>
   <label>¿Cómo lo sabes?<textarea value={p.evidence||''} onChange={e=>product(i,{evidence:e.target.value||null})}/></label>
   <label>Barreras (una por línea)<textarea value={p.barriers?.join('\n')||''} onChange={e=>product(i,{barriers:e.target.value?e.target.value.split('\n').filter(Boolean):null})}/></label>
   <label className="voice-check"><input type="checkbox" checked={Array.isArray(p.barriers)&&p.barriers.length===0} onChange={e=>product(i,{barriers:e.target.checked?[]:null})}/>Confirmo que no hubo barreras</label>
  </section>)}
  {draft.products.length<5&&!draft.not_attended_reason&&<button type="button" onClick={()=>change({...draft,products:[...draft.products,{position:draft.products.length+1,name:'',objective:null,metric:null,target:null,unit:null,due_date:null,achievement:'unknown',evidence:null,barriers:null}]})}>+ Agregar producto presentado</button>}
  <h2>2. Droguerías de destino</h2><p>No equivale a una venta ni confirma existencias.</p>
  <label>Una sede por línea<textarea value={draft.referrals?.map((r:any)=>r.destination).join('\n')||''} onChange={e=>change({...draft,referrals:e.target.value?e.target.value.split('\n').filter(Boolean).map((destination:string,i:number)=>({destination,products:draft.referrals?.[i]?.products||[]})):null})}/></label>
  {draft.referrals?.map((r:any,i:number)=><section className="voice-product" key={i}><strong>{r.destination}</strong><p>Productos direccionados a esta sede</p>{!r.products?.length&&<p>Marcas no informadas. Confírmalas antes de cerrar el reporte.</p>}{draft.products.filter((p:any)=>p.name).map((p:any)=><label className="voice-check" key={p.name}><input type="checkbox" checked={(r.products||[]).includes(p.name)} onChange={e=>change({...draft,referrals:draft.referrals.map((v:any,n:number)=>n===i?{...v,products:e.target.checked?[...(v.products||[]),p.name]:(v.products||[]).filter((name:string)=>name!==p.name)}:v)})}/>{p.name}</label>)}</section>)}
  <label className="voice-check"><input type="checkbox" checked={Array.isArray(draft.referrals)&&draft.referrals.length===0} onChange={e=>change({...draft,referrals:e.target.checked?[]:null})}/>No hubo direccionamiento</label>
  <h2>3. Compromisos para la próxima visita</h2><p>Al confirmar, estos compromisos se convierten en tareas de seguimiento. <a href="/territorio/?module=tasks">Ver pendientes</a></p>
  {draft.commitments?.map((c:any,i:number)=><section className="voice-product" key={i}><label>Responsable<select value={c.owner} onChange={e=>change({...draft,commitments:draft.commitments.map((x:any,n:number)=>n===i?{...x,owner:e.target.value}:x)})}><option value="doctor">Médico</option><option value="representative">Visitador</option><option value="unknown">No informado</option></select></label><label>Acción<textarea value={c.action} onChange={e=>change({...draft,commitments:draft.commitments.map((x:any,n:number)=>n===i?{...x,action:e.target.value}:x)})}/></label>{c.due_text&&<p>Plazo mencionado: {c.due_text}</p>}<label>Objetivo para el próximo encuentro<input value={c.next_objective||''} onChange={e=>change({...draft,commitments:draft.commitments.map((x:any,n:number)=>n===i?{...x,next_objective:e.target.value||null}:x)})}/></label><label>Fecha acordada<input type="date" value={c.due_date||''} onChange={e=>change({...draft,commitments:draft.commitments.map((x:any,n:number)=>n===i?{...x,due_date:e.target.value||null}:x)})}/></label><button onClick={()=>change({...draft,commitments:draft.commitments.filter((_:any,n:number)=>n!==i)})}>Quitar compromiso</button></section>)}
  <button onClick={()=>change({...draft,commitments:[...(draft.commitments||[]),{owner:'unknown',action:'',due_date:null,next_objective:null}]})}>+ Agregar compromiso</button>
  <label className="voice-check"><input type="checkbox" checked={Array.isArray(draft.commitments)&&draft.commitments.length===0} onChange={e=>change({...draft,commitments:e.target.checked?[]:null})}/>No quedaron compromisos</label>
  {!draft.products.length&&<label>Si la visita no se realizó, motivo<textarea value={draft.not_attended_reason||''} onChange={e=>change({...draft,not_attended_reason:e.target.value||null})}/></label>}
  <footer><button disabled={busy} onClick={()=>save(false)}>Guardar borrador</button><button className="voice-primary" disabled={busy} onClick={()=>save(true)}>Confirmar lo registrado</button></footer>
  </fieldset>
  {data.missing.length>0&&<details><summary>Información pendiente ({data.missing.length})</summary><ul>{data.missing.map((x:string)=><li key={x}>{x}</li>)}</ul></details>}
  <details><summary>Conversación y trazabilidad</summary><small>{data.agent_version?'Registro de UNO':'Sin extracción de voz'}</small>{data.transcript.map((t:any,i:number)=><p key={i}><b>{t.role==='agent'?'UNO':'Visitador'}:</b> {t.text}</p>)}</details>
  <a className="voice-primary" href={"/territorio/?module=brief&visit="+id}>Ver preparación y aprendizaje de esta visita</a>
  <button onClick={async()=>{await flush(user);await load();}}>Actualizar estado</button>
  </>}
 </main>;
}
