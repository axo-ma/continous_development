"""Finite requests over the genuine Desktop-provided app-tools MCP pipe.

Starts only the bundled MCP bridge client, never an independent app-server.
Does not invent a pipe, caller identity or connection credentials. Host lifecycle
and tool authorization still apply. No Goal mutation or arbitrary RPC is exposed.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


class DesktopBridge:
    READ_TOOLS = {'read_thread', 'get_usage_limits'}

    def __init__(self, server, caller, *, allow_send=False, timeout=8, env=None):
        env = os.environ if env is None else env
        if not isinstance(caller, str) or not caller:
            raise ValueError('actual authorized caller thread required')
        if not 0 < timeout <= 30:
            raise ValueError('finite request timeout required')
        runtime = env.get('CODEX_MCP_NODE_PATH')
        if not runtime or not env.get('CODEX_APP_TOOLS_PIPE_PATH') or not Path(server).is_file():
            raise RuntimeError('Desktop connection environment unavailable')
        self.caller, self.allow_send, self.timeout = caller, allow_send, timeout
        self.inbox, self.sequence = queue.Queue(), 0
        self.child = subprocess.Popen([runtime, str(server)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            env=dict(env), creationflags=0x08000000 if os.name == 'nt' else 0)
        def reader():
            for line in self.child.stdout:
                try:
                    self.inbox.put(json.loads(line))
                except ValueError:
                    pass
            self.inbox.put(None)
        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        try:
            self.request('initialize', {'protocolVersion': '2024-11-05',
                'capabilities': {}, 'clientInfo': {'name': 'cd5_external_bridge', 'version': '1'}})
            self.child.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            self.child.stdin.flush()
            self.catalog = self.request('tools/list', {})
        except Exception:
            self.close()
            raise

    def request(self, method, params):
        if method not in {'initialize', 'tools/list', 'tools/call'}:
            raise ValueError('arbitrary host RPC prohibited')
        if method == 'tools/call':
            permitted = self.READ_TOOLS | ({'send_message_to_thread'} if self.allow_send else set())
            if not isinstance(params, dict) or params.get('name') not in permitted:
                raise ValueError('tool not authorized for this bridge')
        self.sequence += 1
        identity = self.sequence
        self.child.stdin.write(json.dumps(dict(jsonrpc='2.0', id=identity,
                                               method=method, params=params)) + '\n')
        self.child.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Desktop request outcome unknown')
            item = self.inbox.get(timeout=remaining)
            if item is None:
                raise RuntimeError('Desktop connection closed')
            if item.get('id') == identity:
                if 'error' in item:
                    error = item['error']
                    raise RuntimeError('Desktop request rejected: ' + str(error.get('code'))
                                       + ' ' + str(error.get('message', ''))[:300])
                return item['result']

    def call(self, name, arguments):
        permitted = self.READ_TOOLS | ({'send_message_to_thread'} if self.allow_send else set())
        if name not in permitted:
            raise ValueError('tool not authorized for this bridge')
        if name not in {t.get('name') for t in self.catalog.get('tools', [])}:
            raise RuntimeError('Desktop tool unavailable')
        result = self.request('tools/call', {'name': name, 'arguments': arguments,
            '_meta': {'codex_thread_id': self.caller}})
        if result.get('isError'):
            raise RuntimeError('Desktop tool rejected operation')
        for block in result.get('content', []):
            if block.get('type') == 'text':
                try:
                    return json.loads(block['text'])
                except ValueError:
                    continue
        raise RuntimeError('Desktop tool returned no structured response')

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()
        try:
            self.child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=1)
        self.reader.join(timeout=.2)
        self.child.stdin.close()
        self.child.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
