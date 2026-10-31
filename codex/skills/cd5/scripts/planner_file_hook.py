"""Exact-chat Interrupt and literal user commands; zero model or host calls."""
import argparse
import json
from pathlib import Path
import sys
try:
    from .planner_controls import user_command
except ImportError:
    from planner_controls import user_command


def handle(event, target, directory):
    if not isinstance(event, dict) or event.get('session_id') != target:
        return {}
    name = event.get('hook_event_name')
    if name == 'Interrupt':
        user_command(directory, 'stop')
        return {}
    if name == 'UserPromptSubmit' and isinstance(event.get('prompt'), str):
        command = event['prompt'].strip().lower()
        if command == 'continue goal':
            return {'decision': 'block', 'reason': 'Используйте Continue Planner; прежняя команда не включает продолжение.'}
        action = {'stop planner': 'stop', 'continue planner': 'continue', 'stop goal': 'stop'}.get(command)
        if action:
            user_command(directory, action)
            return {'decision': 'block', 'reason':
                'Автопродолжение выключено' if action == 'stop' else
                'Автопродолжение разрешено'}
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = handle(json.loads(sys.stdin.read(65537)), args.target, args.directory)
    except Exception:
        result = {'systemMessage': 'Не удалось записать команду Stop Planner; состояние не подтверждено.'}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
