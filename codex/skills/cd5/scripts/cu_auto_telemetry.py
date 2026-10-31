"""Read-only, anchored Control Unit telemetry. Missing proof never becomes zero."""
from __future__ import annotations

from copy import deepcopy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

try:
    from .cd5_config import config
    from . import project_memory as pm
except ImportError:
    from cd5_config import config
    import project_memory as pm

FIELDS = ('cached_input', 'uncached_input', 'output')


def _settings(root):
    units = config(root).get('control_units', {})
    settings = units.get('telemetry', {}) if isinstance(units, dict) else None
    if not isinstance(settings, dict):
        raise ValueError('control_units.telemetry must be an object')
    return settings


def _roots(root, settings):
    supplied = settings.get('session_roots')
    if supplied is not None and (not isinstance(supplied, list) or any(not isinstance(p, str) or not p for p in supplied)):
        raise ValueError('telemetry.session_roots must be a list of paths')
    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    paths = supplied if supplied is not None else [str(home / 'sessions'), str(home / 'archived_sessions')]
    return [(Path(root) / p).resolve() if not Path(p).is_absolute() else Path(p).resolve() for p in paths]


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _header(path):
    try:
        with path.open(encoding='utf-8-sig') as stream:
            row = json.loads(next(line for line in stream if line.strip()))
        return row if isinstance(row, dict) and row.get('type') == 'session_meta' and isinstance(row.get('payload'), dict) and isinstance(row['payload'].get('id'), str) else None
    except (OSError, ValueError, StopIteration):
        return None


def _index(root, settings, thread=None):
    found = {}
    for directory in _roots(root, settings):
        if not directory.is_dir():
            continue
        # Native lookup remains focused when no explicit fixture roots are supplied.
        pattern = '*' + thread + '*.jsonl' if thread else '*.jsonl'
        paths = list(directory.rglob(pattern))
        if thread and settings.get('session_roots') is not None and not paths:
            paths = list(directory.rglob('*.jsonl'))
        for path in paths:
            header = _header(path)
            if header and (not thread or header['payload']['id'] == thread):
                found.setdefault(header['payload']['id'], []).append(path)
    return found


def _counts(raw):
    if not isinstance(raw, dict):
        return None
    values = [raw.get(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')]
    if any(type(value) is not int or value < 0 for value in values) or values[1] > values[0]:
        return None
    reasoning = raw.get('reasoning_output_tokens')
    if reasoning is not None and (type(reasoning) is not int or not 0 <= reasoning <= values[2]):
        return None
    return dict(zip(FIELDS, (values[1], values[0] - values[1], values[2])))


def _read(path):
    rows, turns, snapshots, active, source_errors = [], [], [], None, []
    try:
        raw = path.read_bytes()
        raw_lines = raw.splitlines(keepends=True)
        lines = [line.decode('utf-8-sig').rstrip('\r\n') for line in raw_lines]
    except (OSError, UnicodeError):
        return None
    prefix = hashlib.sha256()
    for position, line in enumerate(lines, 1):
        prefix.update(raw_lines[position - 1])
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            source_errors.append('unreadable_source_prefix')
            if active:
                active['diagnostics'].append('unreadable_source_row')
            continue
        if not isinstance(row, dict) or not isinstance(row.get('payload', {}), dict):
            source_errors.append('invalid_source_prefix')
            if active:
                active['diagnostics'].append('invalid_source_row')
            continue
        row['_position'] = position
        row['_sha256'] = hashlib.sha256(line.encode('utf-8')).hexdigest()
        row['_prefix_sha256'] = prefix.hexdigest()
        rows.append(row)
        payload = row.get('payload', {})
        kind = payload.get('type') if row.get('type') == 'event_msg' else None
        if kind == 'task_started':
            if active:
                active['diagnostics'].append('missing_task_complete')
            active = {'id': payload.get('turn_id'), 'start': row, 'end': None, 'snapshots': [],
                      'baseline': snapshots[-1] if snapshots else None, 'models': set(), 'efforts': set(), 'diagnostics': list(source_errors)}
            turns.append(active)
        elif row.get('type') == 'turn_context' and active:
            if payload.get('model'):
                active['models'].add(payload['model'])
            if payload.get('effort'):
                active['efforts'].add(payload['effort'])
        elif kind == 'token_count':
            info = payload.get('info')
            snap = {'row': row, 'counts': _counts(info.get('total_token_usage') if isinstance(info, dict) else None)}
            total = info.get('total_token_usage') if isinstance(info, dict) else None
            last = info.get('last_token_usage') if isinstance(info, dict) else None
            if (active and active['baseline'] is None and not snapshots and not source_errors
                    and rows[0].get('type') == 'session_meta' and rows[0]['_position'] == 1
                    and snap['counts'] is not None and _counts(last) == snap['counts'] and total == last
                    and all(type(v) is int and v >= 0 for v in total.values())):
                active['baseline'] = {'row': row, 'counts': dict.fromkeys(FIELDS, 0),
                                      'derived': 'initial_baseline_from_total_equals_last'}
            snapshots.append(snap)
            if active:
                active['snapshots'].append(snap)
        elif kind == 'task_complete' and active:
            if payload.get('turn_id') != active['id']:
                active['diagnostics'].append('completion_identity_mismatch')
            else:
                active['end'] = row
                active = None
    if not rows or rows[0].get('type') != 'session_meta':
        return None
    return {'path': str(path), 'meta': rows[0]['payload'], 'rows': rows, 'turns': turns}


def _capture_anchor(root, thread_id):
    """Capture an observed active turn, never fabricate one from a timestamp."""
    settings = _settings(root)
    if settings.get('enabled') is False or not isinstance(thread_id, str) or not thread_id:
        return None
    paths = _index(root, settings, thread_id).get(thread_id, [])
    if len(paths) != 1:
        return None
    session = _read(paths[0])
    if not session or session['meta'].get('id') != thread_id or not session['turns']:
        return None
    turn = session['turns'][-1]
    if turn['end'] or not turn['id'] or turn['diagnostics']:
        return None
    return {'schema_version': 1, 'thread_id': thread_id, 'turn_id': turn['id'], 'source_file': session['path'],
            'start_position': turn['start']['_position'], 'start_sha256': turn['start']['_sha256'],
            'prefix_sha256': turn['start']['_prefix_sha256'],
            'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat()}


def capture_anchor(root, thread_id):
    """Optional telemetry must never prevent canonical CU metadata recording."""
    try:
        return _capture_anchor(root, thread_id)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _anchor(row, sessions):
    anchor = row['payload'].get('auto_anchor')
    if not isinstance(anchor, dict) or anchor.get('thread_id') != row.get('provenance', {}).get('caller_thread_id'):
        return None
    session = sessions.get(anchor['thread_id'])
    # Native archival moves the journal without changing its identity or bytes.
    # The unique indexed session plus the saved prefix/start witnesses proves
    # continuity; its old absolute filename is provenance, not an identity key.
    if not session:
        return None
    for index, turn in enumerate(session['turns']):
        if (turn['id'] == anchor.get('turn_id') and turn['start']['_position'] == anchor.get('start_position')
                and turn['start']['_sha256'] == anchor.get('start_sha256')):
            if turn['start']['_prefix_sha256'] == anchor.get('prefix_sha256'):
                return anchor['thread_id'], index
    return None


def _claims(events, sessions):
    try:
        from .cu_cost_ledger import exact_claims
    except ImportError:
        from cu_cost_ledger import exact_claims
    units, claims, registered, _ = exact_claims(events, sessions, _anchor)
    return units, claims, registered


def _measure(session, indices, person, diagnostics=()):
    notes, usage, models, efforts, duration, durations = list(diagnostics), dict.fromkeys(FIELDS, 0), set(), set(), 0, []
    witnesses = []
    for index in sorted(indices):
        turn = session['turns'][index]
        notes.extend(turn['diagnostics']); models.update(turn['models']); efforts.update(turn['efforts'])
        if len(turn['models']) != 1:
            notes.append('missing_or_mixed_models')
        baseline, ending = turn['baseline'], turn['snapshots'][-1] if turn['snapshots'] else None
        sequence = ([baseline] if baseline else []) + turn['snapshots']
        valid = baseline and ending and all(s['counts'] is not None for s in sequence)
        if not baseline:
            notes.append('missing_counter_baseline')
        if not ending:
            notes.append('missing_counter_snapshot')
        if valid:
            valid = all(all(b['counts'][k] >= a['counts'][k] for k in FIELDS) for a, b in zip(sequence, sequence[1:]))
            if not valid:
                notes.append('counter_reset_or_contradiction')
        else:
            notes.append('missing_or_invalid_counter')
        if not turn['end']:
            notes.append('pending_turn')
        if valid:
            for key in FIELDS:
                usage[key] += ending['counts'][key] - baseline['counts'][key]
        measured = (turn['end'] or {}).get('payload', {}).get('duration_ms')
        if type(measured) is int and measured >= 0:
            duration += measured; durations.append(measured)
        else:
            notes.append('missing_measured_duration')
        witnesses.append({'turn_id': turn['id'], 'start_position': turn['start']['_position'],
                          'end_position': (turn['end'] or {}).get('_position'), 'start_sha256': turn['start']['_sha256'],
                          'end_sha256': (turn['end'] or {}).get('_sha256'),
                          'baseline_sha256': baseline['row']['_sha256'] if baseline else None,
                          'baseline_kind': baseline.get('derived', 'observed_snapshot') if baseline else None,
                          'ending_sha256': ending['row']['_sha256'] if ending else None})
        first = baseline['row']['_position'] if baseline else turn['start']['_position']
        last = (turn['end'] or (ending or {}).get('row') or turn['start'])['_position']
        witnesses[-1]['selected_events_sha256'] = hashlib.sha256(''.join(
            r['_sha256'] for r in session['rows'] if first <= r['_position'] <= last).encode()).hexdigest()
    if not indices:
        notes.append('no_verified_turns')
    if len(models) != 1:
        notes.append('missing_or_mixed_models')
    complete = not any(note not in ('unregistered_discovered_child', 'missing_measured_duration') for note in notes)
    # A running turn already contains measured request counters. Preserve their
    # observed delta as partial coverage instead of hiding it until completion.
    # Ambiguous attribution, resets and missing/model evidence still invalidate it.
    observed = bool(indices) and not any(note not in (
        'unregistered_discovered_child', 'missing_measured_duration', 'pending_turn') for note in notes)
    return {**deepcopy(person), 'participant_id': session['meta']['id'], 'thread_id': session['meta']['id'],
            'name': person.get('name') or 'Участник', 'role': person.get('role') or 'роль не указана',
            'model': next(iter(models)) if len(models) == 1 else None,
            'reasoning': next(iter(efforts)) if len(efforts) == 1 else None,
            'usage': usage if complete or observed else dict.fromkeys(FIELDS), 'coverage': 'complete' if complete else 'partial',
            'elapsed_ms': duration if len(durations) == len(indices) and indices else None,
            'exclusive_scope': False, 'telemetry_diagnostics': sorted(set(notes)),
            'telemetry_provenance': {'source_file': session['path'], 'turns': witnesses,
                                     'observed_through': ending['row'].get('timestamp') if indices and ending else None,
                                     'method': 'anchored_full_turn_deltas'}}


def _spawn(meta):
    source = meta.get('source') or {}
    subagent = source.get('subagent') if isinstance(source, dict) else None
    spawn = subagent.get('thread_spawn') if isinstance(subagent, dict) else None
    return spawn if isinstance(spawn, dict) else {}


def _request_scoped(session, indices):
    """Verify owned request deltas, excluding inherited fork totals and repeats.

Native last_token_usage is the local model response usage. Each cumulative
advance must equal it; parent-inclusive or unexplained jumps fail this proof.
"""
    observed = False
    for index in indices:
        turn = session['turns'][index]
        prior = turn.get('baseline')
        if not prior or prior.get('counts') is None:
            return False
        previous = prior['counts']
        for snapshot in turn['snapshots']:
            current = snapshot.get('counts')
            if current is None:
                return False
            if current == previous:
                continue
            info = snapshot['row'].get('payload', {}).get('info') or {}
            local = _counts(info.get('last_token_usage'))
            delta = {key: current[key] - previous[key] for key in FIELDS}
            if local is None or any(value < 0 for value in delta.values()) or local != delta:
                return False
            observed = True
            previous = current
    return observed


def _child(session, parent, parent_turns):
    meta = session['meta']; spawn = _spawn(meta)
    if meta.get('parent_thread_id') != parent or spawn.get('parent_thread_id') != parent:
        return False
    created = _stamp(meta.get('timestamp'))
    if not created:
        return False
    return any(_within(created, t) for t in parent_turns)


def _observed_end(turn):
    """Bound unfinished native turns by observed counters, never wall time."""
    row = turn['end'] or (turn['snapshots'][-1]['row'] if turn['snapshots'] else turn['start'])
    return _stamp(row.get('timestamp'))


def _within(stamp, turn):
    start, end = _stamp(turn['start'].get('timestamp')), _observed_end(turn)
    return bool(stamp and start and end and start <= stamp <= end)


def _resolve_registered_people(units, sessions):
    """Resolve explicit paths only with unique native identity and ancestry proof."""
    registered = {}
    for cu, unit in units.items():
        resolved = {}
        for identity, person in unit['people'].items():
            path = person.get('agent_path') or (identity if identity.startswith('/') else None)
            parent = person.get('parent_thread_id')
            matches = [key for key, session in sessions.items() if path and parent
                       and session['meta'].get('agent_path') == path
                       and _spawn(session['meta']).get('agent_path') == path
                       and session['meta'].get('parent_thread_id') == parent
                       and _spawn(session['meta']).get('parent_thread_id') == parent]
            actual = matches[0] if identity not in sessions and len(matches) == 1 else identity
            if actual != identity:
                person = {**person, 'registered_identity': identity}
            resolved[actual] = person
            registered.setdefault(actual, set()).add(cu)
        unit['people'] = resolved
    return registered


def resolve_agent_identity(root, agent_path, parent_thread_id):
    """Resolve a canonical task path to one proven native UUID, read-only."""
    if not isinstance(agent_path, str) or not agent_path.startswith('/') or not parent_thread_id:
        raise ValueError('an exact canonical agent path and parent thread are required')
    matches = []
    for identity, paths in _index(root, _settings(root)).items():
        if len(paths) != 1:
            continue
        header = _header(paths[0])
        meta = header['payload'] if header else {}
        if (meta.get('agent_path') == agent_path and _spawn(meta).get('agent_path') == agent_path
                and meta.get('parent_thread_id') == parent_thread_id
                and _spawn(meta).get('parent_thread_id') == parent_thread_id):
            matches.append(identity)
    if len(matches) != 1:
        raise ValueError('cannot resolve one native worker for this exact agent path and parent; retry after its native session header exists, or supply its verified thread UUID')
    return matches[0]


def _sessions(root, settings, events):
    """Index headers, but read bodies only for anchored HQs and proven descendants."""
    paths = _index(root, settings)
    headers = {identity: _header(files[0]) for identity, files in paths.items() if len(files) == 1}
    headers = {identity: h['payload'] for identity, h in headers.items() if h}
    eligible = {r.get('payload', {}).get('auto_anchor', {}).get('thread_id') for r in events
                if isinstance(r.get('payload', {}).get('auto_anchor'), dict)} & headers.keys()
    eligible.update(r.get('payload', {}).get('turn_anchor', {}).get('thread_id') for r in events
                    if isinstance(r.get('payload', {}).get('turn_anchor'), dict))
    eligible.update(r.get('payload', {}).get('participant', {}).get('thread_id') for r in events
                    if isinstance(r.get('payload', {}).get('participant'), dict))
    eligible.intersection_update(headers.keys())
    related = set(eligible)
    changed = True
    while changed:
        changed = False
        for identity, meta in headers.items():
            parent = meta.get('parent_thread_id')
            if parent not in eligible:
                continue
            related.add(identity)
            if identity not in eligible and _spawn(meta).get('parent_thread_id') == parent:
                eligible.add(identity); changed = True
    sessions = {identity: _read(paths[identity][0]) for identity in eligible}
    sessions = {identity: s for identity, s in sessions.items() if s and s['meta'].get('id') == identity}
    for identity in related - eligible:
        sessions[identity] = {'path': str(paths[identity][0]), 'meta': headers[identity], 'rows': [], 'turns': []}
    # Forked helper journals may replay parent turn markers without counters.
    # Exact native parent turn IDs prove those are inherited context, not work
    # performed by the child. Preserve source rows and never discard counted work.
    inherited = {}
    for identity, session in sessions.items():
        parent = session['meta'].get('parent_thread_id')
        if parent in sessions and _spawn(session['meta']).get('parent_thread_id') == parent:
            ids = {turn['id'] for turn in sessions[parent]['turns']}
            inherited[identity] = {t['id'] for t in session['turns'] if t['id'] in ids and not t['snapshots']}
    for identity, ids in inherited.items():
        sessions[identity]['turns'] = [t for t in sessions[identity]['turns'] if t['id'] not in ids]
    return sessions


def enrich_report(root, data, events):
    """Pure unique source-turn ledger; never infer ownership from CU lifetime."""
    settings = _settings(root)
    if settings.get('enabled') is False or not any(r.get('payload', {}).get('auto_anchor') or r.get('payload', {}).get('turn_anchor') for r in events):
        return deepcopy(data)
    sessions = _sessions(root, settings, events)
    independent = False
    evidence = settings.get('independent_scope_evidence')
    if evidence:
        try:
            independent = bool(pm.select(root, 'evidence', [evidence], full=True))
        except (ValueError, OSError, pm.MemoryError):
            pass
    try:
        from .cu_cost_ledger import build, apply
    except ImportError:
        from cu_cost_ledger import build, apply
    import sys
    ledger=build(events, sessions, sys.modules[__name__], independent)
    if ledger['units'] and all(u['manual'] for u in ledger['units'].values()):
        return deepcopy(data)
    return apply(data, ledger)
