"""Bounded model-free observation across the launching owner's turn boundary."""
import argparse
import json
from pathlib import Path
import time
try:
    from .desktop_tools_bridge import DesktopBridge
    from .planner_control import atomic
except ImportError:
    from desktop_tools_bridge import DesktopBridge
    from planner_control import atomic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--caller', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180:
        parser.error('finite bound1–180 seconds required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(started_at=time.time(), model_inputs=0, messages_sent=0,
                  second_app_servers=0, after_owner_turn=False, status='connecting')
    atomic(args.output, report)
    try:
        with DesktopBridge(args.server, args.caller) as bridge:
            initial = bridge.call('read_thread', dict(threadId=args.caller, turnLimit=1,
                includeOutputs=False, maxOutputCharsPerItem=1))
            if initial['thread']['id'] != args.caller:
                raise RuntimeError('owner identity mismatch')
            initial_turn = initial['turns'][0]['id']
            report.update(status='observing', initial_turn=initial_turn,
                          initial_status=initial['thread']['status'])
            atomic(args.output, report)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                current = bridge.call('read_thread', dict(threadId=args.caller, turnLimit=1,
                    includeOutputs=False, maxOutputCharsPerItem=1))
                if current['thread']['id'] != args.caller:
                    raise RuntimeError('owner identity changed')
                turn = current['turns'][0]
                status = current['thread']['status']
                if turn['id'] != initial_turn or (turn['status'] in ('completed', 'interrupted', 'failed')
                                                 and status.get('type') == 'idle'):
                    quota = bridge.call('get_usage_limits', {})
                    report.update(status='verified_after_owner_turn', after_owner_turn=True,
                        observed_at=time.time(), observed_turn=turn['id'],
                        observed_status=status,
                        quota_window=quota.get('rateLimits', {}).get('primary'))
                    atomic(args.output, report)
                    return
                time.sleep(1)
            report.update(status='observation_bound_reached', observed_at=time.time())
    except Exception as error:
        report.update(status='connection_unconfirmed', error_type=type(error).__name__,
                      observed_at=time.time())
    atomic(args.output, report)


if __name__ == '__main__':
    main()
