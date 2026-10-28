"""Project observations in proven native quota windows; never account-wide totals.

No journal/history writes, wall-clock window extrapolation, or model calls.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal, localcontext

try:
    from . import cu_auto_telemetry as native
    from .work_units import load_rates, price_usage
except ImportError:
    import cu_auto_telemetry as native
    from work_units import load_rates, price_usage

FIELDS = native.FIELDS
SAFE_NOTES = {'pending_turn', 'missing_measured_duration', 'unregistered_discovered_child'}


def _iso(stamp):
    return stamp.astimezone(dt.timezone.utc).isoformat() if stamp else None


def _ref(session, row):
    return {'source_file': session['path'], 'position': row['_position'], 'sha256': row['_sha256']}


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    return {}


def _quota(session, row):
    limits = row.get('payload', {}).get('rate_limits')
    if not isinstance(limits, dict):
        return None
    primary = limits.get('primary')
    if not isinstance(primary, dict) or primary.get('window_minutes') != 300:
        return None
    reset = primary.get('resets_at')
    if type(reset) is not int or reset < 0:
        return None
    try:
        end = dt.datetime.fromtimestamp(reset, dt.timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    start = end - dt.timedelta(minutes=300)
    observed = native._stamp(row.get('timestamp'))
    if not observed or not start <= observed < end:
        return None
    account = session['meta'].get('creator_account_id')
    scope = 'account:' + str(account) if account else 'session:' + session['meta']['id']
    scope_hash = hashlib.sha256(scope.encode()).hexdigest()[:16]
    limit_id = limits.get('limit_id') or 'unspecified'
    key = f'{scope_hash}:{limit_id}:{reset}'
    return {'window_id': key, 'limit_id': limit_id, 'starts_at': _iso(start), 'ends_at': _iso(end),
            'account_scope_key': scope_hash,
            'window_minutes': 300, 'account_identity_verified': bool(account),
            'boundary_method': 'observed_native_reset_and_duration',
            'reset_evidence': [_ref(session, row)], 'assignments': [], 'coverage': 'partial',
            'diagnostics': ['project_observations_only', 'not_subscription_capacity']}


def _assignment(session, turn, sessions, unit):
    """Expose only explicit parent spawn/followup messages, never thinking/system text."""
    parent_id = session['meta'].get('parent_thread_id')
    if not parent_id:
        return {'status': 'cu_context', 'text': unit.get('goal') or unit.get('title'), 'provenance': []}
    spawn = native._spawn(session['meta'])
    path = session['meta'].get('agent_path')
    parent = sessions.get(parent_id)
    same = [s for s in sessions.values() if s['meta'].get('parent_thread_id') == parent_id
            and s['meta'].get('agent_path') == path and native._spawn(s['meta']).get('agent_path') == path]
    if (not parent or not path or spawn.get('parent_thread_id') != parent_id
            or spawn.get('agent_path') != path or len(same) != 1):
        return {'status': 'unavailable', 'text': None, 'provenance': [], 'diagnostics': ['assignment_identity_not_verified']}
    started = native._stamp(turn['start'].get('timestamp'))
    index = next((i for i, item in enumerate(session['turns']) if item['id'] == turn['id']), None)
    after = native._stamp(session['turns'][index - 1]['start'].get('timestamp')) if index else None
    outputs = {r['payload'].get('call_id'): r for r in parent['rows']
               if r.get('type') == 'response_item' and r['payload'].get('type') == 'function_call_output'}
    candidates = []
    for row in parent['rows']:
        payload = row['payload']
        if row.get('type') != 'response_item' or payload.get('type') != 'function_call':
            continue
        at = native._stamp(row.get('timestamp'))
        if not at or not started or at > started or (after and at <= after):
            continue
        args = _object(payload.get('arguments'))
        name = payload.get('name', '').rsplit('.', 1)[-1]
        refs = [_ref(parent, row)]
        if name == 'spawn_agent':
            if not session['turns'] or turn['id'] != session['turns'][0]['id']:
                continue  # an old spawn brief does not describe a reused turn
            output = outputs.get(payload.get('call_id'))
            answer = _object(output['payload'].get('output')) if output else {}
            # A saved canonical result path plus unique native parent/path proof.
            if answer.get('task_name') != path:
                continue
            refs.append(_ref(parent, output))
            text = args.get('message')
        elif name == 'followup_task' and args.get('target') in (path, session['meta']['id']):
            text = args.get('message')
        else:
            continue
        if isinstance(text, str) and text.strip():
            candidates.append((at, row['_position'], text, refs, name))
    if not candidates:
        return {'status': 'unavailable', 'text': None, 'provenance': [], 'diagnostics': ['saved_assignment_unavailable']}
    _, _, text, refs, name = max(candidates, key=lambda item: (item[0], item[1]))
    return {'status': 'verified_saved_brief', 'text': text[:4000], 'truncated': len(text) > 4000,
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'kind': name, 'provenance': refs}


def _agent_result(session, turn, observed_position):
    """Use an explicit native final answer, never analysis/system/tool output."""
    end = turn['end']
    text = (end or {}).get('payload', {}).get('last_agent_message')
    row = end
    if not isinstance(text, str) or not text.strip():
        finals = [r for r in session['rows'] if turn['start']['_position'] <= r['_position'] <= observed_position
                  and r.get('type') == 'response_item' and r['payload'].get('type') == 'message'
                  and r['payload'].get('role') == 'assistant' and r['payload'].get('phase') == 'final_answer']
        row = finals[-1] if finals else None
        content = row['payload'].get('content') if row else None
        text = '\n'.join(item['text'] for item in content if isinstance(item, dict)
                         and item.get('type') == 'output_text' and isinstance(item.get('text'), str)) if isinstance(content, list) else None
    if not isinstance(text, str) or not text.strip():
        return None
    return {'text': text[:4000], 'truncated': len(text) > 4000,
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'provenance': [_ref(session, row)]}


def _selection(data, sessions):
    selected, rejected = [], []
    for unit in data.get('units', []):
        for person in unit.get('participants', []):
            identity = person.get('thread_id') or person.get('participant_id')
            session = sessions.get(identity)
            notes = set(person.get('telemetry_diagnostics', [])) - SAFE_NOTES
            witnesses = person.get('telemetry_provenance', {}).get('turns', [])
            if not session or notes or not witnesses:
                rejected.append({'cu_id': unit.get('cu_id'), 'thread_id': identity,
                                 'diagnostics': sorted(notes) or ['verified_turn_witness_unavailable']})
                continue
            for witness in witnesses:
                matches = [t for t in session['turns'] if t['id'] == witness.get('turn_id')
                           and t['start']['_position'] == witness.get('start_position')
                           and t['start']['_sha256'] == witness.get('start_sha256')]
                turn = matches[0] if len(matches) == 1 else None
                if not turn or turn['diagnostics'] or len(turn['models']) != 1:
                    rejected.append({'cu_id': unit.get('cu_id'), 'thread_id': identity,
                                     'turn_id': witness.get('turn_id'), 'diagnostics': ['turn_identity_or_model_not_verified']})
                    continue
                snapshots = turn['snapshots']
                stop = next((i for i, snap in enumerate(snapshots)
                             if snap['row']['_sha256'] == witness.get('ending_sha256')), None)
                baseline = turn['baseline']
                if stop is None or not baseline or baseline['row']['_sha256'] != witness.get('baseline_sha256'):
                    rejected.append({'cu_id': unit.get('cu_id'), 'thread_id': identity,
                                     'turn_id': turn['id'], 'diagnostics': ['counter_witness_not_verified']})
                    continue
                chosen = snapshots[:stop + 1]
                ending_position = witness.get('end_position') or chosen[-1]['row']['_position']
                source_hash = hashlib.sha256(''.join(r['_sha256'] for r in session['rows']
                    if baseline['row']['_position'] <= r['_position'] <= ending_position).encode()).hexdigest()
                ending_rows = [r for r in session['rows'] if r['_position'] == witness.get('end_position')]
                if (source_hash != witness.get('selected_events_sha256')
                        or (witness.get('end_position') and (not ending_rows or ending_rows[0]['_sha256'] != witness.get('end_sha256')))
                        or person.get('model') != next(iter(turn['models']))):
                    rejected.append({'cu_id': unit.get('cu_id'), 'thread_id': identity,
                                     'turn_id': turn['id'], 'diagnostics': ['selected_source_witness_changed']})
                    continue
                seq = [baseline, *chosen]
                if any(s['counts'] is None for s in seq) or any(
                        b['counts'][k] < a['counts'][k] for a, b in zip(seq, seq[1:]) for k in FIELDS):
                    rejected.append({'cu_id': unit.get('cu_id'), 'thread_id': identity,
                                     'turn_id': turn['id'], 'diagnostics': ['invalid_or_reset_counter']})
                    continue
                selected.append((unit, person, session, {**turn, 'end':turn['end'] if witness.get('end_position') else None}, baseline, chosen))
    return selected, rejected


def _actors(assignments, rates):
    """A native actor's requests add; distinct parent/child actors never do."""
    groups = {}
    for row in assignments:
        groups.setdefault(row['thread_id'], []).append(row)
    actors = []
    for identity, rows in groups.items():
        usage = {k: sum(row['usage'][k] for row in rows) for k in FIELDS}
        coverage = 'complete' if all(row['coverage'] == 'complete' for row in rows) else 'partial'
        roles = {row.get('role') for row in rows}
        models = sorted({row['model'] for row in rows})
        if len(models) == 1:
            cost = price_usage(models[0], usage, coverage=coverage, rates=rates)
        else:
            prices = [row['work_units'] for row in rows]
            known = [row.get('known_value') for row in prices]
            with localcontext() as context:
                context.prec = 80
                total = format(sum((Decimal(value) for value in known if value is not None), Decimal(0)), 'f') if all(value is not None for value in known) else None
            cost = {'value': total if coverage == 'complete' else None, 'known_value': total,
                    'status': coverage if total is not None else 'unknown', 'basis': prices[0]['basis'],
                    'rate_date': rates['rate_date'], 'notes': ['models_priced_in_separate_verified_turns']}
        actors.append({'thread_id': identity, 'role': next(iter(roles)) if len(roles) == 1 else None,
                       'name': rows[0].get('name'), 'models': models, 'usage': usage, 'coverage': coverage,
                       'work_units': cost, 'request_count': sum(row['request_count'] for row in rows),
                       'assignment_count': len(rows), 'observed_from': min((row['observed_from'] for row in rows if row['observed_from']), default=None),
                       'observed_through': max((row['observed_through'] for row in rows if row['observed_through']), default=None),
                       'diagnostics': ['actor_only_not_team_total'] + ([] if len(roles) == 1 else ['conflicting_recorded_roles'])})
    return actors


def _window_total(assignments):
    """One conservative project subtotal; never add unproven overlapping scopes.

    Verified exclusive rows add. Other actors may include those requests, so
    take the maximum of that independent subtotal and each actor's subtotal.
    This is a lower bound, not an estimate of the missing/overlapping portion.
    """
    with localcontext() as context:
        context.prec = 80
        independent, actors = Decimal(0), {}
        known = False
        complete = bool(assignments)
        for row in assignments:
            cost = row['work_units']
            value = cost.get('known_value', cost.get('value'))
            complete &= (row.get('exclusive_scope') is True and cost.get('status') == 'complete')
            if value is None:
                continue
            amount = Decimal(str(value)); known = True
            identity = row['thread_id']
            actors[identity] = actors.get(identity, Decimal(0)) + amount
            if row.get('exclusive_scope') is True:
                independent += amount
        total = max([independent, *actors.values()]) if known else None
        text = format(total, 'f') if total is not None else None
    return {'value': text if complete else None, 'known_value': text,
            'status': 'complete' if complete else 'partial' if known else 'unknown',
            'method': 'exclusive_sum' if complete else 'non_overlapping_lower_bound',
            'notes': [] if complete else ['incomplete_or_overlapping_scope_not_summed']}


def _merge_reset_variants(windows):
    """Coalesce at most two seconds of jitter, only for a verified same account.

    Compare with the first boundary, not the previous one (no transitive drift).
    Preserve every observed interval and its source evidence unchanged.
    """
    merged = []
    for window in sorted(windows, key=lambda w: (w['ends_at'], w['window_id'])):
        target = next((item for item in merged
            if item['account_identity_verified'] and window['account_identity_verified']
            and item['account_scope_key'] == window['account_scope_key']
            and item['limit_id'] == window['limit_id']
            and 0 <= (native._stamp(window['ends_at']) - native._stamp(item['ends_at'])).total_seconds() <= 2), None)
        variant = {k: window[k] for k in ('window_id', 'starts_at', 'ends_at', 'reset_evidence')}
        if target is None:
            window['boundary_variants'] = [variant]
            merged.append(window)
        else:
            target['boundary_variants'].append(variant)
            target['assignments'].extend(window['assignments'])
            target['reset_evidence'] = target['reset_evidence'] + window['reset_evidence']
            target['diagnostics'].append('native_reset_jitter_coalesced')
    return merged


def build_quota_usage(root, data, events=None, rate_path=None):
    """Return verified request observations grouped by explicitly observed 300m resets.

    ``windows[].assignments`` retain actor rows; ``total`` is one conservative
    project subtotal, without adding unproven overlapping scopes.
    ``unassigned`` retains token observations lacking a provable boundary.
    ``diagnostics`` contains rejected ambiguous/unverifiable source selections.
    The input report and canonical events/journals are not modified.
    """
    if events is None:
        try:
            from .control_units import _events
        except ImportError:
            from control_units import _events
        events = _events(root)
    rates = load_rates(rate_path)
    scope = data.get('scope') or {}
    zone = dt.timezone(dt.timedelta(hours=3))
    date_since = dt.datetime.combine(dt.date.fromisoformat(scope['since']), dt.time.min, zone) if scope.get('since') else None
    date_until = dt.datetime.combine(dt.date.fromisoformat(scope['until']) + dt.timedelta(days=1), dt.time.min, zone) if scope.get('until') else None
    settings = native._settings(root)
    result = {'schema_version': 1, 'scope': 'project_observed_usage', 'windows': [], 'unassigned': [],
              'unassigned_actors': [],
              'diagnostics': [], 'account_total': None, 'subscription_percent': None,
              'boundary_policy': 'observed_native_reset_only'}
    if settings.get('enabled') is False:
        result['diagnostics'].append({'diagnostics': ['native_telemetry_disabled']})
        return result
    sessions = native._sessions(root, settings, events)
    units, claims, _ = native._claims(events, sessions)
    selected, rejected = _selection(data, sessions)
    result['diagnostics'].extend(rejected)
    # Detect duplicate actor-turn claims even when the report selection omitted
    # another CU: ascend verified ancestry into every canonical owner selection.
    def claimants(session, turn):
        found = set()
        current = session
        chain = set()
        while current and current['meta']['id'] not in chain:
            identity = current['meta']['id']; chain.add(identity)
            for cu, unit in units.items():
                for owner, index in unit['selected']:
                    if owner == identity and native._within(native._stamp(turn['start'].get('timestamp')), sessions[owner]['turns'][index]):
                        found.add(cu)
            parent = current['meta'].get('parent_thread_id')
            if native._spawn(current['meta']).get('parent_thread_id') != parent:
                break
            current = sessions.get(parent)
        return found
    windows, groups, seen = {}, {}, set()
    for unit, person, session, turn, baseline, snapshots in selected:
        cu = unit['cu_id']; identity = session['meta']['id']
        owners = claimants(session, turn)
        if cu not in owners or owners - {cu}:
            result['diagnostics'].append({'cu_id': cu, 'thread_id': identity, 'turn_id': turn['id'],
                                          'diagnostics': ['ambiguous_turn_claim' if owners else 'canonical_cu_claim_unverified']})
            continue
        assignment = _assignment(session, turn, sessions, unit)
        agent_result = _agent_result(session, turn, (turn['end'] or snapshots[-1]['row'])['_position'])
        prior = baseline
        for snap in snapshots:
            row = snap['row']; key = (identity, turn['id'], row['_sha256'])
            previous_snapshot = prior
            usage = {k: snap['counts'][k] - prior['counts'][k] for k in FIELDS}
            observed = native._stamp(row.get('timestamp'))
            previous = native._stamp(prior['row'].get('timestamp'))
            start = native._stamp(turn['start'].get('timestamp'))
            # Initial derived zero shares its row with first snapshot; the real
            # turn start bounds that first request, not its own ending timestamp.
            request_start = start if prior.get('derived') else max(start, previous) if start and previous else None
            if not any(usage.values()):
                continue  # no new measured request; preserve the last-changing baseline
            prior = snap
            # Date requests select observations by their recorded completion
            # timestamp, not a prorated share of an in-flight model request.
            if observed and ((date_since and observed < date_since) or (date_until and observed >= date_until)):
                continue
            if key in seen:
                continue
            seen.add(key)
            if not any(usage.values()):
                continue  # repeated cumulative observations are not requests
            quota = _quota(session, row)
            notes = []
            if not quota:
                notes.append('native_reset_boundary_unavailable')
            elif not request_start or not observed or not native._stamp(quota['starts_at']) <= request_start <= observed < native._stamp(quota['ends_at']):
                notes.append('request_span_crosses_or_lacks_reset_boundary')
            coverage = 'complete' if turn['end'] else 'partial'
            if not turn['end']:
                notes.append('pending_turn_observation')
            window_key = quota['window_id'] if quota and not any(n != 'pending_turn_observation' for n in notes) else None
            bucket = (window_key, cu, identity, turn['id'])
            if bucket not in groups:
                groups[bucket] = {'cu_id': cu, 'cu_title': unit.get('title'), 'result': unit.get('result'),
                    'thread_id': identity, 'participant_id': identity, 'role': person.get('role'),
                    'name': person.get('name'), 'model': next(iter(turn['models'])), 'turn_id': turn['id'],
                    'assignment': assignment, 'usage': dict.fromkeys(FIELDS, 0), 'coverage': coverage,
                    'agent_result': agent_result,
                    'exclusive_scope': person.get('exclusive_scope') is True, 'request_count': 0,
                    'observed_from': _iso(request_start), 'observed_through': _iso(observed),
                    'diagnostics': [], 'provenance': []}
            group = groups[bucket]
            for k in FIELDS:
                group['usage'][k] += usage[k]
            group['request_count'] += 1
            group['observed_through'] = _iso(observed)
            group['diagnostics'] = sorted(set(group['diagnostics']) | set(notes))
            group['provenance'].append({'ending': _ref(session, row), 'baseline': _ref(session, previous_snapshot['row']),
                                        'baseline_kind': previous_snapshot.get('derived', 'observed_snapshot')})
            if window_key:
                if window_key not in windows:
                    windows[window_key] = quota
                elif quota['reset_evidence'][0] not in windows[window_key]['reset_evidence']:
                    windows[window_key]['reset_evidence'].extend(quota['reset_evidence'])
    for (window_key, _, _, _), group in groups.items():
        group['work_units'] = price_usage(group['model'], group['usage'], coverage=group['coverage'], rates=rates)
        if window_key:
            windows[window_key]['assignments'].append(group)
        else:
            result['unassigned'].append(group)
    result['windows'] = sorted(_merge_reset_variants(windows.values()), key=lambda w: (w['starts_at'], w['window_id']), reverse=True)
    for window in result['windows']:
        window['actors'] = _actors(window['assignments'], rates)
        window['total'] = _window_total(window['assignments'])
        # Completeness is relative to this project's selected work, not account
        # coverage. Only real rejected/unassigned observations make it incomplete.
        gaps = []
        for rejected in result['diagnostics']:
            session = sessions.get(rejected.get('thread_id'))
            turns = [t for t in session['turns'] if not rejected.get('turn_id') or t['id'] == rejected['turn_id']] if session else []
            if not turns or any(not native._stamp(t['start'].get('timestamp')) or not native._observed_end(t)
                    or (native._stamp(t['start'].get('timestamp')) < native._stamp(window['ends_at'])
                        and native._observed_end(t) >= native._stamp(window['starts_at'])) for t in turns):
                gaps.append('rejected_project_observations')
        for row in result['unassigned']:
            start, end = native._stamp(row['observed_from']), native._stamp(row['observed_through'])
            if not start or not end or start < native._stamp(window['ends_at']) and end >= native._stamp(window['starts_at']):
                gaps.append('unassigned_project_observations')
        if gaps and window['total']['status'] == 'complete':
            window['total'].update(status='partial', value=None)
        window['total']['notes'].extend(sorted(set(gaps)))
        window['total']['notes'].append('project_observations_only')
    result['unassigned_actors'] = _actors(result['unassigned'], rates)
    for i, window in enumerate(result['windows']):
        for other in result['windows'][i + 1:]:
            if (window['account_scope_key'] == other['account_scope_key'] and window['limit_id'] == other['limit_id']
                    and window['starts_at'] < other['ends_at'] and other['starts_at'] < window['ends_at']):
                for item in (window, other):
                    if 'overlapping_native_reset_evidence' not in item['diagnostics']:
                        item['diagnostics'].append('overlapping_native_reset_evidence')
    return result
