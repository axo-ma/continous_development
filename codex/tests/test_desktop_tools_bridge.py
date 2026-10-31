"""Synthetic stdio MCP server. Never connects to a user's Desktop pipe."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from tools.desktop_tools_bridge import DesktopBridge


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = Path(self.temp.name) / 'synthetic_server.py'
        self.server.write_text('''import sys,json
for line in sys.stdin:
 q=json.loads(line)
 if 'id' not in q:continue
 if q['method']=='tools/list':
  result={'tools':[{'name':n} for n in ['read_thread','get_usage_limits','send_message_to_thread']]}
 elif q['method']=='tools/call':
  result={'content':[{'type':'text','text':json.dumps({'caller':q['params']['_meta']['codex_thread_id']})}]}
 else:result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'synthetic','version':'1'}}
 print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':result}),flush=True)
''', encoding='utf-8')
        self.env = dict(os.environ, CODEX_MCP_NODE_PATH=sys.executable,
                        CODEX_APP_TOOLS_PIPE_PATH='synthetic-not-used')

    def test_real_stdio_handshake_and_actual_caller_metadata(self):
        with DesktopBridge(self.server, 'synthetic-owner', env=self.env) as bridge:
            self.assertEqual(bridge.call('read_thread', {})['caller'], 'synthetic-owner')

    def test_readonly_instance_cannot_send_or_mutate_goal(self):
        with DesktopBridge(self.server, 'synthetic-owner', env=self.env) as bridge:
            for name in ('send_message_to_thread', 'update_goal', 'thread/goal/set'):
                with self.assertRaises(ValueError):
                    bridge.call(name, {})
            with self.assertRaises(ValueError):
                bridge.request('thread/resume', {})
            with self.assertRaises(ValueError):
                bridge.request('tools/call', {'name': 'send_message_to_thread', 'arguments': {}})

    def test_explicit_send_mode_does_not_enable_other_tools(self):
        with DesktopBridge(self.server, 'synthetic-owner', env=self.env, allow_send=True) as bridge:
            self.assertEqual(bridge.call('send_message_to_thread', {})['caller'], 'synthetic-owner')
            with self.assertRaises(ValueError):
                bridge.call('create_thread', {})

    def test_missing_real_connection_environment_is_not_fabricated(self):
        with self.assertRaises(RuntimeError):
            DesktopBridge(self.server, 'synthetic-owner', env={})


if __name__ == '__main__':
    unittest.main()
