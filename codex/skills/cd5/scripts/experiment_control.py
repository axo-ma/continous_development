"""Local experiment admission, status and automatic process-event recording (no shell)."""
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
import subprocess
from pathlib import Path

try:
    from .experiment_registry import append_event, build_event, read_events, RegistryError
except ImportError:
    from experiment_registry import append_event, build_event, read_events, RegistryError




class ControlError(ValueError):
    pass


def stopped(state):
    return (state.get('user_stopped') is True or state.get('user_stop', {}).get('active') is True
            or state.get('phase') == 'user_stopped')


def route(state, *, planner_status='idle', executor_status='idle', used_percent=None,
          ordinary_allowed=None, control_only=False):
    if stopped(state):
        return {'action': 'wait_user_stop', 'reason': 'explicit scientific user stop'}
    if state.get('schema_version') != 3:
        return {'action': 'inspect_state', 'reason': 'unsupported state schema'}
    if state.get('cd5', {}).get('enabled') is False:
        return {'action': 'wait_cd5_disabled', 'reason': 'CD5 workflow paused independently of MAC'}
    if state.get('goal_status') == 'verified_complete':
        return {'action': 'complete', 'reason': 'whole-goal completion recorded'}
    if ordinary_allowed is False or (used_percent is not None and used_percent >= 90):
        return {'action': 'wait_quota', 'reason': 'checkpoint; reuse only authorized wakeup'}
    if ordinary_allowed is not True or used_percent is None:
        return {'action': 'quota_unknown', 'reason': 'fresh quota required'}
    active = {'active', 'running', 'inprogress', 'in_progress', 'working'}
    idle = {'idle', 'completed', 'notloaded', 'not_loaded', 'done'}
    ps, es = str(planner_status or '').strip().lower(), str(executor_status or '').strip().lower()
    control_self = control_only and ps in active
    if es in active or (ps in active and not control_self):
        return {'action': 'wait_active', 'reason': 'avoid duplicate work'}
    if es not in idle or (ps not in idle and not control_self):
        return {'action': 'inspect_status', 'reason': 'native status unknown; not permission to duplicate work'}
    task = state.get('active_task')
    if task and task.get('status') in {'running', 'awaiting_review'}:
        return {'action': 'inspect_task', 'reason': 'reconcile live executor/result; do not repeat'}
    return {'action': 'planner_decision', 'reason': 'planner chooses only within current authorization'}


def validate_state(root):
    root = Path(root).resolve()
    state = json.loads((memory_dir(root) / 'CHECKPOINT.json').read_text(encoding='utf-8-sig'))
    if state.get('schema_version') != 3 or not state.get('owner', {}).get('thread_id'):
        raise ControlError('schema3 and planner owner required')
    if state.get('owner', {}).get('role') != cd5_config(root)['owner_role']:
        raise ControlError('STATE owner must be planner')
    if not isinstance(state.get('next_action'), dict):
        raise ControlError('one structured next_action required')
    if stopped(state) and state['next_action'].get('kind') != 'wait_user':
        raise ControlError('user stop must not contain an executable next_action')
    for value in state.get('memory', {}).values():
        path = (root / value).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ControlError(f'missing or external memory: {value}')
    if len(state.get('memory', {})) != 5:
        raise ControlError('exactly five canonical memory paths required')
    expected = memory_map(root)
    if state.get('memory') != expected:
        raise ControlError('schema3 memory map must match the exact five canonical files')
    return state


def local_file(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ControlError(f'not a workspace file: {value}')
    return path


def run_task(root, task_id, command):
    """One admitted process invocation. Exit 0 records process completion, never correctness."""
    root = Path(root).resolve()
    lock = memory_dir(root) / '.execution.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError as exc:
        raise ControlError('execution lock exists; inspect current/abandoned process, never auto-clear') from exc
    try:
        with handle:
            handle.write(task_id)
        state = validate_state(root)
        if stopped(state):
            raise ControlError('scientific work stopped by user')
        if state.get('cd5', {}).get('enabled') is False:
            raise ControlError('CD5 workflow is paused')
        task = state.get('active_task') or {}
        if task.get('id') != task_id or task.get('status') != 'authorized':
            raise ControlError('matching authorized active task required')
        if command != task.get('command') or not command or not all(isinstance(x, str) for x in command):
            raise ControlError('argv must exactly match planner-frozen command')
        for key in ('question', 'evidence_gap', 'prior_evidence', 'novelty_reason', 'acceptance_criteria'):
            if not task.get(key):
                raise ControlError(f'missing task field: {key}')
        protocol = local_file(root, task['protocol_path'])
        digest = hashlib.sha256(protocol.read_bytes()).hexdigest()
        if digest != task.get('protocol_sha256'):
            raise ControlError('protocol changed after approval')
        events = [e for e in read_events(root) if e['experiment_id'] == task_id]
        starts = [e for e in events if e['event_type'] == 'execution_started']
        maximum = task.get('max_attempts')
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1 or len(starts) >= maximum:
            raise ControlError('attempt budget exhausted or missing')
        terminals = {e.get('machine_facts', {}).get('start_event_id') for e in events
                     if e['event_type'] in {'execution_completed', 'technical_failed', 'stopped', 'truncated'}}
        if any(e['event_id'] not in terminals for e in starts):
            raise ControlError('unfinished attempt exists; reconcile without automatic retry')
        provenance = {'writer': 'experiment_control', 'scope': 'process facts only; no semantic score'}
        def record(kind, facts):
            return append_event(root, build_event(task_id, kind, source_paths=[task['protocol_path']],
                provenance=provenance, machine_facts=facts, root=root))
        if not any(e['event_type'] == 'protocol_frozen' and any(r.get('sha256') == digest for r in e['source_refs']) for e in events):
            record('protocol_frozen', {'protocol_sha256': digest, 'approved_by': state['owner']['thread_id'],
                                       'question': task['question'], 'evidence_gap': task['evidence_gap'],
                                       'novelty_reason': task['novelty_reason'], 'prior_evidence': task['prior_evidence']})
        start = record('execution_started', {'command': command, 'attempt': len(starts) + 1,
                                             'protocol_sha256': digest})
        try:
            result = subprocess.run(command, cwd=root, shell=False, check=False)
        except (OSError, KeyboardInterrupt) as exc:
            record('technical_failed', {'start_event_id': start['event_id'], 'error_type': type(exc).__name__})
            raise ControlError('process failed/interrupted; attempt retained') from exc
        record('execution_completed' if result.returncode == 0 else 'technical_failed',
               {'start_event_id': start['event_id'], 'exit_code': result.returncode,
                'semantic_status': 'not_assessed', 'attempt': len(starts) + 1})
        return result.returncode
    finally:
        lock.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path.cwd())
    subs = ap.add_subparsers(dest='operation', required=True)
    subs.add_parser('validate')
    subs.add_parser('status')
    run = subs.add_parser('run')
    run.add_argument('--task-id', required=True)
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = ap.parse_args()
    try:
        if args.operation == 'run':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            return run_task(args.root, args.task_id, command)
        state = validate_state(args.root)
        print(json.dumps({'valid': True, 'phase': state.get('phase', 'unspecified'), 'owner': state['owner'],
                          'next_action': state['next_action'], 'user_stop': stopped(state)}, ensure_ascii=False))
        return 0
    except (ControlError, RegistryError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
