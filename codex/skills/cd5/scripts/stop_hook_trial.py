"""Opt-in, one-shot Stop trial. No app-server, Goal writes or direct model calls.

Not a production continuation driver. Every non-target event is a no-op.
The exact command definition must be trusted through the host UI.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


def admitted(event, state):
    if not isinstance(event, dict) or not isinstance(state, dict):
        return False
    if not isinstance(state.get('target'), str) or not state['target']:
        return False
    if event.get('session_id') != state.get('target'):
        return False
    if event.get('hook_event_name') != 'Stop' or event.get('stop_hook_active') is not False:
        return False
    if not isinstance(event.get('turn_id'), str) or not event['turn_id']:
        return False
    required = {'authorized': True, 'stop': False, 'waiting_user': False,
                'goal_complete': False, 'workers_idle': True, 'goal_absent': True,
                'driver': 'stop_trial', 'remaining_step': 'CD5_STOP_STEP_TWO'}
    if any(type(state.get(key)) is not type(value) or state[key] != value
           for key, value in required.items()):
        return False
    if (state.get('owner') != state.get('target')
            or type(state.get('generation')) is not int or state['generation'] != 1):
        return False
    if event.get('last_assistant_message') != 'CD5_STOP_STEP_ONE':
        return False
    return True


def quota_allowed(value):
    if not isinstance(value, dict):
        return False
    if value.get('ordinaryUsageAllowed') is not True:
        return False
    buckets = value.get('rateLimitsByLimitId')
    bucket = buckets.get('codex') if isinstance(buckets, dict) else value.get('rateLimits')
    if not isinstance(bucket, dict):
        return False
    window = bucket.get('primary', {})
    if not isinstance(window, dict):
        return False
    percent = window.get('usedPercent')
    return (window.get('windowDurationMins') == 300 and type(percent) in (int, float)
            and 0 <= percent < 90 and bucket.get('spendControlReached') is not True)


def read_quota(env, state):
    """First-party MCP client on the actual hook pipe; one finite read."""
    runtime = env.get('CODEX_MCP_NODE_PATH')
    server = Path(state['server'])
    if not runtime or not env.get('CODEX_APP_TOOLS_PIPE_PATH') or not server.is_file():
        raise RuntimeError('connection_environment_unavailable')
    child = subprocess.Popen([runtime, str(server)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
        creationflags=0x08000000 if os.name == 'nt' else 0)
    inbox = queue.Queue()
    def reader():
        for line in child.stdout:
            try:
                inbox.put(json.loads(line))
            except ValueError:
                pass
        inbox.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8
    def request(identity, method, params):
        child.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': identity,
            'method': method, 'params': params}) + '\n')
        child.stdin.flush()
        while True:
            item = inbox.get(timeout=max(.01, deadline - time.monotonic()))
            if item is None or time.monotonic() > deadline:
                raise RuntimeError('connection_unconfirmed')
            if item.get('id') == identity:
                if 'error' in item:
                    raise RuntimeError('read_rejected')
                return item['result']
    try:
        request(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'cd5_stop_trial_readonly', 'version': '1'}})
        child.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        child.stdin.flush()
        catalog = request(2, 'tools/list', {})
        if 'get_usage_limits' not in [t.get('name') for t in catalog.get('tools', [])]:
            raise RuntimeError('quota_tool_unavailable')
        result = request(3, 'tools/call', {'name': 'get_usage_limits', 'arguments': {},
            '_meta': {'codex_thread_id': state['target']}})
        if result.get('isError'):
            raise RuntimeError('quota_read_rejected')
        return json.loads(next(c['text'] for c in result['content'] if c.get('type') == 'text'))
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=1)
        thread.join(timeout=.2)
        child.stdin.close()
        child.stdout.close()


def run(event, state_path, env, connector=read_quota):
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if event.get('session_id') != state.get('target'):
        return {}
    receipt = state_path.with_name('receipt.json')
    if event.get('hook_event_name') == 'Interrupt':
        state['stop'] = True
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        return {}
    if not admitted(event, state):
        return {}
    try:
        with receipt.open('x', encoding='utf-8') as f:
            json.dump({'decision': 'reserved_unconfirmed', 'turn_id': event['turn_id']}, f)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        return {}
    report = {'session_id': state['target'], 'turn_id': event['turn_id'],
              'observed_at': time.time(), 'decision': 'deny',
              'model_inputs_sent': 0, 'goal_writes': 0, 'app_servers_started': 0}
    output = {}
    try:
        quota = connector(env, state)
        report['quota_allowed'] = quota_allowed(quota)
        report['quota'] = {k: quota.get(k) for k in
                          ('ordinaryUsageAllowed', 'rateLimits', 'rateLimitsByLimitId')}
        latest = json.loads(state_path.read_text(encoding='utf-8'))
        if latest == state and report['quota_allowed']:
            report['decision'] = 'block_once'
            output = {'decision': 'block', 'reason':
                'Разрешённый второй шаг технического опыта: ответь только CD5_STOP_STEP_TWO. '
                'Не вызывай инструменты, не создавай Goal или помощников. Затем заверши ход.'}
    except Exception:
        report['reason'] = 'quota_connection_unconfirmed'
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    output = {}
    try:
        event = json.loads(sys.stdin.read(65537))
        output = run(event, args.state, os.environ)
    except Exception:
        pass
    # Command pipes may use a Windows legacy encoding. JSON escapes preserve
    # the Unicode reason without depending on the process stdout code page.
    print(json.dumps(output, ensure_ascii=True))


if __name__ == '__main__':
    main()
