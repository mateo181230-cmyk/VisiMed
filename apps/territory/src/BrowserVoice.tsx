import {useEffect,useRef,useState} from 'react';
import {Mic,MicOff,Square,CheckCircle2,RefreshCw} from 'lucide-react';
import {api} from './api';
import './browser-voice.css';

function voiceMessage(error:any,fallback:string){
 const text=typeof error?.message==='string'?error.message:'';
 // Transport and SDK diagnostics belong in telemetry, never in the product UI.
 if(!text||/eleven\s*labs|11\s*labs|wss?:\/\/|api[_ -]?key|token|stack|fetch/i.test(text))return fallback;
 return text;
}

export function BrowserVoice({visitId,enabled,confirmed=false,compact=false,onSaved}:{visitId:string;enabled:boolean;confirmed?:boolean;compact?:boolean;onSaved:()=>void}){
 const [state,setState]=useState('idle'),[error,setError]=useState(''),[elapsed,setElapsed]=useState(0),[muted,setMuted]=useState(false),[speaking,setSpeaking]=useState(false),[messages,setMessages]=useState<{role:string;text:string}[]>([]);
 const [voiceReady,setVoiceReady]=useState(false),sdk=useRef<{Conversation:any}|null>(null);
 const connection=useRef<any>(null),call=useRef(''),conversation=useRef(''),bound=useRef(false),started=useRef(0),saved=useRef(onSaved),ending=useRef(false),mounted=useRef(true);
 const orb=useRef<HTMLDivElement>(null);
 const key='uno-browser-call:'+visitId;
 saved.current=onSaved;
 useEffect(()=>{let live=true;import('@elevenlabs/client').then(module=>{if(live){sdk.current=module;setVoiceReady(true)}}).catch(()=>{if(live)setError('No se pudo descargar la voz. Actualiza la página con conexión a internet.');});return()=>{live=false}},[]);
 async function bind(){
  if(!call.current||!conversation.current||bound.current)return;
  await api('/browser-voice/'+call.current+'/bind',{conversation_id:conversation.current});bound.current=true;
 }
 async function recover(){
  if(!call.current)return;
  try{
   await bind();
   const r=await api('/browser-voice/'+call.current);
   if(!mounted.current)return;
   if(r.report_saved){setState('saved');setError('');sessionStorage.removeItem(key);saved.current();}
   else if(r.status==='failed'||r.status==='cancelled'){setState('error');setError('La entrevista no tiene información suficiente. Puedes volver a conversar o completar el reporte abajo.');sessionStorage.removeItem(key);saved.current();}
  }catch(e:any){if(mounted.current)setError(navigator.onLine?voiceMessage(e,'No pudimos recuperar el reporte de UNO. Toca «Actualizar reporte» para volver a consultar.'):'Se perdió la conexión. Volveremos a buscar el reporte cuando estés en línea.');}
 }
 async function finish(){
  if(ending.current)return;ending.current=true;
  setState('processing');
  try{await connection.current?.endSession();}catch{setError('Recuperando el reporte de la conversación…');}finally{connection.current=null;ending.current=false;await recover();}
 }
 useEffect(()=>{
  mounted.current=true;
  try{const v=JSON.parse(sessionStorage.getItem(key)||'null');if(v){call.current=v.call;conversation.current=v.conversation||'';setState('processing');recover();}}catch{}
  return()=>{mounted.current=false;connection.current?.endSession();connection.current=null;};
 },[visitId]);
 useEffect(()=>{
  if(state!=='connected')return;
  const t=setInterval(()=>{const seconds=Math.floor((Date.now()-started.current)/1000);setElapsed(seconds);if(seconds>=285)finish();},500);
  const prevent=(e:BeforeUnloadEvent)=>{e.preventDefault();};window.addEventListener('beforeunload',prevent);
  return()=>{clearInterval(t);window.removeEventListener('beforeunload',prevent);};
 },[state]);
 useEffect(()=>{if(state!=='processing')return;const t=setInterval(recover,5000);return()=>clearInterval(t);},[state]);
 useEffect(()=>{
  if(state!=='connected'){orb.current?.style.setProperty('--voice-energy','0');return;}
  let frame=0,last=0;
  const sample=(now:number)=>{
   if(now-last>=50){
    last=now;let value=0;
    try{value=speaking?connection.current?.getOutputVolume?.():(muted?0:connection.current?.getInputVolume?.());}catch{}
    const level=Number.isFinite(value)?Math.max(0,Math.min(1,Number(value)*3)):0;
    orb.current?.style.setProperty('--voice-energy',String(level));
   }
   frame=requestAnimationFrame(sample);
  };
  frame=requestAnimationFrame(sample);
  return()=>{cancelAnimationFrame(frame);orb.current?.style.setProperty('--voice-energy','0');};
 },[state,speaking,muted]);
 async function start(){
  setError('');setMessages([]);setElapsed(0);setMuted(false);setState('connecting');bound.current=false;call.current='';conversation.current='';
  try{
   if(!navigator.onLine)throw new Error('Conéctate a internet para conversar con UNO. Tu reporte escrito sigue disponible sin conexión.');
   if(!navigator.mediaDevices?.getUserMedia)throw new Error('Abre esta página con HTTPS en Safari o Chrome y permite el micrófono.');
   const stream=await navigator.mediaDevices.getUserMedia({audio:true});stream.getTracks().forEach(t=>t.stop());
   if(!sdk.current)throw new Error('Espera a que termine de preparar la voz.');
   const {Conversation}=sdk.current;
   const data=await api('/browser-voice/start',{visit_id:visitId});call.current=data.call_id;
   sessionStorage.setItem(key,JSON.stringify({call:call.current}));
   const conn=await Conversation.startSession({
    signedUrl:data.signed_url,connectionType:'websocket',dynamicVariables:data.dynamic_variables,userId:data.user_id,useWakeLock:true,
    onConnect:()=>{started.current=Date.now();if(mounted.current)setState('connected');},
    onDisconnect:()=>{connection.current=null;if(mounted.current){setState('processing');recover();}},
    onModeChange:(m:any)=>setSpeaking(m.mode==='speaking'),
    onMessage:(m:any)=>{if(m.message?.trim())setMessages(old=>[...old.slice(-59),{role:m.source==='user'?'Tú':'UNO',text:m.message}]);},
    onError:()=>{if(mounted.current)setError('La conexión de voz se interrumpió. Estamos conservando lo recibido.');},
   });
   connection.current=conn;conversation.current=conn.getId();
   sessionStorage.setItem(key,JSON.stringify({call:call.current,conversation:conversation.current}));
   for(let n=0;n<4&&!bound.current;n++){try{await bind();}catch{await new Promise(r=>setTimeout(r,800));}}
   if(!bound.current)setError('Voz conectada. Estamos vinculando la conversación al reporte.');
  }catch(e:any){
   connection.current?.endSession();connection.current=null;
   if(call.current&&!conversation.current)await api('/browser-voice/'+call.current+'/cancel',{}).catch(()=>{});
   sessionStorage.removeItem(key);setState('error');
   setError(e.name==='NotAllowedError'?'Permite el micrófono en tu navegador y vuelve a tocar «Hablar con UNO».':voiceMessage(e,'No pudimos conectar con la voz de UNO. Reintenta o completa el reporte por escrito.'));
  }
 }
 const isSaved=state==='saved'||confirmed;
 const active=state==='connected',working=['connecting','processing'].includes(state);
 return <section className={'browser-voice browser-voice--'+state+(compact&&!active&&!working&&!confirmed?' browser-voice--compact':'')} aria-label="Conversación de voz con UNO">
  <header><div ref={orb} aria-hidden="true" className={'browser-voice-orb '+(active?'live ':'')+(speaking?'is-speaking ':'')+(working?'is-working':'')}><i className="uno-orb-ring"/><i className="uno-orb-core"/><span className="uno-orb-word">uno</span></div><div><span>UNO · VOZ EN LA APP</span><h2 aria-live="polite">{active?(muted?'Micrófono en silencio':speaking?'UNO está hablando':'Te escucho'):state==='connecting'?'Conectando con UNO…':state==='processing'?'Preparando tu reporte…':isSaved?'Tu reporte está guardado':'Cuéntalo una vez. Queda conectado.'}</h2><small className="uno-voice-status">{active?'Conversación en vivo · habla con naturalidad':working?'Mantén esta pantalla abierta':isSaved?'Vinculado a esta visita':'Tu visita, convertida en acciones'}</small></div></header>
  <p>{confirmed?'Tu entrevista ya está confirmada. Los productos, resultados y compromisos quedaron conectados al seguimiento de esta visita.':isSaved?'Revisa abajo los productos, resultados y compromisos. Al confirmar alimentarán el seguimiento y gerencia.':'Habla desde este celular. UNO conoce la visita y las marcas SNC; convertirá tu conversación en un reporte para revisar.'}</p>
  <div className="browser-voice-meta"><span>Máximo 5 minutos</span><span>Vinculado a esta visita</span><span>Requiere internet</span></div>
  {active&&<div className="browser-voice-timer" role="timer">{Math.floor(elapsed/60)}:{String(elapsed%60).padStart(2,'0')} <small>/ 4:45{elapsed>=260?' · Cerrando los últimos detalles':''}</small></div>}
  <div className="browser-voice-controls">
   {active?<><button onClick={()=>{connection.current?.setMicMuted(!muted);setMuted(!muted)}}>{muted?<MicOff size={18}/>:<Mic size={18}/>} {muted?'Activar micrófono':'Silenciar'}</button><button className="browser-voice-end" onClick={finish}><Square size={16}/>Terminar y guardar</button></>:confirmed?<span className="browser-voice-success"><CheckCircle2 size={20}/>Reporte recibido</span>:<button className="browser-voice-start" disabled={!enabled||working||!voiceReady} onClick={start}><Mic size={19}/>{state==='connecting'?'Conectando con UNO…':state==='processing'?'Procesando conversación…':!voiceReady?'Preparando voz…':'Hablar con UNO'}</button>}
   {state==='processing'&&<button onClick={recover}><RefreshCw size={17}/>Actualizar reporte</button>}
  </div>
  {!enabled&&!isSaved&&<small>Termina la visita para habilitar la entrevista. Los reportes confirmados se conservan.</small>}
  {error&&<p role="alert" className="browser-voice-error">{error}</p>}
  {!!messages.length&&<details className="browser-voice-transcript" open={active}><summary>Conversación en vivo ({messages.length})</summary><div aria-live="polite">{messages.map((m,i)=><p key={i}><strong>{m.role}</strong>{m.text}</p>)}</div></details>}
 </section>;
}
