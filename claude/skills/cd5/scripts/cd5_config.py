"""Project-local CD5 layout; no account, machine or project identifiers."""
import json
from pathlib import Path

FILES = {'outline': 'OUTLINE.md', 'checkpoint': 'CHECKPOINT.json', 'evidence': 'EVIDENCE.jsonl',
         'knowledge': 'KNOWLEDGE.jsonl', 'attention': 'ATTENTION.jsonl'}


def config(root):
    root = Path(root).resolve()
    path = root / '.cd5/config.json'
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('CD5 config must be an object')
    memory = data.get('memory_dir', 'coordination/cd5')
    if not isinstance(memory, str) or not memory or Path(memory).is_absolute():
        raise ValueError('memory_dir must be relative to project')
    target = (root / memory).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError('memory_dir escapes project')
    role = data.get('owner_role', 'hq')
    if not isinstance(role, str) or not role.strip():
        raise ValueError('owner_role required')
    return {**data, 'memory_dir': target.relative_to(root).as_posix(), 'owner_role': role}


def memory_dir(root):
    root = Path(root).resolve()
    return root / config(root)['memory_dir']


def memory_map(root):
    directory = config(root)['memory_dir']
    return {key: directory + '/' + name for key, name in FILES.items()}
