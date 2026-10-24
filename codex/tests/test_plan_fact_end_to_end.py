"""Exercise real CLIs and native-shaped journals, without a live project."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.cd5_fixtures import configure


class PlanFactEndToEndTests(unittest.TestCase):
    def test_numeric_plan_and_measured_fact_survive_cli_storage_and_report(self):
        scripts = Path(__file__).parents[1] / 'tools'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configure(root)
            config_path = root / '.cd5/config.json'
            config = json.loads(config_path.read_text())
            config['control_units'] = {'telemetry': {'session_roots': ['native']}}
            config_path.write_text(json.dumps(config))
            memory = root / config.get('memory_dir', 'coordination/cd5')
            memory.mkdir(parents=True, exist_ok=True)
            checkpoint = {'schema_version': 3, 'owner': {'role': 'hq', 'thread_id': 'owner'},
                          'user_stop': {'active': True}, 'next_action': {'kind': 'wait_user'}}
            for name in ['OUTLINE.md', 'EVIDENCE.jsonl', 'KNOWLEDGE.jsonl', 'ATTENTION.jsonl']:
                (memory / name).write_text('')
            (memory / 'CHECKPOINT.json').write_text(json.dumps(checkpoint))
            native = root / 'native'
            native.mkdir()
            journal = native / 'owner.jsonl'

            def append(*rows):
                with journal.open('a', encoding='utf-8') as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + '\n')

            def event(kind, second, **payload):
                return {'type': 'event_msg', 'timestamp': f'2026-10-24T12:00:{second:02d}+00:00',
                        'payload': {'type': kind, **payload}}

            def counter(second, total, cached, output):
                return event('token_count', second, info={'total_token_usage': {
                    'input_tokens': total, 'cached_input_tokens': cached, 'output_tokens': output}})

            def start(identity, second):
                append(event('task_started', second, turn_id=identity),
                       {'type': 'turn_context', 'payload': {'turn_id': identity,
                        'model': 'gpt-6.1-sol', 'effort': 'low'}})

            def cli(script, *args, success=True):
                result = subprocess.run([sys.executable, str(scripts / script), '--root', str(root), *args],
                                        capture_output=True, text=True, encoding='utf-8')
                if success:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                return result

            append({'type': 'session_meta', 'payload': {'id': 'owner'}}, counter(0, 0, 0, 0))
            start('first-turn', 1)
            cli('control_units.py', 'begin', '--cu', 'CU-first', '--title', 'Synthetic first task',
                '--caller-thread', 'owner', '--forecast-low', '2', '--forecast-high', '5')
            append(counter(5, 1000000, 800000, 10000))
            cli('control_units.py', 'finish', '--cu', 'CU-first', '--result', 'Synthetic result',
                '--caller-thread', 'owner')
            append(event('task_complete', 6, turn_id='first-turn', duration_ms=5000))

            # A new task gets its own estimate; a bare new begin is rejected.
            start('second-turn', 10)
            rejected = cli('control_units.py', 'begin', '--cu', 'CU-second', '--title', 'Synthetic next task',
                           '--caller-thread', 'owner', success=False)
            self.assertIn('--forecast-low', rejected.stderr)
            cli('control_units.py', 'begin', '--cu', 'CU-second', '--title', 'Synthetic next task',
                '--caller-thread', 'owner', '--forecast-low', '8', '--forecast-high', '12')
            append(counter(15, 1100000, 850000, 12000))
            output = root / 'report.html'
            cli('control_unit_report.py', '--output', str(output))
            html = output.read_text(encoding='utf-8')
            data = json.loads(html.split('type="application/json">', 1)[1].split('</script>', 1)[0])
            units = {unit['cu_id']: unit for unit in data['units']}
            self.assertEqual(set(units), {'CU-first', 'CU-second'})
            self.assertEqual(units['CU-first']['budget']['forecast']['low'], '2')
            self.assertEqual(units['CU-first']['budget']['original_forecast']['high'], '5')
            self.assertEqual(units['CU-first']['work_units']['value'], '5.8')
            self.assertEqual(units['CU-second']['budget']['forecast']['low'], '8')
            self.assertEqual(units['CU-second']['budget']['forecast']['high'], '12')
            self.assertEqual(units['CU-second']['work_units']['status'], 'partial')
            self.assertEqual(units['CU-second']['work_units']['known_value'], '1.25')
            self.assertIsNone(units['CU-second']['work_units']['value'])
            self.assertEqual(json.loads((memory / 'CHECKPOINT.json').read_text()), checkpoint)


if __name__ == '__main__':
    unittest.main()
