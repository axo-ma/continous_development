"""Migration proposals do not inherit open intervals or silently resolve conflicts."""
import unittest
from unittest.mock import patch
from tools.cu_assignment_candidates import candidates


class CandidateTests(unittest.TestCase):
    def test_only_exact_turns_and_conflicts_are_preserved(self):
        sessions={'owner':{'turns':[{'id':str(i),'start':{'_sha256':'proof'+str(i)}} for i in range(4)]}}
        def row(cu,identity,index):
            return dict(id=identity,payload=dict(type='control_unit_event',cu_id=cu),point=('owner',index))
        events=[row('old-open','a',0),row('new','b',2),row('other','c',2)]
        with patch('tools.cu_assignment_candidates._anchor',side_effect=lambda r,s:r['point']):
            result=candidates(events,sessions)
            self.assertEqual(result,candidates(events+events,sessions))
        self.assertEqual({r['turn_id'] for r in result},{'0','2'})
        conflict=next(r for r in result if r['turn_id']=='2')
        self.assertIsNone(conflict['confirmed_candidate'])
        self.assertEqual(set(conflict['candidates']),{'new','other'})
