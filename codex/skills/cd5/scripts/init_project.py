"""Initialize new five-file memory; never adopt or overwrite existing memory implicitly."""
import argparse
import json
from pathlib import Path
from cd5_config import FILES, memory_dir, memory_map


def initialize(root, task, owner, memory='coordination/cd5', owner_role='hq'):
    root = Path(root).resolve(strict=True)
    configuration = root/'.cd5/config.json'
    if configuration.exists():
        raise ValueError('project already configured; inspect existing memory')
    path = (root/memory).resolve()
    if path == root or not path.is_relative_to(root) or Path(memory).is_absolute():
        raise ValueError('memory must stay inside project')
    if path.exists() and any(path.iterdir()):
        raise ValueError('memory destination is not empty')
    if not task.strip() or not owner.strip() or not owner_role.strip():
        raise ValueError('task and owner required')
    configuration.parent.mkdir(exist_ok=True)
    configuration.write_text(json.dumps({'schema_version': 1, 'memory_dir': memory,
                                         'owner_role': owner_role}, indent=2), encoding='utf-8')
    path.mkdir(parents=True, exist_ok=True)
    cp = {'schema_version': 3, 'phase': 'user_stopped', 'owner': {'role': owner_role, 'thread_id': owner},
          'memory': memory_map(root), 'user_stop': {'active': True, 'reason': 'new project; explicit start required'},
          'next_action': {'kind': 'wait_user'}, 'continuity': {'quota_stop_used_percent': 90},
          'cd5': {'enabled': True}}
    for kind, filename in FILES.items():
        content = '# '+task+'\n\n## Goal\n\nDefine the goal and scope.\n\n## Risks\n\nIdentify and address risks before execution.\n\n## Milestones\n\n- [ ] `MS-01` — Define sufficient result\n  - status: not_started\n  - criteria: awaiting definition\n' if kind == 'outline' else ''
        if kind == 'checkpoint':
            content = json.dumps(cp, indent=2)+'\n'
        (path/filename).write_text(content, encoding='utf-8')
    return cp


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--owner-thread', required=True)
    parser.add_argument('--memory-dir', default='coordination/cd5')
    parser.add_argument('--owner-role', default='hq')
    args = parser.parse_args()
    try:
        print(json.dumps(initialize(args.root, args.task, args.owner_thread, args.memory_dir, args.owner_role), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
