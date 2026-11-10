"""Deterministic, scoped management answers when the generative provider is unavailable."""
import unicodedata


def answer_from_metrics(snapshot, question, commercial=None):
    q = ''.join(c for c in unicodedata.normalize('NFD', question.lower()) if not unicodedata.combining(c))
    c = snapshot['counts']
    performance = snapshot.get('performance', {})
    frequency = performance.get('frequency', {})
    paragraphs, actions = [], []
    if any(word in q for word in ('venta', 'prescrip', 'rotacion', 'mercado', 'close', 'cadena')):
        paragraphs.append('Los registros de visitas no demuestran ventas ni prescripciones causadas por la visita.')
        if commercial is not None:
            series = commercial['series']
            matched = [r for r in series if r['brand'].lower() in q]
            selected = matched or series
            paragraphs.append(f"Hay {len(commercial['batches'])} cargas comerciales y {len(series)} series separadas por fuente, período, métrica y unidad.")
            for r in selected[:6]:
                value = r['value'] if r['value'] is not None else 'sin dato'
                paragraphs.append(f"{r['brand']} · {r['source']} · {r['period']} · {r['metric']}: {value} {r['unit']}; {r['missing']} valores faltantes.")
            actions.append({'label':'Consultar los cortes comerciales','href':'/territorio/?module=management&view=commercial'})
        else:
            paragraphs.append('Tu perfil no tiene acceso a los cortes comerciales de gerencia de línea.')
    elif any(word in q for word in ('mercadeo', 'actividad', 'actividades', 'asisten')):
        paragraphs.append(f"En {snapshot['start']} a {snapshot['end']} se realizaron {c['marketing_completed']} actividades, con {c['attendances']} asistencias: {c['panel_attendances']} del panel y {c['external_attendances']} externas. Una asistencia no equivale a un médico único ni cubre la frecuencia FZ.")
        actions.append({'label':'Revisar las actividades','href':'/territorio/?module=marketing'})
    else:
        paragraphs.append(f"En {snapshot['start']} a {snapshot['end']}: {c['finished_visits']} visitas terminadas, {c['confirmed_reports']} reportes confirmados y {c['pending_reports']} por confirmar. Cobertura: {c['covered_doctors']} de {c['panel_doctors']} médicos.")
        if c['pending_reports']:
            paragraphs.append(f"Primero revisa los {c['pending_reports']} reportes pendientes para conservar sus resultados y compromisos.")
            actions.append({'label':'Revisar visitas y reportes','href':'/territorio/?module=management&view=visits'})
        if c['overdue_tasks']:
            paragraphs.append(f"Hay {c['overdue_tasks']} compromisos vencidos; acuerda su cierre o una nueva fecha con el responsable.")
        if frequency.get('overdue_windows'):
            paragraphs.append(f"Frecuencia: {frequency['overdue_windows']} ventanas FZ vencidas. Revisa recepción, disponibilidad y separación entre contactos antes de reprogramar.")
        missing_hours = c['panel_sites']-c['confirmed_hours']
        missing_locations = c['panel_sites']-c['verified_locations']
        if missing_hours or missing_locations:
            paragraphs.append(f"Para ampliar las rutas faltan horarios confirmados en {missing_hours} contactos y validación de ubicación en {missing_locations}. Estas son restricciones operativas; no se deben inventar horarios.")
        actions.append({'label':'Revisar territorio y rutas','href':'/territorio/'})
    return {'answer':'\n\n'.join(paragraphs),'as_of':snapshot['as_of'],'sources':['Indicadores autorizados de VisiMed']+(['Cortes comerciales importados'] if commercial is not None else []),'changes_made':False,'mode':'verified_metrics','notice':'Lectura automática de datos verificados. El proveedor generativo no está disponible; esta respuesta usa reglas explícitas, no un modelo de lenguaje.','actions':actions}
