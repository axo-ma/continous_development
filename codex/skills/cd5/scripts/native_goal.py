"""Read-only CD5/native Goal admission plan. Never calls models or mutates goals.

The current owner executes returned actions through native Goal tools, respecting
their authorization contract, and reads back the result. Files are observations,
not a substitute for native state or proof of human authorization.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

try:
    from .cd5_config import memory_dir
    from .continuation_admission import decide as continuation_decision
except ImportError:
    from cd5_config import memory_dir
    from continuation_admission import decide as continuation_decision


def objective_digest(objective):
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
        raise ValueError('objective must contain 1–4000 characters')
    return hashlib.sha256(objective.encode('utf-8')).hexdigest()


def fresh(observation, now):
    at = observation.get('observed_at')
    return (isinstance(at, (float, int)) and not isinstance(at, bool)
            and math.isfinite(at) and 0 <= now - at <= 60)


def plan(checkpoint, caller, objective, native, quota, activity, authorization,
         *, now=None, token_budget=None, continuation_observation=None):
    """Decide only; no implicit status updates or delegated host identity."""
    now = time.time() if now is None else now
    objective_digest(objective)
    if token_budget is not None and (type(token_budget) is not int or token_budget <= 0):
        raise ValueError('explicit token budget must be a positive integer')
    if checkpoint.get('owner', {}).get('thread_id') != caller:
        return {'action': 'hold', 'reason': 'caller_is_not_owner'}
    if ('continuation_admission_required' in checkpoint
            and type(checkpoint['continuation_admission_required']) is not bool):
        return {'action': 'hold', 'reason': 'invalid_continuation_admission_setting'}
    if not fresh(native, now) or native.get('available') is not True or native.get('caller_thread_id') != caller:
        return {'action': 'get_goal', 'reason': 'fresh_native_observation_required'}
    if 'goal' not in native:
        return {'action': 'get_goal', 'reason': 'missing_goal_is_not_observed_absence'}
    goal = native['goal']
    if goal is not None and not isinstance(goal, dict):
        raise ValueError('native goal must be object or observed null')
    if goal is not None and goal.get('threadId', goal.get('thread_id', caller)) != caller:
        return {'action': 'hold', 'reason': 'native_goal_owner_mismatch'}
    status = goal.get('status') if goal else None
    active = status == 'active'

    reason = None
    stop = checkpoint.get('user_stop', {}).get('active')
    if stop is not False:
        reason = 'user_stop' if stop is True else 'stop_unknown'
    elif checkpoint.get('cd5', {}).get('enabled') is False:
        reason = 'cd5_off'
    elif checkpoint.get('next_action', {}).get('kind') in {'wait_user', 'wait_user_decision'}:
        reason = 'wait_user'
    elif checkpoint.get('goal_status') in {'complete', 'completed', 'verified_complete', 'closed'}:
        if goal is None or status == 'complete':
            return {'action': 'hold', 'reason': 'goal_already_complete'}
        return {'action': 'verify_completion', 'reason': 'canonical_completion_requires_native_evidence_audit'}
    elif not fresh(quota, now):
        reason = 'quota_unknown'
    else:
        data = quota.get('data') or {}
        rates = (data.get('rateLimitsByLimitId') or {}).get('codex') or data.get('rateLimits') or {}
        primary = rates.get('primary') or {}
        used = primary.get('usedPercent')
        if (data.get('ordinaryUsageAllowed') is not True or primary.get('windowDurationMins') != 300
                or not isinstance(used, (float, int)) or isinstance(used, bool)
                or not math.isfinite(used) or not 0 <= used <= 100):
            reason = 'quota_unknown_or_disallowed'
        elif used >= 90:
            reason = 'quota90'
    if reason:
        if active:
            permitted = (authorization.get('pause_requested') is True
                         or reason in authorization.get('explicit_pause_reasons', []))
            return {'action': 'pause_goal' if permitted else 'request_user_pause',
                    'reason': reason, 'end_turn': True,
                    'do_not_poll_or_launch_successor': True}
        return {'action': 'hold', 'reason': reason, 'end_turn': True}
    if (not fresh(activity, now) or activity.get('caller_thread_id') != caller
            or activity.get('conflicting_work') is not False or activity.get('workers_idle') is not True):
        return {'action': 'hold', 'reason': 'activity_active_or_unknown'}
    if not checkpoint.get('next_action', {}).get('kind'):
        return {'action': 'hold', 'reason': 'no_next_action'}
    if goal is not None:
        if goal.get('objective') != objective:
            return {'action': 'hold', 'reason': 'existing_goal_conflict_preserve_objective_and_accounting'}
        if status == 'active':
            if checkpoint.get('continuation_admission_required') is True:
                if (not isinstance(continuation_observation, dict)
                        or continuation_observation.get('quota') != quota.get('data')
                        or continuation_observation.get('quota_observed_at') != quota.get('observed_at')):
                    return {'action': 'hold', 'reason': 'detailed_observation_missing_or_quota_mismatch',
                            'end_turn': True, 'external_dispatch_allowed': False}
                decision = continuation_decision(checkpoint, continuation_observation, now)
                if not decision['allowed']:
                    return {'action': 'hold', 'reason': 'continuation_denied:' + decision['reason'],
                            'end_turn': True, 'external_dispatch_allowed': False}
            return {'action': 'continue', 'reason': 'matching_active_native_goal',
                    'preserve_usage_and_budget': True, 'external_dispatch_allowed': False}
        return {'action': 'wait_user_resume', 'reason': 'native_goal_' + str(status),
                'preserve_usage_and_budget': True}
    if authorization.get('create_requested') is not True:
        return {'action': 'hold', 'reason': 'explicit_goal_authorization_required'}
    result = {'action': 'create_goal', 'reason': 'authorized_owner_has_no_native_goal',
              'objective': objective, 'read_back_required': True}
    if token_budget is not None:
        if authorization.get('token_budget_requested') is not True:
            return {'action': 'hold', 'reason': 'token_budget_requires_explicit_request'}
        result['token_budget'] = token_budget
    return result


def receipt(caller, result, *, now=None):
    """Small checkpoint observation of a successful native read, never a claim of wakeup."""
    goal = result.get('goal')
    if goal is not None and not isinstance(goal, dict):
        raise ValueError('native goal result must be object or null')
    if 'goal' not in result:
        raise ValueError('native result must distinguish unavailable from absent')
    if goal and goal.get('threadId', goal.get('thread_id', caller)) != caller:
        raise ValueError('native goal belongs to a different thread')
    out = {'driver': 'native', 'owner_thread_id': caller,
           'observed_at': time.time() if now is None else now,
           'status': goal.get('status') if goal else 'absent',
           'ordinary_continuation_verified': False,
           'quota_reset_resume_verified': False, 'restart_resume_verified': False}
    if goal:
        out['objective_sha256'] = objective_digest(goal.get('objective'))
        out['token_budget'] = goal.get('tokenBudget', goal.get('token_budget'))
        out['tokens_used'] = goal.get('tokensUsed', goal.get('tokens_used'))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--caller-thread', required=True)
    parser.add_argument('--objective-file', type=Path, required=True)
    parser.add_argument('--observations', type=Path, required=True,
                        help='Fresh native/quota/activity observations and explicit authorization')
    parser.add_argument('--token-budget', type=int)
    args = parser.parse_args()
    checkpoint = json.loads((memory_dir(args.root) / 'CHECKPOINT.json').read_text(encoding='utf-8-sig'))
    observations = json.loads(args.observations.read_text(encoding='utf-8-sig'))
    print(json.dumps(plan(checkpoint, args.caller_thread,
          args.objective_file.read_text(encoding='utf-8').strip(),
          observations.get('native', {}), observations.get('quota', {}),
          observations.get('activity', {}), observations.get('authorization', {}),
          token_budget=args.token_budget,
          continuation_observation=observations.get('continuation')), ensure_ascii=True))


if __name__ == '__main__':
    main()
