"""Synthetic stdio service; no real account, app, model or journal access."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.native_goal_probe import probe


SERVER = '''
import json,sys,time
from pathlib import Path
mode,log=sys.argv[1:3]
for line in sys.stdin:
    request=json.loads(line)
    with Path(log).open('a') as stream:stream.write(json.dumps(request)+'\\n')
    if 'id' not in request:continue
    method=request['method']
    if mode=='timeout' and method=='thread/goal/get':time.sleep(15)
    if method=='initialize':result={}
    elif method=='thread/goal/get':
        if mode=='error':
            print(json.dumps({'id':request['id'],'error':{'code':-32601}}),flush=True)
            continue
        goal=None if mode=='absent' else {'objective':'Synthetic private objective',
              'status':'paused','tokensUsed':17,'createdAt':100,'updatedAt':200}
        result={'goal':goal}
    elif method=='account/rateLimits/read':
        result={'rateLimits':{'primary':{'usedPercent':4,'windowDurationMins':300}}}
        if mode!='unknown_quota':result['ordinaryUsageAllowed']=True
    elif method=='thread/read':result={'thread':{'status':{'type':'notLoaded'}}}
    else:raise RuntimeError('forbidden request')
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
'''


class NativeGoalProbeTests(unittest.TestCase):
    def run_probe(self, mode='normal', timeout=2):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'synthetic_server.py'
            log=Path(tmp)/'requests.jsonl'
            script.write_text(SERVER,encoding='utf-8')
            report=probe([sys.executable,str(script),mode,str(log)],
                         '11111111-1111-4111-8111-111111111111',timeout=timeout)
            requests=[json.loads(line) for line in log.read_text().splitlines()]
            return report,requests

    def test_reads_never_load_turn_or_mutate_and_do_not_imply_desktop_idle(self):
        report,requests=self.run_probe()
        self.assertEqual([row['method'] for row in requests],
            ['initialize','initialized','thread/goal/get','account/rateLimits/read','thread/read'])
        self.assertFalse(requests[-1]['params']['includeTurns'])
        self.assertEqual(report['goal_status'],'paused')
        self.assertEqual(report['tokens_used'],17)
        self.assertNotIn('objective',report)
        self.assertFalse(report['wake_supported'])
        self.assertIsNone(report['workers_idle'])
        self.assertFalse(report['live_desktop_activity_verified'])
        self.assertTrue(report['helper_exited'])
        self.assertEqual(report['model_inputs_sent'],0)

    def test_unknown_absent_and_unavailable_are_distinct(self):
        report,_=self.run_probe('unknown_quota')
        self.assertIsNone(report['ordinary_usage_allowed_if_provided'])
        report,_=self.run_probe('absent')
        self.assertTrue(report['goal_read_ok'])
        self.assertFalse(report['goal_exists'])
        report,_=self.run_probe('error')
        self.assertFalse(report['goal_read_ok'])
        self.assertNotIn('goal_exists',report)
        self.assertTrue(report['helper_exited'])

    def test_timeout_reaps_helper_without_retrying(self):
        report,requests=self.run_probe('timeout',timeout=.5)
        self.assertIn('probe_error_type',report)
        self.assertTrue(report['helper_exited'])
        self.assertEqual(sum(row['method']=='thread/goal/get' for row in requests),1)
        self.assertFalse(report['wake_supported'])
