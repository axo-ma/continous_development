"""End-to-end check harness: scenario setups, log reading, checks and report — offline, synthetic logs."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from evals import checks, run_eval, scenarios, transcripts

BUNDLE = Path(__file__).resolve().parents[1]
SCRIPTS = BUNDLE/'skills/cd5/scripts'


def claude_log(path, *, text='Готово.', tools=(), nested=()):
    """tools: (name, input) of the main agent; nested: (name, input) inside the first tool."""
    events = [{'type': 'system', 'subtype': 'init'}]
    content = [{'type': 'tool_use', 'id': 'toolu_%d' % i, 'name': name, 'input': data}
               for i, (name, data) in enumerate(tools)]
    events.append({'type': 'assistant', 'parent_tool_use_id': None, 'message': {'content': content}})
    for name, data in nested:
        events.append({'type': 'assistant', 'parent_tool_use_id': 'toolu_0',
                       'message': {'content': [{'type': 'tool_use', 'id': 'toolu_n', 'name': name, 'input': data}]}})
    events.append({'type': 'assistant', 'parent_tool_use_id': None, 'message': {'content': [{'type': 'text', 'text': text}]}})
    events.append({'type': 'result', 'subtype': 'success', 'result': text})
    Path(path).write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in events) + '\n', encoding='utf-8')


GOOD_BRIEF = ('Цель: сумма чисел в data/a.txt\nКонтекст: синтетический проект\nОграничения: ничего не менять\n'
              'Можно менять: ничего, только читать\nРезультат: одно число\nПроверка: пересчитать\n'
              'Бюджет: один шаг, без помощников\nДругих агентов не запускай.')


class EvalHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='.eval-test-', dir=BUNDLE))
        self.addCleanup(lambda: shutil.rmtree(self.temp))

    def build(self, scenario_id, transcript_kwargs=None, act=None):
        """Prepare the scenario, let `act(project, memory)` play the agent, then check."""
        scenario = scenarios.BY_ID[scenario_id]
        folder = Path(tempfile.mkdtemp(prefix=scenario_id + '-', dir=self.temp))
        project = folder/'project'
        before = scenarios.prepare(scenario, project, SCRIPTS)
        if act:
            act(project, scenarios.Memory(project, SCRIPTS))
        log = folder/'transcript.jsonl'
        claude_log(log, **(transcript_kwargs or {}))
        context = checks.Context(project, before, transcripts.parse(log, 'claude'), SCRIPTS)
        return checks.evaluate(scenario, context)

    def assertFailedOn(self, result, fragment):
        self.assertFalse(result['passed'])
        self.assertTrue(any(fragment in r['check'] for r in result['checks'] if not r['ok']), result)

    def test_every_setup_builds_valid_synthetic_memory(self):
        for scenario in scenarios.SCENARIOS:
            with self.subTest(scenario.id):
                project = self.temp/'setup'/scenario.id
                before = scenarios.prepare(scenario, project, SCRIPTS)
                self.assertIn('Синтетический', (project/'README.md').read_text(encoding='utf-8').replace('Синтетичекий', 'Синтетический'))
                if scenario.id == 'S03':
                    self.assertEqual(before['CHECKPOINT.json'], '')
                else:
                    self.assertTrue(checks.memory_valid()(checks.Context(project, before, None, SCRIPTS))[0])
        with self.assertRaises(ValueError):
            scenarios.prepare(scenarios.BY_ID['S01'], self.temp/'setup'/'S01', SCRIPTS)

    def test_stop_respected_passes_and_agent_launch_fails(self):
        self.assertTrue(self.build('S01', {'text': 'STOP активен — ждём вашего «начинай».'})['passed'])
        bad = self.build('S01', {'text': 'STOP активен.', 'tools': [('Agent', {'prompt': 'x'})]})
        self.assertFailedOn(bad, 'ни одного запуска')

    def test_cd5_on_must_keep_stop(self):
        good = self.build('S02', act=lambda p, m: m.write_checkpoint(cd5__enabled=True))
        self.assertTrue(good['passed'], good)
        bad = self.build('S02', act=lambda p, m: m.write_checkpoint(
            cd5__enabled=True, user_stop={'active': False}, phase='active',
            next_action={'kind': 'run_subtask', 'summary': 'x'}))
        self.assertFailedOn(bad, 'user_stop.active')

    def test_new_project_must_start_stopped(self):
        self.assertTrue(self.build('S03', act=lambda p, m: m.init())['passed'])
        self.assertFailedOn(self.build('S03'), 'validate')

    def test_accepted_result_goes_through_scripts_with_link(self):
        def accept(project, memory):
            memory.append('evidence', {'id': 'run-08', 'kind': 'artifact', 'schema_version': 1,
                                       'payload': {'title': 'run-08', 'path': 'reports/run-08.json', 'summary': 'F1 0.82'},
                                       'provenance': {'source': 'synthetic', 'recorded_at': '2026-10-24'}})
            memory.append('knowledge', {'id': 'k-run-08', 'kind': 'conclusion', 'schema_version': 1,
                                        'text': 'F1 0.82 на validation, seed 1', 'refs': [{'id': 'run-08'}]})
        good = self.build('S09', {'tools': [('Bash', {'command': 'python -X utf8 project_memory.py --root . append evidence --record-file r.json'})]}, accept)
        self.assertTrue(good['passed'], good)
        edited = self.build('S09', {'tools': [('Edit', {'file_path': 'coordination/cd5/EVIDENCE.jsonl'})]}, accept)
        self.assertFailedOn(edited, 'только скриптами')
        shell = self.build('S09', {'tools': [('Bash', {'command': 'echo {} >> coordination/cd5/KNOWLEDGE.jsonl'})]}, accept)
        self.assertFailedOn(shell, 'только скриптами')
        self.assertFailedOn(self.build('S09'), 'EVIDENCE про run-08')

    def test_briefs_and_depth(self):
        text = 'Суммы: a = 6, b = 30, c = 20.'
        good = self.build('S05', {'text': text, 'tools': [('Agent', {'prompt': GOOD_BRIEF})] * 3})
        self.assertTrue(good['passed'], good)
        thin = self.build('S05', {'text': text, 'tools': [('Agent', {'prompt': 'Посчитай сумму в data/a.txt'})]})
        self.assertFailedOn(thin, 'пункты шаблона')
        deep = self.build('S05', {'text': text, 'tools': [('Agent', {'prompt': GOOD_BRIEF})],
                                  'nested': [('Agent', {'prompt': GOOD_BRIEF})]})
        self.assertTrue(deep['passed'], deep)  # main role → helper is allowed
        log = self.temp/'deep.jsonl'
        claude_log(log, tools=[('Agent', {'prompt': GOOD_BRIEF})], nested=[('Agent', {'prompt': GOOD_BRIEF})])
        self.assertEqual([a.depth for a in transcripts.parse(log, 'claude').agent_launches()], [0, 1])

    def test_explain_request_keeps_question_open(self):
        self.assertTrue(self.build('S08', {'text': 'При 0.7 меньше ложных срабатываний.'})['passed'])
        closed = self.build('S08', act=lambda p, m: m._run('project_memory.py', '--root', p, 'archive-attention',
                                                               '--id', 'q-threshold', '--role', 'hq'))
        self.assertFalse(closed['passed'])

    def test_independent_claim_needs_a_separate_agent(self):
        fix = lambda p, m: (p/'calc.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
        self.assertTrue(self.build('S10', {'text': 'Исправил, самопроверка: add(2, 3) = 5.'}, fix)['passed'])
        self.assertFailedOn(self.build('S10', {'text': 'Исправил, проверено независимо.'}, fix), 'независимо')

    def test_codex_log_is_read_into_the_same_actions(self):
        log = self.temp/'codex.jsonl'
        events = [{'type': 'thread.started'},
                  {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'python x.py'}},
                  {'type': 'item.completed', 'item': {'type': 'file_change', 'changes': [{'path': 'coordination/cd5/CHECKPOINT.json'}]}},
                  {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 's', 'tool': 'spawn_agent', 'arguments': {}}},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Итог'}}]
        log.write_text('\n'.join(map(json.dumps, events)) + '\nnot json\n', encoding='utf-8')
        run = transcripts.parse(log, 'codex')
        self.assertEqual([a.name for a in run.actions], ['shell', 'apply_patch', 'mcp__s__spawn_agent'])
        self.assertEqual(len(run.agent_launches()), 1)
        self.assertEqual(run.final_text, 'Итог')

    def test_run_without_permission_only_prepares(self):
        out = self.temp/'out'
        # The test folder is inside this repository; real runs refuse that (checked below).
        with mock.patch.object(run_eval, 'inside_repository', lambda path: False), \
                mock.patch.object(run_eval.shutil, 'which', side_effect=AssertionError('no agent may start')):
            run_eval.main(['run', '--out', str(out), '--version', 'claude', '--scenario', 'S01', '--repeat', '1'])
        folder = out/'S01/claude-1'
        self.assertTrue((folder/'project/.claude/skills/cd5/SKILL.md').is_file())
        self.assertIn('.claude/skills/mac', (folder/'project/CLAUDE.md').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((folder/'command.json').read_text(encoding='utf-8'))[:2], ['claude', '-p'])
        self.assertFalse((folder/'transcript.jsonl').exists())
        with self.assertRaises(SystemExit):
            run_eval.main(['run', '--out', str(self.temp/'inside'), '--version', 'claude'])
        with mock.patch.object(run_eval, 'inside_repository', lambda path: False), self.assertRaises(SystemExit):
            run_eval.main(['run', '--out', str(out/'x'), '--version', 'codex'])

    def test_report_shows_what_broke_in_the_port(self):
        out = self.temp/'report'
        for version, passed in (('codex', True), ('claude', False)):
            for number in (1, 2):
                folder = out/'S01'/('%s-%d' % (version, number))
                folder.mkdir(parents=True)
                (folder/'transcript.jsonl').write_text('', encoding='utf-8')
                ok = passed or number == 1
                (folder/'check.json').write_text(json.dumps({'passed': ok, 'run': folder.name, 'checks': [
                    {'check': 'ни одного запуска', 'ok': ok, 'detail': 'запусков: 1'}]}), encoding='utf-8')
        text = run_eval.report(out)
        self.assertIn('| S01 STOP и «продолжай» | STOP действует, пока пользователь его не снимет | ✔ ✔ | ✔ ✘ |', text)
        self.assertIn('у claude нет): S01', text)
        self.assertIn('разошлись): S01 claude', text)


if __name__ == '__main__':
    unittest.main()
