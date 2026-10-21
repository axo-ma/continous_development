"""Read explicitly assigned rollout intervals; never infer logical tasks from turns."""
from __future__ import annotations

import sys as _cd5_sys
from pathlib import Path as _CD5Path
if str(_CD5Path(__file__).resolve().parent) not in _cd5_sys.path:
    _cd5_sys.path.insert(0, str(_CD5Path(__file__).resolve().parent))
try:
    from .cd5_config import config as cd5_config, memory_dir, memory_map
except ImportError:
    from cd5_config import config as cd5_config, memory_dir, memory_map


import argparse
import hashlib
import json
from pathlib import Path

try:
    from . import project_memory as pm
except ImportError:
    import project_memory as pm

FIELDS = {'input': 'input_tokens', 'cached_input': 'cached_input_tokens',
          'output': 'output_tokens', 'reasoning': 'reasoning_output_tokens'}


def counts(raw):
    if not isinstance(raw, dict):
        return None
    values = {k: raw.get(v) for k, v in FIELDS.items()}
    if any(type(v) is not int or v < 0 for v in values.values()):
        return None
    if values['cached_input'] > values['input'] or values['reasoning'] > values['output']:
        return None
    values['uncached_input'] = values['input'] - values['cached_input']
    return values


def participant(spec, owner):
    path = Path(spec['source_file']).resolve()
    first = None
    # Verify identity before examining any remaining records.
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if line.strip():
                first = json.loads(line)
                break
        if not first or first.get('type') != 'session_meta':
            raise ValueError('rollout must begin with session_meta')
        meta = first['payload']
        if meta.get('id') != spec['thread_id']:
            raise ValueError('thread identity mismatch')
        if spec['thread_id'] != owner:
            parent = spec.get('parent_thread_id', owner)
            spawn = (meta.get('source') or {})
            spawn = spawn.get('subagent', {}).get('thread_spawn', {}) if isinstance(spawn, dict) else {}
            if meta.get('parent_thread_id') != parent or spawn.get('parent_thread_id') != parent:
                raise ValueError('unverified child parent')
        rows = [first] + [json.loads(line) for line in stream if line.strip()]
    lo, hi = spec['baseline_ordinal'], spec['end_ordinal']
    if type(lo) is not int or type(hi) is not int or lo < 0 or hi <= lo:
        raise ValueError('explicit ordered baseline/end ordinals required')
    selected = [r for r in rows if type(r.get('ordinal')) is int and lo <= r['ordinal'] <= hi]
    ordinals = [r['ordinal'] for r in selected]
    if len(ordinals) != len(set(ordinals)) or ordinals != sorted(ordinals):
        raise ValueError('duplicate or unordered source ordinals')
    snapshots, contexts, turns = [], [], []
    selected_starts = set()
    model = effort = turn = None
    for row in rows:
        p = row.get('payload', {})
        if row.get('type') == 'turn_context':
            model, effort = p.get('model'), p.get('effort')
            turn = p.get('turn_id')
        if type(row.get('ordinal')) is not int or not lo <= row['ordinal'] <= hi:
            continue
        if row.get('type') == 'event_msg' and p.get('type') == 'token_count':
            info = p.get('info') or {}
            snapshots.append((row, counts(info.get('total_token_usage'))))
            last = counts(info.get('last_token_usage'))
            contexts.append({'ordinal': row['ordinal'], 'timestamp': row.get('timestamp'),
                             'turn_id': turn, 'model': model, 'reasoning': effort,
                             'reported_last_request_input': last['input'] if last else None,
                             'context_window': info.get('model_context_window')})
        if row.get('type') == 'event_msg' and p.get('type') == 'task_complete':
            turns.append({'turn_id': p.get('turn_id'), 'started_at': p.get('started_at'),
                          'completed_at': p.get('completed_at'),
                          'elapsed_in_turn_ms': p.get('duration_ms') if p.get('turn_id') in selected_starts else None})
        if row.get('type') == 'event_msg' and p.get('type') == 'task_started':
            selected_starts.add(p.get('turn_id'))
    # The final usage snapshot commonly precedes task_complete. Attribute that
    # measured duration only when the matching start is inside the interval and
    # no further token snapshot or new turn occurs before the completion marker.
    timing_rows = []
    for row in rows:
        if type(row.get('ordinal')) is not int or row['ordinal'] <= hi:
            continue
        p = row.get('payload', {})
        if row.get('type') != 'event_msg':
            continue
        if p.get('type') in {'task_started', 'token_count'}:
            break
        if p.get('type') == 'task_complete':
            if p.get('turn_id') in selected_starts and not any(t['turn_id'] == p.get('turn_id') for t in turns):
                turns.append({'turn_id': p.get('turn_id'), 'started_at': p.get('started_at'),
                              'completed_at': p.get('completed_at'), 'elapsed_in_turn_ms': p.get('duration_ms')})
                timing_rows.append(row)
            break
    baseline = next((c for r, c in snapshots if r['ordinal'] == lo), None)
    ending = next((c for r, c in snapshots if r['ordinal'] == hi), None)
    valid = [c for _, c in snapshots if c is not None]
    reset = any(any(b[k] < a[k] for k in FIELDS) for a, b in zip(valid, valid[1:]))
    complete = baseline is not None and ending is not None and not reset and len(valid) == len(snapshots)
    inconsistent = False
    if complete:
        delta = {k: ending[k] - baseline[k] for k in FIELDS}
        inconsistent = delta['cached_input'] > delta['input'] or delta['reasoning'] > delta['output']
        complete = not inconsistent
    usage = {k: ending[k] - baseline[k] if complete else None
             for k in (*FIELDS, 'uncached_input')}
    return {'thread_id': spec['thread_id'], 'role': spec['role'],
            'parent_thread_id': spec.get('parent_thread_id', owner) if spec['thread_id'] != owner else None,
            'agent_path': spec.get('agent_path'), 'turn_ids': sorted({c['turn_id'] for c in contexts if c['turn_id']}),
            'source_file': str(path),
            'selected_events_sha256': hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
            'baseline_ordinal': lo, 'end_ordinal': hi, 'baseline': baseline, 'ending': ending,
            'usage': usage, 'coverage': 'bounded_interval' if complete else 'partial',
            'counter_reset': reset, 'inconsistent_delta': inconsistent, 'context_observations': contexts,
            'request_count': None, 'request_count_note': 'snapshots may repeat; not a call count',
            'completed_turns': turns, 'active_ms': None, 'tool_wait_ms': None,
            'completion_witness_sha256': hashlib.sha256(json.dumps(timing_rows, sort_keys=True).encode()).hexdigest(),
            'agent_wait_ms': None, 'human_wait_ms': None}


def collect(mapping):
    pm._safe_id(mapping['task_id'])
    owner = mapping['owner_thread_id']
    specs = mapping['participants']
    if not specs:
        raise ValueError('participants required')
    seen = set()
    for spec in specs:
        if spec['thread_id'] in seen:
            raise ValueError('one explicit interval per participant; split/revise mapping instead of overlapping')
        seen.add(spec['thread_id'])
        if spec['role'] not in {'hq', 'executor', 'helper', 'reviewer', 'consultant'}:
            raise ValueError('invalid participant role')
    by_id = {s['thread_id']: s for s in specs}
    for spec in specs:
        if spec['thread_id'] == owner:
            if spec.get('parent_thread_id') is not None:
                raise ValueError('owner cannot have a parent in this task')
            continue
        parent = spec.get('parent_thread_id', owner)
        if parent == owner:
            continue
        upstream = by_id.get(parent)
        if (spec['role'] != 'helper' or upstream is None
                or upstream['thread_id'] == spec['thread_id']
                or upstream['role'] not in {'executor', 'reviewer', 'consultant'}
                or upstream.get('parent_thread_id', owner) != owner):
            raise ValueError('only a direct main role may create a nested helper')
    return {'type': 'task_telemetry', 'task_id': mapping['task_id'],
            'owner_thread_id': owner, 'participants': [participant(s, owner) for s in specs],
            'team_total': None, 'team_total_status': 'unknown_parent_child_accounting_scope',
            'local_inference': mapping.get('local_inference'),
            'scope': 'explicit_intervals_only', 'historical': mapping.get('historical', False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--root', default='.')
    parser.add_argument('--record', action='store_true', help='append witness through memory API')
    args = parser.parse_args()
    try:
        result = collect(json.loads(Path(args.mapping).read_text(encoding='utf-8-sig')))
        if args.record:
            digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
            row = {'schema_version': 1, 'id': 'telemetry-' + digest, 'kind': 'artifact',
                   'provenance': {'source': 'verified_rollout_intervals'}, 'payload': result}
            existing = pm.query(args.root, 'evidence', row['id'], limit=1)
            if not existing:
                pm.append(args.root, 'evidence', row, 'hq')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, pm.MemoryError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
