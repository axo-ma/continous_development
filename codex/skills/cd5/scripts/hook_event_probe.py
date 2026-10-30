"""Finite test-session-only hook recorder. Never continues or controls a chat.

SubagentStop is a stop boundary, not proof of terminal completion: other hooks
may continue the worker. Recorded identities are candidates for a live status
read, not a complete activity inventory or permission to resume.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

EVENTS = {'SubagentStart', 'SubagentStop', 'Interrupt', 'Stop', 'SessionStart',
          'SessionEnd', 'UserPromptSubmit'}


def observation(event, target):
    if (not isinstance(event, dict) or not isinstance(target, str) or not target
            or event.get('session_id') != target
            or event.get('hook_event_name') not in EVENTS):
        return None
    name = event['hook_event_name']
    result = {'session_id': target, 'event': name, 'observed_at': time.time()}
    for key in ('turn_id', 'agent_id', 'agent_type', 'source', 'stop_hook_active'):
        value = event.get(key)
        if isinstance(value, str) and len(value) <= 200:
            result[key] = value
        elif key == 'stop_hook_active' and type(value) is bool:
            result[key] = value
    if name in ('SubagentStart', 'SubagentStop'):
        result['worker_identity_present'] = bool(result.get('agent_id'))
        result['terminal_completion_proven'] = False
    if name == 'Interrupt':
        result['manual_interrupt_observed'] = True
    return result


def record(event, target, directory):
    row = observation(event, target)
    if row is None:
        return False
    # Unique immutable files avoid shared append races and require no waiting
    # or persistent service. No text, transcript paths or environment is saved.
    directory.mkdir(parents=True, exist_ok=True)
    import uuid
    path = directory / (str(time.time_ns()) + '-' + uuid.uuid4().hex + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(row, stream, ensure_ascii=True)
        stream.flush()
        os.fsync(stream.fileno())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        event = json.loads(sys.stdin.read(65537))
        record(event, args.target, args.output)
    except Exception:
        # This probe has no admission authority. Missing receipts are unknown.
        pass
    print('{}')


if __name__ == '__main__':
    main()
