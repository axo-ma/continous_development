"""Claude installer, independent skills, custom memory layout, STOP invariants, no Codex leftovers."""
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
        # Private copy of the skills; SKILL.md stubs only here (they are written separately).
        self.source = self.temp/'src'
        shutil.copytree(BUNDLE/'skills', self.source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('cd5', 'mac'):
            (self.source/name).mkdir(exist_ok=True)
            if not (self.source/name/'SKILL.md').exists():
                (self.source/name/'SKILL.md').write_text('---\nname: %s\n---\nstub\n' % name, encoding='utf-8')
        self.destination = self.temp/'other-user/custom skills'
        self.project = self.temp/'arbitrary project'
        self.project.mkdir()

    def cli(self, skill, script, *args, success=True):
        result = subprocess.run([sys.executable, str(self.destination/skill/'scripts'/script), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8', cwd=self.temp)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return json.loads(result.stdout) if success else result.stderr

    def init(self, *args):
        return self.cli('cd5', 'init_project.py', '--root', self.project, '--task', 'Other task',
                        '--owner-thread', 'actual-owner', *args)

    def test_cd5_alone_new_project_starts_stopped_and_validates(self):
        installer.install(self.source, self.destination, ('cd5',))
        self.assertFalse((self.destination/'mac').exists())
        cp = self.init()
        self.assertTrue(cp['user_stop']['active'])
        result = self.cli('cd5', 'project_memory.py', '--root', self.project, 'validate')
        self.assertEqual(result['checkpoint']['schema_version'], 3)
        self.cli('cd5', 'attention.py', '--root', self.project, 'list')
        before = (self.project/'coordination/cd5/CHECKPOINT.json').read_bytes()
        self.cli('cd5', 'init_project.py', '--root', self.project, '--task', 'Other',
                 '--owner-thread', 'other', success=False)
        self.assertEqual(before, (self.project/'coordination/cd5/CHECKPOINT.json').read_bytes())

    def test_custom_memory_dir_and_role(self):
        installer.install(self.source, self.destination, ('cd5',))
        cp = self.init('--memory-dir', 'work/memory', '--owner-role', 'custom_planner')
        self.assertEqual(cp['owner']['role'], 'custom_planner')
        self.cli('cd5', 'project_memory.py', '--root', self.project, 'validate')
        self.assertTrue((self.project/'work/memory/CHECKPOINT.json').is_file())
        cp['owner']['role'] = 'wrong'
        (self.project/'work/memory/CHECKPOINT.json').write_text(json.dumps(cp))
        self.cli('cd5', 'project_memory.py', '--root', self.project, 'validate', success=False)

    def test_escaping_memory_dir_rejected(self):
        installer.install(self.source, self.destination, ('cd5',))
        self.cli('cd5', 'init_project.py', '--root', self.project, '--task', 'x', '--owner-thread', 'p',
                 '--memory-dir', '../outside', success=False)

    def test_reinstall_keeps_backup_and_skips_pycache_and_foreign_skills(self):
        (self.destination/'new-hq').mkdir(parents=True)
        (self.destination/'new-hq/SKILL.md').write_text('mine', encoding='utf-8')
        installer.install(self.source, self.destination)
        self.assertTrue((self.destination/'mac/SKILL.md').is_file())
        (self.destination/'cd5/local-note.txt').write_text('old version marker', encoding='utf-8')
        pycache = self.source/'cd5/scripts/__pycache__'
        pycache.mkdir()
        (pycache/'x.pyc').write_bytes(b'0')
        result = installer.install(self.source, self.destination, ('cd5',))
        backup = Path(result['backup'])
        self.assertEqual(backup.parent, self.destination.parent/'skill-backups')
        self.assertEqual((backup/'cd5/local-note.txt').read_text(encoding='utf-8'), 'old version marker')
        self.assertFalse((self.destination/'cd5/local-note.txt').exists())
        self.assertFalse((self.destination/'cd5/scripts/__pycache__').exists())
        self.assertEqual((self.destination/'new-hq/SKILL.md').read_text(encoding='utf-8'), 'mine')

    def test_invalid_skill_name_rejected(self):
        with self.assertRaises(ValueError):
            installer.install(self.source, self.destination, ('nope',))

    def test_attention_html_has_no_codex_bridge(self):
        installer.install(self.source, self.destination, ('cd5',))
        self.init()
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0,sys.argv[1])\n"
            "import project_memory as pm, attention\n"
            "root=Path(sys.argv[2])\n"
            "pm.append(root,'attention',{'schema_version':1,'id':'question-a','kind':'attention_item',"
            "'status':'open','title':'Choice','question':'Which path?','blocking':True},'hq')\n"
            "out=attention.write_board(root, root/'board.html')\n"
            "sys.stdout.buffer.write(out.read_bytes())\n")
        result = subprocess.run([sys.executable, '-c', code, str(self.destination/'cd5/scripts'), str(self.project)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        html = result.stdout.decode('utf-8')
        self.assertNotIn('window.openai', html)
        self.assertNotIn('sendFollowUpMessage', html)
        self.assertIn('Ответьте в чате штаба', html)

    def test_skills_have_no_codex_references(self):
        for path in (BUNDLE/'skills').rglob('*'):
            if path.is_file() and path.suffix in {'.py', '.md', '.html', '.json'} and '__pycache__' not in path.parts:
                text = path.read_text(encoding='utf-8', errors='replace')
                self.assertNotIn('window.openai', text, str(path))
                self.assertNotIn('codex/', text.replace('\\', '/'), str(path))


if __name__ == '__main__':
    unittest.main()
