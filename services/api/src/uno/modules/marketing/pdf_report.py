"""Executive vector report from authorized operational and imported snapshots."""
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

INK='#193F33'; TEXT='#273E35'; MUTED='#65766B'; PAPER='#F4F5EF'
PALE='#E6EDE3'; PURPLE='#7964A5'; LINE='#DDE3D9'
W,H=A4

def number(value, decimals=0):
    if value is None: return 'Sin dato'
    return f'{float(value):,.{decimals}f}'.replace(',', '_').replace('.', ',').replace('_', '.')

def generate(snapshot, author, commercial=None):
    out=BytesIO();c=Canvas(out,pagesize=A4)
    c.setTitle('VisiMed | Informe ejecutivo SNC');c.setAuthor('VisiMed - Novamed')
    reference=snapshot.get('reference') or {}
    demo=snapshot.get('mode')=='demo'
    page=0;styles={}
    def text(value,x,top,width,size=9,color=TEXT,bold=False):
        key=(size,color,bold)
        if key not in styles:
            styles[key]=ParagraphStyle(str(key),fontName='Helvetica-Bold' if bold else 'Helvetica',fontSize=size,leading=size*1.35,textColor=colors.HexColor(color))
        p=Paragraph(escape(str(value)).replace('\n','<br/>'),styles[key]);_,h=p.wrap(width,H)
        p.drawOn(c,x,H-top-h)
        return h
    def box(x,top,w,h,fill='white',stroke=None,r=9):
        c.setFillColor(colors.toColor(fill));c.setStrokeColor(colors.toColor(stroke or fill))
        c.roundRect(x,H-top-h,w,h,r,fill=1,stroke=bool(stroke))
    def rule(top,x=34,w=W-68):
        c.setStrokeColor(colors.HexColor(LINE));c.setLineWidth(.6);c.line(x,H-top,x+w,H-top)
    def start(title,subtitle):
        nonlocal page
        if page:c.showPage()
        page+=1;box(0,0,W,H,PAPER,r=0)
        text('VISIMED  /  NOVAMED',34,25,300,10,INK,True)
        text('SNC · BOGOTÁ',W-155,25,120,9,MUTED,True)
        rule(49)
        text(title,34,67,W-68,27,INK,True)
        text(subtitle,34,109,W-68,9,MUTED)
        rule(H-42)
        text('Uso interno · '+('Demostración identificada; no computa como piloto' if demo else 'Piloto SNC · datos del alcance autorizado'),34,H-32,W-100,7,MUTED)
        text(f'{page:02}',W-54,H-32,25,8,INK,True)
    def metric(x,top,w,value,label):
        box(x,top,w,81)
        text(number(value),x+13,top+10,w-26,24,INK,True)
        text(label,x+13,top+45,w-26,8,MUTED)
    def bars(rows,x,top,w,height,label='name',value='value',color=INK,decimals=0):
        if not rows:
            text('Todavía no hay datos para esta lectura.',x,top,w,9,MUTED);return
        rows=rows[:8];stride=height/max(1,len(rows));maximum=max(1,*[abs(float(r.get(value) or 0)) for r in rows])
        for i,r in enumerate(rows):
            t=top+i*stride;v=r.get(value)
            text(str(r[label])[:65],x,t,w-70,8,TEXT,True)
            text(number(v,decimals),x+w-65,t,65,8,INK,True)
            box(x,t+23,w,4,PALE,r=2)
            if v is not None and float(v)!=0:box(x,t+23,max(2,(w/maximum)*abs(float(v))),4,color,r=2)
    def callout(title,detail,top,kind=INK,height=62):
        box(34,top,W-68,height,'white')
        box(34,top,4,height,kind,r=0)
        text(title,48,top+10,W-96,10,kind,True)
        text(detail,48,top+29,W-96,8,MUTED)

    try:cut=datetime.fromisoformat(snapshot['as_of']).astimezone(ZoneInfo('America/Bogota')).strftime('%d/%m/%Y %H:%M')
    except (ValueError,KeyError):cut=str(snapshot.get('as_of',''))
    period=f"{snapshot['start']} a {snapshot['end']} · Corte {cut} (Bogotá)"
    start('El territorio, con evidencia.',period+'\nPreparado para '+str(author))
    values=[(reference.get('doctors'),'Médicos en el panel recibido'),(reference.get('active_contacts'),'Contactos activos en Bogotá'),(reference.get('verified_sites'),'Sedes con ubicación verificada')]
    for i,(v,l) in enumerate(values):metric(34+i*179,154,169,v,l)
    box(34,250,527,206)
    text('01  DISTRIBUCIÓN DEL PANEL',49,264,490,10,INK,True)
    team=reference.get('team',[])
    bars(team,49,294,497,135,label='name',value='active')
    text('Cada contacto corresponde a un médico y su sede. No equivale a una visita realizada.',49,436,495,7,MUTED)
    box(34,470,255,211);box(301,470,260,211)
    text('02  ESPECIALIDADES',49,485,225,10,INK,True)
    bars(reference.get('specialties',[])[:5],49,512,225,157)
    text('03  SEDES VERIFICADAS',316,485,230,10,INK,True)
    points=reference.get('points',[])
    if points:
        left,right=min(p['lng'] for p in points),max(p['lng'] for p in points)
        bottom,upper=min(p['lat'] for p in points),max(p['lat'] for p in points)
        box(316,514,230,138,PALE)
        c.setFillColor(colors.HexColor(INK))
        for p in points:
            x=324+214*(p['lng']-left)/max(.001,right-left)
            t=642-118*(p['lat']-bottom)/max(.001,upper-bottom)
            c.circle(x,H-t,1.8,stroke=0,fill=1)
        text('Norte arriba · Coordenadas verificadas',320,658,220,7,MUTED)
    else:text('Sin coordenadas verificadas en este alcance.',316,526,225,9,MUTED)
    pending=sum(max(0,t.get('active',0)-t.get('hours',0)) for t in team)
    callout('Listo para planear; pendiente por confirmar',
            f'{number(pending)} contactos activos aún sin recepción confirmada. El rutero respeta los horarios registrados: no completa la agenda inventando disponibilidad.',696,height=71)

    start('De la visita al seguimiento.',period)
    count=snapshot['counts']
    for i,(key,label) in enumerate([('finished_visits','Visitas terminadas'),('confirmed_reports','Reportes confirmados'),('marketing_completed','Actividades de mercadeo cerradas')]):
        metric(34+i*179,143,169,count.get(key),label)
    text('DEMOSTRACIÓN · cifras separadas del piloto' if demo else 'EJECUCIÓN REAL DEL PERÍODO',34,236,527,9,PURPLE if demo else INK,True)
    box(34,259,527,163)
    text('Ritmo de la jornada',49,271,490,11,INK,True)
    trend=snapshot.get('trend',[]);maximum=max([1]+[max(r.get('planned',0),r.get('finished',0)) for r in trend]);step=477/max(1,len(trend))
    for i,r in enumerate(trend):
        x=59+i*step;bw=min(8,step*.32)
        for field,offset,col in [('planned',0,'#BCCEB8'),('finished',bw+1,INK)]:
            h=83*r.get(field,0)/maximum
            if h:box(x+offset,386-h,bw,h,col,r=0)
        if i%max(1,(len(trend)+9)//10)==0:text(r['day'][5:],x,391,40,6,MUTED)
    text(str(maximum),42,301,18,7,MUTED)
    text('Programadas: verde claro · Terminadas: verde oscuro · Unidad: visitas',49,407,490,7,MUTED)
    text('Lo confirmado por el equipo',34,438,527,13,INK,True)
    reports=snapshot.get('recent_confirmed_reports',[]);y=465
    if reports:
        for r in reports[:2]:
            body='; '.join(p['name']+': '+(p.get('evidence') or 'Resultado pendiente de especificar') for p in r.get('products',[])[:2])[:420]
            callout(r.get('doctor') or 'Reporte confirmado',body,y,height=90);y+=101
    else:
        callout('Todavía no hay reportes confirmados',
                'La próxima visita conectará objetivo, marcas, evidencia, barreras y compromisos. Estos resultados aparecerán después de que el visitador los confirme.',y,height=82);y+=94
    alerts=(snapshot.get('alerts',[])+snapshot.get('intelligence',{}).get('findings',[]))[:2]
    for a in alerts:
        if y>682:break
        callout(str(a['title'])[:95],str(a['detail'])[:210],y,kind=PURPLE,height=67);y+=76
    baseline=snapshot.get('intelligence',{}).get('baseline',{})
    text(str(baseline.get('note','Sin evidencia suficiente para una proyección.'))[:440],34,757,527,7,MUTED)

    if commercial and commercial.get('series'):
        groups=defaultdict(list)
        for r in commercial['series']:groups[(r['source'],r['period'],r['metric'],r['unit'])].append(r)
        group_list=sorted(groups.items(),key=lambda it:it[0][1],reverse=True)
        source_names={'chains':'Cadenas','distribution':'Distribución','closeup':'Close-Up'}
        metric_names={'inventory':'Inventario','rotation':'Rotación','distribution':'Distribución','mov':'MOV · definición de la fuente'}
        unit_names={'units':'unidades','source_mov':'unidad de origen','COP':'COP'}
        for offset in range(0,len(group_list),4):
            start('Las marcas, en sus fuentes.', 'Cortes comerciales importados · Separados de la actividad diaria del piloto')
            for n,(group,rows) in enumerate(group_list[offset:offset+4]):
                source,month,metric_name,unit=group;x=34+(n%2)*270;y=147+(n//2)*296
                box(x,y,257,282)
                text(source_names.get(source,source)+' · '+month,x+13,y+11,233,10,INK,True)
                text(metric_names.get(metric_name,metric_name)+' · '+unit_names.get(unit,unit),x+13,y+30,233,8,MUTED)
                observed=[r for r in rows if r['value'] is not None]
                observed.sort(key=lambda r:float(r['value']),reverse=True)
                bars(observed[:5],x+13,y+56,231,185,label='brand',color=PURPLE,decimals=0 if unit=='COP' else 1)
                text(f"{sum(r['observed'] for r in rows)} observaciones · {sum(r['missing'] for r in rows)} sin valor · Top 5 por marca",x+13,y+253,231,6.5,MUTED)
            text('Cada gráfico conserva fuente, período, métrica y unidad. MOV mantiene su definición original pendiente de validación. Los vacíos no son ceros; la longitud de barra representa magnitud y la cifra conserva el signo.',34,778,527,7,MUTED)

    start('Fuentes y próximas decisiones.', 'Trazabilidad del informe · Datos recibidos, evidencia registrada y límites de lectura')
    text('QUÉ HACER CON ESTA LECTURA',34,145,527,10,INK,True)
    callout('1. Completar la disponibilidad antes de ampliar la ruta',f'{number(pending)} contactos activos sin horario de recepción confirmado. Validar por sede y conservar FZ por ciclo.',168,height=70)
    callout('2. Cerrar el ciclo después de cada visita','Confirmar el reporte, revisar compromisos y abrir la preparación del mismo médico. La retroalimentación conserva la evidencia y el material aprobado.',248,height=70)
    callout('3. Comparar fuentes sin atribuir ventas sin evidencia','Los cortes comerciales son contexto de la línea. La actividad registrada permite evaluar ejecución; no demuestra por sí sola incremento de ventas o prescripción.',328,height=70)
    text('MATERIAL APROBADO DEL PILOTO',34,419,527,10,INK,True);y=444
    for r in reference.get('documents',[])[:6]:
        if r.get('status')!='approved':continue
        text(r['title'],34,y,419,9,TEXT,True)
        text(str(r['slides'])+' diapositivas',458,y,103,8,MUTED);rule(y+21);y+=29
    text('PROCEDENCIA Y DEFINICIONES',34,max(613,y+13),527,10,INK,True)
    origins='Panel SNC Bogotá y confirmaciones de los visitadores. '
    if commercial:origins+='Cortes: '+'; '.join(b['filename'] for b in commercial.get('batches',[]) if b['status']=='committed')+'. '
    origins+='Los originales completos están en Datos y fuentes, según el permiso de la cuenta.'
    text(origins,34,639,527,8,MUTED)
    text(snapshot['definitions']['coverage']+' '+snapshot['definitions']['report_rate'],34,710,527,8,MUTED)
    text('La georreferenciación representa sedes registradas; no es seguimiento continuo de personas. Las reglas de alerta y el modelo de referencia conservan su estado de validación. Este informe no acredita resultados clínicos.',34,758,527,7,MUTED)
    c.save();return out.getvalue()

