"""Exact, reversible removal without touching unrelated hooks or trust."""
import copy
import unittest
from tools.cleanup_continuator_hooks import clean


class CleanupHooksTests(unittest.TestCase):
    def fixture(self):
        root='/authorized/development'
        shared={'type':'command','command':'current-shared','timeout':4}
        definition={'hooks':{e:[{'hooks':[shared]}] for e in ('SessionStart','UserPromptSubmit','Interrupt')}}
        data=copy.deepcopy(definition)
        def add(event,command):data['hooks'].setdefault(event,[]).insert(0,{'hooks':[{'type':'command','command':command}]})
        add('SessionStart','/old/connection-probe.py')
        for e in ('Stop','Interrupt'):
            add(e,root+'/reports/stop-hook-trial-20261029/stop-trial-eace4764e486f1c9.py --state '+root+'/reports/stop-hook-trial-20261029/attempt-2/state.json')
        for e in ('Stop','Interrupt','SubagentStart','SubagentStop','UserPromptSubmit'):
            add(e,root+'/reports/hook-event-observation-20261030/event-probe-1e411c665f47be48.py --target target --output '+root+'/reports/hook-event-observation-20261030/events')
        return root,definition,data

    def test_only_exact_eight_removed_and_shared_preserved(self):
        root,definition,data=self.fixture()
        result,removed=clean(data,definition,root,'/old/connection-probe.py','target')
        self.assertEqual(sum(removed.values()),8)
        self.assertEqual(result['hooks'],definition['hooks'])
        self.assertEqual(sum(len(g['hooks']) for gs in data['hooks'].values() for g in gs),11)
        again,removed=clean(result,definition,root,'/old/connection-probe.py','target')
        self.assertEqual(removed,{})
        self.assertEqual(result,again)

    def test_unrelated_hooks_survive_and_partial_match_rejected(self):
        root,definition,data=self.fixture()
        other={'hooks':[{'type':'command','command':'unrelated'}]}
        data['hooks']['Stop'].append(other)
        result,_=clean(data,definition,root,'/old/connection-probe.py','target')
        self.assertEqual(result['hooks']['Stop'],[other])
        data['hooks']['SubagentStop']=[]
        with self.assertRaises(ValueError):
            clean(data,definition,root,'/old/connection-probe.py','target')
