"""Explicit configuration for fixtures representing the existing project layout."""
import json


def configure(root):
    directory = root / '.cd5'
    directory.mkdir(exist_ok=True)
    (directory/'config.json').write_text(json.dumps({'schema_version': 1,
        'memory_dir': 'coordination/cd5', 'owner_role': 'hq'}), encoding='utf-8')
