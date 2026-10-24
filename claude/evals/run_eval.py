"""End-to-end check of CD5/MAC: the same scenarios on the Codex and the Claude version.

Usage, from the `claude/` folder (`python` = Python 3.10+ with `-X utf8`):

    python -X utf8 -m evals.run_eval list
    python -X utf8 -m evals.run_eval run --out <folder> [--version claude codex] [--scenario S01 S02] [--repeat 2]
    python -X utf8 -m evals.run_eval check --out <folder>
    python -X utf8 -m evals.run_eval report --out <folder>

`run` without `--confirm-spend` only prepares the projects and prints the commands:
real runs spend usage and start only on an explicit user permission.
The output folder must be outside any repository: the agents would otherwise read its
CLAUDE.md/AGENTS.md. Projects are synthetic; never copy a real project's memory here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import checks, scenarios, transcripts

BUNDLE = Path(__file__).resolve().parents[1]
VERSIONS = ('codex', 'claude')


def install_claude(project, bundle):
    target = project/'.claude/skills'
    for name in ('cd5', 'mac'):
        shutil.copytree(bundle/'skills'/name, target/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    fragment = (bundle/'CLAUDE.fragment.md').read_text(encoding='utf-8')
    (project/'CLAUDE.md').write_text(fragment.replace('~/.claude/skills/', '.claude/skills/'), encoding='utf-8')


def install_codex(project, bundle):
    # Repository-level skills folder; not yet verified on a real Codex run.
    target = project/'.codex/skills'
    for name in ('cd5', 'mac'):
        shutil.copytree(bundle/'skills'/name, target/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    fragment = bundle/'AGENTS.fragment.md'
    if fragment.is_file():
        shutil.copy2(fragment, project/'AGENTS.md')


def command(version, project, prompt, model=None):
    if version == 'claude':
        line = ['claude', '-p', prompt, '--output-format', 'stream-json', '--verbose',
                '--permission-mode', 'bypassPermissions']
    else:
        line = ['codex', 'exec', '--json', '--skip-git-repo-check', '--sandbox', 'workspace-write',
                '-C', str(project), prompt]
    if model:
        line[2:2] = ['--model', model]
    return line


def run_folder(out, scenario, version, number):
    return Path(out)/scenario.id/('%s-%d' % (version, number))


def inside_repository(path):
    return any((parent/'.git').exists() for parent in [path, *path.parents])


def prepare_run(folder, scenario, version, bundles):
    project = folder/'project'
    before = scenarios.prepare(scenario, project, BUNDLE/'skills/cd5/scripts')
    (install_claude if version == 'claude' else install_codex)(project, bundles[version])
    (folder/'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding='utf-8')
    return project


def check_run(folder, scenario, version):
    run = transcripts.parse(folder/'transcript.jsonl', version)
    before = json.loads((folder/'before.json').read_text(encoding='utf-8'))
    context = checks.Context(folder/'project', before, run, BUNDLE/'skills/cd5/scripts')
    result = checks.evaluate(scenario, context)
    result.update(version=version, run=folder.name)
    (folder/'check.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    return result


def do_run(args):
    out = Path(args.out).resolve()
    if inside_repository(out):
        raise SystemExit('--out must be outside any git repository: %s' % out)
    bundles = {'claude': BUNDLE}
    if 'codex' in args.version:
        if not args.codex_bundle:
            raise SystemExit('--codex-bundle <path to the codex/ folder> is required for the codex version')
        bundles['codex'] = Path(args.codex_bundle).resolve()
    for scenario in selected(args.scenario):
        for version in args.version:
            if version not in scenario.versions:
                continue
            for number in range(1, args.repeat + 1):
                folder = run_folder(out, scenario, version, number)
                if folder.exists():
                    print('skip existing', folder)
                    continue
                project = prepare_run(folder, scenario, version, bundles)
                line = command(version, project, scenario.prompt, args.model)
                (folder/'command.json').write_text(json.dumps(line, ensure_ascii=False), encoding='utf-8')
                if not args.confirm_spend:
                    print('prepared', folder)
                    continue
                executable = shutil.which(line[0])
                if not executable:
                    raise SystemExit('%s is not on PATH' % line[0])
                with open(folder/'transcript.jsonl', 'w', encoding='utf-8') as log, \
                        open(folder/'stderr.txt', 'w', encoding='utf-8') as errors:
                    try:
                        subprocess.run([executable, *line[1:]], cwd=project, stdout=log, stderr=errors,
                                       timeout=args.timeout, env=os.environ.copy())
                    except subprocess.TimeoutExpired:
                        errors.write('timeout after %ss\n' % args.timeout)
                result = check_run(folder, scenario, version)
                print(scenario.id, version, number, 'PASS' if result['passed'] else 'FAIL')
    if not args.confirm_spend:
        print('Nothing was run. Add --confirm-spend to start the agents (spends usage).')


def do_check(args):
    for scenario, version, folder in existing(args.out):
        result = check_run(folder, scenario, version)
        print(scenario.id, folder.name, 'PASS' if result['passed'] else 'FAIL')


def existing(out):
    for scenario in scenarios.SCENARIOS:
        for folder in sorted((Path(out)/scenario.id).glob('*-*')):
            version = folder.name.rsplit('-', 1)[0]
            if version in VERSIONS and (folder/'transcript.jsonl').is_file():
                yield scenario, version, folder


def report(out):
    results = {}
    for scenario, version, folder in existing(out):
        path = folder/'check.json'
        if path.is_file():
            results.setdefault(scenario.id, {}).setdefault(version, []).append(json.loads(path.read_text(encoding='utf-8')))
    mark = lambda r: '✔' if r['passed'] else '✘'
    lines = ['| сценарий | правило | codex | claude |', '|---|---|---|---|']
    broken, unstable, failures = [], [], []
    for scenario in scenarios.SCENARIOS:
        row = results.get(scenario.id, {})
        cells = [' '.join(mark(r) for r in sorted(row.get(v, []), key=lambda r: r['run'])) or '—' for v in VERSIONS]
        lines.append('| %s %s | %s | %s | %s |' % (scenario.id, scenario.title, scenario.rule, *cells))
        old, new = row.get('codex', []), row.get('claude', [])
        if old and new and all(r['passed'] for r in old) and not all(r['passed'] for r in new):
            broken.append(scenario.id)
        for version, runs in row.items():
            if len({r['passed'] for r in runs}) > 1:
                unstable.append('%s %s' % (scenario.id, version))
            for r in runs:
                failures += ['- %s %s: %s — %s' % (scenario.id, r['run'], x['check'], x['detail'])
                             for x in r['checks'] if not x['ok']]
    lines += ['', 'Поломки переноса (у codex всё прошло, у claude нет): ' + (', '.join(broken) or 'нет'),
              'Нестабильно (прогоны одной версии разошлись): ' + (', '.join(unstable) or 'нет')]
    if failures:
        lines += ['', 'Непройденные проверки:', *failures]
    return '\n'.join(lines)


def selected(ids):
    if not ids:
        return scenarios.SCENARIOS
    unknown = [i for i in ids if i not in scenarios.BY_ID]
    if unknown:
        raise SystemExit('unknown scenarios: ' + ', '.join(unknown))
    return [scenarios.BY_ID[i] for i in ids]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    run = sub.add_parser('run')
    run.add_argument('--out', required=True)
    run.add_argument('--version', nargs='+', choices=VERSIONS, default=list(VERSIONS))
    run.add_argument('--scenario', nargs='*')
    run.add_argument('--repeat', type=int, default=2)
    run.add_argument('--codex-bundle', help='path to the codex/ folder of the canonical repository')
    run.add_argument('--model')
    run.add_argument('--timeout', type=int, default=900)
    run.add_argument('--confirm-spend', action='store_true', help='actually start the agents')
    for name in ('check', 'report'):
        sub.add_parser(name).add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.action == 'list':
        for s in scenarios.SCENARIOS:
            print('%s  %s — %s\n     «%s»' % (s.id, s.title, s.rule, s.prompt))
    elif args.action == 'run':
        do_run(args)
    elif args.action == 'check':
        do_check(args)
    else:
        print(report(args.out))


if __name__ == '__main__':
    sys.exit(main())
