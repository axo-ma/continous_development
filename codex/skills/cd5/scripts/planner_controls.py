"""CD5 controls: stop_planner wins; only explicit Continue Planner reopens work."""
from pathlib import Path
import time


def permission(directory):
    directory = Path(directory)
    # Transitional safety: a still-trusted older Interrupt hook may write old Stop.
    if any((directory/name).exists() for name in ('stop_planner', 'Stop Goal')):
        return 'stopped'
    return 'continue' if (directory/'continue_planner').exists() else 'idle'


def migrate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    old_stop, old_continue = directory/'Stop Goal', directory/'Continue Goal'
    if old_stop.exists():
        (directory/'stop_planner').touch(exist_ok=True)
        old_stop.unlink()  # New Stop is already present; never an unguarded gap.
    if old_continue.exists():
        archive = directory/'legacy-controls'
        archive.mkdir(exist_ok=True)
        old_continue.rename(archive/('Continue Goal.'+str(time.time_ns())))
    # Never create continue_planner during migration.


def user_command(directory, command):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if command == 'stop':
        (directory/'stop_planner').touch(exist_ok=True)
    elif command == 'continue':
        (directory/'continue_planner').touch(exist_ok=True)
        for name in ('stop_planner', 'Stop Goal', 'Continue Goal'):
            (directory/name).unlink(missing_ok=True)
    else:
        raise ValueError('explicit Stop Planner or Continue Planner required')


def finish_or_wait(directory):
    for name in ('continue_planner', 'Continue Goal'):
        (Path(directory)/name).unlink(missing_ok=True)
