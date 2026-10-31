"""Multi-HQ sequencing, current owner and flags, using no real model calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools.shared_continuator import SharedService, run
from tools.planner_control import locked
from tools.continuator_hook import handle
from tools.planner_controls import user_command


class SharedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.roots = [self.home/'hq1', self.home/'hq2']
        self.sends = []
        self.quota = 20
        self.turns = {'owner1':'initial1', 'owner2':'initial2', 'new-owner':'new-initial'}
        self.busy = set()
        self.caller = None
        entries = []
        for n, root in enumerate(self.roots, 1):
            memory = root/'coordination/cd5'
            memory.mkdir(parents=True)
            (memory/'CHECKPOINT.json').write_text(json.dumps({'owner':{'thread_id':'owner'+str(n)}}), encoding='utf-8')
            entries.append(dict(root=str(root),authorized=True,model='gpt-6.1-sol',mac_script='fake'))
        (self.home/'REGISTRY.json').write_text(json.dumps(dict(projects=entries,app_tools_cache=str(self.home/'cache'))), encoding='utf-8')
        self.service = SharedService(self.home, self)
        policy = patch('tools.file_continuation_service.subprocess.run', return_value=SimpleNamespace(returncode=0,stdout='{"authorized":true}'))
        policy.start()
        self.addCleanup(policy.stop)

    def flags(self, n):
        return self.roots[n]/'coordination/cd5/goal-control'

    def call(self, name, args):
        if name == 'read_thread':
            owner = args['threadId']
            return dict(thread=dict(id=owner,status={'type':'active' if owner in self.busy else 'idle'}),turns=[dict(id=self.turns[owner],status='completed')])
        if name == 'get_usage_limits':
            return dict(ordinaryUsageAllowed=True,rateLimits=dict(primary=dict(usedPercent=self.quota,windowDurationMins=300)))
        self.sends.append((self.caller,args['threadId']))
        return dict(threadId=args['threadId'])

    def test_two_hqs_independent_flags_and_sequential_sends(self):
        user_command(self.flags(0),'continue')
        user_command(self.flags(1),'stop')
        result = self.service.step()
        self.assertEqual(self.sends,[('owner1','owner1')])
        self.assertEqual(result[1]['reason'],'stopped')
        user_command(self.flags(1),'continue')
        self.service.step()
        self.assertEqual(self.sends,[('owner1','owner1'),('owner2','owner2')])
        self.service.step()
        self.assertEqual(len(self.sends),2)

    def test_handoff_routes_service_and_commands_to_current_owner_only(self):
        cp=self.roots[0]/'coordination/cd5/CHECKPOINT.json'
        user_command(self.flags(0),'continue')
        self.service.step()
        cp.write_text(json.dumps({'owner':{'thread_id':'new-owner'}}),encoding='utf-8')
        self.service.step()
        self.assertEqual(self.sends, [('owner1','owner1'),('new-owner','new-owner')])
        handle(dict(session_id='owner1',hook_event_name='Interrupt'),self.home,{})
        self.assertFalse((self.flags(0)/'stop_planner').exists())
        handle(dict(session_id='new-owner',hook_event_name='Interrupt'),self.home,{})
        self.assertTrue((self.flags(0)/'stop_planner').exists())
        self.service.step()
        self.assertEqual(len(self.sends),2)

    def test_busy_and_quota90_do_not_send(self):
        for n in range(2): user_command(self.flags(n),'continue')
        self.busy={'owner1','owner2'}
        self.service.step()
        self.assertEqual(self.sends,[])
        self.busy.clear()
        self.quota=90
        self.service.step()
        self.assertEqual(self.sends,[])

    def test_unenrolled_chat_does_not_touch_any_flags(self):
        self.assertEqual(handle(dict(session_id='unrelated',hook_event_name='UserPromptSubmit',prompt='Continue Planner'),self.home,{}),{})
        self.assertFalse(any(self.flags(n).exists() for n in range(2)))

    def test_singleton_is_per_user_even_with_different_configuration_home(self):
        with patch('tools.shared_continuator.Path.home', return_value=self.home):
            with locked(self.home/'.codex/cd5-continuator/instance'):
                with self.assertRaises((PermissionError, BlockingIOError)):
                    run(self.home/'another-config', seconds=1)

    def test_actual_descriptor_refreshes_only_on_current_owner_event(self):
        server=self.home/'cache/1.2.3/server.mjs'
        server.parent.mkdir(parents=True)
        server.touch()
        env={'CODEX_MCP_NODE_PATH':'provided-runtime','CODEX_APP_TOOLS_PIPE_PATH':'provided-first'}
        event=dict(session_id='owner1',hook_event_name='SessionStart')
        handle(event,self.home,env)
        path=self.home/'CONNECTION.json'
        self.assertEqual(json.loads(path.read_text())['environment'],env)
        env['CODEX_APP_TOOLS_PIPE_PATH']='provided-second'
        handle(event,self.home,env)
        self.assertEqual(json.loads(path.read_text())['environment'],env)
