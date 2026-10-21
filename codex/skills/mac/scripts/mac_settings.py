"""One portable MAC switch. Optional settings remain local to this installation."""
import argparse
import json
import os
from pathlib import Path
import tempfile


def load(skill_dir):
    path = Path(skill_dir) / 'settings.json'
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schema_version': 1, 'mode': 'auto'}
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('mode') not in {'auto', 'off'}:
        raise ValueError('invalid MAC settings; inspect instead of enabling delegation')
    if 'enabled' in data or 'mac' in data:
        raise ValueError('duplicate legacy switch is not supported')
    return data


def set_mode(skill_dir, mode):
    if mode not in {'auto', 'off'}:
        raise ValueError('mode must be auto or off')
    directory = Path(skill_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.settings.lock'
    handle = lock.open('x', encoding='utf-8')
    try:
            data = load(directory)
            data['mode'] = mode
            fd, temporary = tempfile.mkstemp(dir=directory, prefix='.settings-', suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, directory/'settings.json')
            finally:
                Path(temporary).unlink(missing_ok=True)
            return data
    finally:
        handle.close()
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-dir', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('mode', choices=['auto', 'off', 'status'], nargs='?', default='status')
    args = parser.parse_args()
    try:
        result = load(args.skill_dir) if args.mode == 'status' else set_mode(args.skill_dir, args.mode)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
