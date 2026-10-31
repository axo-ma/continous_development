"""Sequential service: read two files, observe Desktop, send one continue.

It never creates/deletes control files or reasons about the task. No native Goal,
new app-server, helper inventory or restart/quota-recovery system is involved.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
try:
    from .desktop_tools_bridge import DesktopBridge
    from .planner_controls import permission
    from .planner_control import atomic, locked, read
    from .stop_hook_trial import quota_allowed
except ImportError:
    from desktop_tools_bridge import DesktopBridge
    from planner_controls import permission
    from planner_control import atomic, locked, read
    from stop_hook_trial import quota_allowed


class FileService:
    def __init__(self, config, bridge, saved=None):
        self.config, self.bridge = config, bridge
        self.status = saved if saved is not None else dict(used=0, waiting=False,
            before_turn=None, uncertain=False, quota_hold_permission=None)
        self.session = config.get('mode') == 'session'
        if self.session:
            if config.get('session_authorized') is not True or config.get('limit') is not None:
                raise ValueError('explicit session authorization and no trial limit required')
        elif type(config.get('limit')) is not int or config['limit'] not in (2, 3):
            raise ValueError('independent trial limit2–3 required')
        if (type(self.status.get('used')) is not int or self.status['used'] < 0
                or (not self.session and self.status['used'] > config['limit'])):
            raise ValueError('invalid persisted send count')
        if any(type(self.status.get(k)) is not bool for k in ('waiting', 'uncertain')):
            raise ValueError('invalid persisted send state')
        if self.status.get('target', config['target']) != config['target']:
            raise ValueError('status belongs to another chat')
        self.status['target'] = config['target']

    def save(self, reason):
        self.status.update(reason=reason, observed_at=time.time())
        atomic(Path(self.config['status']), self.status)
        return dict(self.status)

    def tick(self):
        allowed = permission(self.config['flags'])
        if allowed != 'continue':
            return self.save(allowed)
        if self.status['uncertain']:
            return self.save('send_outcome_unknown_no_retry')
        stamp = (Path(self.config['flags']) / 'continue_planner').stat().st_mtime_ns
        if self.status.get('quota_hold_permission') == stamp:
            return self.save('quota_closed_wait_for_explicit_permission')
        result = self.bridge.call('read_thread', dict(threadId=self.config['target'],
            turnLimit=1, includeOutputs=False, maxOutputCharsPerItem=1))
        if result.get('thread', {}).get('id') != self.config['target'] or not result.get('turns'):
            return self.save('unknown_activity')
        host, turn = result['thread']['status'], result['turns'][0]
        if self.status['waiting']:
            if turn['id'] == self.status['before_turn']:
                return self.save('awaiting_sent_turn_no_duplicate')
            if turn['status'] not in ('completed', 'interrupted', 'failed'):
                return self.save('waiting_for_result')
            self.status['waiting'] = False
        if host.get('type') != 'idle' or host.get('activeFlags') not in (None, []):
            return self.save('chat_busy_or_unknown')
        if not self.session and self.status['used'] >= self.config['limit']:
            return self.save('trial_limit_reached')
        if not quota_allowed(self.bridge.call('get_usage_limits', {})):
            self.status['quota_hold_permission'] = stamp
            return self.save('quota_closed')
        check = subprocess.run([sys.executable, '-X', 'utf8', self.config['mac_script'],
            'check-model', '--model', self.config['model']], capture_output=True,
            text=True, encoding='utf-8', timeout=5)
        if check.returncode or json.loads(check.stdout).get('authorized') is not True:
            return self.save('model_policy_denied')
        if permission(self.config['flags']) != 'continue':
            return self.save('permission_removed_before_send')
        self.status.update(used=self.status['used'] + 1, waiting=True,
                           before_turn=turn['id'], uncertain=True)
        self.save('sending_once')  # Persist before sending; never blindly replay.
        response = self.bridge.call('send_message_to_thread', dict(threadId=self.config['target'],
            model=self.config['model'], thinking='low', prompt=self.config['message']))
        if response.get('threadId') != self.config['target']:
            return self.save('send_outcome_unknown_no_retry')
        self.status['uncertain'] = False
        return self.save('sent')


def run(config):
    status = Path(config['status'])
    status.parent.mkdir(parents=True, exist_ok=True)
    if config.get('native_goal_disabled') is not True:
        raise ValueError('native Goal must be disabled')
    session = config.get('mode') == 'session'
    seconds = config.get('seconds', 600)
    if session and (config.get('session_authorized') is not True or seconds is not None):
        raise ValueError('explicit session authorization required')
    if not session and (type(seconds) is not int or not 1 <= seconds <= 600):
        raise ValueError('finite trial horizon1–600 seconds required')
    flags = Path(config['flags'])
    flags.mkdir(parents=True, exist_ok=True)
    # One sender for this flag directory, even with a different status path.
    with locked(flags / '.service-instance'):
        saved = read(status) if status.exists() else None
        FileService(config, None, saved)  # Reject malformed state before connecting.
        deadline = None if session else time.monotonic() + seconds
        bridge = None
        service = None
        try:
            while deadline is None or time.monotonic() < deadline:
                try:
                    if bridge is None:
                        bridge = DesktopBridge(config['server'], config['caller'], allow_send=True)
                        service = FileService(config, bridge, saved)
                    service.tick()
                    saved = dict(service.status)
                except Exception:
                    if service is not None:
                        service.save('connection_unavailable_waiting_no_blind_send')
                        saved = dict(service.status)
                    if bridge is not None:
                        bridge.close()
                    bridge = None
                    if service is None:
                        atomic(status, dict(saved or {}, reason='connection_unavailable',
                                            observed_at=time.time()))
                time.sleep(1)
        finally:
            if bridge is not None:
                bridge.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    config = read(args.config)
    if config.get('mode') == 'session':
        parser.error('per-HQ production processes are retired; use shared_continuator.py')
    run(config)


if __name__ == '__main__':
    main()
