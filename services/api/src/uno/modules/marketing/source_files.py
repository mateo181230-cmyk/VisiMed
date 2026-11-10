"""Immutable originals, served only after role and pilot-scope validation."""
import json
from pathlib import Path
from uno.errors import ApiError
from uno.modules.auth.permissions import permits,line_ids

ROOT=Path('/opt/uno-source-library')

def listing(actor):
 path=ROOT/'manifest.json'
 if not path.is_file():return []
 data=json.loads(path.read_text(encoding='utf-8'))
 def allowed(r):
  scope=line_ids(actor)
  if r.get('line_id') and scope is not None and r['line_id'] not in {str(x) for x in scope}:return False
  if r['audience']=='line':return actor.management_profile=='line' and permits(actor,'dashboard.read')
  if r['audience']=='management':return permits(actor,'dashboard.read')
  return actor.role=='rep' or permits(actor,'dashboard.read')
 return [r for r in data if allowed(r)]

def get(actor,id):
 row=next((r for r in listing(actor) if r['id']==id),None)
 if not row:raise ApiError(404,'source_not_found','No encontramos un archivo autorizado para esta cuenta')
 path=(ROOT/row['stored']).resolve()
 if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
  raise ApiError(404,'source_not_found','El original no está disponible')
 return row,path
