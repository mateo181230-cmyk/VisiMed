import {useEffect,useState} from 'react';
import {MapPin,CheckCircle2,Mic,ArrowRight,LocateFixed} from 'lucide-react';
import {api,locate,type User} from './api';
import {BrowserVoice} from './BrowserVoice';
import './connected.css';
export function DemoScreen({user}:{user:User}) {
 const [data,setData]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const load=()=>api('/demo').then(d=>{setData(d);setError('')}).catch(e=>setError(e.message));
 useEffect(()=>{load();const t=setInterval(load,15000);return()=>clearInterval(t)},[]);
 async function action(kind:string){setBusy(true);setError('');try{
  if(!navigator.onLine)throw new Error('Conéctate a internet para verificar la llegada de la demo.');
  if(kind==='prepare')setData(await api('/demo/prepare',{}));
  else if(kind==='rehearsal')setData(await api('/demo/rehearsal',{request_id:crypto.randomUUID()}));
  else {const gps=await locate();setData(await api(`/demo/${data.visit_id}/${kind}`,{location:{lat:gps.lat,lng:gps.lng,precision_m:gps.accuracy_m,fix_ts:new Date().toISOString(),source:'gps'},permission:'granted'}));}
 }catch(e:any){setError(e.message)}finally{setBusy(false)}}
 const id=data?.visit_id,started=data&&data.status!=='scheduled',done=data&&['finished','in_call','processing','ready','confirmed','no_interview','error'].includes(data.status);
 return <main className="connected-page demo-page"><a className="connected-back" href="/territorio/">← Volver a VisiMed</a>
  {id&&done&&user.role==='rep'&&<BrowserVoice key={id} visitId={id} enabled={data.status!=='confirmed'} confirmed={data.status==='confirmed'} compact onSaved={load}/>}
  <div className="connected-eyebrow">NOVAMED · DEMOSTRACIÓN</div><h1>Una visita, de principio a fin.</h1>
  <p className="connected-lead">{user.name}. Usa tu celular en la oficina para recorrer el mismo flujo que tendrá el visitador.</p>
  <div className="demo-notice">Datos de demostración. Esta visita no suma a la cobertura, frecuencia ni resultados del piloto.</div>
  {error&&<div role="alert" className="notice danger">{error}<button onClick={load}>Reintentar</button></div>}
  {data&&<><section className="connected-card demo-site"><MapPin size={28}/><div><h2>{data.doctor}</h2><strong>{data.institution}</strong><p>{data.address}</p><small>Ubicación horizontal · radio de {data.radius_m} m. El GPS no verifica el piso.</small></div></section>
  <section className="connected-card"><h2>Tu reunión con la Dra. Juliana</h2><p><strong>Escenario simulado:</strong> dispone de cinco minutos y pide evidencia científica concreta. Presenta ESLUX primero y ESCILOM después. Usa únicamente el material SNC aprobado.</p><p><strong>Prepárate:</strong> revisa las fuentes, identifica dos preguntas por marca y define qué evidencia demostrará que lograste el objetivo. Lleva un siguiente paso con responsable y fecha.</p><div className="connected-links"><a href="/territorio/?module=calendar">Ver agenda</a><a href="/territorio/">Ruta y potencial</a><a href="/territorio/?module=library">Material aprobado</a><a href="/territorio/?module=marketing">Mercadeo</a></div></section>
  <ol className="demo-steps">
   <li><span className="step-number">1</span><div><h2>Preparar la visita</h2><p>Define qué quieres lograr con cada marca SNC y consulta el material aprobado.</p>{!id?<button className="button" disabled={busy} onClick={()=>action('prepare')}>Preparar demostración <ArrowRight size={17}/></button>:<a className="button secondary" href={'/territorio/?module=brief&visit='+id}>Abrir preparación</a>}</div></li>
   <li><span className="step-number">2</span><div><h2>Registrar la llegada</h2><p>Activa ubicación precisa. Solo podrás iniciar cerca del punto registrado de Novamed.</p>{started&&id?<span className="demo-success"><CheckCircle2 size={18}/> Llegada registrada{data.arrival_distance_m!=null?' · '+data.arrival_distance_m+' m':''}</span>:<button className="button" disabled={busy||!id} onClick={()=>action('arrive')}><LocateFixed size={18}/>{busy?'Verificando…':'Estoy en Novamed'}</button>}</div></li>
   <li><span className="step-number">3</span><div><h2>Terminar y hablar con UNO</h2><p>La entrevista ocurre aquí, con el micrófono del celular. Cuenta lo que pasó y confirma el resumen. Máximo cinco minutos; mantén la pantalla abierta y la conexión a internet.</p><button className="button" disabled={busy||!id||!started||done} onClick={()=>action('finish')}><CheckCircle2 size={18}/>{done?'Visita terminada':'Terminar visita'}</button>{done&&<a className="button secondary" href={'/territorio/?report='+id+'&from=demo'}><Mic size={18}/>Hablar con UNO</a>}</div></li>
   <li><span className="step-number">4</span><div><h2>Confirmar lo que ocurrió</h2><p>Revisa marcas, objetivos, barreras, droguerías y compromisos. Los campos no informados quedan visibles.</p>{done&&<a className="button secondary" href={'/territorio/?report='+id+'&from=demo'}>Revisar reporte</a>}</div></li>
   <li><span className="step-number">5</span><div><h2>Aprender y dar seguimiento</h2><p>El reporte confirmado alimenta UNO, la retroalimentación y los compromisos de la próxima visita.</p>{done&&<div className="connected-links"><a href={'/territorio/?module=brief&visit='+id}>Ver retroalimentación</a><a href="/territorio/?module=tasks">Ver compromisos</a><a href="/inteligencia">Conversar con UNO</a></div>}</div></li>
   <li><span className="step-number">6</span><div><h2>Mostrar el impacto a gerencia</h2><p>Entra con una cuenta de gerencia y selecciona «Demostración» para ver resultados, gráficas, el agente de análisis y el informe PDF. Los resultados reales del piloto se mantienen separados.</p></div></li>
  </ol></>}
  {done&&<section className="connected-card"><h2>¿Quieres ensayar de nuevo?</h2><p>Crea otra visita de demostración. El reporte y la conversación anteriores se conservan.</p><button className="button secondary" disabled={busy} onClick={()=>action('rehearsal')}>Crear nuevo ensayo</button></section>}
 </main>
}
