"""Refresh actual Desktop connection and route commands to current enrolled owners."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
try:
    from .planner_file_hook import handle as handle_command
    from .planner_control import atomic, read
    from .shared_continuator import projects, current_project
except ImportError:
    from planner_file_hook import handle as handle_command
    from planner_control import atomic, read
    from shared_continuator import projects, current_project


def publish(home, owner, env):
    keys = ('CODEX_MCP_NODE_PATH', 'CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_APP_TOOLS_CALLER_HOST_ID')
    environment = {k: env[k] for k in keys if env.get(k)}
    if not all(environment.get(k) for k in keys[:2]):
        return False
    registry = read(Path(home)/'REGISTRY.json')
    cache = Path(registry['app_tools_cache'])
    servers = list(cache.glob('*/server.mjs'))
    if not servers:
        return False
    server = max(servers, key=lambda p: tuple(int(n) for n in p.parent.name.split('.')))
    descriptor = dict(source='actual_desktop_environment', publisher=owner,
                      server=str(server), environment=environment)
    path = Path(home)/'CONNECTION.json'
    if not path.exists() or read(path) != descriptor:
        atomic(path, descriptor)
    return True


def handle(event, home, env):
    if not isinstance(event, dict):
        return {}
    for entry, root in projects(Path(home)/'REGISTRY.json'):
        owner, flags, _ = current_project(entry, root)
        if event.get('session_id') != owner:
            continue
        publish(home, owner, env)
        result = handle_command(event, owner, flags)
        atomic(Path(home)/'HOOK-LAST.json', dict(event=event.get('hook_event_name'),
            owner=owner, observed_at=time.time(), connection_registered=(Path(home)/'CONNECTION.json').exists()))
        return result
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = handle(json.loads(sys.stdin.read(65537)), args.home, os.environ)
    except Exception:
        result = {'systemMessage': 'CD5: обработчик не подтвердил запись команды; состояние не изменено или неизвестно.'}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
