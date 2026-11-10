import {useState} from 'react';
import {Home,CalendarDays,MessageCircle,GraduationCap,ClipboardCheck,LayoutGrid,X,Route,Users,Megaphone,BookOpen,ChartNoAxesCombined} from 'lucide-react';
import type {User} from './api';
import './navigation.css';

export function AppNavigation({user}:{user:User}) {
 const [open,setOpen]=useState(false);
 const q=new URLSearchParams(location.search), module=q.get('module');
 const manager=user.role==='manager';
 const items=[{label:'Hoy',href:user.role==='rep'?'/':'/territorio/?module=today',Icon:Home,active:module==='today'},
  {label:'Agenda',href:'/territorio/?module=calendar',Icon:CalendarDays,active:module==='calendar'},
  {label:'Chat con UNO',href:'/inteligencia',Icon:MessageCircle,active:false},
  {label:'Entrenar',href:'/territorio/?module=study',Icon:GraduationCap,active:module==='library'||(module==='study'&&!q.has('stage'))},
  {label:'Preparar',href:'/territorio/?module=study&stage=before',Icon:ClipboardCheck,active:module==='brief'||(module==='study'&&q.has('stage'))}];
 const tools=[{label:'Mi ruta',detail:'Recorrido y próximas paradas',href:'/territorio/',Icon:Route},
  {label:'Panel y potencial',detail:'Médicos, sedes y cuestionario',href:'/territorio/?tab=potential',Icon:Users},
  {label:'Mercadeo',detail:'Programar y cerrar actividades',href:'/territorio/?module=marketing',Icon:Megaphone},
  {label:'Compromisos',detail:'Pendientes de tus visitas',href:'/territorio/?module=tasks',Icon:ClipboardCheck},
  {label:'Material y documentos',detail:'Biblioteca SNC y guías de operación',href:'/territorio/?module=library',Icon:BookOpen},
  ...(manager?[{label:'Gerencia',detail:'Indicadores, análisis y reportes',href:'/territorio/?module=management',Icon:ChartNoAxesCombined}]:[])];
 return <>
  {user.demo_mode&&<aside className="vm-demo-strip">Demostración · Panel real de referencia y escenarios ilustrativos.</aside>}
  <div className="vm-nav-space"/>
  <button className="vm-tools-button" onClick={()=>setOpen(!open)} aria-expanded={open} aria-controls="vm-tools"><LayoutGrid size={18}/> Módulos</button>
  {open&&<div className="vm-tools-overlay" onClick={()=>setOpen(false)}><section className="vm-tools-sheet" id="vm-tools" role="dialog" aria-modal="true" aria-label="Módulos de VisiMed" onClick={e=>e.stopPropagation()}><header><div><strong>Tu VisiMed</strong><small>{user.name} · Una sola jornada</small></div><button onClick={()=>setOpen(false)} aria-label="Cerrar módulos"><X/></button></header><div className="vm-tools-grid">{tools.map(({label,detail,href,Icon})=><a key={label} href={href}><Icon size={23}/><span><b>{label}</b><small>{detail}</small></span></a>)}</div></section></div>}
  <nav className="vm-bottom-nav" aria-label="Principal"><ul>{items.map(({label,href,Icon,active})=><li key={label}><a href={href} aria-current={active?'page':undefined}><Icon size={24} strokeWidth={1.7}/><span>{label}</span></a></li>)}</ul></nav>
 </>;
}
