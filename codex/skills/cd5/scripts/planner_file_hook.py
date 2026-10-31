"""Exact-chat Interrupt and literal user commands; zero model or host calls."""
import argparse
import json
from pathlib import Path
import sys
try:
    from .planner_controls import user_command
except ImportError:
    from planner_controls import user_command


COMMANDS = {}
for action, phrases in {
    'enable': ('enable continuator', 'включить континуатор', 'включи континуатор'),
    'disable': ('disable continuator', 'отключить континуатор', 'отключи континуатор', 'выключить континуатор'),
    'start': ('start planner', 'continue planner', 'continue hq', 'start hq', 'продолжай',
              'продолжить hq', 'продолжи hq', 'продолжить штаб', 'продолжи штаб',
              'стартануть планер', 'стартовать планер', 'запусти планер', 'продолжить планер', 'продолжить чат', 'продолжи чат', 'start chat', 'continue chat'),
    'stop': ('stop planner', 'stop hq', 'stop goal', 'остановить планер', 'останови планер',
             'остановить hq', 'останови hq', 'остановить штаб', 'останови штаб', 'остановить чат', 'останови чат', 'stop chat'),
}.items():
    COMMANDS.update(dict.fromkeys(phrases, action))


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
            return {'decision': 'block', 'reason': 'Используйте «Продолжай» для запуска штаба; включение Continuator — отдельная команда.'}
        action = COMMANDS.get(command.rstrip('.!').strip())
        if action:
            user_command(directory, action)
            if action == 'start':
                return {}  # Run this user turn even when Continuator is disabled.
            return {'decision': 'block', 'reason': {
                'enable': 'Continuator включён; состояние приостановки штаба сохранено.',
                'disable': 'Continuator выключен; состояние планировщика сохранено.',
                'stop': 'Штаб приостановлен; включение Continuator не изменено.',
            }[action]}
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = handle(json.loads(sys.stdin.read(65537)), args.target, args.directory)
    except Exception:
        result = {'systemMessage': 'CD5: запись команды не подтверждена; состояние неизвестно.'}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
