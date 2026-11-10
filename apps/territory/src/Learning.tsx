import { useEffect, useState } from "react";
import { BookOpen, CheckCircle2, Plus, Target, Trash2 } from "lucide-react";
import { api, ApiError, db, send, flush, type User } from "./api";
import "./learning.css";
import {StudyChat} from './Study';

export function LearningPanel({user,id}:{user:User;id:string}) {
  const [data,setData]=useState<any>(null),[objectives,setObjectives]=useState<any[]>([]),[error,setError]=useState(""),[note,setNote]=useState(""),[busy,setBusy]=useState(false);
  const [queued,setQueued]=useState(false),[reflection,setReflection]=useState("");
  const key=user.id+":learning:"+id;
  const show=(d:any)=>{setData(d);setObjectives(d.objectives);setReflection(d.reflection?.text||"");};
  async function load(){
    const pending=(await db.commands.where("actor_id").equals(user.id).toArray()).filter(x=>x.type.startsWith("learning.")&&x.payload.visit_id===id);
    setQueued(!!pending.length);
    const local=await db.snapshots.get(key);
    if(pending.length&&local){show(local.data);setNote("Hay cambios guardados en este celular pendientes de sincronización.");if(pending.some(x=>x.error))setError("La sincronización requiere revisión. Abre Mi ruta para revisar la operación pendiente.");return;}
    try {const d=await api("/learning/"+id);show(d);await db.snapshots.put({id:key,data:d});}
    catch(e){if(e instanceof ApiError){setData(null);setError(e.message);return}if(local){show({...local.data,cached:true});setNote("Última preparación guardada en este celular.");}else setError((e as Error).message);}
  }
  async function sync(){setBusy(true);try{await flush(user);await load();const pending=(await db.commands.where("actor_id").equals(user.id).toArray()).some(x=>x.type.startsWith("learning.")&&x.payload.visit_id===id);if(!pending){setNote("Cambios sincronizados con la visita.");setError("");}}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  useEffect(()=>{load();const reconnect=()=>sync();window.addEventListener("online",reconnect);return()=>window.removeEventListener("online",reconnect)},[id,user.id]);
  async function save(type:string,payload:any){setBusy(true);setError("");try{const r=await send(user,type,{visit_id:id,...payload},data.version);setNote(r.queued?"Guardado en este celular. Se enviará cuando sincronices.":"Guardado en la visita.");if(!r.queued)await load();else{setQueued(true);const d={...data,...(type==="learning.plan"?{objectives}:{}),...(type==="learning.reflection"?{reflection:{text:reflection}}:{})};await db.snapshots.put({id:key,data:d});}}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const edit=(i:number,k:string,v:string)=>setObjectives(objectives.map((o,n)=>n===i?{...o,[k]:v}:o));
  return <section className="learning-panel">
    {error&&<p role="alert" className="wf-error">{error}</p>}{note&&<p role="status" className="wf-note">{note}</p>}
    {queued&&<button disabled={busy} onClick={sync}>Sincronizar cambios guardados</button>}
    {data&&<>
      <header className="lp-title"><Target size={24}/><div><p className="wf-eyebrow">{data.mode==="feedback"?"DESPUÉS DE LA VISITA":data.mode==="awaiting_report"?"REPORTE PENDIENTE":"PREPARACIÓN POR MARCA"}</p><h2>{data.mode==="feedback"?"Lo que pasó. Lo que sigue.":data.mode==="awaiting_report"?"Conserva el resultado de tu visita.":"Una intención clara para cada marca."}</h2></div></header>
      {data.site&&<p>{data.site.name} · {data.site.address}</p>}
      {data.mode==="awaiting_report"&&<p className="wf-note">La visita terminó. <a href={"/territorio/?report="+id}>Confirma su reporte</a> para recibir feedback de esta conversación. Los resultados anteriores conservan su fecha de origen.</p>}
      {data.mode!=="feedback"&&<fieldset className="lp-objectives" disabled={!data.can_plan||busy||queued}>{objectives.map((o,i)=><article className="wf-card" key={i}>
        <div className="lp-row"><label>Marca<select value={o.product_id} onChange={e=>edit(i,"product_id",e.target.value)}><option value="">Selecciona</option>{data.catalogue.map((p:any)=><option key={p.id} value={p.id} disabled={objectives.some((x,j)=>j!==i&&x.product_id===p.id)}>{p.name}</option>)}</select></label><button aria-label="Quitar objetivo" onClick={()=>setObjectives(objectives.filter((_,j)=>j!==i))}><Trash2 size={18}/></button></div>
        <label>¿Qué quieres lograr con este médico?<textarea value={o.objective} maxLength={500} onChange={e=>edit(i,"objective",e.target.value)} placeholder="Resolver su duda sobre la evidencia de…"/></label>
        <label>¿Cómo sabrás que lo lograste?<input value={o.measure} maxLength={200} onChange={e=>edit(i,"measure",e.target.value)} placeholder="Responder las dos preguntas pendientes"/></label>
        <label>¿Para cuándo?<input value={o.due} maxLength={100} onChange={e=>edit(i,"due",e.target.value)} placeholder="Durante esta visita"/></label>
      </article>)}{data.can_plan&&<div className="wf-actions"><button disabled={objectives.length>=5||busy} onClick={()=>setObjectives([...objectives,{product_id:"",objective:"",measure:"",due:""}])}><Plus size={16}/> Añadir marca</button><button className="wf-primary" disabled={busy||objectives.some(o=>!o.product_id||o.objective.trim().length<8)} onClick={()=>save("learning.plan",{objectives})}>Guardar preparación</button></div>}</fieldset>}
      {!!data.products.length&&<><h3>{data.mode==="feedback"?"Resultado confirmado":"Última conversación confirmada"}</h3><p className="lp-meta">Fuente: visita del {new Date(data.source_at).toLocaleDateString("es-CO")}. Son hechos reportados por el visitador.</p>{data.products.map((p:any)=><article className="wf-card" key={p.name}><strong>{p.name}</strong><span className="lp-result">{{achieved:"Logrado",partial:"Parcial",not_achieved:"No logrado",unknown:"Sin confirmar"}[p.result as string]}</span><p>{p.objective||"Objetivo no registrado"}</p><p><b>Evidencia:</b> {p.evidence||"Pendiente"}</p><p><b>Barreras:</b> {p.barriers===null?"No registradas":p.barriers.join("; ")||"No se reportaron barreras"}</p></article>)}</>}
      {data.observations.map((o:any,i:number)=><aside className="lp-insight" key={i}><BookOpen size={20}/><div><strong>{o.product} · Necesidad observada</strong><p>{o.guidance}</p><small>{o.text}</small></div></aside>)}
      {data.can_edit&&<StudyChat user={user} id={id} mode={data.mode}/>}
      <h3>Prepárate con material aprobado</h3>
      {!data.sources.length&&<p>No hay material aprobado relacionado con esta conversación. Puedes consultar la biblioteca; no se inventará evidencia clínica.</p>}
      {data.sources.map((s:any)=><details className="wf-card" key={s.document_id+":"+s.slide}><summary>{s.title} · diapositiva {s.slide}</summary><p>{s.excerpt}</p><a href={s.href}>Abrir fuente · versión {s.version}</a></details>)}
      {data.lesson&&<div className="wf-card lp-lesson"><p className="wf-eyebrow">REPASO BREVE · COMPRENSIÓN DE LECTURA</p><h3>Completa la frase de la fuente</h3><p>{data.lesson.question}</p><div className="lp-options">{data.lesson.options.map((o:string)=><button key={o} disabled={busy||queued||!data.can_edit} onClick={()=>save("learning.answer",{lesson_id:data.lesson.id,answer:o})}>{o}</button>)}</div>{data.lesson.attempt&&<p role="status"><CheckCircle2 size={16}/> {data.lesson.attempt.correct?"Respuesta correcta.":"Revisa la fuente. La palabra es "+data.lesson.attempt.expected+"."} Intentos: {data.lesson.attempt.attempts}</p>}<a href={data.lesson.source.href}>{data.lesson.source.title} · diapositiva {data.lesson.source.slide}</a><h3>Llévalo a la conversación</h3><label>¿Cómo explicarías esta evidencia y sus límites al médico?<textarea value={reflection} maxLength={1500} disabled={busy||queued||!data.can_edit} onChange={e=>setReflection(e.target.value)} placeholder="Resume la fuente con tus palabras y anota qué necesitas aclarar."/></label><p>Tu reflexión se guarda como autoevaluación. No recibe una calificación clínica automática.</p><button disabled={busy||queued||!data.can_edit||reflection.trim().length<20} onClick={()=>save("learning.reflection",{lesson_id:data.lesson.id,text:reflection})}>Guardar reflexión</button>{data.reflection&&<small>Reflexión conservada con la fuente de esta visita.</small>}</div>}
      {!!Object.keys(data.previous_learning).length&&<p className="lp-meta">Tu repaso anterior: {Object.values(data.previous_learning).filter((a:any)=>a.correct).length} respuestas correctas de {Object.keys(data.previous_learning).length}. Se conserva para la próxima preparación.</p>}
    </>}
  </section>
}
