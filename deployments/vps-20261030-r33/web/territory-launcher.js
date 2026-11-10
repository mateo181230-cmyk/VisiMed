// Shared product menu; no credentials are read and no external actions are triggered.
(() => {
 document.addEventListener('click',event=>{
  const anchor=event.target.closest?.('a[href]');if(!anchor||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  const url=new URL(anchor.href,location.href);if(url.origin!==location.origin)return;
  const destinations={'/preparacion':'/territorio/?module=study&stage=before','/entrenar':'/territorio/?module=study'};
  const preparation=url.pathname.match(/^\/preparacion\/([a-f0-9-]{36})\/?$/);
  const destination=preparation?'/territorio/?module=brief&visit='+preparation[1]:destinations[url.pathname];
  if(destination){event.preventDefault();event.stopPropagation();location.assign(destination)}
 },true);
 const icon=(path)=>'<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+path+'</svg>';
 const grid=icon('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>');
 const button=document.createElement('button');button.className='vm-tools-button';button.innerHTML=grid+' Módulos';button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','vm-tools');
 const overlay=document.createElement('div');overlay.className='vm-tools-overlay';overlay.hidden=true;
 const tools=[['Mi ruta','Recorrido y próximas paradas','/territorio/','<path d="M4 18C4 10 20 14 20 6M4 18h4m12-12h-4"/><circle cx="4" cy="18" r="3"/><circle cx="20" cy="6" r="3"/>'],['Panel y potencial','Médicos, sedes y cuestionario','/territorio/?tab=potential','<circle cx="12" cy="8" r="4"/><path d="M4 21v-3a8 8 0 0 1 16 0v3"/>'],['Mercadeo','Programar y cerrar actividades','/territorio/?module=marketing','<path d="M3 10v5h4l12 4V5L7 10H3Zm4 5 2 6"/>'],['Compromisos','Pendientes de tus visitas','/territorio/?module=tasks','<rect x="5" y="4" width="14" height="17" rx="2"/><path d="m8 13 3 3 5-6M9 4V2h6v2"/>'],['Material y documentos','Biblioteca SNC y guías de operación','/territorio/?module=library','<path d="M12 5v16M3 3l9 2 9-2v16l-9 2-9-2Z"/>']];
 let cached=null;try{cached=JSON.parse(localStorage.getItem('territory-last-user')||'null')}catch{}
 tools.push(['Gerencia','Indicadores, análisis y reportes','/territorio/?module=management','<path d="M4 20V10m8 10V4m8 16v-7M2 22h20"/>']);
 overlay.innerHTML='<section class="vm-tools-sheet" id="vm-tools" role="dialog" aria-modal="true" aria-label="Módulos de VisiMed"><header><div><strong>Tu VisiMed</strong><small>Novamed · Una sola jornada</small></div><button aria-label="Cerrar módulos">'+icon('<path d="m6 6 12 12M6 18 18 6"/>')+'</button></header><div class="vm-tools-grid">'+tools.map(([name,detail,href,path])=>'<a href="'+href+'">'+icon(path)+'<span><b>'+name+'</b><small>'+detail+'</small></span></a>').join('')+'</div></section>';
 const close=()=>{overlay.hidden=true;button.setAttribute('aria-expanded','false');button.focus()};
 button.onclick=()=>{overlay.hidden=!overlay.hidden;button.setAttribute('aria-expanded',String(!overlay.hidden));if(!overlay.hidden)overlay.querySelector('button').focus()};
 overlay.onclick=e=>{if(e.target===overlay)close()};overlay.querySelector('button').onclick=close;
 overlay.onkeydown=e=>{if(e.key==='Escape')close();if(e.key==='Tab'){const nodes=[...overlay.querySelectorAll('button,a')];if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1).focus()}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0].focus()}}};
 const visitLinks=document.createElement('div');visitLinks.className='vm-visit-links';
 const strip=document.createElement('aside');strip.className='vm-demo-strip';strip.hidden=!cached?.demo_mode;strip.innerHTML='Demostración · Panel real de referencia y escenarios ilustrativos.';
 document.body.append(button,overlay,visitLinks,strip);
 let prior='';const update=()=>{let identity='';try{identity=localStorage.getItem('territory-last-user')||'';cached=JSON.parse(identity||'null')}catch{cached=null}const key=location.pathname+location.search+identity;if(key===prior)return;prior=key;const hidden=/^\/(login|registro)(\/|$)/.test(location.pathname);button.hidden=hidden;strip.hidden=hidden||!cached?.demo_mode;overlay.querySelector('a[href="/territorio/?module=management"]').hidden=cached?.role!=='manager';overlay.hidden=true;const match=location.pathname.match(/^\/visitas\/([a-f0-9-]{36})(?:\/|$)/);visitLinks.hidden=!match;if(match)visitLinks.innerHTML='<a href="/territorio/?report='+match[1]+'">Revisar reporte por producto</a><a href="/territorio/?module=study&visit='+match[1]+'">Preparación y aprendizaje</a><a href="/territorio/?module=calendar">Volver a mi agenda</a>';};
 update();window.addEventListener('popstate',update);window.addEventListener('visimed-identity',update);setInterval(update,750);
})();
