"""Deterministic per-source-turn costs and assignments; CU state never owns a range."""
from copy import deepcopy
import hashlib

FIELDS = ('cached_input', 'uncached_input', 'output')
REASONS = {
    'no_exact_assignment': 'Для этого хода нет подтверждённого назначения работе.',
    'conflicting_assignments': 'Один ход отмечен у нескольких работ; требуется исправление назначения.',
    'unverified_assignment': 'Не удалось проверить исходный ход поручения.',
    'child_reused_without_assignment': 'Чат использован в нескольких работах без границ нового поручения.',
    'ancestry_not_verified': 'Не подтверждена связь помощника с поручением.',
    'missing_counter': 'В исходном журнале нет достаточного счётчика или модели.',
    'scope_not_verified': 'Не доказано, что счётчики родителя и помощника независимы.',
    'pending_turn': 'Ход ещё выполняется; учтены только уже записанные счётчики.',
}


def point(anchor, sessions):
    if not isinstance(anchor, dict):
        return None
    thread = anchor.get('thread_id')
    for index, turn in enumerate(sessions.get(thread, {}).get('turns', [])):
        start = turn['start']
        if (turn['id'] == anchor.get('turn_id') and start['_position'] == anchor.get('start_position')
                and start['_sha256'] == anchor.get('start_sha256')
                and start['_prefix_sha256'] == anchor.get('prefix_sha256')):
            return thread, index
    return None


def exact_claims(events, sessions, verified_anchor):
    units, claims, registered = {}, {}, {}
    assignments, overrides = {}, {}
    for row in sorted(events, key=lambda r: r.get('payload', {}).get('sequence', 0)):
        p = row.get('payload', {})
        if p.get('type') != 'control_unit_event':
            continue
        cu, action = p['cu_id'], p['action']
        u = units.setdefault(cu, dict(selected=set(), diagnostics=[], active=None, manual=False, people={}))
        if action == 'measurement':
            u['manual'] = True
        if action == 'open':
            owner = p.get('owner') or dict(thread_id=row.get('provenance', {}).get('caller_thread_id'), role='hq', name='Штаб')
            u['people'][owner.get('thread_id') or owner.get('participant_id')] = owner
        if action == 'participant':
            person = p['participant']; identity = person.get('thread_id') or person.get('participant_id')
            u['people'][identity] = person
            registered.setdefault(identity, set()).add(cu)
        if action in ('open', 'status', 'bind_turn') and not p.get('historical'):
            found = verified_anchor(row, sessions)
            if found and (found[0] in u['people'] or action == 'bind_turn'):
                u['people'].setdefault(found[0], dict(thread_id=found[0], role='hq', name='Штаб'))
                claims.setdefault(found, set()).add(cu)
            elif action in ('open', 'bind_turn') or p.get('status') == 'open':
                u['diagnostics'].append('missing_or_unverified_open_anchor')
        if action == 'allocation':
            found = point(p.get('turn_anchor'), sessions)
            if found:
                # An explicit append-only correction takes precedence, retaining prior rows.
                overrides[found] = {cu} if p.get('allocated', True) else set()
        assignment = p.get('assignment')
        if isinstance(assignment, dict):
            identity = assignment['assignment_id']
            if assignment.get('operation', 'start') == 'start':
                previous = assignments.get(assignment.get('previous_assignment_id'))
                boundary = assignment.get('previous_end_anchor')
                if previous and boundary:
                    previous['end_anchor'] = boundary
                assignments[identity] = dict(assignment, cu_id=cu)
            elif identity in assignments:
                assignments[identity]['end_anchor'] = assignment.get('end_anchor')
    claims.update(overrides)
    for (thread, index), owners in claims.items():
        for cu in owners:
            units[cu]['selected'].add((thread, index))
    return units, claims, registered, assignments


def build(events, sessions, auto, independent=False):
    units, claims, registered, assignments = exact_claims(events, sessions, auto._anchor)
    registered = auto._resolve_registered_people(units, sessions)
    notes, uncertain_owners = {}, {}
    # Explicit job boundaries are child-source turns, not parent/CU calendar spans.
    explicit_threads = set()
    for assignment in assignments.values():
        start = point(assignment.get('start_anchor'), sessions)
        end = point(assignment.get('end_anchor'), sessions) if assignment.get('end_anchor') else None
        if not start or (assignment.get('end_anchor') and (not end or end[0] != start[0] or end[1] < start[1])):
            continue
        thread, first = start
        explicit_threads.add(thread)
        last = end[1] if end else len(sessions[thread]['turns'])-1
        for i in range(first, last+1):
            claims.setdefault((thread, i), set()).add(assignment['cu_id'])
    # Legacy registration is evidence for one original spawn assignment only.
    # Multiple registrations cannot allocate a reused chat's whole lifetime.
    assigned = set(explicit_threads)
    changed = True
    while changed:
        changed = False
        for thread, session in sessions.items():
            parent = session['meta'].get('parent_thread_id')
            if not parent or thread in assigned:
                continue
            spawn = auto._spawn(session['meta'])
            if spawn.get('parent_thread_id') != parent:
                notes[thread] = 'ancestry_not_verified'
                assigned.add(thread)
                continue
            owners = registered.get(thread, set())
            if len(owners) > 1:
                notes[thread] = 'child_reused_without_assignment'; uncertain_owners[thread]=set(owners); assigned.add(thread)
                continue
            if not owners:
                parent_session = sessions.get(parent, {})
                created = auto._stamp(session['meta'].get('timestamp'))
                starts = [i for i, t in enumerate(parent_session.get('turns', [])) if auto._within(created, t)]
                if len(starts) == 1:
                    owners = claims.get((parent, starts[0]), set())
                    if len(owners)>1:
                        notes[thread]='conflicting_assignments';uncertain_owners[thread]=set(owners)
            if len(owners) == 1:
                cu = next(iter(owners))
                for i in range(len(session['turns'])):
                    claims.setdefault((thread, i), set()).add(cu)
                assigned.add(thread); changed = True
    children = {s['meta'].get('parent_thread_id') for s in sessions.values() if s['meta'].get('parent_thread_id')}
    measurements = []
    for thread, session in sorted(sessions.items()):
        parent = session['meta'].get('parent_thread_id')
        connected_counter_scope = bool(parent or thread in children)
        for index, turn in enumerate(session['turns']):
            owners = claims.get((thread, index), set())
            cu = next(iter(owners)) if len(owners) == 1 else None
            person = units.get(cu, {}).get('people', {}).get(thread, {})
            role = person.get('role') or (auto._spawn(session['meta']).get('agent_role') or 'роль не указана' if parent else 'hq')
            measured = auto._measure(session, {index}, dict(person, role=role, name=person.get('name') or ('Штаб' if role == 'hq' else 'Помощник')))
            if parent and not person:
                measured['telemetry_diagnostics'].append('unregistered_discovered_child')
            scope = independent or not connected_counter_scope or auto._request_scoped(session, {index})
            reason = ('conflicting_assignments' if len(owners) > 1 else
                      notes.get(thread, 'no_exact_assignment') if cu is None else '')
            if not all(type(measured['usage'].get(k)) is int for k in FIELDS):
                reason = reason or 'missing_counter'
            elif not scope:
                reason = reason or 'scope_not_verified'
            elif measured['coverage'] != 'complete':
                reason = reason or 'pending_turn'
            key = hashlib.sha256((thread+'\0'+turn['id']).encode()).hexdigest()
            measurements.append(dict(source_key=key, thread_id=thread, turn_id=turn['id'], cu_id=cu,
                started_at=turn['start'].get('timestamp'), ended_at=(turn['end'] or (turn['snapshots'][-1]['row'] if turn['snapshots'] else turn['start'])).get('timestamp'),
                candidate_cus=sorted(owners or uncertain_owners.get(thread,set())),person=person,
                reason=reason, explanation=REASONS.get(reason, ''), model=measured['model'],
                usage=measured['usage'], coverage=measured['coverage'], exclusive_scope=scope,
                elapsed_ms=measured['elapsed_ms'], role=role, name=measured['name'],
                provenance=measured['telemetry_provenance'], diagnostics=measured['telemetry_diagnostics']))
    unique = {}
    for item in measurements:
        previous = unique.get(item['source_key'])
        if previous and previous != item:
            previous.update(cu_id=None, reason='conflicting_assignments', explanation='Повторный turn_id имеет противоречивые исходные записи.', usage=dict.fromkeys(FIELDS))
        elif previous is None:
            unique[item['source_key']] = item
    return dict(events=[unique[k] for k in sorted(unique)], assignments=list(assignments.values()),
                reasons=deepcopy(REASONS), units=units, claims=claims)


def apply(out, ledger):
    result = deepcopy(out)
    events = ledger['events']
    for unit in result['units']:
        selected = [r for r in events if r['cu_id'] == unit['cu_id']]
        if ledger['units'].get(unit['cu_id'], {}).get('manual'):
            continue  # Existing independently verified manual measurement remains authoritative.
        participants = []
        for thread in sorted({r['thread_id'] for r in selected},key=lambda t:(
                not any(r['role']=='hq' for r in selected if r['thread_id']==t),
                min((r.get('started_at') or '' for r in selected if r['thread_id']==t),default=''),t)):
            rows = [r for r in selected if r['thread_id'] == thread]
            rows.sort(key=lambda r:r['provenance']['turns'][0]['start_position'])
            models = {r['model'] for r in rows}
            complete = all(r['coverage'] == 'complete' and all(type(r['usage'][k]) is int for k in FIELDS) for r in rows)
            usage = {k: sum(r['usage'][k] for r in rows) if all(type(r['usage'][k]) is int for r in rows) else None for k in FIELDS}
            witnesses = [w for r in rows for w in r['provenance']['turns']]
            participants.append(dict(participant_id=thread, thread_id=thread, role=rows[0]['role'], name=rows[0]['name'],
                **{k:v for k,v in rows[0]['person'].items() if k not in ('participant_id','thread_id','role','name','model','usage')},
                model=next(iter(models)) if len(models) == 1 else None, usage=usage,
                coverage='complete' if complete else 'partial', exclusive_scope=all(r['exclusive_scope'] for r in rows),
                elapsed_ms=sum(r['elapsed_ms'] for r in rows) if all(r['elapsed_ms'] is not None for r in rows) else None,
                telemetry_diagnostics=sorted({n for r in rows for n in r['diagnostics']}),
                telemetry_provenance=dict(source_file=rows[0]['provenance']['source_file'], turns=witnesses, method='explicit_source_turn_assignments')))
        reasons = sorted({r['explanation'] for r in selected if r['explanation']})
        if not selected:
            reasons = ['Нет подтверждённых назначений измеренных ходов этой работе.']
        missing_people = set(ledger['units'].get(unit['cu_id'], {}).get('people', {})) - {r['thread_id'] for r in selected}
        if missing_people:
            reasons.append('У зарегистрированного участника нет подтверждённых ходов поручения.')
        disputed=[r for r in events if r['cu_id'] is None and unit['cu_id'] in r.get('candidate_cus',[])]
        for thread in sorted({r['thread_id'] for r in disputed}):
            rows=[r for r in disputed if r['thread_id']==thread]
            diagnostic='ambiguous_turn_claim' if rows[0]['role']=='hq' else ('child_reused_across_control_units' if rows[0]['reason']=='child_reused_without_assignment' else 'ambiguous_parent_turn_claim')
            existing = next((p for p in participants if p['thread_id'] == thread), None)
            if existing is not None:
                existing['telemetry_diagnostics'] = sorted(set(existing['telemetry_diagnostics'] + [diagnostic]))
                reasons.append(rows[0]['explanation'])
                continue
            participants.append(dict(participant_id=thread,thread_id=thread,role=rows[0]['role'],name=rows[0]['name'],
                model=rows[0]['model'],usage=dict.fromkeys(FIELDS),coverage='partial',exclusive_scope=False,
                elapsed_ms=None,telemetry_diagnostics=[diagnostic],telemetry_provenance={'method':'unallocated_conflict'}))
            reasons.append(rows[0]['explanation'])
        complete = bool(participants) and not reasons and all(p['coverage'] == 'complete' and p['exclusive_scope'] for p in participants)
        unit.update(participants=participants, usage={k:sum(p['usage'][k] for p in participants) if complete else None for k in FIELDS},
                    accounting_scope='confirmed_source_assignments',
                    usage_status='complete' if complete else ('partial' if selected or disputed else 'unknown'),
                    accounting_reasons=reasons, telemetry_diagnostics=sorted({r['reason'] for r in selected if r['reason']}),
                    telemetry_provenance={'method':'explicit_source_turn_assignments'},
                    reported_ms=sum(p['elapsed_ms'] for p in participants if p['role']=='hq') if all(p['elapsed_ms'] is not None for p in participants if p['role']=='hq') else None)
        if 'scope_not_verified' in unit['telemetry_diagnostics']:
            unit['telemetry_diagnostics'].append('parent_child_scope_not_verified')
        if missing_people:
            unit['telemetry_diagnostics'].append('registered_participant_not_verified')
    result['accounting'] = dict(schema_version=1, events=events,
        counts=dict(measured=len(events), assigned=sum(r['cu_id'] is not None for r in events), unallocated=sum(r['cu_id'] is None for r in events)),
        manual_units_requiring_reconciliation=sorted(cu for cu,u in ledger['units'].items() if u['manual']),
        method='unique_verified_source_turns_not_cu_lifetime')
    if isinstance(result.get('scope'),dict):
        result['scope']['usage_label']='Расход проекта за всю доступную историю: назначенный и не распределённый; фильтр строк задач его не меняет'
    return result
