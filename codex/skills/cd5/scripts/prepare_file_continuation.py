"""Historical per-chat preparation fixture; production uses setup_shared_continuator."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
try:
    from .cd5_config import memory_dir
    from .planner_control import atomic, read
except ImportError:
    from cd5_config import memory_dir
    from planner_control import atomic, read


def prepare(root, thread, server, hooks_file, mac_script, model):
    root = Path(root).resolve()
    server, mac_script, hooks_file = map(Path, (server, mac_script, hooks_file))
    if not thread or not server.is_file() or not mac_script.is_file():
        raise ValueError('actual chat, Desktop bridge and installed MAC script required')
    runtime = memory_dir(root) / 'goal-control'
    runtime.mkdir(parents=True, exist_ok=True)
    if (runtime/'CONFIG.json').exists() and read(runtime/'CONFIG.json').get('target') != thread:
        raise ValueError('this project control directory already belongs to another chat')
    source = Path(__file__).resolve().parent
    names = ('goal_files.py', 'goal_file_hook.py')
    digest = hashlib.sha256(b''.join((source/name).read_bytes() for name in names)).hexdigest()
    frozen = runtime / ('hooks-' + digest[:16])
    frozen.mkdir(exist_ok=True)
    for name in names:
        shutil.copy2(source/name, frozen/name)
    command = (f'"{sys.executable}" -X utf8 "{frozen / "goal_file_hook.py"}" '
               f'--target {thread} --directory "{runtime}"')
    group = {'hooks': [dict(type='command', command=command, timeout=2,
                           statusMessage='CD5: Stop Goal / Continue Goal — рабочий штаб')]}
    definition = {'description': 'Управление продолжением одного штаба',
                  'hooks': {event: [group] for event in ('Interrupt', 'UserPromptSubmit')}}
    current = read(hooks_file) if hooks_file.exists() else {'hooks': {}}
    original = json.dumps(current, ensure_ascii=False, indent=2)
    backup = runtime / ('hooks-before-' + hashlib.sha256(original.encode()).hexdigest()[:16] + '.json')
    if not backup.exists():
        atomic(backup, current)
    for event in definition['hooks']:
        groups = current.setdefault('hooks', {}).get(event, [])
        current['hooks'][event] = [g for g in groups if not any(
            'goal_file_hook.py' in h.get('command', '') and f'--target {thread} ' in h['command']
            for h in g.get('hooks', []))] + [group]
    hooks_file.parent.mkdir(parents=True, exist_ok=True)
    atomic(hooks_file, current)
    atomic(runtime/'hook-definition.json', definition)
    config = dict(mode='session', session_authorized=True, limit=None, seconds=None,
        native_goal_disabled=True, server=str(server), caller=thread, target=thread,
        flags=str(runtime), status=str(runtime/'SERVICE.json'), mac_script=str(mac_script), model=model,
        message=(f'Автоматическое продолжение ранее разрешённой работы CD5. Прочитай текущую '
                 f'память проекта и инструкцию file-continuation.md установленного CD5. '
                 f'Файлы управления: {runtime}. Сначала проверь Stop Goal: при наличии закончи '
                 f'без работы. Не создавай Continue Goal и не удаляй Stop Goal из автоматического '
                 f'сообщения. Если есть разрешённая работа — выполни следующий полезный шаг. '
                 f'Перед окончательным завершением, обязательным вопросом человеку, STOP или '
                 f'закрытой квотой удали Continue Goal. Промежуточный отчёт не означает завершения. '
                 f'Native Goal не создавай и не возобновляй; сообщения другим чатам без прямого '
                 f'поручения пользователя не отправляй.'))
    atomic(runtime/'CONFIG.json', config)
    return dict(config=str(runtime/'CONFIG.json'), definition=str(runtime/'hook-definition.json'),
                flags=str(runtime), frozen_sha256=digest, started=False, trust_changed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--thread', required=True)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--hooks-file', required=True, type=Path)
    parser.add_argument('--mac-script', required=True, type=Path)
    parser.add_argument('--model', required=True)
    parser.add_argument('--session-authorized', action='store_true', required=True)
    args = parser.parse_args()
    parser.error('per-chat setup is retired; use setup_shared_continuator.py')


if __name__ == '__main__':
    main()
