import copy
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tests import test_experiment_control as fixture
from tools import attention, project_memory as pm
from tools.decision_authority import human_requirement
from tools.experiment_control import ControlError, route, run_task
from tools.experiment_registry import read_events


class HQAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ControlTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root

    def test_agent_wait_and_blocking_labels_do_not_create_human_gate(self):
        self.f.state['next_action'] = {'kind':'wait_user'}
        self.f.save()
        pm.append(self.root,'attention',dict(schema_version=1,id='internal',kind='attention_item',status='blocking',
            payload=dict(question='Approve revised internal protocol?',blocking=True)), 'hq')
        path=self.root/'coordination/cd5/ATTENTION.jsonl';before=path.read_bytes()
        data=attention.list_items(self.root)
        self.assertEqual(data['items'][0]['status'],'owner_action')
        self.assertEqual(data['human_items'],[])
        self.assertEqual(len(data['owner_actions']),1)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(route(self.f.state,used_percent=20,ordinary_allowed=True)['action'],'planner_decision')

    def test_actual_requirement_has_source_and_does_not_promote_other_questions(self):
        for identity,payload in [('real',dict(constraint_source='system_permission',human_constraint_evidence='host approval rejection for the requested write')),
                                 ('internal',dict(constraint_source='hq',human_constraint_evidence='agent preference'))]:
            pm.append(self.root,'attention',dict(schema_version=1,id=identity,kind='attention_item',status='blocking',
                payload=dict(question=identity,blocking=True,**payload)),'hq')
        self.f.state['next_action']={'kind':'wait_user'};self.f.save()
        result=attention.list_items(self.root)
        self.assertEqual([x['id'] for x in result['human_items']],['real'])
        self.assertEqual([x['id'] for x in result['owner_actions']],['internal'])
        self.assertFalse(human_requirement(dict(constraint_source='user')))

    def test_real_constraint_does_not_hide_independent_work(self):
        state=copy.deepcopy(self.f.state)
        state['blocker']=dict(constraint_source='direct_user',human_constraint_evidence='user says ask before uploading',blocks_all_work=True)
        self.assertEqual(route(state,used_percent=20,ordinary_allowed=True)['action'],'wait_required_constraint')
        state['ready_actions']=[dict(authorized=True,useful=True,blocked=False,requires_human=False,kind='local_review')]
        self.assertEqual(route(state,used_percent=20,ordinary_allowed=True)['action'],'planner_decision')
        state['user_stop']['active']=True
        self.assertEqual(route(state,used_percent=20,ordinary_allowed=True)['action'],'wait_user_stop')

    def test_cu_and_task_completion_are_not_whole_plan_completion(self):
        state=copy.deepcopy(self.f.state);state['active_task']['status']='completed'
        state['cu_status']='completed';state['milestone_status']='completed'
        self.assertEqual(route(state,used_percent=20,ordinary_allowed=True)['action'],'planner_decision')
        state['whole_plan_complete']=True
        self.assertEqual(route(state,used_percent=20,ordinary_allowed=True)['action'],'complete')

    def revise(self):
        protocol=self.root/'results/test/PROTOCOL-v2.md';protocol.write_text('corrected',encoding='utf-8')
        self.f.state['active_task'].update(protocol_path='results/test/PROTOCOL-v2.md',
            protocol_sha256=hashlib.sha256(b'corrected').hexdigest(),max_attempts=2,revision=2,revision_reason='Repair the failed command within the assigned plan')
        self.f.save()

    def test_hq_repairs_versions_and_continues_without_human_reapproval(self):
        with patch('tools.experiment_control.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            self.assertEqual(run_task(self.root,'test',['fake']),1)
        first=read_events(self.root)
        with self.assertRaises(ControlError) as error:run_task(self.root,'test',['fake'])
        self.assertEqual(error.exception.action,'revise_in_hq')
        self.revise()
        with patch('tools.experiment_control.subprocess.run',return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(run_task(self.root,'test',['fake']),0)
        events=read_events(self.root)
        self.assertEqual(events[:len(first)],first)
        self.assertEqual([e['machine_facts']['attempt'] for e in events if e['event_type']=='execution_started'],[1,2])
        self.assertEqual((self.root/'results/test/PROTOCOL.md').read_text(),'test')
        versions=[e['machine_facts'] for e in events if e['event_type']=='protocol_frozen']
        self.assertEqual([v['revision'] for v in versions],[1,2])
        self.assertTrue(all(v['approval_authority']=='hq' and v['approved_by']=='p' for v in versions))

    def test_actual_user_limit_survives_revision_and_removal_from_current_state(self):
        self.f.state['active_task']['user_max_attempts']=1;self.f.save()
        with patch('tools.experiment_control.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            run_task(self.root,'test',['fake'])
        before=read_events(self.root);self.revise()
        del self.f.state['active_task']['user_max_attempts'];self.f.save()
        with patch('tools.experiment_control.subprocess.run') as process:
            with self.assertRaises(ControlError) as error:run_task(self.root,'test',['fake'])
            self.assertEqual(error.exception.action,'respect_user_limit');process.assert_not_called()
        self.assertEqual(read_events(self.root),before)

    def test_silent_allocation_change_needs_hq_revision_not_human(self):
        with patch('tools.experiment_control.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            run_task(self.root,'test',['fake'])
        self.f.state['active_task']['max_attempts']=2;self.f.save()
        with self.assertRaises(ControlError) as error:run_task(self.root,'test',['fake'])
        self.assertEqual(error.exception.action,'revise_in_hq')
