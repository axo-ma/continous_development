"""Enroll an authorized HQ, prepare frozen shared hooks and optional Windows logon."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
try:
    from .cd5_config import memory_dir
    from .planner_controls import migrate
    from .planner_control import atomic, read
except ImportError:
    from cd5_config import memory_dir
    from planner_controls import migrate
    from planner_control import atomic, read


def setup(home, root, hooks_file, cache, mac_script, model, install_logon=False):
    home, root, hooks_file = Path(home).resolve(), Path(root).resolve(), Path(hooks_file)
    cp = read(memory_dir(root)/'CHECKPOINT.json')
    owner = cp.get('owner', {}).get('thread_id')
    if not owner:
        raise ValueError('canonical current owner required before enrollment')
    policy = subprocess.run([sys.executable, '-X', 'utf8', str(mac_script),
                             'check-model', '--model', model], capture_output=True,
                            text=True, encoding='utf-8', timeout=10)
    if policy.returncode or json.loads(policy.stdout).get('authorized') is not True:
        raise ValueError('model policy denied enrollment')
    migrate(memory_dir(root)/'goal-control')
    home.mkdir(parents=True, exist_ok=True)
    registry_path = home/'REGISTRY.json'
    registry = read(registry_path) if registry_path.exists() else dict(schema_version=1, projects=[])
    registry['app_tools_cache'] = str(Path(cache).resolve())
    entries = registry['projects']
    matches = [e for e in entries if Path(e['root']).resolve() == root]
    if len(matches) > 1:
        raise ValueError('duplicate project enrollment')
    entry = matches[0] if matches else {}
    entry.update(root=str(root), authorized=True, model=model, mac_script=str(Path(mac_script).resolve()))
    if not matches:
        entries.append(entry)
    atomic(registry_path, registry)
    source = Path(__file__).resolve().parent
    names = ('continuator_hook.py', 'shared_continuator.py', 'planner_file_hook.py',
             'planner_controls.py', 'desktop_tools_bridge.py', 'file_continuation_service.py',
             'planner_control.py', 'cd5_config.py', 'stop_hook_trial.py', 'continuator_runtime.py')
    digest = hashlib.sha256(b''.join((source/n).read_bytes() for n in names)).hexdigest()
    frozen = home/('hooks-'+digest[:16])
    frozen.mkdir(exist_ok=True)
    for name in names:
        shutil.copy2(source/name, frozen/name)
    command = subprocess.list2cmdline([sys.executable, '-X', 'utf8', str(frozen/'continuator_hook.py'), '--home', str(home)])
    group = {'hooks': [dict(type='command', command=command, timeout=4,
                           statusMessage='CD5 controls: Continuator on/off; HQ start/suspend') ]}
    definition = dict(hooks={e:[group] for e in ('SessionStart', 'UserPromptSubmit', 'Interrupt')})
    current = read(hooks_file) if hooks_file.exists() else {'hooks':{}}
    original = json.dumps(current, ensure_ascii=False)
    backup = home/('hooks-before-'+hashlib.sha256(original.encode()).hexdigest()[:16]+'.json')
    if not backup.exists():
        atomic(backup, current)
    owners = {read(memory_dir(Path(e['root']))/'CHECKPOINT.json')['owner']['thread_id'] for e in entries if e.get('authorized') is True}
    for event in definition['hooks']:
        groups = current.setdefault('hooks', {}).get(event, [])
        def replaced(group):
            for hook in group.get('hooks', []):
                cmd = hook.get('command', '')
                if 'continuator_hook.py' in cmd and str(home) in cmd:
                    return True
                if any(n in cmd for n in ('planner_file_hook.py', 'goal_file_hook.py')) and any(f'--target {o} ' in cmd for o in owners):
                    return True
            return False
        current['hooks'][event] = [g for g in groups if not replaced(g)] + [group]
    hooks_file.parent.mkdir(parents=True, exist_ok=True)
    atomic(hooks_file, current)
    atomic(home/'hook-definition.json', definition)
    launcher = subprocess.list2cmdline([str(Path(sys.executable).with_name('pythonw.exe')),
        str(source/'shared_continuator.py'), '--home', str(home)])
    receipt = dict(home=str(home), project=str(root), current_owner=owner,
                   hooks=str(home/'hook-definition.json'), launcher=launcher,
                   logon_installed=False, started=False, trust_changed=False)
    if install_logon:
        if os.name != 'nt' or not Path(sys.executable).with_name('pythonw.exe').is_file():
            raise ValueError('Windows pythonw required')
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
            str(source/'install_continuator_task.ps1'), '-HomeDirectory', str(home),
            '-PythonExecutable', sys.executable], check=True, capture_output=True, text=True,
            encoding='utf-8', timeout=30)
        receipt['logon_installed'] = True
        receipt['started'] = True
        receipt['recovery_mechanism'] = 'Windows Task Scheduler'
    atomic(home/'SETUP.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('home', 'root', 'hooks-file', 'app-tools-cache', 'mac-script'):
        parser.add_argument('--'+flag, type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--authorized', required=True, action='store_true')
    parser.add_argument('--install-logon', action='store_true')
    args = parser.parse_args()
    print(json.dumps(setup(args.home, args.root, args.hooks_file, args.app_tools_cache,
                           args.mac_script, args.model, args.install_logon), ensure_ascii=False))


if __name__ == '__main__':
    main()
