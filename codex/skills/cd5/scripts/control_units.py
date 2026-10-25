"""Control Units: bounded reporting groups, independent of delegation granularity."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

try:
    from . import project_memory as pm, task_telemetry, cu_budget as budgeting
    from .cd5_config import memory_dir, config
except ImportError:
    import project_memory as pm
    import task_telemetry
    import cu_budget as budgeting
    from cd5_config import memory_dir, config

FIELDS = ('cached_input', 'uncached_input', 'output')
STATES = {'open', 'paused', 'completed', 'cancelled'}
ROLES = {'hq', 'executor', 'helper', 'reviewer', 'consultant'}
TRANSITIONS = {'open': STATES, 'paused': STATES, 'completed': {'completed'}, 'cancelled': {'cancelled'}}


def _stamp(value=None):
    value = value or dt.datetime.now(dt.timezone.utc).isoformat()
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timestamps require a timezone')
    return parsed.isoformat()


def _text(value, name, required=False, maximum=32768):
    if not isinstance(value, str) or len(value.encode('utf-8')) > maximum or (required and not value.strip()):
        raise ValueError(f'{name} must be text, at most {maximum} UTF-8 bytes')
    return value


def _rows(root):
    try:
        from .cu_archive import evidence_rows
    except ImportError:
        from cu_archive import evidence_rows
    return evidence_rows(root)


def _events(root):
    rows = [r for r in _rows(root) if isinstance(r.get('payload'), dict)
            and r['payload'].get('type') == 'control_unit_event']
    return sorted(rows, key=lambda r: r['payload'].get('sequence', 0))


def _owner(root, caller_thread_id):
    cp = json.loads((memory_dir(root) / 'CHECKPOINT.json').read_text(encoding='utf-8-sig'))
    if cp.get('owner', {}).get('thread_id') != caller_thread_id:
        raise ValueError('only the current CD5 owner may change Control Units')
    return cp


def _source(value):
    if not isinstance(value, dict):
        raise ValueError('source must be an object')
    out = {'label': _text(value.get('label', 'Источник'), 'source label', maximum=512)}
    for key in ('path', 'text', 'thread_id', 'turn_id'):
        if key in value:
            out[key] = _text(value[key], 'source '+key)
    # A path is a reference, never an instruction to read or execute a file.
    return out


def _person(value):
    if not isinstance(value, dict):
        raise ValueError('participant must be an object')
    role = value.get('role')
    if role not in ROLES:
        raise ValueError('invalid participant role')
    thread = pm._safe_id(value.get('thread_id'))
    parent = value.get('parent_thread_id')
    if parent is not None:
        pm._safe_id(parent)
    return {'participant_id': thread, 'thread_id': thread, 'parent_thread_id': parent,
            'name': _text(value.get('name', role), 'participant name', required=True, maximum=512),
            'role': role, 'model': value.get('model'), 'reasoning': value.get('reasoning'),
            'agent_path': value.get('agent_path')}


def _units(rows):
    units = {}
    task_links = {}
    for row in rows:
        p = row['payload']; key = p['cu_id']; action = p['action']; stamp = p['at']
        if action == 'open':
            if key in units:
                raise ValueError('duplicate Control Unit open event: '+key)
            owner = p.get('owner') or _person({'thread_id': row['provenance']['caller_thread_id'], 'name': 'Штаб', 'role': 'hq'})
            units[key] = {'cu_id': key, 'title': p['title'], 'goal': p['goal'],
                          'description': p.get('description', ''), 'result': '', 'result_detail': '',
                          'status': 'open', 'started_at': stamp, 'ended_at': None,
                          'milestone_id': p.get('milestone_id'), 'historical': p.get('historical', False),
                          'sources': p.get('sources', []), 'people': {owner['participant_id']: owner}, 'measurements': [],
                          'task_ids': [], 'state_at': stamp, 'event_ids': [row['id']],
                          'budget': budgeting.initial_budget()}
            if 'budget' in p:
                units[key]['budget'] = budgeting.apply_patch(units[key]['budget'], p['budget'], at=stamp,
                                                             event_id=row['id'], initial=True)
            if 'forecast_unknown_reason' in p:
                units[key]['budget']['forecast_unknown_reason'] = p['forecast_unknown_reason']
            continue
        if key not in units:
            raise ValueError('Control Unit event has no open event: '+key)
        u = units[key]; u['event_ids'].append(row['id'])
        if action == 'status':
            status = p['status']
            if status not in TRANSITIONS[u['status']]:
                raise ValueError('closed Control Units cannot silently reopen')
            latest = max([u['state_at']] + [h['at'] for h in u['budget']['history']], key=dt.datetime.fromisoformat)
            if dt.datetime.fromisoformat(stamp) < dt.datetime.fromisoformat(latest):
                raise ValueError('Control Unit status timestamps must be ordered')
            u.update(status=status, state_at=stamp)
            if 'result' in p:
                u['result'] = p['result']
            if 'result_detail' in p:
                u['result_detail'] = p['result_detail']
            u['ended_at'] = stamp if status in {'completed', 'cancelled'} else None
            u['sources'].extend(p.get('sources', []))
        elif action == 'participant':
            person = p['participant']; previous = u['people'].get(person['participant_id'])
            if previous and (previous['role'], previous.get('parent_thread_id')) != (person['role'], person.get('parent_thread_id')):
                raise ValueError('participant identity/ancestry cannot change')
            u['people'][person['participant_id']] = person
        elif action == 'link_task':
            task = p['task_id']
            if task in task_links and task_links[task] != key:
                raise ValueError('a task cannot be counted under two Control Units')
            task_links[task] = key
            if task not in u['task_ids']:
                u['task_ids'].append(task)
        elif action == 'measurement':
            u['measurements'].append(p)
        elif action == 'budget':
            if u['status'] in {'completed', 'cancelled'}:
                raise ValueError('closed Control Unit budgets cannot be rewritten after the result')
            latest = max([u['state_at']] + [h['at'] for h in u['budget']['history']], key=dt.datetime.fromisoformat)
            if dt.datetime.fromisoformat(stamp) < dt.datetime.fromisoformat(latest):
                raise ValueError('budget revisions must be timestamp ordered')
            u['budget'] = budgeting.apply_patch(u['budget'], p['budget'], at=stamp, event_id=row['id'])
    return units


def record(root, data, caller_thread_id):
    """Owner-only metadata mutation; never changes CHECKPOINT, STOP or acceptance."""
    root = pm._base(root); _owner(root, caller_thread_id)
    cu_id = pm._safe_id(data.get('cu_id')); event_id = pm._safe_id(data.get('event_id'))
    action = data.get('action')
    if action not in {'open', 'status', 'participant', 'link_task', 'budget'}:
        raise ValueError('action must be open, status, participant, link_task or budget')
    payload = {'type': 'control_unit_event', 'action': action, 'cu_id': cu_id}
    def budget_patch():
        values = dict(data)
        record_id = 'cu-' + hashlib.sha256(event_id.encode()).hexdigest()
        existing = next((row for row in _events(root) if row['id'] == record_id), None)
        saved = (existing or {}).get('payload', {}).get('budget', {})
        if isinstance(values.get('forecast'), dict) and isinstance(saved.get('forecast'), dict):
            values['forecast'] = dict(values['forecast'])
            if 'rate_date' not in values['forecast']:
                values['forecast']['rate_date'] = saved['forecast']['rate_date']
        if 'limit' in values and 'limit_rate_date' not in values and 'limit_rate_date' in saved:
            values['limit_rate_date'] = saved['limit_rate_date']
        return budgeting.normalize_patch(values)
    if action == 'open':
        payload.update(title=_text(data.get('title'), 'title', True, 512),
                       goal=_text(data.get('goal'), 'goal', True, 4096),
                       description=_text(data.get('description', ''), 'description'))
        if data.get('milestone_id'):
            payload['milestone_id'] = pm._safe_id(data['milestone_id'])
        payload['historical'] = data.get('historical') is True
        payload['owner'] = _person({'thread_id': caller_thread_id, 'name': 'Штаб', 'role': 'hq',
                                    'model': data.get('model'), 'reasoning': data.get('reasoning')})
        if 'forecast' in data or 'limit' in data:
            payload['budget'] = budget_patch()
        if 'forecast_unknown_reason' in data:
            if data.get('forecast') is not None:
                raise ValueError('supply a forecast range or an unknown reason, not both')
            payload['forecast_unknown_reason'] = _text(data['forecast_unknown_reason'], 'forecast unknown reason', True, 4096)
    elif action == 'status':
        if data.get('status') not in STATES:
            raise ValueError('invalid status')
        payload['status'] = data['status']
        for key in ('result', 'result_detail'):
            if key in data:
                payload[key] = _text(data[key], key, key == 'result' and data['status'] == 'completed')
        if data['status'] == 'completed' and not payload.get('result'):
            raise ValueError('completed CU requires a result; pause is not completion')
    elif action == 'participant':
        person = data.get('participant')
        if isinstance(person, dict) and not person.get('thread_id') and person.get('agent_path'):
            try:
                from .cu_auto_telemetry import resolve_agent_identity
            except ImportError:
                from cu_auto_telemetry import resolve_agent_identity
            parent = person.get('parent_thread_id') or caller_thread_id
            person = {**person, 'parent_thread_id': parent,
                      'thread_id': resolve_agent_identity(root, person['agent_path'], parent)}
        payload['participant'] = _person(person)
    elif action == 'budget':
        _text(data.get('reason'), 'budget revision reason', True, 4096)
        payload['budget'] = budget_patch()
    else:
        payload['task_id'] = pm._safe_id(data.get('task_id'))
    if 'sources' in data:
        if not isinstance(data['sources'], list) or len(data['sources']) > 30:
            raise ValueError('sources must be a bounded list')
        payload['sources'] = [_source(v) for v in data['sources']]
    return _append(root, payload, event_id, data.get('at'), caller_thread_id)


def _append(root, payload, event_id, at, caller):
    lock = pm._lock(memory_dir(root) / '.control-units')
    try:
        _owner(root, caller)
        rows = _events(root); record_id = 'cu-' + hashlib.sha256(event_id.encode()).hexdigest()
        old = next((r for r in rows if r['id'] == record_id), None)
        # Capture the caller turn once; retries keep the original attribution.
        historical = payload.get('historical') is True
        if payload['action'] == 'status':
            historical = _units(rows).get(payload['cu_id'], {}).get('historical', False)
        if not old and not historical and payload['action'] == 'open':
            if not payload.get('budget', {}).get('forecast'):
                raise ValueError('new CU requires a numeric whole-team forecast range: --forecast-low and --forecast-high; uncertainty requires a wider justified range, not forecast_unknown_reason; no WU limit is required')
        existing_unit = _units(rows).get(payload['cu_id'], {})
        if not old and payload['action'] == 'budget':
            patch = payload.get('budget', {})
            if ('forecast' in patch and patch['forecast'] is None) or payload.get('forecast_unknown_reason'):
                raise ValueError('active work requires a numeric whole-team forecast; revise the range instead of clearing it')
        if payload['action'] in {'open', 'status'} and not historical:
            if old:
                if 'auto_anchor' in old['payload']:
                    payload['auto_anchor'] = old['payload']['auto_anchor']
            else:
                try:
                    from .cu_auto_telemetry import capture_anchor
                except ImportError:
                    from cu_auto_telemetry import capture_anchor
                anchor = capture_anchor(root, caller)
                if anchor is not None:
                    if payload['action'] == 'open' or payload.get('status') == 'open':
                        conflicts = sorted({r['payload']['cu_id'] for r in rows
                            if r['payload']['cu_id'] != payload['cu_id']
                            and isinstance(r['payload'].get('auto_anchor'), dict)
                            and r['payload']['auto_anchor'].get('thread_id') == anchor.get('thread_id')
                            and r['payload']['auto_anchor'].get('turn_id') == anchor.get('turn_id')})
                        if conflicts:
                            raise ValueError('this owner turn already belongs to CU '+', '.join(conflicts)+
                                '; continue that CU or begin the next CU in a new user turn so factual usage can be attributed')
                    payload['auto_anchor'] = anchor
        payload = {**payload, 'at': _stamp(at or (old['payload']['at'] if old else None)),
                   'sequence': old['payload']['sequence'] if old else max((r['payload'].get('sequence', 0) for r in rows), default=0)+1}
        row = {'schema_version': 1, 'id': record_id, 'kind': 'artifact',
               'provenance': {'source': 'control_units', 'event_id': event_id, 'caller_thread_id': caller},
               'payload': payload}
        if old:
            if old['payload'] != payload:
                raise ValueError('event ID already used with different content')
            return old
        if payload['action'] == 'measurement':
            _check_intervals(_units(rows), payload['cu_id'], payload['telemetry'])
        _units(rows + [row])
        policy = config(root).get('control_units', {})
        if not isinstance(policy, dict):
            raise ValueError('control_units configuration must be an object')
        for field, default in [('keep_active_events', 300), ('max_active_bytes', 262144)]:
            if type(policy.get(field, default)) is not int or policy.get(field, default) < 0:
                raise ValueError('invalid Control Unit archive limit: '+field)
        saved = pm.append(root, 'evidence', row, 'hq')
        try:
            from .cu_archive import archive_evidence
        except ImportError:
            from cu_archive import archive_evidence
        hot = [r for r in pm._jsonl(memory_dir(root)/'EVIDENCE.jsonl')
               if isinstance(r.get('payload'), dict) and r['payload'].get('type', '').startswith('control_unit')]
        hot_bytes = sum(len((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode()) for r in hot)
        cap_count, cap_bytes = policy.get('keep_active_events', 300), policy.get('max_active_bytes', 262144)
        if len(hot) > cap_count or hot_bytes > cap_bytes:
            # Batch retirement avoids one archive file for every subsequent event.
            archive_evidence(root, int(cap_count*.75), int(cap_bytes*.75), cu_only=True, apply=True)
        return saved
    finally:
        lock.unlink(missing_ok=True)


def _check_intervals(units, cu_id, result):
    for other in units.values():
        for previous in other['measurements']:
            for a in previous['telemetry']['participants']:
                for b in result['participants']:
                    overlap = (a['thread_id'] == b['thread_id']
                               and max(a['baseline_ordinal'], b['baseline_ordinal']) < min(a['end_ordinal'], b['end_ordinal']))
                    same = (other['cu_id'] == cu_id and a['baseline_ordinal'] == b['baseline_ordinal']
                            and a['end_ordinal'] == b['end_ordinal']
                            and a['selected_events_sha256'] == b['selected_events_sha256'])
                    if overlap and not same:
                        raise ValueError('overlapping telemetry interval already attributed')


def measure(root, cu_id, mapping, event_id, caller_thread_id, exclusive_scope_evidence=None):
    """Read exact assigned rollout intervals using the existing verified collector."""
    root = pm._base(root); _owner(root, caller_thread_id); pm._safe_id(cu_id); pm._safe_id(event_id)
    units = _units(_events(root))
    if cu_id not in units:
        raise ValueError('unknown Control Unit')
    result = task_telemetry.collect(mapping)
    u = units[cu_id]
    if mapping['task_id'] != cu_id and mapping['task_id'] not in u['task_ids']:
        raise ValueError('telemetry task must be explicitly linked to this Control Unit')
    for person in result['participants']:
        registered = u['people'].get(person['thread_id'])
        if registered is None or registered['role'] != person['role']:
            raise ValueError('register every measured participant before collection')
        if registered.get('parent_thread_id') != person.get('parent_thread_id'):
            raise ValueError('registered and observed ancestry disagree')
    if exclusive_scope_evidence is not None:
        pm._safe_id(exclusive_scope_evidence)
        pm.select(root, 'evidence', [exclusive_scope_evidence], full=True)
    # Rechecked under the CU lock before append, including concurrent collectors.
    _check_intervals(units, cu_id, result)
    payload = {'type': 'control_unit_event', 'action': 'measurement', 'cu_id': cu_id,
               'telemetry': result, 'exclusive_scope_evidence': exclusive_scope_evidence}
    return _append(root, payload, event_id, None, caller_thread_id)


def _report_unit(u):
    participants = []; all_durations = []
    for person in u['people'].values():
        segments = {}; proofs = {}
        for measurement in u['measurements']:
            for p in measurement['telemetry']['participants']:
                if p['thread_id'] != person['thread_id']:
                    continue
                key = (p['thread_id'], p['baseline_ordinal'], p['end_ordinal'], p['selected_events_sha256'])
                segments[key] = p
                proofs[key] = proofs.get(key, False) or bool(measurement.get('exclusive_scope_evidence'))
        pieces = list(segments.values())
        observed_models = sorted({c['model'] for piece in pieces for c in piece.get('context_observations', [])
                                  if isinstance(c.get('model'), str) and c['model']})
        observed_efforts = sorted({c['reasoning'] for piece in pieces for c in piece.get('context_observations', [])
                                   if isinstance(c.get('reasoning'), str) and c['reasoning']})
        complete = bool(pieces) and all(p['coverage'] == 'bounded_interval' for p in pieces)
        usage = {k: sum(p['usage'][k] for p in pieces) if complete else None for k in FIELDS}
        elapsed = [t['elapsed_in_turn_ms'] for p in pieces for t in p.get('completed_turns', [])]
        elapsed_ms = sum(elapsed) if elapsed and all(type(x) is int and x >= 0 for x in elapsed) else None
        if person['role'] == 'hq' and elapsed_ms is not None:
            all_durations.append(elapsed_ms)
        participants.append({**person,
                             'model': observed_models[0] if len(observed_models) == 1 else (None if observed_models else person.get('model')),
                             'reasoning': observed_efforts[0] if len(observed_efforts) == 1 else ('mixed' if observed_efforts else person.get('reasoning')),
                             'models_observed': observed_models, 'reasoning_observed': observed_efforts,
                             'elapsed_ms': elapsed_ms, 'usage': usage,
                             'coverage': 'complete' if complete else ('partial' if pieces else 'unknown'),
                             'exclusive_scope': bool(pieces) and all(proofs.values())})
    complete_team = bool(participants) and all(p['coverage'] == 'complete' and p['exclusive_scope'] for p in participants)
    usage = {k: sum(p['usage'][k] for p in participants) if complete_team else None for k in FIELDS}
    end = dt.datetime.fromisoformat(u['ended_at']) if u['ended_at'] else dt.datetime.now(dt.timezone.utc)
    elapsed = max(0, round((end-dt.datetime.fromisoformat(u['started_at'])).total_seconds()*1000))
    return {k: u[k] for k in ('cu_id', 'title', 'goal', 'description', 'result', 'result_detail',
                              'status', 'started_at', 'ended_at', 'milestone_id', 'historical', 'sources', 'task_ids', 'budget')} | {
        'participants': participants, 'usage': usage,
        'usage_status': 'complete' if complete_team else ('partial' if any(p['coverage'] != 'unknown' for p in participants) else 'unknown'),
        'elapsed_ms': elapsed, 'reported_ms': sum(all_durations) if all_durations else None}


def report_data(root, limit=10, *, all_units=False, since=None, until=None, auto_telemetry=True):
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError('limit must be from 1 to 10000')
    zone = dt.timezone(dt.timedelta(hours=3))
    lo = dt.datetime.combine(dt.date.fromisoformat(since), dt.time.min, zone) if since else None
    hi = dt.datetime.combine(dt.date.fromisoformat(until)+dt.timedelta(days=1), dt.time.min, zone) if until else None
    if lo and hi and lo >= hi:
        raise ValueError('since must not be after until')
    all_rows = [_report_unit(u) for u in _units(_events(root)).values()]
    rows = [r for r in all_rows if (not lo or not r['ended_at'] or dt.datetime.fromisoformat(r['ended_at']) >= lo)
            and (not hi or dt.datetime.fromisoformat(r['started_at']) < hi)]
    rows.sort(key=lambda r: (dt.datetime.fromisoformat(r['started_at']), r['cu_id']), reverse=True)
    if not (all_units or since or until):
        rows = rows[:limit]
    label = f'{since or "начала истории"} — {until or "сегодня"}' if since or until else ('За всё время' if all_units else f'Последние {limit} CU')
    result = {'schema_version': 1, 'title': 'CD5 · Progress Report', 'generated_at': _stamp(), 'units': rows,
            'scope': {'label': label, 'since': since, 'until': until, 'total_units': len(rows),
                      'usage_label': 'Расход выбранных CU за всё выполнение'},
            'covers_from': min((r['started_at'] for r in all_rows), default=None, key=dt.datetime.fromisoformat),
            'source': 'Control Unit events in EVIDENCE and its lossless archive'}
    if auto_telemetry:
        try:
            from .cu_auto_telemetry import enrich_report
        except ImportError:
            from cu_auto_telemetry import enrich_report
        result = enrich_report(root, result, _events(root))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', default='.')
    sub = parser.add_subparsers(dest='command', required=True)
    write = sub.add_parser('record'); write.add_argument('--record-file', required=True); write.add_argument('--caller-thread', required=True)
    begin = sub.add_parser('begin', help='Open one user-facing work unit; capture its current owner turn automatically')
    begin.add_argument('--cu', required=True); begin.add_argument('--title', required=True); begin.add_argument('--goal')
    begin.add_argument('--caller-thread', required=True); begin.add_argument('--source')
    budget = sub.add_parser('budget', help='Revise forecast or an independently authorized whole-team WU limit')
    budget.add_argument('--cu', required=True); budget.add_argument('--caller-thread', required=True)
    budget.add_argument('--event-id', required=True); budget.add_argument('--reason', required=True)
    for command in (begin, budget):
        command.add_argument('--forecast-unknown-reason', help='Why no defensible prospective forecast is currently available')
        command.add_argument('--forecast-low'); command.add_argument('--forecast-high')
        command.add_argument('--confidence', choices=['low', 'medium', 'high'])
        command.add_argument('--limit-wu'); command.add_argument('--clear-forecast', action='store_true')
        command.add_argument('--clear-limit', action='store_true')
    finish = sub.add_parser('finish', help='Reuse a short existing result; capture the closing owner turn automatically')
    finish.add_argument('--cu', required=True); finish.add_argument('--result', required=True)
    finish.add_argument('--caller-thread', required=True); finish.add_argument('--source')
    participant = sub.add_parser('participant', help='Register an explicit role using a canonical agent path or native thread UUID')
    participant.add_argument('--cu', required=True); participant.add_argument('--caller-thread', required=True)
    participant.add_argument('--agent-path'); participant.add_argument('--thread'); participant.add_argument('--parent')
    participant.add_argument('--role', required=True, choices=sorted(ROLES)); participant.add_argument('--name')
    collect = sub.add_parser('collect'); collect.add_argument('--cu', required=True); collect.add_argument('--mapping', required=True)
    collect.add_argument('--event-id', required=True); collect.add_argument('--caller-thread', required=True); collect.add_argument('--exclusive-scope-evidence')
    read = sub.add_parser('summary'); read.add_argument('--limit', type=int, default=10); read.add_argument('--all', action='store_true', dest='all_units')
    read.add_argument('--since'); read.add_argument('--until')
    args = parser.parse_args(argv)
    try:
        fields = {}
        if args.command in {'begin', 'budget'}:
            if args.forecast_unknown_reason:
                fields['forecast_unknown_reason'] = args.forecast_unknown_reason
            if args.clear_forecast:
                if args.forecast_low is not None or args.forecast_high is not None or args.confidence is not None:
                    raise ValueError('clearing a forecast cannot also replace it')
                fields['forecast'] = None
            elif any(v is not None for v in (args.forecast_low, args.forecast_high, args.confidence)):
                fields['forecast'] = {'low':args.forecast_low, 'high':args.forecast_high, 'confidence':args.confidence or 'low'}
            if args.clear_limit and args.limit_wu is not None:
                raise ValueError('clearing a limit cannot also replace it')
            if args.clear_limit or args.limit_wu is not None:
                fields['limit'] = None if args.clear_limit else args.limit_wu
        if args.command in {'begin', 'finish'}:
            data = {'cu_id': args.cu, 'event_id': args.command+'-'+args.cu}
            if args.command == 'begin':
                if fields.get('forecast') is None:
                    raise ValueError('begin requires --forecast-low and --forecast-high for the whole team; no WU limit is required')
                if args.forecast_unknown_reason:
                    fields['forecast_unknown_reason'] = args.forecast_unknown_reason
                data.update(action='open', title=args.title, goal=args.goal or args.title, **fields)
            else:
                data.update(action='status', status='completed', result=args.result)
            if args.source:
                data['sources'] = [{'label':'Existing brief' if args.command == 'begin' else 'Existing result', 'path':args.source}]
            saved = record(args.root, data, args.caller_thread)
            out = {'cu_id': args.cu, 'action': saved['payload']['action'],
                   'usage_anchor_captured': bool(saved['payload'].get('auto_anchor'))}
        elif args.command == 'participant':
            if not args.thread and not args.agent_path:
                raise ValueError('participant requires --agent-path or --thread')
            person = {'thread_id': args.thread, 'agent_path': args.agent_path,
                      'parent_thread_id': args.parent or args.caller_thread, 'role': args.role,
                      'name': args.name or args.role}
            identity = args.thread or args.agent_path
            event_id = 'participant-'+args.cu+'-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
            saved = record(args.root, {'action':'participant','cu_id':args.cu,'event_id':event_id,
                                      'participant':person}, args.caller_thread)
            out = {'cu_id':args.cu,'action':'participant','participant':saved['payload']['participant']}
        elif args.command == 'budget':
            saved = record(args.root, {'action':'budget', 'cu_id':args.cu, 'event_id':args.event_id,
                                       'reason':args.reason, **fields}, args.caller_thread)
            out = {'cu_id':args.cu, 'action':'budget', 'budget':saved['payload']['budget']}
        elif args.command == 'record':
            out = record(args.root, json.loads(Path(args.record_file).read_text(encoding='utf-8-sig')), args.caller_thread)
        elif args.command == 'collect':
            out = measure(args.root, args.cu, json.loads(Path(args.mapping).read_text(encoding='utf-8-sig')), args.event_id,
                          args.caller_thread, args.exclusive_scope_evidence)
        else:
            out = report_data(args.root, args.limit, all_units=args.all_units, since=args.since, until=args.until)
        print(json.dumps(out, ensure_ascii=False, indent=2)); return 0
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
