"""Deterministic, fail-closed Planner supervisor. No model calls during checks.

The host adapter is an explicit argv JSON array, never a shell command. It reads
one JSON request from stdin and returns one JSON response. See planner-control.md.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import hashlib
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

try:
    from .cd5_config import memory_dir
except ImportError:
    from cd5_config import memory_dir

STATES = {'STOP', 'RUNNING', 'WAIT_QUOTA', 'WAIT_WORKER', 'WAIT_USER',
          'READY', 'COMPLETE', 'DISPATCHING', 'BLOCKED'}


def stamp(now=None):
    return dt.datetime.fromtimestamp(time.time() if now is None else now, dt.timezone.utc).isoformat()


def atomic(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.planner-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers/indexers can briefly deny replacement of a status file.
        # Keep the old durable state until replacement succeeds; never drop it.
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(.01 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(directory):
    """OS releases this lock after a crash; no stale PID-file deletion race."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.planner.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def read(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('expected JSON object: ' + str(path))
    return value


def checkpoint_hash(checkpoint):
    return hashlib.sha256(json.dumps(checkpoint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sync_checkpoint(root, checkpoint):
    """Called after a canonical HQ write; never creates or arms control files."""
    directory = memory_dir(root)
    if not (directory / 'PLANNER_STATE.json').exists():
        return
    with locked(directory):
        old = load(directory)
        record = checkpoint.get('planner_control', {})
        state = record.get('state')
        reason = record.get('reason')
        if checkpoint.get('user_stop', {}).get('active') is not False:
            state, reason = 'STOP', 'canonical user STOP'
        elif checkpoint.get('cd5', {}).get('enabled') is False:
            state, reason = 'STOP', 'CD5 disabled'
        elif checkpoint.get('owner', {}).get('thread_id') != old.get('owner_thread_id'):
            state, reason = 'BLOCKED', 'owner changed; explicit adoption required'
        elif checkpoint.get('goal_status') in {'complete', 'completed', 'closed'}:
            state, reason = 'COMPLETE', 'canonical goal completed'
        elif old['state'] in {'STOP', 'BLOCKED', 'DISPATCHING'}:
            state, reason = old['state'], old['reason']
        elif state not in STATES - {'DISPATCHING'} or not reason:
            state, reason = 'BLOCKED', 'checkpoint has no explicit Planner lifecycle record'
        resume = record.get('reset_at')
        if state == 'WAIT_QUOTA' and not finite(resume):
            state, reason = 'BLOCKED', 'missing observed quota reset'
        save(directory, old, state, reason, 'checkpoint',
             checkpoint_sha256=checkpoint_hash(checkpoint),
             authorized=record.get('authorized') is True,
             next_action=checkpoint.get('next_action'),
             resume_after=resume + 60 if finite(resume) else None,
             heartbeat_at=time.time())


def save(directory, previous, state, reason, source, now=None, **fields):
    if state not in STATES:
        raise ValueError('invalid state')
    value = {**previous, **fields, 'schema_version': 1, 'state': state,
             'reason': reason, 'updated_at': stamp(now),
             'revision': previous.get('revision', 0) + 1}
    event = {'event_id': str(uuid.uuid4()), 'at': value['updated_at'],
             'from': previous.get('state'), 'to': state, 'reason': reason,
             'source': source, 'snapshot': value}
    # Durable write-ahead journal. If replacement fails, later ticks stop until
    # an operator reconciles the last snapshot; they never repeat a dispatch.
    with (directory / 'PLANNER_EVENTS.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    atomic(directory / 'PLANNER_STATE.json', value)
    return value


def load(directory):
    state = read(directory / 'PLANNER_STATE.json')
    if state.get('state') not in STATES or state.get('schema_version') != 1:
        raise ValueError('invalid state; automatic continuation disabled')
    with (directory / 'PLANNER_EVENTS.jsonl').open(encoding='utf-8') as stream:
        last = None
        for line in stream:
            last = json.loads(line)
    if not last or last.get('snapshot') != state:
        raise ValueError('state/journal mismatch; reconcile before continuation')
    return state


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def decide(state, checkpoint, observation, now):
    """Pure admission policy. Observation must come from a live host probe."""
    if checkpoint.get('user_stop', {}).get('active') is not False:
        return 'hold', 'user STOP or unknown STOP'
    if checkpoint.get('cd5', {}).get('enabled') is False:
        return 'hold', 'CD5 disabled'
    if checkpoint.get('native_goal', {}).get('driver') == 'native':
        return 'hold', 'native_goal_drives_continuation'
    if checkpoint.get('owner', {}).get('thread_id') != state.get('owner_thread_id'):
        return 'hold', 'owner changed'
    if state.get('checkpoint_sha256') and state['checkpoint_sha256'] != checkpoint_hash(checkpoint):
        return 'hold', 'checkpoint changed without lifecycle synchronization'
    if checkpoint.get('goal_status') in {'complete', 'completed', 'closed'}:
        return 'hold', 'goal completed'
    if state['state'] in {'STOP', 'WAIT_USER', 'COMPLETE', 'BLOCKED', 'DISPATCHING'}:
        return 'hold', state['state']
    if state['state'] == 'WAIT_QUOTA':
        reset = state.get('resume_after')
        if not finite(reset) or now < reset:
            return 'hold', 'waiting for recorded reset plus safety margin'
    observed = observation.get('observed_at')
    if not finite(observed) or not 0 <= now - observed <= 60:
        return 'hold', 'stale or unknown host observation'
    if observation.get('owner_thread_id') != state.get('owner_thread_id'):
        return 'hold', 'probe owner mismatch'
    if observation.get('wake_supported') is not True:
        return 'hold', observation.get('reason', 'host does not support safe wake')
    if observation.get('planner_status') != 'idle' or observation.get('workers_idle') is not True:
        return 'hold', 'native activity active or unknown'
    quota = observation.get('quota', {})
    used = quota.get('used_percent')
    if (quota.get('ordinary_allowed') is not True or quota.get('window_minutes') != 300
            or not finite(used) or not 0 <= used < 90):
        return 'hold', 'quota unavailable or admission denied'
    if not state.get('next_action') or state.get('authorized') is not True:
        return 'hold', 'no authorized pending action'
    if state['state'] == 'RUNNING':
        heartbeat = state.get('heartbeat_at')
        if not finite(heartbeat) or now - heartbeat < state.get('lease_seconds', 900):
            return 'hold', 'lease active or unknown'
        if state.get('recovery_attempts', 0) >= 1:
            return 'block', 'repeated crash; HQ must inspect actual state before another dispatch'
        return 'wake', 'recover once after expired lease and verified native idle'
    return 'wake', 'resume condition satisfied'


def adapter_call(argv, request):
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise ValueError('adapter must be a nonempty argv array')
    result = subprocess.run(argv, input=json.dumps(request), text=True,
                            capture_output=True, timeout=30, check=True, shell=False)
    response = json.loads(result.stdout)
    if not isinstance(response, dict):
        raise ValueError('adapter returned no JSON object')
    return response


def tick(root, adapter=None, now=None):
    directory = memory_dir(root)
    now = time.time() if now is None else now
    with locked(directory):
        state = load(directory)
        checkpoint = read(directory / 'CHECKPOINT.json')
        # Cheap gates before any host connection. No model or adapter for waits.
        action, reason = decide(state, checkpoint, {}, now)
        if reason != 'stale or unknown host observation':
            return {'action': action, 'reason': reason}
        if adapter is None:
            return {'action': 'hold', 'reason': 'host adapter not configured'}
        probe = adapter_call(adapter, {'operation': 'probe', 'root': str(root),
                                     'owner_thread_id': state['owner_thread_id']})
        action, reason = decide(state, checkpoint, probe, now)
        if action == 'block':
            save(directory, state, 'BLOCKED', reason, 'watchdog', now)
        if action != 'wake':
            return {'action': action, 'reason': reason}
        # Re-read STOP immediately before reserving dispatch. The host must also
        # atomically check idle/STOP when accepting this idempotency key.
        checkpoint = read(directory / 'CHECKPOINT.json')
        if decide(state, checkpoint, probe, now)[0] != 'wake':
            return {'action': 'hold', 'reason': 'admission changed'}
        key = str(uuid.uuid4())
        recovery = state.get('recovery_attempts', 0) + (state['state'] == 'RUNNING')
        pending = save(directory, state, 'DISPATCHING', reason, 'watchdog', now,
                       dispatch_id=key, recovery_attempts=recovery)
        # Timeout/crash is ambiguous. Keep DISPATCHING and never resend blindly.
        response = adapter_call(adapter, {'operation': 'wake', 'root': str(root),
            'owner_thread_id': state['owner_thread_id'], 'dispatch_id': key,
            'expected_idle': True, 'next_action': state['next_action'],
            'message': 'Read current CD5 and canonical memory. Verify fresh quota, STOP, '
                       'owner and activity. Reconcile interrupted work before continuing '
                       'the authorized next action. Do not repeat scientific runs blindly.'})
        if response.get('accepted') is not True or response.get('dispatch_id') != key:
            return {'action': 'hold', 'reason': 'dispatch unconfirmed; inspect before retry'}
        save(directory, pending, 'RUNNING', 'host accepted wake', 'watchdog', now,
             heartbeat_at=now)
        return {'action': 'woke', 'dispatch_id': key}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--owner-thread', required=True)
    change = sub.add_parser('set')
    change.add_argument('--state', choices=sorted(STATES - {'DISPATCHING'}), required=True)
    change.add_argument('--reason', required=True)
    change.add_argument('--next-action')
    change.add_argument('--authorized', action='store_true')
    change.add_argument('--reset-at', type=float)
    change.add_argument('--source', choices=['planner', 'user'], default='planner')
    sub.add_parser('status')
    sub.add_parser('heartbeat')
    sub.add_parser('reconcile', help='restore last complete journal snapshot as BLOCKED; never resend')
    for name in ('tick', 'watch'):
        p = sub.add_parser(name)
        p.add_argument('--adapter', type=Path, help='JSON file containing adapter argv array')
        if name == 'watch':
            p.add_argument('--interval', type=int, default=60)
    args = parser.parse_args(argv)
    directory = memory_dir(args.root)
    if args.command in {'tick', 'watch'}:
        adapter = json.loads(args.adapter.read_text(encoding='utf-8-sig')) if args.adapter else None
        if args.command == 'tick':
            print(json.dumps(tick(args.root, adapter)))
            return
        while True:
            try:
                result = tick(args.root, adapter)
            except Exception as exc:
                # No retries after ambiguity/corruption; report to host stderr.
                print(str(exc), file=__import__('sys').stderr)
                raise SystemExit(1)
            if result['action'] == 'woke':
                print(json.dumps(result), flush=True)
            time.sleep(max(10, args.interval))
    else:
        with locked(directory):
            if args.command == 'init':
                if any((directory / n).exists() for n in ('PLANNER_STATE.json', 'PLANNER_EVENTS.jsonl')):
                    raise ValueError('control files already exist; refusing overwrite')
                state = save(directory, {}, 'STOP', 'initialized; not armed', 'user',
                             owner_thread_id=args.owner_thread, authorized=False,
                             recovery_attempts=0, lease_seconds=900)
            else:
                if args.command == 'reconcile':
                    snapshots = []
                    with (directory / 'PLANNER_EVENTS.jsonl').open(encoding='utf-8') as stream:
                        for line in stream:
                            try:
                                snapshots.append(json.loads(line)['snapshot'])
                            except (ValueError, KeyError):
                                raise ValueError('journal damaged; preserve files and inspect manually')
                    if not snapshots:
                        raise ValueError('no recoverable snapshot')
                    state = save(directory, snapshots[-1], 'BLOCKED',
                                 'explicit reconciliation; inspect host before rearming', 'user',
                                 authorized=False)
                    print(json.dumps(state, ensure_ascii=False))
                    return
                state = load(directory)
                if args.command == 'heartbeat':
                    if state['state'] != 'RUNNING':
                        raise ValueError('heartbeat requires RUNNING')
                    # Heartbeats update state and journal together for crash consistency.
                    state = save(directory, state, 'RUNNING', 'lease refreshed', 'planner',
                                 heartbeat_at=time.time())
                elif args.command == 'set':
                    if state['state'] in {'STOP', 'BLOCKED', 'DISPATCHING'} and args.source != 'user':
                        raise ValueError('explicit user reconciliation required')
                    if args.state == 'WAIT_QUOTA' and not finite(args.reset_at):
                        raise ValueError('WAIT_QUOTA requires observed reset epoch')
                    checkpoint = read(directory / 'CHECKPOINT.json')
                    if checkpoint.get('owner', {}).get('thread_id') != state['owner_thread_id']:
                        raise ValueError('owner changed; explicit new adoption required')
                    state = save(directory, state, args.state, args.reason, args.source,
                        checkpoint_sha256=checkpoint_hash(checkpoint),
                        next_action=args.next_action, authorized=args.authorized,
                        resume_after=args.reset_at + 60 if args.reset_at is not None else None,
                        heartbeat_at=time.time(),
                        recovery_attempts=0 if args.source == 'user' else state.get('recovery_attempts', 0))
            print(json.dumps(state, ensure_ascii=False))


if __name__ == '__main__':
    main()
