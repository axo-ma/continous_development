"""Read-only worker identity registry and fresh-status assessment.

Never infer a complete inventory from observed hooks. A caller must establish
coverage independently before using this component in continuation admission.
SubagentStop does not remove an identity: followups need not emit SubagentStart.
No model calls, host writes or dispatch are performed here.
"""
import math


def registry(events, owner):
    if not isinstance(owner, str) or not owner:
        raise ValueError('explicit owner required')
    workers = set()
    invalid = False
    interrupted = False
    rows = list(events)
    # Recover descendant closure without relying on filesystem event ordering.
    # An unrelated session never joins the tree without an observed parent edge.
    changed = True
    while changed:
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                invalid = True
                continue
            parent = row.get('session_id')
            if not isinstance(parent, str) or parent not in workers | {owner}:
                continue
            event = row.get('event')
            if event == 'Interrupt':
                interrupted = True
            elif event in ('SubagentStart', 'SubagentStop'):
                identity = row.get('agent_id')
                if (not isinstance(identity, str) or not identity
                        or identity in (owner, parent)):
                    invalid = True
                elif identity not in workers:
                    workers.add(identity)
                    changed = True
    return {'owner': owner, 'workers': sorted(workers), 'invalid_events': invalid,
            'interrupted': interrupted, 'coverage_verified': False}


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def assess(known, observations, now, generation, max_age=5):
    """Assess known workers only; fresh same-host reads must supply observations.

    Each observation carries owner, generation, thread_id, observed_at and the
    actual host status object. The function validates inputs, not their provenance.
    Coverage remains explicitly unverified even for an empty known-worker list.
    """
    if (not _finite_number(now) or not _finite_number(max_age) or not 0 < max_age <= 60
            or type(generation) is not int or generation < 1):
        raise ValueError('finite observation clock and explicit generation required')
    result = {'known_workers_idle': False, 'coverage_verified': False,
              'workers': list(known['workers']), 'reason': 'unknown'}
    if known['invalid_events'] or known['interrupted']:
        result['reason'] = 'invalid_events_or_interrupt'
        return result
    if not isinstance(observations, list):
        result['reason'] = 'missing_observations'
        return result
    seen = {}
    for row in observations:
        if not isinstance(row, dict):
            result['reason'] = 'malformed_observation'
            return result
        identity = row.get('thread_id')
        if not isinstance(identity, str) or identity in seen:
            result['reason'] = 'duplicate_or_invalid_identity'
            return result
        seen[identity] = row
    for identity in known['workers']:
        row = seen.get(identity, {})
        observed = row.get('observed_at')
        if (row.get('owner') != known['owner'] or type(row.get('generation')) is not int
                or row['generation'] != generation or not _finite_number(observed)
                or not 0 <= now - observed <= max_age):
            result['reason'] = 'missing_stale_or_wrong_owner_observation'
            return result
        status = row.get('status')
        if not isinstance(status, dict) or status.get('type') != 'idle':
            result['reason'] = 'worker_not_proven_idle'
            return result
        if status.get('activeFlags') not in (None, []):
            result['reason'] = 'worker_waiting_or_active'
            return result
    result.update(known_workers_idle=True, reason='known_workers_idle_coverage_unverified')
    return result
