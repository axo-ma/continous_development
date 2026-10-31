"""One per-user CD5 service; sequentially service explicitly enrolled HQs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
try:
    from .cd5_config import memory_dir
    from .desktop_tools_bridge import DesktopBridge
    from .file_continuation_service import FileService
    from .planner_controls import permission
    from .planner_control import atomic, locked, read
except ImportError:
    from cd5_config import memory_dir
    from desktop_tools_bridge import DesktopBridge
    from file_continuation_service import FileService
    from planner_controls import permission
    from planner_control import atomic, locked, read


def projects(registry):
    data = read(Path(registry))
    entries = data.get('projects')
    if not isinstance(entries, list):
        raise ValueError('explicit enrolled project list required')
    roots = set()
    for entry in entries:
        if entry.get('authorized') is not True:
            continue
        root = Path(entry['root']).resolve()
        if root in roots:
            raise ValueError('duplicate enrolled project')
        roots.add(root)
        yield entry, root


def current_project(entry, root):
    memory = memory_dir(root)
    checkpoint = read(memory/'CHECKPOINT.json')
    owner = checkpoint.get('owner', {}).get('thread_id')
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError('current CHECKPOINT owner required')
    flags = memory/'goal-control'
    return owner, flags, dict(mode='session', session_authorized=True, limit=None,
        target=owner, flags=str(flags), status=str(flags/'SERVICE.json'),
        mac_script=entry['mac_script'], model=entry['model'],
        message=entry.get('message') or (
            f'Продолжай ранее разрешённую работу CD5 в {root}. Прочитай текущие '
            f'OUTLINE и CHECKPOINT. Управление: {flags}. Сначала проверь stop_planner; '
            f'при наличии не начинай работу. Автоматическое сообщение не разрешает '
            f'создавать continue_planner или удалять stop_planner. Выполни следующий полезный '
            f'разрешённый шаг. Перед окончательным завершением или обязательным вопросом '
            f'удали continue_planner. При квоте>=90 сохрани continue_planner и закончи ход; '
            f'служба сама дождётся квоты<90 без модели. Промежуточный отчёт не причина '
            f'останавливать работу. Встроенные Goal агентов не использовать как драйвер CD5.'))


class SharedService:
    def __init__(self, home, bridge):
        self.home, self.bridge = Path(home), bridge

    def step(self):
        results = []
        for entry, root in projects(self.home/'REGISTRY.json'):
            try:
                owner, flags, config = current_project(entry, root)
                flags.mkdir(parents=True, exist_ok=True)
                status_file = Path(config['status'])
                saved = read(status_file) if status_file.exists() else None
                if saved and saved.get('target') != owner:
                    if saved.get('uncertain') is True:
                        results.append(dict(root=str(root), reason='owner_changed_after_uncertain_send'))
                        continue
                    # The canonical accepted ownership record moved; keep counters/history.
                    history = list(saved.get('owner_history', []))
                    history.append({k: v for k, v in saved.items() if k != 'owner_history'})
                    saved = dict(used=saved['used'], waiting=False, before_turn=None,
                                 uncertain=False,
                                 target=owner, owner_history=history)
                # A new actor between checks must not receive the old actor's send.
                real_call = self.bridge.call
                def bound_call(name, args):
                    actual = read(memory_dir(root)/'CHECKPOINT.json').get('owner', {}).get('thread_id')
                    if actual != owner:
                        raise RuntimeError('owner changed during observation')
                    self.bridge.caller = owner
                    return real_call(name, args)
                class Bound:
                    call = staticmethod(bound_call)
                if 'trial_limit' in entry:
                    config.update(mode='trial', limit=entry['trial_limit'])
                with locked(flags/'.service-instance'):
                    service = FileService(config, Bound(), saved)
                    # No Desktop call if Stop/no permission; no model while waiting.
                    result = service.tick()
                results.append(dict(root=str(root), owner=owner, used=result['used'], reason=result['reason']))
            except Exception as error:
                results.append(dict(root=str(root), reason='unavailable_no_send', error=type(error).__name__))
        return results


def connection(home):
    descriptor = read(Path(home)/'CONNECTION.json')
    if descriptor.get('source') != 'actual_desktop_environment':
        raise ValueError('actual Desktop environment registration required')
    environment = descriptor['environment']
    if not environment.get('CODEX_APP_TOOLS_PIPE_PATH') or not environment.get('CODEX_MCP_NODE_PATH'):
        raise ValueError('Desktop registration incomplete')
    return descriptor, hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()


def run(home, seconds=None):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    # Independent of configuration/home: only one instance for this Windows user.
    with locked(Path.home()/'.codex/cd5-continuator/instance'):
        atomic(home/'PROCESS.json', dict(pid=os.getpid(), started_at=time.time(), service='shared'))
        deadline = None if seconds is None else time.monotonic()+seconds
        bridge, fingerprint, next_health = None, None, 0
        try:
            while deadline is None or time.monotonic() < deadline:
                state = dict(pid=os.getpid(), observed_at=time.time(), projects=[])
                try:
                    descriptor, current = connection(home)
                    if current != fingerprint and bridge is not None:
                        bridge.close()
                        bridge = None
                    if bridge is None:
                        # OS-login process needs no inherited Codex environment.
                        env = {k: v for k, v in os.environ.items() if not k.startswith('CODEX_')}
                        env.update(descriptor['environment'])
                        bridge = DesktopBridge(descriptor['server'], descriptor['publisher'],
                                               allow_send=True, env=env)
                        fingerprint = current
                        next_health = 0
                    if time.monotonic() >= next_health:
                        bridge.caller = descriptor['publisher']
                        bridge.call('get_usage_limits', {})  # Real host, not just local MCP initialization.
                        next_health = time.monotonic()+30
                    state.update(reason='connected', projects=SharedService(home, bridge).step())
                except Exception as error:
                    state.update(reason='waiting_for_desktop', error=type(error).__name__)
                    if bridge is not None:
                        bridge.close()
                    bridge = None
                atomic(home/'STATUS.json', state)
                time.sleep(2)
        finally:
            if bridge is not None:
                bridge.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--seconds', type=int)
    args = parser.parse_args()
    if args.seconds is not None and not 1 <= args.seconds <= 600:
        parser.error('test seconds must be1–600')
    try:
        run(args.home, args.seconds)
    except PermissionError:
        # OS login and manual launch may coincide: the already-running one owns it.
        return


if __name__ == '__main__':
    main()
