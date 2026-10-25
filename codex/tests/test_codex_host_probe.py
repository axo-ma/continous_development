"""Synthetic existing-server protocol; no real Codex or account access."""
import sys
import tempfile
from pathlib import Path
import unittest
from tools import codex_host_probe


class HostProbeTests(unittest.TestCase):
    def test_probe_uses_only_read_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'synthetic_server.py'
            script.write_text('''import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 method=r['method']
 assert method in ['initialize','thread/loaded/list','thread/read','account/rateLimits/read']
 values={'initialize':{}, 'thread/loaded/list':{'data':['synthetic']},
 'thread/read':{'thread':{'status':{'type':'idle'}}},
 'account/rateLimits/read':{'ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':20,'windowDurationMins':300}}}}
 print(json.dumps({'id':r['id'],'result':values[method]}),flush=True)
''', encoding='utf-8')
            result = codex_host_probe.probe([sys.executable, str(script)], 'synthetic')
            self.assertEqual(result['planner_status'], 'idle')
            self.assertEqual(result['quota']['used_percent'], 20)
            self.assertIn('not established', result['reason'])


if __name__ == '__main__':
    unittest.main()
