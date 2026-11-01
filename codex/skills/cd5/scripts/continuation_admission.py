"""Historical native-Goal fixture, not admission for the active shared Continuator.

One read-only continuation decision. Never resumes, dispatches or starts a service.

Caller supplies actual fresh same-host observations, verified worker coverage,
and the exact checkpoint. This module cannot establish observation provenance.
"""
import hashlib
import json
import math
try:
    from .worker_observations import assess
    from .stop_hook_trial import quota_allowed
except ImportError:
    from worker_observations import assess
    from stop_hook_trial import quota_allowed


def fingerprint(checkpoint):
    return hashlib.sha256(json.dumps(checkpoint, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def fresh(observed, now):
    return (type(observed) in (int, float) and math.isfinite(observed)
            and 0 <= now - observed <= 5)


def decide(checkpoint, observation, now):
    result = {'allowed': False, 'external_dispatch_allowed': False,
              'driver': None, 'reason': 'invalid_input'}
    def deny(reason):
        return dict(result, reason=reason)
    if (not isinstance(checkpoint, dict) or not isinstance(observation, dict)
            or type(now) not in (int, float) or not math.isfinite(now)):
        return result
    try:
        owner = checkpoint['owner']['thread_id']
        generation = checkpoint['owner_generation']
        if not isinstance(owner, str) or not owner or type(generation) is not int or generation < 1:
            return deny('unknown_owner')
        if checkpoint['user_stop']['active'] is not False:
            return deny('user_stop_or_unknown')
        if checkpoint['cd5']['enabled'] is not True:
            return deny('cd5_disabled_or_unknown')
        for key in ('waiting_user', 'goal_complete'):
            if checkpoint.get(key) is not False:
                return deny(key + '_or_unknown')
        if checkpoint.get('continuation_authorized') is not True:
            return deny('authorization_closed')
        if not isinstance(checkpoint.get('next_action'), dict) or not checkpoint['next_action'].get('kind'):
            return deny('no_next_action')
        if checkpoint['next_action']['kind'] in ('wait_user', 'wait_quota', 'complete', 'stop'):
            return deny('waiting_or_complete')
        if (observation.get('owner_thread_id') != owner
                or type(observation.get('generation')) is not int
                or observation['generation'] != generation
                or observation.get('checkpoint_sha256') != fingerprint(checkpoint)):
            return deny('owner_or_checkpoint_changed')
        if not fresh(observation.get('observed_at'), now):
            return deny('stale_or_unknown_activity')
        if observation.get('pending_input') is not False:
            return deny('pending_input_or_unknown')
        status = observation.get('owner_status')
        context = observation.get('execution_context', 'idle_boundary')
        owner_active_here = False
        if context == 'owner_turn':
            host_turn = observation.get('host_turn', {})
            expected_turn = observation.get('expected_turn_id')
            owner_active_here = (observation.get('caller_thread_id') == owner
                and isinstance(expected_turn, str) and bool(expected_turn)
                and isinstance(host_turn, dict) and host_turn.get('id') == expected_turn
                and host_turn.get('status') == 'inProgress')
        if (context not in ('idle_boundary', 'owner_turn') or not isinstance(status, dict)
                or status.get('activeFlags') not in (None, [])
                or (context == 'owner_turn' and
                    (not owner_active_here or status.get('type') != 'active'))
                or (context == 'idle_boundary' and status.get('type') != 'idle')):
            return deny('owner_not_proven_idle')
        if not fresh(observation.get('quota_observed_at'), now) or not quota_allowed(observation.get('quota')):
            return deny('quota_closed_or_unknown')
        known = observation['worker_registry']
        if known.get('owner') != owner:
            return deny('worker_owner_mismatch')
        # Coverage is independent of the known-worker idle check. A receipt ID
        # is an audit reference, not proof by itself; caller verifies its source.
        if (observation.get('worker_coverage_verified') is not True
                or not isinstance(observation.get('coverage_receipt_id'), str)
                or not observation['coverage_receipt_id']):
            return deny('worker_coverage_unknown')
        workers = assess(known, observation.get('worker_statuses'), now, generation)
        if workers['known_workers_idle'] is not True:
            return deny(workers['reason'])
        driver = checkpoint['native_goal']['driver']
        result['driver'] = driver
        if driver != 'native':
            return deny('alternative_driver_not_implemented')
        if (observation.get('native_goal_status') != 'active'
                or observation.get('other_driver_active') is not False):
            return deny('goal_inactive_or_competing_driver')
        if observation.get('boundary_already_consumed') is not False:
            return deny('duplicate_or_unknown_boundary')
        return dict(result, allowed=True,
                    reason='current_native_owner_only' if context == 'owner_turn' else 'native_only')
    except (KeyError, TypeError, ValueError, AttributeError):
        return deny('missing_or_malformed_state')
