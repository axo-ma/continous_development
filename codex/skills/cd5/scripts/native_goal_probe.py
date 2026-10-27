"""Finite official AppServer read probe. No thread loading, turns or Goal writes."""
import argparse
import hashlib
import os
import uuid
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

ALLOWED = {'initialize', 'thread/goal/get', 'account/rateLimits/read', 'thread/read'}


def probe(command, owner, timeout=12):
    """Read persisted metadata only. Never infer live Desktop idle or wake support."""
    uuid.UUID(owner)
    if (not isinstance(command, (list, tuple)) or not command
            or any(not isinstance(part, str) or not part for part in command)):
        raise ValueError('explicit trusted CLI argv required')
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
        raise ValueError('timeout must be between 0 and 30 seconds')
    child = subprocess.Popen([*command, 'app-server', '--stdio'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', creationflags=0x08000000 if os.name == 'nt' else 0)
    inbox = queue.Queue()
    def read():
        for line in child.stdout:
            try: inbox.put(json.loads(line))
            except ValueError: pass
        inbox.put({'closed': True})
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    methods = []
    def request(number, method, params):
        if method not in ALLOWED:
            raise ValueError('mutating or unknown request forbidden')
        methods.append(method)
        child.stdin.write(json.dumps({'id': number, 'method': method, 'params': params}) + '\n')
        child.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            message = inbox.get(timeout=max(0.01, deadline - time.monotonic()))
            if message.get('closed'): raise RuntimeError('service closed')
            if message.get('id') == number: return message
            if time.monotonic() >= deadline: raise TimeoutError('read deadline')
    report = {'model_inputs_sent': 0, 'goal_mutations_sent': 0,
              'thread_loads_sent': 0,
              'scope': 'persisted_metadata_only', 'wake_supported': False,
              'workers_idle': None, 'live_desktop_activity_verified': False}
    try:
        initialized = request(1, 'initialize', {'clientInfo': {
            'name': 'cd5_readonly_recovery_probe', 'version': '1'}})
        report['initialize_ok'] = 'result' in initialized
        if not report['initialize_ok']:
            report['initialize_error_code'] = initialized.get('error', {}).get('code')
        else:
            child.stdin.write('{"method":"initialized","params":{}}\n')
            child.stdin.flush()
            response = request(2, 'thread/goal/get', {'threadId': owner})
            report['goal_read_ok'] = 'result' in response
            if 'result' in response:
                goal = response['result'].get('goal')
                report['goal_exists'] = goal is not None
                if goal:
                    report.update(goal_status=goal.get('status'), tokens_used=goal.get('tokensUsed'),
                                  created_at=goal.get('createdAt'), updated_at=goal.get('updatedAt'),
                                  objective_sha256=hashlib.sha256(goal['objective'].encode()).hexdigest())
            else:
                report['goal_error_code'] = response.get('error', {}).get('code')
            response = request(3, 'account/rateLimits/read', {})
            report['quota_read_ok'] = 'result' in response
            if 'result' in response:
                rates = response['result']
                report['quota_result_fields'] = sorted(rates)
                report['ordinary_usage_allowed_if_provided'] = rates.get('ordinaryUsageAllowed') if type(rates.get('ordinaryUsageAllowed')) is bool else None
                bucket = (rates.get('rateLimitsByLimitId') or {}).get('codex') or rates.get('rateLimits') or {}
                report['quota_primary'] = bucket.get('primary')
            else:
                report['quota_error_code'] = response.get('error', {}).get('code')
            response = request(4, 'thread/read', {'threadId': owner, 'includeTurns': False})
            report['thread_metadata_read_ok'] = 'result' in response
            if 'result' in response:
                report['thread_runtime_status'] = response['result'].get('thread', {}).get('status')
            else:
                report['thread_read_error_code'] = response.get('error', {}).get('code')
    except Exception as error:
        report['probe_error_type'] = type(error).__name__
    finally:
        child.terminate()
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        reader.join(timeout=2)
        child.stdin.close()
        child.stdout.close()
        report['requests'] = methods
        report['helper_exited'] = child.poll() is not None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True, type=Path, help='Explicit trusted installed Codex CLI path')
    parser.add_argument('--owner-thread', required=True)
    args = parser.parse_args()
    if not args.cli.is_file():
        parser.error('CLI file does not exist')
    try:
        print(json.dumps(probe([str(args.cli)], args.owner_thread), ensure_ascii=False))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__': main()
