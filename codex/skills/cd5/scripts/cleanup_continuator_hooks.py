"""Remove only the eight identified historical test hooks, with an exact backup."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import shutil
try:
    from .planner_control import atomic, read
except ImportError:
    from planner_control import atomic, read


def clean(data, definition, development_root, connection_probe, technical_target):
    result = copy.deepcopy(data)
    root = str(Path(development_root)).replace('\\', '/').rstrip('/')
    probe = str(Path(connection_probe)).replace('\\', '/')
    trial = root+'/reports/stop-hook-trial-20261029/stop-trial-eace4764e486f1c9.py'
    state = root+'/reports/stop-hook-trial-20261029/attempt-2/state.json'
    recorder = root+'/reports/hook-event-observation-20261030/event-probe-1e411c665f47be48.py'
    output = root+'/reports/hook-event-observation-20261030/events'
    removed = Counter()
    for event, groups in list(result.get('hooks', {}).items()):
        kept_groups = []
        for group in groups:
            kept = []
            for hook in group.get('hooks', []):
                command = hook.get('command', '').replace('\\', '/')
                kind = None
                if event == 'SessionStart' and probe in command:
                    kind = 'connection_probe'
                elif event in ('Stop', 'Interrupt') and trial in command and state in command and '--state' in command:
                    kind = 'stop_trial'
                elif (event in ('Stop', 'Interrupt', 'SubagentStart', 'SubagentStop', 'UserPromptSubmit')
                      and recorder in command and output in command
                      and '--target '+technical_target+' ' in command):
                    kind = 'event_probe'
                if kind:
                    removed[kind] += 1
                else:
                    kept.append(hook)
            if kept:
                kept_groups.append(dict(group, hooks=kept))
        if kept_groups:
            result['hooks'][event] = kept_groups
        else:
            del result['hooks'][event]
    if removed and removed != Counter(connection_probe=1, stop_trial=2, event_probe=5):
        raise ValueError('historical definitions differ from the authorized eight; no write')
    # Preserve the current exact definitions; never edit config.toml or trusted_hash.
    for event, groups in definition['hooks'].items():
        expected = [h for g in groups for h in g['hooks']]
        actual = [h for g in result['hooks'].get(event, []) for h in g['hooks']]
        if any(actual.count(h) != 1 for h in expected):
            raise ValueError('current shared hook missing or duplicated; no write')
    result['description'] = 'CD5 Continuator and Controls: подключённые Planner'
    return result, dict(removed)


def cleanup(path, definition, development_root, connection_probe, technical_target, backup_dir):
    path, backup_dir = Path(path), Path(backup_dir)
    before = path.read_bytes()
    result, removed = clean(read(path), definition, development_root, connection_probe, technical_target)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir/('hooks-before-test-cleanup-'+hashlib.sha256(before).hexdigest()[:16]+'.json')
    if not backup.exists():
        shutil.copy2(path, backup)
    atomic(path, result)
    return dict(removed=removed, remaining=sum(len(g['hooks']) for gs in result['hooks'].values() for g in gs),
                backup=str(backup), trust_changed=False, platform_retrust_may_be_required=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('hooks-file', 'definition', 'development-root', 'connection-probe', 'backup-dir'):
        p.add_argument('--'+flag, required=True, type=Path)
    p.add_argument('--technical-target', required=True)
    a = p.parse_args()
    print(json.dumps(cleanup(a.hooks_file, read(a.definition), a.development_root,
                            a.connection_probe, a.technical_target, a.backup_dir), ensure_ascii=False))


if __name__ == '__main__':
    main()
