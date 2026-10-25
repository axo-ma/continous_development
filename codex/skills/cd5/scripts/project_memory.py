"""Five-file project memory API. Roles are caller assertions, not cryptographic identity."""
from __future__ import annotations

import sys as _cd5_sys
from pathlib import Path as _CD5Path
if str(_CD5Path(__file__).resolve().parent) not in _cd5_sys.path:
    _cd5_sys.path.insert(0, str(_CD5Path(__file__).resolve().parent))
try:
    from .cd5_config import config as cd5_config, memory_dir, memory_map
except ImportError:
    from cd5_config import config as cd5_config, memory_dir, memory_map

import argparse, hashlib, json, os, tempfile, time, re, datetime, math
from pathlib import Path

FILES={'outline':'OUTLINE.md','checkpoint':'CHECKPOINT.json','evidence':'EVIDENCE.jsonl','knowledge':'KNOWLEDGE.jsonl','attention':'ATTENTION.jsonl'}
ROLE_WRITES={'hq':{'outline','checkpoint','knowledge','attention','evidence'},'executor':{'evidence'},'helper':{'evidence'},'reviewer':{'evidence'}}
class MemoryError(ValueError): pass
ID_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$')
def _safe_id(value):
 if not isinstance(value,str) or not ID_RE.fullmatch(value): raise MemoryError('id must use 1-160 safe letters, digits, dot, underscore, colon, or hyphen')
 return value
def _migration_lock(base): return memory_dir(base)/'.memory-migration.lock'
def _assert_no_migration(base):
 if _migration_lock(base).exists(): raise MemoryError('five-file migration is in progress; writes are paused')

def _base(root):
 p=Path(root).resolve(strict=True)
 if not p.is_dir(): raise MemoryError('root must be a directory')
 return p

def _path(root,kind):
 if kind not in FILES: raise MemoryError('unknown memory kind')
 p=(memory_dir(root)/FILES[kind]).resolve()
 if not p.is_relative_to(root): raise MemoryError('path escape')
 return p

def _lock(path,timeout=10):
 lock=path.with_suffix(path.suffix+'.lock'); lock.parent.mkdir(parents=True,exist_ok=True)
 end=time.monotonic()+timeout
 while True:
  try:
   fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.write(fd,str(os.getpid()).encode()); os.close(fd); return lock
  except FileExistsError:
   if time.monotonic()>end: raise MemoryError('timed out waiting for memory lock')
   time.sleep(.05)

def _atomic(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp): os.unlink(tmp)

def _jsonl(path):
 rows=[]; ids=set()
 if not path.exists(): return rows
 with path.open('r',encoding='utf-8-sig') as f:
  for n,line in enumerate(f,1):
   if not line.strip(): raise MemoryError(f'blank JSONL row {n}')
   try: row=json.loads(line)
   except json.JSONDecodeError as e: raise MemoryError(f'invalid JSONL row {n}: {e}')
   rid=row.get('id')
   _safe_id(rid) if rid is not None else (_ for _ in ()).throw(MemoryError(f'missing id at row {n}'))
   if rid in ids: raise MemoryError(f'duplicate id {rid}')
   ids.add(rid); rows.append(row)
 return rows

def evidence_history(root):
 """Archive-aware explicit lookup; normal context queries still read only hot records."""
 try:
  from .cu_archive import evidence_rows
 except ImportError:
  from cu_archive import evidence_rows
 return evidence_rows(root)

def _validate_checkpoint(cp, root=None):
 if not isinstance(cp,dict) or cp.get('schema_version')!=3: raise MemoryError('CHECKPOINT must use schema_version 3')
 expected=memory_map(root or Path.cwd())
 if cp.get('memory')!=expected: raise MemoryError('CHECKPOINT memory map must name exactly the five canonical files')
 owner=cp.get('owner',{})
 if owner.get('role')!=cd5_config(root or Path.cwd())['owner_role'] or not owner.get('thread_id'): raise MemoryError('CHECKPOINT must preserve configured owner role and thread_id')
 if not isinstance(cp.get('next_action'),dict) or not cp['next_action'].get('kind'): raise MemoryError('CHECKPOINT requires one structured next_action')
 stop=cp.get('user_stop')
 if not isinstance(stop,dict) or not isinstance(stop.get('active'),bool): raise MemoryError('CHECKPOINT user_stop.active must be explicit boolean')
 if stop.get('active') and cp['next_action'].get('kind')!='wait_user': raise MemoryError('active user STOP requires wait_user next_action')
 continuity=cp.get('continuity',{})
 if continuity and continuity.get('quota_stop_used_percent')!=90: raise MemoryError('current continuity quota threshold must remain 90%')
 return cp

def _chat_budget_error(value):
 if not isinstance(value,dict): return 'invalid_chat_budget'
 if type(value.get('limit')) is not int or value['limit'] not in {2,3}: return 'counter_mismatch_or_invalid_limit'
 if type(value.get('used')) is not int or value['used']<0 or not isinstance(value.get('stages'),dict): return 'counter_mismatch_or_invalid_limit'
 for stage in value['stages'].values():
  if (not isinstance(stage,dict) or type(stage.get('weight')) is not int
      or stage.get('weight') not in {1,2,3} or stage.get('disposition') not in {'accepted','blocker_saved'}):
   return 'invalid_recorded_stage'
 if sum(x['weight'] for x in value['stages'].values())!=value['used']: return 'counter_mismatch_requires_review'
 return None

def chat_budget_policy(cp, caller_thread_id, stage_id=None, disposition=None, *,
                       return_count=0, log_chars=0, dispute=False,
                       context_used_percent=None, role_violation=False,
                       manual_refresh=False, premature_compaction=False,
                       accepted_handoff=False, safe_boundary=False,
                       workers_status='unknown'):
 """Pure bounded HQ rotation policy. Caller persists the returned budget with CHECKPOINT."""
 if not isinstance(accepted_handoff,bool) or not isinstance(safe_boundary,bool):
  return {'action':'inspect','reason':'handoff_and_boundary_flags_must_be_boolean','chat_budget':cp.get('chat_budget')}
 if any(not isinstance(flag,bool) for flag in (dispute,role_violation,manual_refresh,premature_compaction)) or not isinstance(workers_status,str):
  return {'action':'inspect','reason':'policy_flags_or_worker_status_invalid','chat_budget':cp.get('chat_budget')}
 owner=cp.get('owner',{}).get('thread_id')
 if not owner or caller_thread_id!=owner:
  return {'action':'inspect','reason':'caller_is_not_checkpoint_owner','chat_budget':cp.get('chat_budget')}
 old=cp.get('chat_budget')
 if old is None:
  budget={'owner_thread_id':owner,'limit':3,'used':0,'stages':{},'rotation_pending':False}
  if accepted_handoff:
   budget['initialized_after_handoff']=True
 else:
  validation_error=_chat_budget_error(old)
  if validation_error:
   return {'action':'inspect','reason':validation_error,'chat_budget':old}
 if old is not None and old.get('owner_thread_id')!=owner:
  if not accepted_handoff:
   return {'action':'inspect','reason':'owner_changed_without_confirmed_handoff','chat_budget':old}
  inherited_limit=old.get('limit',3)
  if type(inherited_limit) is not int or inherited_limit not in {2,3}:
   return {'action':'inspect','reason':'prior_owner_budget_limit_requires_review','chat_budget':old}
  budget={'owner_thread_id':owner,'limit':inherited_limit,'used':0,'stages':{},'rotation_pending':False,'initialized_after_handoff':True}
 elif old is not None:
  budget=dict(old); budget['stages']=dict(old['stages'])

 # User STOP and explicit whole-goal completion always outrank rotation.
 if cp.get('user_stop',{}).get('active'):
  return {'action':'stop','reason':'user_stop','chat_budget':budget}
 if cp.get('goal_status') in {'complete','verified_complete'}:
  return {'action':'stop','reason':'goal_complete','chat_budget':budget}
 if premature_compaction is True:
  budget['limit']=max(2,budget['limit']-1)
  budget['calibration']='reduced_after_observed_premature_compaction'
 if manual_refresh is True:
  budget['rotation_pending']=True; budget['rotation_reason']='manual_refresh'
 if role_violation is True and not budget.get('role_violation_confirmed'):
  budget['role_violation_confirmed']=True
  budget['rotation_pending']=True; budget['rotation_reason']='first_confirmed_role_violation'
 if context_used_percent is not None:
  if type(context_used_percent) not in {int,float} or not math.isfinite(context_used_percent):
   return {'action':'inspect','reason':'invalid_context_telemetry','chat_budget':budget}
  telemetry=float(context_used_percent)
  if not 0<=telemetry<=100:
   return {'action':'inspect','reason':'context_telemetry_out_of_range','chat_budget':budget}
  if telemetry>=65:
   budget['rotation_pending']=True; budget.setdefault('rotation_reason','context_telemetry_65_percent')

 if stage_id is not None:
  if not isinstance(stage_id,str) or not ID_RE.fullmatch(stage_id):
   raise MemoryError('stage_id must use 1-160 safe letters, digits, dot, underscore, colon, or hyphen')
  if disposition not in {'accepted','blocker_saved'}:
   raise MemoryError('only accepted or blocker_saved stages may be recorded')
  existing=budget['stages'].get(stage_id)
  if existing is None:
   if type(return_count) is not int or return_count<0 or type(log_chars) is not int or log_chars<0 or not isinstance(dispute,bool):
    return {'action':'inspect','reason':'invalid_stage_weight_inputs','chat_budget':budget}
   returns=return_count; logs=log_chars
   weight=3 if returns>2 else 2 if returns>0 or logs>=8000 or dispute else 1
   budget['stages'][stage_id]={'weight':weight,'disposition':disposition}
   budget['used']+=weight
  elif existing.get('disposition')!=disposition:
   return {'action':'inspect','reason':'stage_id_reused_with_different_disposition','chat_budget':budget}

 if budget.get('used',0)>=budget['limit']:
  budget['rotation_pending']=True; budget.setdefault('rotation_reason','bounded_budget_reached')
 active=workers_status not in {'idle','none','completed'}
 if budget.get('rotation_pending'):
  if not safe_boundary or active:
   return {'action':'rotation_pending','reason':'wait_for_safe_boundary_or_known_idle_workers','chat_budget':budget}
  return {'action':'rotate','reason':budget.get('rotation_reason'),'chat_budget':budget}
 return {'action':'continue','reason':'budget_allows_next_useful_step','chat_budget':budget}

def validate(root):
 base=_base(root); findings={}
 for kind in FILES:
  if not _path(base,kind).is_file(): raise MemoryError(f'missing canonical file: {FILES[kind]}')
 for kind in ['evidence','knowledge','attention']:
  rows=_jsonl(_path(base,kind)); findings[kind]={'count':len(rows),'ids':len({x['id'] for x in rows})}
 for x in evidence_history(base):
  if x.get('schema_version')!=1 or not isinstance(x.get('provenance'),dict) or 'payload' not in x: raise MemoryError('evidence envelopes require schema_version 1, payload, and provenance')
  if x.get('kind') not in {'experiment_event','artifact','source'}: raise MemoryError(f"unsupported evidence kind: {x.get('kind')}")
  if x.get('kind')=='experiment_event' and (not isinstance(x.get('payload'),dict) or x['payload'].get('event_id')!=x['id']): raise MemoryError('experiment event id must match payload event_id')
 for x in _jsonl(_path(base,'knowledge')):
  if x.get('schema_version')!=1 or not isinstance(x.get('kind'),str) or not x['kind']: raise MemoryError('knowledge entries require schema_version 1 and kind')
 for x in _jsonl(_path(base,'attention')):
  if x.get('schema_version')!=1: raise MemoryError('attention entries require schema_version 1')
 for row in _jsonl(_path(base,'attention')):
  if row.get('kind')=='attention_archive_ref': _archived_attention(base,row)
  elif row.get('kind')!='attention_item': raise MemoryError(f"unsupported attention kind: {row.get('kind')}")
 cp=_validate_checkpoint(json.loads(_path(base,'checkpoint').read_text(encoding='utf-8-sig')), base)
 evidence_ids={x['id'] for x in evidence_history(base)}
 for row in _jsonl(_path(base,'knowledge')):
  for ref in row.get('refs',[]):
   if not isinstance(ref,dict) or _safe_id(ref.get('id')) not in evidence_ids: raise MemoryError(f'unresolved evidence reference {ref}')
 findings['checkpoint']={'schema_version':3,'memory_map':'exact-five'}
 return findings

def query(root,kind,terms,limit=20,include_closed=False):
 base=_base(root)
 if kind not in ('evidence','knowledge','attention'): raise MemoryError('query supports evidence, knowledge, attention')
 words=str(terms).casefold().split(); rows=_jsonl(_path(base,kind))
 if kind=='attention' and not include_closed: rows=[r for r in rows if r.get('status')!='closed']
 hits=[]
 for row in rows:
  if kind=='attention' and row.get('kind')=='attention_archive_ref' and include_closed: row=_archived_attention(base,row)
  hay=json.dumps(row,ensure_ascii=False).casefold()
  score=sum(w in hay for w in words)
  if score: hits.append((score,row))
 hits.sort(key=lambda x:(-x[0],x[1]['id']))
 out=[r for _,r in hits[:max(1,min(int(limit),100))]]
 legacy_id=str(terms).strip()
 duplicates=[r for r in rows if r.get('provenance',{}).get('legacy_id')==legacy_id]
 if len(duplicates)>1:
  ambiguity={'source_id':legacy_id,'occurrences':len(duplicates),'ids':[r['id'] for r in duplicates]}
  out=[({**r,'legacy_id_ambiguity':ambiguity} if r in duplicates else r) for r in out]
 return out

_MILESTONE_RE=re.compile(r'^\s*-\s*\[([ xX])\]\s+`([A-Za-z0-9][A-Za-z0-9_.:-]{0,159})`\s*[—-]\s*(.+?)\s*$')
def _outline_milestones(text):
 """Read explicit list or heading milestones in a bounded plan section."""
 milestones=[]; section_level=None; current=None; field=None; fenced=False
 aliases={'planned':'planned','not_started':'planned','впереди':'planned','запланирована':'planned',
          'in_progress':'in_progress','в работе':'in_progress','начата':'in_progress',
          'blocked':'blocked','заблокирована':'blocked',
          'complete':'complete','completed':'complete','завершена':'complete'}
 for line in text.splitlines():
  if re.match(r'^\s*(```|~~~)',line): fenced=not fenced; continue
  if fenced: continue
  heading=re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$',line)
  if heading:
   level=len(heading.group(1)); title=heading.group(2)
   if title.casefold() in {'milestones','project milestones','вехи','вехи проекта'}:
    section_level=level; current=None; continue
   if section_level is None: continue
   if level<=section_level: section_level=None; current=None; continue
   match=re.match(r'`?(MS-[A-Za-z0-9_-]+)`?[.\s:—-]+(.+)$',title,re.I)
   if match:
    current={'id':match.group(1),'title':match.group(2),'status':'unknown','criteria':[],'latest_change':None}
    milestones.append(current); field=None
   else: current=None
   continue
  if section_level is None: continue
  match=_MILESTONE_RE.match(line)
  if match:
   current={'id':match.group(2),'title':match.group(3),'status':'complete' if match.group(1).strip().casefold()=='x' else 'planned','criteria':[],'latest_change':None}
   milestones.append(current); field=None; continue
  if current is None: continue
  label=re.match(r'^\s*(?:-\s+)?(?:\*\*)?([^:*]+):(?:\*\*)?\s*(.*)$',line)
  if label and ('**' in line or label.group(1).strip().casefold() in {'status','criteria','completion criteria','latest change'}):
   key=label.group(1).strip().casefold(); value=label.group(2).strip(); field=None
   if key in {'status','статус'}:
    value=value.casefold()
    current['status']=next((status for name,status in aliases.items()
                            if re.match(re.escape(name)+r'(?:$|[.\s;,:(])',value)), 'unknown')
   elif key in {'criteria','completion criteria','критерий завершения','критерии завершения'}:
    field='criteria'
    if value: current['criteria'].append(value)
   elif key in {'latest change','последнее изменение'}: current['latest_change']=value
  elif field=='criteria' and line.strip():
   current['criteria'].append(re.sub(r'^\s*-\s+', '', line).strip())
 return milestones


def progress_view(root,milestone_id=None,limit=10):
 """Return bounded progress from explicit OUTLINE milestones and accepted KNOWLEDGE task results."""
 base=_base(root); outline=_path(base,'outline').read_text(encoding='utf-8-sig')
 all_milestones=_outline_milestones(outline); diagnostics=[]
 milestones=all_milestones
 if milestone_id is not None:
  _safe_id(milestone_id)
  milestones=[m for m in all_milestones if m['id']==milestone_id]
  if not milestones: diagnostics.append({'kind':'unknown_milestone','milestone_id':milestone_id})
 evidence_ids={r['id'] for r in evidence_history(base)}
 rows=[r for r in _jsonl(_path(base,'knowledge')) if r.get('kind')=='task_result']
 latest={}; superseded=set(); revisions={}; latest_order={}
 for row_index,row in enumerate(rows):
  if row.get('status')!='accepted':
   diagnostics.append({'kind':'unaccepted_task_result','record_id':row['id'],'status':row.get('status')})
   continue
  task_id=row.get('task_id'); mid=row.get('milestone_id'); refs=row.get('refs',[])
  if not isinstance(task_id,str) or not ID_RE.fullmatch(task_id):
   diagnostics.append({'kind':'invalid_task_id','record_id':row['id']}); continue
  if not isinstance(mid,str) or not ID_RE.fullmatch(mid) or mid not in {m['id'] for m in all_milestones}:
   diagnostics.append({'kind':'unknown_milestone','record_id':row['id'],'milestone_id':mid}); continue
  if not isinstance(refs,list) or not refs:
   diagnostics.append({'kind':'missing_evidence_refs','record_id':row['id']}); continue
  missing=[ref.get('id') if isinstance(ref,dict) else None for ref in refs if not isinstance(ref,dict) or ref.get('id') not in evidence_ids]
  if missing:
   diagnostics.append({'kind':'unresolved_evidence_refs','record_id':row['id'],'evidence_ids':missing}); continue
  if any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('goal','result','meaning')):
   diagnostics.append({'kind':'incomplete_task_result','record_id':row['id']}); continue
  older=latest.get(task_id)
  if older is not None: superseded.add(older['id'])
  latest[task_id]=row; revisions[task_id]=revisions.get(task_id,0)+1; latest_order[task_id]=row_index
  # Revisions are scoped to the same stable task_id. Arbitrary supersedes IDs
  # must never hide accepted results from a different logical task.
 accepted=[r for r in latest.values() if r['id'] not in superseded]
 if milestone_id is not None and not milestones: accepted=[]
 elif milestone_id is not None: accepted=[r for r in accepted if r.get('milestone_id')==milestone_id]
 result=[]
 for milestone in milestones:
  linked=sorted((r for r in accepted if r.get('milestone_id')==milestone['id']),key=lambda r:latest_order[r['task_id']],reverse=True)
  shown=linked[:max(1,min(int(limit),100))]
  tasks=[]
  for r in shown:
   task={'task_id':r['task_id'],'goal':r['goal'],'result':r['result'],'meaning':r['meaning'],'evidence_ids':[x['id'] for x in r['refs']],'accepted_revision_count':revisions[r['task_id']]}
   for key in ('parent_task_id','executor','started_at','ended_at','time','usage','local_inference','cost_attribution','category'):
    if key in r: task[key]=r[key]
   tasks.append(task)
  result.append({**milestone,'accepted_task_count':len(linked),'omitted_task_count':max(0,len(linked)-len(shown)),'tasks':tasks})
 has_structured=bool(accepted)
 return {'source':'OUTLINE.md + structured KNOWLEDGE task_result records','structured_progress_available':has_structured,'message':None if has_structured else 'structured task progress not yet indexed','milestones':result,'diagnostics':diagnostics,'percentage':None}

def _attention_archive_rel(event_id, root):
 name=hashlib.sha256(event_id.encode('utf-8')).hexdigest()+'.json'
 return cd5_config(root)['memory_dir']+'/archive/attention/'+name

def _archived_attention(base,tombstone):
 if tombstone.get('kind')!='attention_archive_ref': return tombstone
 rel=tombstone.get('archive_path')
 if rel!=_attention_archive_rel(tombstone.get('id',''), base): raise MemoryError('attention archive path does not match hashed ID path')
 if not isinstance(rel,str): raise MemoryError('attention tombstone lacks archive_path')
 path=(base/rel).resolve()
 if not path.is_relative_to(base) or not path.is_file(): raise MemoryError('attention archive path is missing or escapes workspace')
 data=json.loads(path.read_text(encoding='utf-8'))
 record=data.get('record')
 if data.get('kind')!='closed_attention_archive' or data.get('id')!=tombstone['id'] or not isinstance(record,dict): raise MemoryError('invalid attention archive record')
 digest=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if digest!=data.get('record_sha256') or digest!=tombstone.get('record_sha256'): raise MemoryError('attention archive hash mismatch')
 return record

def select(root,kind,ids,full=False,include_closed=False):
 base=_base(root); ids=[_safe_id(i) for i in ids]; all_rows=_jsonl(_path(base,kind)); all_by={r['id']:r for r in all_rows}
 if kind=='evidence' and any(i not in all_by for i in ids):
  all_by={r['id']:r for r in evidence_history(base)}
 by=all_by
 if kind=='attention' and not include_closed: by={i:r for i,r in all_by.items() if r.get('status')!='closed'}
 missing=[i for i in ids if i not in by and i not in all_by]
 if missing: raise MemoryError('unknown IDs: '+', '.join(missing))
 result=[]
 for i in ids:
  if i not in by: continue
  row=by[i]
  if kind=='attention' and row.get('kind')=='attention_archive_ref': row=_archived_attention(base,row)
  result.append(row if full else {k:v for k,v in row.items() if k not in ('payload','text','event')})
 return result

def pending_attention(root):
 """Return only current actionable attention records from the canonical register."""
 base=_base(root); rows=_jsonl(_path(base,'attention')); out=[]
 for row in rows:
  if row.get('kind')!='attention_item' or row.get('status') in {'closed','nonblocking'}: continue
  payload=row.get('payload') if isinstance(row.get('payload'),dict) else row.get('event')
  payload=payload if isinstance(payload,dict) else {}
  if payload.get('status')=='nonblocking': continue
  if row.get('id','').casefold().startswith('demo-') or payload.get('demo') is True: continue
  question=payload.get('question')
  if not isinstance(question,str) or not question.strip(): continue
  title=payload.get('title')
  if not isinstance(title,str) or not title.strip(): title='Вопрос требует ответа'
  blocking=(row.get('status')=='blocking' or payload.get('blocking') is True
            or payload.get('status')=='blocking')
  refs=[]
  for key in ('source_refs','sources','refs'):
   value=payload.get(key)
   if isinstance(value,list): refs.extend(x for x in value if isinstance(x,str) and x.strip())
  for key in ('report','source'):
   value=payload.get(key)
   if isinstance(value,str) and value.strip(): refs.append(value)
  item={'id':row['id'],'status':'blocking' if blocking else 'needs_answer',
        'title':title.strip(),'question':question.strip(),'source_refs':list(dict.fromkeys(refs))}
  out.append(item)
 return sorted(out,key=lambda item:item['id'])

def append(root,kind,row,role):
 base=_base(root); _assert_no_migration(base)
 if not isinstance(row,dict): raise MemoryError('row must be an object')
 if kind not in ROLE_WRITES.get(role,set()): raise MemoryError(f'role {role} cannot append {kind}')
 if kind not in ('evidence','knowledge','attention'): raise MemoryError('append supports JSONL catalogues')
 if kind=='evidence' and row.get('kind') not in {'experiment_event','artifact','source'}: raise MemoryError('evidence kind must be experiment_event, artifact, or source')
 if kind=='evidence' and row.get('schema_version',1)!=1: raise MemoryError('evidence schema_version must be 1')
 if kind=='evidence' and 'payload' not in row: raise MemoryError('evidence envelope requires payload')
 if kind=='knowledge' and (not isinstance(row.get('kind'),str) or not row['kind']): raise MemoryError('knowledge record requires a kind')
 if kind=='attention' and row.get('kind') not in {'attention_item','attention_archive_ref'}: raise MemoryError('attention kind must be attention_item or an HQ archive ref')
 if kind=='evidence' and not isinstance(row.get('provenance'),dict): raise MemoryError('evidence envelope requires provenance')
 row=dict(row); row.setdefault('schema_version',1)
 _safe_id(row.get('id'))
 p=_path(base,kind); lock=_lock(p)
 try:
  _assert_no_migration(base)
  rows=_jsonl(p)
  known_rows=evidence_history(base) if kind=='evidence' else rows
  if any(x['id']==row['id'] for x in known_rows): raise MemoryError(f"duplicate id {row['id']}")
  if kind=='evidence' and row.get('kind')=='experiment_event':
   payload=row.get('payload')
   if not isinstance(payload,dict) or payload.get('event_id')!=row['id']: raise MemoryError('experiment_event payload event_id must equal envelope id')
   import importlib.util
   validator_path=Path(__file__).with_name('experiment_registry.py')
   spec=importlib.util.spec_from_file_location('_project_memory_registry_validator',validator_path)
   registry=importlib.util.module_from_spec(spec); spec.loader.exec_module(registry)
   try: registry._validate_event(payload)
   except Exception as exc: raise MemoryError(f'invalid experiment_event payload: {exc}') from exc
  if kind=='knowledge':
   evidence_ids={x['id'] for x in evidence_history(base)}
   for ref in row.get('refs',[]):
    if not isinstance(ref,dict) or _safe_id(ref.get('id')) not in evidence_ids: raise MemoryError(f'unresolved evidence reference {ref}')
  line=(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
  with p.open('ab') as f: f.write(line); f.flush(); os.fsync(f.fileno())
 finally: lock.unlink(missing_ok=True)
 return row

def write_checkpoint(root,value,role):
 base=_base(root); _assert_no_migration(base)
 if role!='hq': raise MemoryError('only HQ may write CHECKPOINT')
 _validate_checkpoint(value, base)
 p=_path(base,'checkpoint'); lock=_lock(p)
 try:
  _assert_no_migration(base)
  _atomic(p,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
  # Operational lifecycle mirrors canonical HQ saves only for opted-in projects.
  # Failure is visible; fingerprint admission prevents stale-state continuation.
  try:
   from .planner_control import sync_checkpoint
  except ImportError:
   from planner_control import sync_checkpoint
  sync_checkpoint(base,value)
 finally: lock.unlink(missing_ok=True)
 return value

def update_attention(root,event_id,mutator,role='hq'):
 base=_base(root); _assert_no_migration(base)
 if role!='hq': raise MemoryError('only HQ may update attention items')
 p=_path(base,'attention'); lock=_lock(p)
 try:
  _assert_no_migration(base)
  rows=_jsonl(p); found=None
  for row in rows:
   if row['id']==event_id: found=row; break
  if found is None: raise MemoryError('attention ID not found')
  if found.get('kind')=='attention_archive_ref' or found.get('status')=='closed': raise MemoryError('closed attention item cannot be updated')
  updated=mutator(dict(found))
  if updated.get('id')!=event_id: raise MemoryError('attention ID is immutable')
  rows=[updated if row['id']==event_id else row for row in rows]
  _atomic(p,(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows)).encode())
  return updated
 finally: lock.unlink(missing_ok=True)

def record_attention_click(root,event_id):
 """Record a user request/click without treating it as approval or gold."""
 import datetime as _dt
 def change(row):
  if isinstance(row.get('request_record'),dict) and row['request_record'].get('status')=='requested': return row
  event=row.get('event') or row.get('payload') or {}
  row['request_record']={'status':'requested','requested_at':_dt.datetime.now(_dt.timezone.utc).isoformat(),'event_snapshot_sha256':event.get('snapshot_sha256'),'interpretation':'request click is not approval or human gold'}
  return row
 return update_attention(root,event_id,change,role='hq')

def archive_attention(root,event_id,role):
 base=_base(root); _assert_no_migration(base); event_id=_safe_id(event_id)
 if role!='hq': raise MemoryError('only HQ may archive attention items')
 p=_path(base,'attention'); lock=_lock(p)
 try:
  _assert_no_migration(base)
  rows=_jsonl(p); found=None
  for row in rows:
   if row['id']==event_id: found=row; break
  if found is None: raise MemoryError('attention ID not found')
  if found.get('kind')=='attention_archive_ref': return _archived_attention(base,found)
  if found.get('status')=='closed': raise MemoryError('closed row requires migration to an archive reference')
  closed=dict(found); closed.update({'status':'closed','closed_by':'hq','closed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
  rel=_attention_archive_rel(event_id, base)
  archive=(base/rel).resolve()
  if not archive.is_relative_to(base): raise MemoryError('archive path escape')
  archive.parent.mkdir(parents=True,exist_ok=True)
  digest=hashlib.sha256(json.dumps(closed,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  record={'schema_version':1,'id':event_id,'kind':'closed_attention_archive','record':closed,'record_sha256':digest}
  data=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode()
  if archive.exists():
   saved=json.loads(archive.read_text(encoding='utf-8')); old=saved.get('record',{})
   compare_old=dict(old); compare_new=dict(closed); compare_old.pop('closed_at',None); compare_new.pop('closed_at',None)
   if saved.get('id')!=event_id or compare_old!=compare_new: raise MemoryError('archive path exists with different content; refusing overwrite')
   closed=old; digest=saved['record_sha256']
  else:
   fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
   with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
  tombstone={'schema_version':1,'id':event_id,'kind':'attention_archive_ref','status':'closed','archive_path':rel,'record_sha256':digest,'closed_at':closed['closed_at']}
  rows=[tombstone if row['id']==event_id else row for row in rows]
  _atomic(p,(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows)).encode())
  return closed
 finally: lock.unlink(missing_ok=True)

def main(argv=None):
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--root',required=True); sub=ap.add_subparsers(dest='cmd',required=True)
 sub.add_parser('validate')
 q=sub.add_parser('query'); q.add_argument('kind',choices=['evidence','knowledge','attention']); q.add_argument('terms'); q.add_argument('--limit',type=int,default=20); q.add_argument('--include-closed',action='store_true')
 s=sub.add_parser('select'); s.add_argument('kind',choices=['evidence','knowledge','attention']); s.add_argument('--id',action='append',required=True); s.add_argument('--full',action='store_true'); s.add_argument('--include-closed',action='store_true')
 apn=sub.add_parser('append'); apn.add_argument('kind',choices=['evidence','knowledge','attention']); apn.add_argument('--record-file',required=True); apn.add_argument('--role',required=True)
 wc=sub.add_parser('write-checkpoint'); wc.add_argument('--input-file',required=True); wc.add_argument('--role',required=True)
 ar=sub.add_parser('archive-attention'); ar.add_argument('--id',required=True); ar.add_argument('--role',required=True)
 pr=sub.add_parser('progress'); pr.add_argument('--milestone',help='show one stable milestone ID'); pr.add_argument('--limit',type=int,default=10)
 sub.add_parser('pending-attention')
 a=ap.parse_args(argv)
 try:
  out=validate(a.root) if a.cmd=='validate' else query(a.root,a.kind,a.terms,a.limit,a.include_closed) if a.cmd=='query' else select(a.root,a.kind,a.id,a.full,a.include_closed) if a.cmd=='select' else pending_attention(a.root) if a.cmd=='pending-attention' else progress_view(a.root,a.milestone,a.limit) if a.cmd=='progress' else append(a.root,a.kind,json.loads(Path(a.record_file).read_text(encoding='utf-8')),a.role) if a.cmd=='append' else write_checkpoint(a.root,json.loads(Path(a.input_file).read_text(encoding='utf-8')),a.role) if a.cmd=='write-checkpoint' else archive_attention(a.root,a.id,a.role)
  print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
 except (MemoryError,OSError,json.JSONDecodeError) as e: ap.error(str(e)); return 2
if __name__=='__main__': raise SystemExit(main())
