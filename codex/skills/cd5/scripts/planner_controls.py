"""User-owned Continuator enable flag and independently suspended HQ."""
from pathlib import Path
import time

LEGACY_STOPS = ('stop_planner', 'Stop Goal')

def permission(directory):
    directory = Path(directory)
    if any((directory/name).exists() for name in ('suspend_HQ', *LEGACY_STOPS)):
        return 'stopped'
    return 'continue' if (directory/'continue_HQ').exists() else 'idle'

def migrate(directory):
    """Rename existing equivalent state; never enable a previously disabled HQ."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_STOPS:
        old = directory/name
        if old.exists():
            (directory/'suspend_HQ').touch(exist_ok=True)
            old.unlink()
    old = directory/'continue_planner'
    if old.exists():
        (directory/'continue_HQ').touch(exist_ok=True)
        old.unlink()
    old = directory/'Continue Goal'
    if old.exists():
        archive = directory/'legacy-controls'
        archive.mkdir(exist_ok=True)
        old.rename(archive/('Continue Goal.'+str(time.time_ns())))

def user_command(directory, command):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if command == 'enable':
        (directory/'continue_HQ').touch(exist_ok=True)
    elif command == 'disable':
        (directory/'continue_HQ').unlink(missing_ok=True)
        (directory/'continue_planner').unlink(missing_ok=True)
    elif command in ('stop', 'suspend'):
        (directory/'suspend_HQ').touch(exist_ok=True)
    elif command in ('start', 'continue'):
        for name in ('suspend_HQ', *LEGACY_STOPS):
            (directory/name).unlink(missing_ok=True)
    else:
        raise ValueError('enable/disable Continuator or start/stop Planner required')

def finish_or_wait(directory):
    """HQ suspends itself while preserving the user's Continuator choice."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'suspend_HQ').touch(exist_ok=True)
