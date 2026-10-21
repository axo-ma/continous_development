"""Clean installation, independent skills, custom memory layout and STOP invariants."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

BUNDLE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bundle_install', BUNDLE/'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='.portable-test-', dir=BUNDLE))
        self.addCleanup(lambda: shutil.rmtree(self.temp))
        self.destination = self.temp/'other-user/custom skills'
        self.project = self.temp/'arbitrary project'
        self.project.mkdir()

    def cli(self, skill, script, *args, success=True):
        result = subprocess.run([sys.executable, str(self.destination/skill/'scripts'/script), *map(str,args)],
                                capture_output=True, text=True, encoding='utf-8', cwd=self.temp)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return json.loads(result.stdout) if success else result.stderr

    def init(self, *args):
        return self.cli('cd5','init_project.py','--root',self.project,'--task','Other task',
                        '--owner-thread','actual-owner', *args)

    def test_cd5_alone_new_project_starts_stopped_and_validates(self):
        installer.install(BUNDLE/'skills', self.destination, ('cd5',))
        self.assertFalse((self.destination/'mac').exists())
        cp = self.init()
        self.assertTrue(cp['user_stop']['active'])
        result = self.cli('cd5','project_memory.py','--root', self.project,'validate')
        self.assertEqual(result['checkpoint']['schema_version'], 3)
        status = self.cli('cd5','experiment_control.py','--root',self.project,'status')
        self.assertTrue(status['user_stop'])
        self.assertEqual(self.cli('cd5','task_ledger.py','--root',self.project,'summary'), [])
        self.cli('cd5','attention.py','--root',self.project,'list')
        before = (self.project/'coordination/cd5/CHECKPOINT.json').read_bytes()
        self.init_failure()
        self.assertEqual(before,(self.project/'coordination/cd5/CHECKPOINT.json').read_bytes())

    def init_failure(self):
        self.cli('cd5','init_project.py','--root',self.project,'--task','Other','--owner-thread','other', success=False)

    def test_mac_alone_switch_and_upgrade_preserve_local_preferences(self):
        installer.install(BUNDLE/'skills',self.destination,('mac',))
        self.assertFalse((self.destination/'cd5').exists())
        self.assertEqual(self.cli('mac','mac_settings.py')['mode'], 'auto')
        self.cli('mac','mac_settings.py','off')
        path = self.destination/'mac/settings.json'
        data = json.loads(path.read_text())
        data['models'] = {'helper': {'model': 'locally-selected', 'effort': 'high'}}
        path.write_text(json.dumps(data))
        installer.install(BUNDLE/'skills',self.destination,('mac',))
        result = self.cli('mac','mac_settings.py')
        self.assertEqual(result['mode'], 'off')
        self.assertEqual(result['models'], data['models'])
        self.assertNotIn('enabled',result)

    def test_custom_memory_role_and_record_path(self):
        installer.install(BUNDLE/'skills', self.destination, ('cd5',))
        cp = self.init('--memory-dir','work/memory','--owner-role','custom_planner')
        self.assertEqual(cp['owner']['role'], 'custom_planner')
        self.cli('cd5','project_memory.py','--root',self.project,'validate')
        event = self.temp/'event.json'
        event.write_text(json.dumps({'event':'start','task_id':'task-a','title':'Task A','goal':'prepare',
            'executor':{'agent':'helper-a','model':'unknown','reasoning':'unknown'},'category':'mechanics'}))
        self.cli('cd5','task_ledger.py','--root',self.project,'record','--record-file',event,'--role','helper')
        rows = self.cli('cd5','task_ledger.py','--root',self.project,'summary')
        self.assertEqual(rows[0]['task_id'], 'task-a')
        self.assertTrue((self.project/'work/memory/EVIDENCE.jsonl').stat().st_size)
        cp['owner']['role'] = 'wrong'
        (self.project/'work/memory/CHECKPOINT.json').write_text(json.dumps(cp))
        self.cli('cd5','project_memory.py','--root',self.project,'validate',success=False)

    def test_escape_layout_and_invalid_mac_rejected(self):
        installer.install(BUNDLE/'skills', self.destination)
        self.cli('cd5','init_project.py','--root',self.project,'--task','x','--owner-thread','p',
                 '--memory-dir','../outside',success=False)
        path=self.destination/'mac/settings.json'
        path.write_text('{"schema_version":1,"mode":"auto","enabled":true}')
        self.cli('mac','mac_settings.py',success=False)

    def test_failed_preflight_can_retry_and_preserves_installation(self):
        installer.install(BUNDLE/'skills', self.destination)
        path = self.destination/'mac/settings.json'
        path.write_text('{"schema_version":2,"mode":"auto"}')
        before = (self.destination/'cd5/SKILL.md').read_bytes()
        with self.assertRaises(ValueError):
            installer.install(BUNDLE/'skills', self.destination)
        self.assertFalse((self.destination/'.cd5-install-stage').exists())
        self.assertEqual(before,(self.destination/'cd5/SKILL.md').read_bytes())
        path.write_text('{"schema_version":1,"mode":"off"}')
        installer.install(BUNDLE/'skills',self.destination)

    def test_attention_archive_and_fragment_need_no_project_tools(self):
        installer.install(BUNDLE/'skills', self.destination, ('cd5',))
        self.init()
        code = '''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import project_memory as pm
from duet_attention_fragment import build_fragment
root=Path(sys.argv[2])
pm.append(root,'attention',{'schema_version':1,'id':'question-a','kind':'attention_item','status':'open',
 'title':'Choice','question':'Which path?','blocking':True},'hq')
path=build_fragment(root,'question-a',Path(sys.argv[1]).parent/'assets/attention.png')
assert path.is_file()
pm.archive_attention(root,'question-a','hq')
pm.validate(root)
print(json.dumps({'ok':True}))
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.destination/'cd5/scripts'),str(self.project)],
                              capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
