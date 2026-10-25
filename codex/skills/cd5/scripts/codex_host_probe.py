"""Read-only probe of an EXISTING Codex app-server control socket.

Never starts a second server, resumes a thread or sends model input. Current
turn/start lacks a documented conditional-idle/idempotency contract, so this
adapter explicitly denies unattended wake. This diagnostic must not imply that
an unrelated standalone app-server knows Desktop activity.
"""
import argparse
import json
import queue
import subprocess
import sys
import threading
import time


def probe(command, owner, timeout=8):
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    messages = queue.Queue()
    def reader():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put({'error': 'control socket disconnected'})
    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    counter = 0
    def call(method, params):
        nonlocal counter
        counter += 1
        process.stdin.write(json.dumps({'id': counter, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            message = messages.get(timeout=max(.01, deadline - time.monotonic()))
            if message.get('id') == counter:
                if 'error' in message:
                    raise RuntimeError('host RPC rejected ' + method)
                return message['result']
            if message.get('error') or time.monotonic() > deadline:
                raise RuntimeError('control socket unavailable')
    try:
        call('initialize', {'clientInfo': {'name': 'cd5_readonly_probe', 'version': '1.0'}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        loaded = call('thread/loaded/list', {})['data']
        if owner not in loaded:
            return {'reason': 'owner not loaded on this server; Desktop activity unverified'}
        thread = call('thread/read', {'threadId': owner, 'includeTurns': False})['thread']
        limits = call('account/rateLimits/read', {})
        quota = (limits.get('rateLimitsByLimitId') or {}).get('codex') or limits.get('rateLimits') or {}
        primary = quota.get('primary') or {}
        return {'planner_status': thread.get('status', {}).get('type'),
                'quota': {'ordinary_allowed': limits.get('ordinaryUsageAllowed'),
                          'used_percent': primary.get('usedPercent'),
                          'window_minutes': primary.get('windowDurationMins'),
                          'resets_at': primary.get('resetsAt')},
                'reason': 'connected; safe conditional wake and worker coverage not established'}
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reader_thread.join(timeout=2)
        process.stdin.close()
        process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--socket')
    args = parser.parse_args()
    request = json.load(sys.stdin)
    response = {'owner_thread_id': request.get('owner_thread_id'),
                'wake_supported': False, 'workers_idle': None}
    if request.get('operation') != 'probe':
        response.update(accepted=False, reason='read-only adapter; wake unsupported')
    else:
        command = [args.codex, 'app-server', 'proxy']
        if args.socket:
            command += ['--sock', args.socket]
        try:
            response.update(probe(command, request['owner_thread_id']))
        except (OSError, RuntimeError, queue.Empty, BrokenPipeError):
            response['reason'] = 'existing Desktop control socket unavailable'
    response['observed_at'] = time.time()
    print(json.dumps(response))


if __name__ == '__main__':
    main()
