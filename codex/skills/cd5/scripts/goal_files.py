"""Two user/HQ-owned control files. The continuation service only reads them."""
from pathlib import Path


def permission(directory):
    directory = Path(directory)
    if (directory / 'Stop Goal').exists():
        return 'stopped'
    return 'continue' if (directory / 'Continue Goal').exists() else 'idle'


def user_command(directory, command):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if command == 'stop':
        (directory / 'Stop Goal').touch(exist_ok=True)
    elif command == 'continue':
        # Stop wins until the explicit user's Continue is ready to take effect.
        (directory / 'Continue Goal').touch(exist_ok=True)
        (directory / 'Stop Goal').unlink(missing_ok=True)
    else:
        raise ValueError('explicit Stop Goal or Continue Goal required')


def finish_or_wait(directory):
    (Path(directory) / 'Continue Goal').unlink(missing_ok=True)
