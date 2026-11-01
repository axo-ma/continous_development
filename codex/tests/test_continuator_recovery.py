import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from tools import shared_continuator as service
from tools import continuator_runtime as runtime
from tools.continuator_task import task_xml, NS
from tests import test_shared_continuator as fixtures


class RecoveryTests(unittest.TestCase):
    def test_windows_task_recovers_failure_and_missing_process_without_second_watcher(self):
        root=ET.fromstring(task_xml('/home/service','/skills/shared_continuator.py','/python/pythonw.exe','S-1-5-21-user',dt.datetime(2026,11,1,tzinfo=dt.timezone.utc)))
        def text(path):return root.find(path,{'t':NS}).text
        self.assertEqual(text('t:Settings/t:MultipleInstancesPolicy'),'IgnoreNew')
        self.assertEqual(text('t:Settings/t:RestartOnFailure/t:Interval'),'PT1M')
        self.assertEqual(text('t:Triggers/t:TimeTrigger/t:Repetition/t:Interval'),'PT1M')
        self.assertEqual(text('t:Settings/t:ExecutionTimeLimit'),'PT0S')
        self.assertEqual(text('t:Principals/t:Principal/t:LogonType'),'InteractiveToken')
        self.assertEqual(len(root.findall('t:Actions/t:Exec',{'t':NS})),1)

    def test_dead_pid_and_stale_connected_status_are_never_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);identity=dict(pid=123,instance_id='one',process_created_at=10)
            (home/'PROCESS.json').write_text(json.dumps(identity))
            (home/'STATUS.json').write_text('{"reason":"connected"}')
            (home/'HEARTBEAT.json').write_text(json.dumps(dict(identity,observed_at=100)))
            with patch.object(runtime,'process_created',return_value=None):self.assertFalse(runtime.health(home,101)['healthy'])
            with patch.object(runtime,'process_created',return_value=10):
                self.assertFalse(runtime.health(home,200)['healthy'])
                self.assertTrue(runtime.health(home,101)['healthy'])
            with patch.object(runtime,'process_created',return_value=20):self.assertFalse(runtime.health(home,101)['healthy'])

    def run_fixture(self, home, connection, writer, bridge_factory=None):
        clock=[0]
        def sleep(seconds):clock[0]+=seconds
        class Bridge:
            def __init__(self,*a,**kw):pass
            def call(self,*a):return {}
            def close(self):pass
        with patch.object(service.Path,'home',return_value=home),patch.object(service,'connection',side_effect=connection),\
             patch.object(service,'DesktopBridge',bridge_factory or Bridge),patch.object(service.SharedService,'step',return_value=[]),\
             patch.object(service,'atomic',side_effect=writer),patch.object(service.time,'monotonic',side_effect=lambda:clock[0]),\
             patch.object(service.time,'sleep',side_effect=sleep):
            service.run(home,seconds=10)

    def test_temporary_state_write_failure_does_not_kill_loop_and_logs_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);original=service.atomic;failed=[False]
            def writer(path,value):
                if path.name=='STATUS.json' and not failed[0]:
                    failed[0]=True;raise PermissionError('simulated temporary sharing violation')
                return original(path,value)
            descriptor=dict(environment={},server='synthetic',publisher='owner')
            self.run_fixture(home,lambda h:(descriptor,'fingerprint'),writer)
            logs=[json.loads(x) for x in (home/'SERVICE.log').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(any(x['event']=='write_recovered' for x in logs))
            self.assertEqual(json.loads((home/'STATUS.json').read_text())['reason'],'connected')
            self.assertEqual(json.loads((home/'EXIT.json').read_text())['reason'],'normal')

    def test_unavailable_desktop_waits_then_reconnects_without_model_or_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);attempts=[0]
            def connection(h):
                attempts[0]+=1
                if attempts[0]<3:raise OSError('simulated unavailable Desktop')
                return dict(environment={},server='synthetic',publisher='owner'),'actual-fixture'
            self.run_fixture(home,connection,service.atomic)
            logs=[json.loads(x) for x in (home/'SERVICE.log').read_text(encoding='utf-8').splitlines()]
            states=[x['state'] for x in logs if x['event']=='state_changed']
            self.assertEqual(states,['waiting_for_desktop','connected'])
            self.assertGreaterEqual(attempts[0],3)
            self.assertFalse((home/'continue_HQ').exists())

    def test_unexpected_fatal_error_is_logged_with_exit_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);original=service.atomic
            def writer(path,value):
                if path.name=='PROCESS.json':raise ValueError('simulated unexpected startup fault')
                return original(path,value)
            with self.assertRaises(ValueError):self.run_fixture(home,lambda h:None,writer)
            events=[json.loads(x) for x in (home/'SERVICE.log').read_text(encoding='utf-8').splitlines()]
            fatal=next(x for x in events if x['event']=='fatal')
            self.assertIn('simulated unexpected startup fault',fatal['traceback'])
            self.assertEqual(json.loads((home/'EXIT.json').read_text())['reason'],'ValueError')

    def test_broken_desktop_client_is_closed_and_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);created=[];closed=[]
            class Client:
                def __init__(self,*a,**kw):self.index=len(created);created.append(self)
                def call(self,*a):
                    if self.index==0:raise TimeoutError('simulated broken Desktop pipe')
                    return {}
                def close(self):closed.append(self.index)
            descriptor=dict(environment={},server='synthetic',publisher='owner')
            self.run_fixture(home,lambda h:(descriptor,'same-actual-descriptor'),service.atomic,Client)
            self.assertEqual(len(created),2)
            self.assertIn(0,closed)
            self.assertEqual(json.loads((home/'STATUS.json').read_text())['reason'],'connected')

    def test_broken_project_status_does_not_prevent_other_hq_from_being_checked(self):
        f=fixtures.SharedTests();f.setUp();self.addCleanup(f.doCleanups)
        for n in range(2):
            f.flags(n).mkdir(parents=True);(f.flags(n)/'continue_HQ').touch();(f.flags(n)/'suspend_HQ').touch()
        (f.flags(0)/'SERVICE.json').write_text('broken')
        result=f.service.step()
        self.assertEqual(result[0]['reason'],'unavailable_no_send')
        self.assertEqual(result[1]['reason'],'stopped')
        self.assertEqual(f.sends,[])
