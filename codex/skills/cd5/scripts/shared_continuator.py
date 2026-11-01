"""One per-user CD5 service; sequentially service explicitly enrolled HQs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
try:
    from .cd5_config import memory_dir
    from .desktop_tools_bridge import DesktopBridge
    from .file_continuation_service import FileService
    from .planner_controls import permission
    from .planner_control import atomic, locked, read
    from .continuator_runtime import Diagnostics, health
except ImportError:
    from cd5_config import memory_dir
    from desktop_tools_bridge import DesktopBridge
    from file_continuation_service import FileService
    from planner_controls import permission
    from planner_control import atomic, locked, read
    from continuator_runtime import Diagnostics, health


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
        message=entry.get('message') if 'trial_limit' in entry else 'Продолжай.')


class SharedService:
    def __init__(self, home, bridge, diagnostics=None):
        self.home, self.bridge = Path(home), bridge
        self.diagnostics = diagnostics
        self.connection_failed = False

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
                    try:
                        return real_call(name, args)
                    except Exception:
                        self.connection_failed = True
                        raise
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
                if self.diagnostics:
                    self.diagnostics.error('project:'+str(root), error)
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
    diagnostics = Diagnostics(home)
    diagnostics.event('starting')
    exit_reason = 'normal'
    bridge = None
    def close_bridge():
        nonlocal bridge
        if bridge is not None:
            try:
                bridge.close()
            except Exception as error:
                diagnostics.error('close_connection', error)
            bridge = None
    try:
        # OS releases this per-user lock after an abnormal process exit.
        with locked(Path.home()/'.codex/cd5-continuator/instance'):
            deadline = None if seconds is None else time.monotonic()+seconds
            fingerprint, next_health, failures = None, 0, 0
            diagnostics.event('started')
            while deadline is None or time.monotonic() < deadline:
                diagnostics.write(home/'PROCESS.json', diagnostics.identity, atomic)
                diagnostics.write(home/'HEARTBEAT.json', dict(diagnostics.identity, observed_at=time.time(), state='checking'), atomic)
                state = dict(pid=os.getpid(), observed_at=time.time(), projects=[])
                try:
                    descriptor, current = connection(home)
                    if current != fingerprint and bridge is not None:
                        close_bridge()
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
                    service = SharedService(home, bridge, diagnostics)
                    state.update(reason='connected', projects=service.step())
                    if service.connection_failed:
                        raise RuntimeError('Desktop connection failed during project observation')
                    failures = 0
                except Exception as error:
                    state.update(reason='waiting_for_desktop', error=type(error).__name__)
                    diagnostics.error('service_cycle', error)
                    failures = min(failures+1, 5)
                    close_bridge()
                diagnostics.transition(state['reason'])
                state['observed_at'] = time.time()
                stored = diagnostics.write(home/'STATUS.json', state, atomic)
                diagnostics.write(home/'HEARTBEAT.json', dict(diagnostics.identity, observed_at=time.time(),
                    state=state['reason'], status_write_ok=stored), atomic)
                time.sleep(min(30, 2**failures) if failures else 2)
    except BaseException as error:
        exit_reason = type(error).__name__
        diagnostics.event('fatal', error_type=exit_reason, traceback=traceback.format_exc()[-6000:])
        raise
    finally:
        close_bridge()
        diagnostics.event('exiting', reason=exit_reason)
        diagnostics.write(home/'EXIT.json', dict(diagnostics.identity, exited_at=time.time(), reason=exit_reason), atomic)
        diagnostics.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--seconds', type=int)
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    if args.seconds is not None and not 1 <= args.seconds <= 600:
        parser.error('test seconds must be1–600')
    if args.health:
        result = health(args.home)
        print(json.dumps(result))
        return 0 if result['healthy'] else 1
    try:
        run(args.home, args.seconds)
    except PermissionError:
        # Already logged with traceback; report failure so Windows can recover.
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
