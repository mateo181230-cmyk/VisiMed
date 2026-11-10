import {useEffect,useState} from 'react';
import {CalendarDays,ChevronLeft,ChevronRight,Plus,X,MapPin,Clock,Route} from 'lucide-react';
import {api,ApiError,db,type User} from './api';
import './connected.css';
import './calendar.css';
const dayKey=(d:Date)=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/Bogota',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
const advance=(s:string,n:number)=>dayKey(new Date(new Date(s+'T12:00:00-05:00').getTime()+n*86400000));
const time=(s:string)=>new Date(s).toLocaleTimeString('es-CO',{timeZone:'America/Bogota',hour:'2-digit',minute:'2-digit',hour12:false});
const minute=(s:string)=>{const[h,m]=time(s).split(':').map(Number);return h*60+m};
const labels:any={medical:'Visita médica',pharmacy:'Visita a droguería',marketing:'Actividad de mercadeo'};
const statuses:any={scheduled:'Programada',in_progress:'En curso',finished:'Por reportar',confirmed:'Reporte confirmado',not_done:'No realizada',cancelled:'Cancelada',completed:'Cerrada',draft:'Borrador'};
export function CalendarScreen({user,todayOnly=false}:{user:User;todayOnly?:boolean}){
 const [day,setDay]=useState(dayKey(new Date())),[view,setView]=useState<'day'|'week'|'month'>(todayOnly||window.innerWidth<700?'day':'week'),[data,setData]=useState<any>(null),[error,setError]=useState(''),[cached,setCached]=useState(false),[selected,setSelected]=useState<any>(null),[revision,setRevision]=useState(0);
 useEffect(()=>{if(!todayOnly)return;const timer=setInterval(()=>setDay(dayKey(new Date())),60000);return()=>clearInterval(timer)},[todayOnly]);
 const weekday=(new Date(day+'T12:00:00-05:00').getUTCDay()+6)%7,weekStart=advance(day,-weekday),monthStart=day.slice(0,8)+'01';
 const monthOffset=(new Date(monthStart+'T12:00:00-05:00').getUTCDay()+6)%7;
 const start=todayOnly?day:view==='month'?advance(monthStart,-monthOffset):weekStart,days=Array.from({length:todayOnly?1:view==='month'?42:7},(_,i)=>advance(start,i));
 const rep=new URLSearchParams(location.search).get('rep'),key=user.id+':calendar:'+start+':'+days.length+':'+(rep||user.id);
 useEffect(()=>{
  let live=true,fetching=false;
  const load=async()=>{
   if(fetching)return;fetching=true;
   try{
    const d=await api('/calendar?start='+start+'&end='+days[days.length-1]+(rep?'&representative_id='+rep:''));
    if(!live)return;setData(d);setCached(false);setError('');
    await db.snapshots.put({id:key,data:d});
   }catch(e:any){
    if(!live)return;
    if(e instanceof ApiError&&e.status<500){setError(e.message);setData(null);return}
    const c=await db.snapshots.get(key);if(!live)return;
    if(c){setData(c.data);setCached(true);setError('')}
    else{setData(null);setError('No pudimos conectar con Novamed para consultar esta agenda. No podemos confirmar qué horarios están disponibles.')}
   }finally{fetching=false}
  };
  setData(null);setCached(false);setError('');void load();
  const timer=setInterval(()=>{if(document.visibilityState==='visible')void load()},30000);
  return()=>{live=false;clearInterval(timer)};
 },[key,revision]);
 const events=data?.events||[],forDay=(d:string)=>events.filter((e:any)=>dayKey(new Date(e.starts_at))===d);
 const shownDays=view==='day'?[day]:days;
 const from=Math.min(7,...events.map((e:any)=>Math.floor(minute(e.starts_at)/60))),to=Math.max(19,...events.map((e:any)=>Math.ceil(minute(e.ends_at)/60)));
 const hours=Array.from({length:to-from},(_,i)=>from+i),height=hours.length*64;
 function shift(n:number){if(view==='month'){const d=new Date(day+'T12:00:00-05:00');d.setUTCMonth(d.getUTCMonth()+n,1);setDay(dayKey(d))}else setDay(advance(day,n*(view==='day'?1:7)))}
 function slots(list:any[]){const ends:number[]=[];return list.map(e=>{const top=(minute(e.starts_at)-from*60)*64/60,body=Math.max(46,(minute(e.ends_at)-minute(e.starts_at))*64/60);let lane=ends.findIndex(end=>end<=top);if(lane<0)lane=ends.length;ends[lane]=top+body+3;return {...e,top,body,lane}}).map((e,_,all)=>({...e,lanes:Math.max(1,...all.filter(a=>a.top<e.top+e.body&&a.top+a.body>e.top).map(a=>a.lane+1))}))}
 return <main className="connected-page calendar-page"><header className="gc-heading"><div><div className="connected-eyebrow">{todayOnly?'VISIMED · JORNADA DEL EQUIPO':'VISIMED · MI AGENDA'}</div><h1>{todayOnly?'Hoy':new Date(day+'T12:00:00-05:00').toLocaleDateString('es-CO',{month:'long',year:'numeric'})}</h1><p>{todayOnly?new Date(day+'T12:00:00-05:00').toLocaleDateString('es-CO',{dateStyle:'full',timeZone:'America/Bogota'}):'Tu ruta, visitas y mercadeo, en el mismo calendario.'}</p></div>{todayOnly?<a className="gc-create" href="/territorio/?module=calendar"><CalendarDays size={19}/> Abrir agenda</a>:user.role==='rep'&&<a className="gc-create" href={'/agenda?fecha='+day}><Plus size={19}/> Nueva visita</a>}</header>
 {todayOnly?<section className="gc-day-summary" aria-label="Resumen de la jornada">{!data?<p role="status">{error?'Jornada sin verificar':'Cargando jornada…'}</p>:<><div><strong>{events.length}</strong><span>Actividades de hoy</span></div><div><strong>{events.filter((e:any)=>e.status==='in_progress').length}</strong><span>En curso</span></div><div><strong>{events.filter((e:any)=>['confirmed','completed','finished'].includes(e.status)).length}</strong><span>Terminadas</span></div></>}</section>:<div className="gc-toolbar"><div><button aria-label="Período anterior" onClick={()=>shift(-1)}><ChevronLeft size={18}/></button><button onClick={()=>setDay(dayKey(new Date()))}>Hoy</button><button aria-label="Período siguiente" onClick={()=>shift(1)}><ChevronRight size={18}/></button></div><input aria-label="Fecha de agenda" type="date" value={day} onChange={e=>e.target.value&&setDay(e.target.value)}/><select aria-label="Vista de calendario" value={view} onChange={e=>setView(e.target.value as any)}><option value="day">Día</option><option value="week">Semana</option><option value="month">Mes</option></select></div>}
 {error&&<div role="alert" className="notice danger"><p>{error}</p><button className="button" onClick={()=>setRevision(n=>n+1)}>Reintentar</button></div>}{!data&&!error&&<p role="status">Consultando tu agenda…</p>}{cached&&<p className="notice">Agenda descargada. Se actualizará al recuperar conexión.</p>}
 <div className="gc-legend"><span className="medical">Médicos</span><span className="pharmacy">Droguerías</span><span className="marketing">Mercadeo</span><small>GMT−5 · Bogotá</small></div>
 {data&&(view==='month'?<div className="gc-month">{days.map(d=><section key={d} className={d.slice(0,7)!==day.slice(0,7)?'muted':''}><button className={d===dayKey(new Date())?'gc-today':''} onClick={()=>{setDay(d);setView('day')}}>{Number(d.slice(-2))}</button>{forDay(d).slice(0,3).map((e:any)=><button key={e.id} className={'gc-month-event '+e.kind} onClick={()=>setSelected(e)}>{time(e.starts_at)} {e.title}</button>)}{forDay(d).length>3&&<button onClick={()=>{setDay(d);setView('day')}}>+{forDay(d).length-3} más</button>}</section>)}</div>:
 <div className="gc-scroll"><div className={'gc-table '+(view==='day'?'one-day':'')} style={{gridTemplateColumns:'48px repeat('+shownDays.length+', minmax('+(view==='day'?'220':'125')+'px, 1fr))'}}><div className="gc-day-heading">HORA</div>{shownDays.map(d=><button key={d} className={'gc-day-heading '+(d===dayKey(new Date())?'gc-is-today':'')} onClick={()=>{setDay(d);setView('day')}}><span>{new Date(d+'T12:00:00-05:00').toLocaleDateString('es-CO',{weekday:'short'})}</span><b>{Number(d.slice(-2))}</b></button>)}<div className="gc-hours" style={{height}}>{hours.map(h=><span key={h} style={{top:(h-from)*64}}>{h}:00</span>)}</div>{shownDays.map(d=><div key={d} className="gc-day" style={{height}}>{hours.map(h=><div key={h} className="gc-hour" style={{top:(h-from)*64}}/>)}{slots(forDay(d)).map(e=><button key={e.id} className={'gc-event '+e.kind} onClick={()=>setSelected(e)} style={{top:e.top,height:e.body,left:(e.lane*100/e.lanes)+'%',width:'calc('+(100/e.lanes)+'% - 4px)'}}><b>{e.title}</b><span>{time(e.starts_at)}{e.demo?' · Demo':''}</span></button>)}{!forDay(d).length&&<div className="gc-empty-day">{cached?'Sin actividades descargadas':'Sin actividades programadas'}</div>}</div>)}</div></div>)}
 <div className="connected-links"><a href={'/territorio/?day='+day+(rep?'&rep='+rep:'')}><Route size={15}/> Recorrido del día</a><a href="/territorio/?module=marketing">Programar mercadeo</a></div><p className="calendar-footnote">Las rutas publicadas aparecen automáticamente. Los bloques médicos y de droguería reservan 20 minutos estimados; las horas de recepción se validan por separado.</p>
 {selected&&<div className="gc-modal-backdrop" onClick={()=>setSelected(null)}><section className="gc-detail" role="dialog" aria-modal="true" aria-label="Detalle de la agenda" onClick={e=>e.stopPropagation()}><button className="gc-close" aria-label="Cerrar detalle" onClick={()=>setSelected(null)}><X/></button><span className={'gc-type '+selected.kind}>{labels[selected.kind]}{selected.demo?' · Demostración':''}</span><h2>{selected.title}</h2><p><Clock size={17}/>{new Date(selected.starts_at).toLocaleDateString('es-CO',{dateStyle:'full',timeZone:'America/Bogota'})}<br/>{time(selected.starts_at)} – {time(selected.ends_at)}</p><p><MapPin size={17}/>{selected.site}<br/>{selected.address}</p><strong>{statuses[selected.status]}</strong>{selected.demo&&<p className="gc-demo-note">Escenario de demostración; no representa ejecución real del piloto.</p>}<div className="gc-detail-actions">{selected.prepare_href&&<a href={selected.prepare_href}>Preparación y aprendizaje</a>}<a className="gc-create" href={selected.kind==='medical'?(selected.status==='confirmed'?'/territorio/?report='+selected.id:'/visitas/'+selected.id):selected.href}>{selected.status==='confirmed'?'Ver reporte':'Abrir actividad'}</a></div></section></div>}
 </main>
}

