// @vitest-environment jsdom
import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {BrowserVoice} from './BrowserVoice';
const mocks=vi.hoisted(()=>({api:vi.fn(),start:vi.fn(),end:vi.fn(),mute:vi.fn(),saved:vi.fn(),input:vi.fn(()=>.1),output:vi.fn(()=>.2)}));
vi.mock('./api',()=>({api:mocks.api}));
vi.mock('@elevenlabs/client',()=>({Conversation:{startSession:mocks.start}}));
let root:Root,host:HTMLDivElement,options:any,frame:FrameRequestCallback;
const conn={getId:()=> 'conversation_qa',endSession:mocks.end,setMicMuted:mocks.mute,getInputVolume:mocks.input,getOutputVolume:mocks.output};
beforeEach(()=>{
 vi.clearAllMocks();sessionStorage.clear();
 (globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
 vi.stubGlobal('requestAnimationFrame',vi.fn((cb:FrameRequestCallback)=>{frame=cb;return 1}));
 vi.stubGlobal('cancelAnimationFrame',vi.fn());
 Object.defineProperty(navigator,'onLine',{configurable:true,value:true});
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn(async()=>({getTracks:()=>[{stop:vi.fn()}]}))}});
 mocks.api.mockImplementation(async(path:string)=>path.endsWith('/start')?{call_id:'call_qa',signed_url:'wss://qa.invalid/session',dynamic_variables:{catalogo_snc:'ESLUX'},user_id:'call_qa'}:path.endsWith('/bind')?{}:{report_saved:true});
 mocks.start.mockImplementation(async(value:any)=>{options=value;value.onConnect();return conn;});
 mocks.end.mockResolvedValue(undefined);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.unstubAllGlobals()});
async function render(enabled=true,confirmed=false){await act(async()=>root.render(<BrowserVoice visitId="visit_qa" enabled={enabled} confirmed={confirmed} onSaved={mocks.saved}/>));await act(async()=>{});}
async function click(text:string){const b=[...host.querySelectorAll('button')].find(b=>b.textContent?.includes(text));expect(b).toBeTruthy();await act(async()=>b!.click());}
describe('UNO: voz conectada al reporte',()=>{
 it('abre la sesión de la visita y vincula el identificador real del SDK',async()=>{
  await render();await click('Hablar con UNO');
  expect(mocks.api).toHaveBeenCalledWith('/browser-voice/start',{visit_id:'visit_qa'});
  expect(options.userId).toBe('call_qa');expect(options.connectionType).toBe('websocket');
  expect(mocks.api).toHaveBeenCalledWith('/browser-voice/call_qa/bind',{conversation_id:'conversation_qa'});
  expect(host.textContent).toContain('Te escucho');
 });
 it('anima la esfera con niveles de audio reales y cambia entre escuchar y hablar',async()=>{
  await render();await click('Hablar con UNO');frame(100);
  expect(Number((host.querySelector('.browser-voice-orb') as HTMLElement).style.getPropertyValue('--voice-energy'))).toBeCloseTo(.3);
  await act(async()=>options.onModeChange({mode:'speaking'}));frame(200);
  expect(host.textContent).toContain('UNO está hablando');
  expect(Number((host.querySelector('.browser-voice-orb') as HTMLElement).style.getPropertyValue('--voice-energy'))).toBeCloseTo(.6);
  await click('Silenciar');expect(mocks.mute).toHaveBeenCalledWith(true);expect(host.textContent).toContain('Micrófono en silencio');
 });
 it('guarda, recupera el reporte y notifica a la pantalla sin confirmarlo por el usuario',async()=>{
  await render();await click('Hablar con UNO');await act(async()=>options.onMessage({source:'user',message:'Presenté Eslux.'}));
  await click('Terminar y guardar');expect(mocks.end).toHaveBeenCalledTimes(1);
  expect(mocks.saved).toHaveBeenCalledTimes(1);expect(host.textContent).toContain('Tu reporte está guardado');
  expect(sessionStorage.getItem('uno-browser-call:visit_qa')).toBeNull();
  expect(mocks.api.mock.calls.some(([p])=>p.includes('confirm'))).toBe(false);
 });
 it('no muestra el proveedor ni diagnósticos técnicos cuando falla el SDK',async()=>{
  mocks.start.mockRejectedValue(new Error('ElevenLabs API returned 500 token=private'));
  await render();await click('Hablar con UNO');
  expect(host.textContent).toContain('No pudimos conectar con la voz de UNO');
  expect(host.textContent).not.toMatch(/eleven|private|token=/i);
  expect(mocks.api).toHaveBeenCalledWith('/browser-voice/call_qa/cancel',{});
 });
 it('impide iniciar antes de terminar una visita y conserva los informes confirmados',async()=>{
  await render(false);expect(host.querySelector('button')!.disabled).toBe(true);
  await render(true,true);expect(host.textContent).toContain('Reporte recibido');expect(host.textContent).not.toContain('Hablar con UNO');
 });
 it('cierra a los 285 segundos y recupera lo recibido',async()=>{
  vi.useFakeTimers();await render();await click('Hablar con UNO');
  await act(async()=>vi.advanceTimersByTimeAsync(285_500));
  expect(mocks.end).toHaveBeenCalled();expect(mocks.saved).toHaveBeenCalled();
 });
});
