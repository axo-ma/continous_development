"""One portable MAC switch. Optional settings remain local to this installation."""
import argparse
import json
import os
from pathlib import Path
import tempfile


def policy_models(data):
    policy = data.get('model_policy')
    if policy is None:
        return None
    allowed = policy.get('allowed_models') if isinstance(policy, dict) else None
    if (not isinstance(allowed, list) or not allowed
            or any(not isinstance(model, str) or not model.strip() for model in allowed)
            or len(set(allowed)) != len(allowed)):
        raise ValueError('invalid model policy; no assignment allowed')
    return set(allowed)


def authorize(data, model, role=None):
    if data.get('mode') != 'auto':
        raise ValueError('MAC is off; optional assignment denied')
    allowed = policy_models(data)
    if allowed is None:
        raise ValueError('explicit model policy required for checked assignments')
    if model not in allowed:
        raise ValueError('model denied by explicit policy; no fallback allowed: ' + str(model))
    if role is not None:
        configured = data.get('models', {}).get(role)
        if not isinstance(configured, dict) or configured.get('model') != model:
            raise ValueError('role/model mismatch; inspect settings instead of substituting')
    return {'authorized': True, 'model': model, 'role': role, 'fallback_allowed': False}


def load(skill_dir):
    path = Path(skill_dir) / 'settings.json'
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schema_version': 1, 'mode': 'auto'}
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('mode') not in {'auto', 'off'}:
        raise ValueError('invalid MAC settings; inspect instead of enabling delegation')
    if 'enabled' in data or 'mac' in data:
        raise ValueError('duplicate legacy switch is not supported')
    allowed = policy_models(data)
    if allowed is not None:
        models = data.get('models', {})
        if not isinstance(models, dict):
            raise ValueError('invalid role models')
        for role, row in models.items():
            if not isinstance(row, dict) or row.get('model') not in allowed:
                raise ValueError('configured role model denied: ' + str(role))
        pilot = data.get('local_pilot', {})
        if pilot.get('enabled') is True and pilot.get('model') not in allowed:
            raise ValueError('enabled pilot model denied')
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
    parser.add_argument('mode', choices=['auto', 'off', 'status', 'check-model'], nargs='?', default='status')
    parser.add_argument('--model')
    parser.add_argument('--role')
    args = parser.parse_args()
    try:
        if args.mode == 'check-model':
            if not args.model:
                raise ValueError('--model is required; never infer a fallback')
            result = authorize(load(args.skill_dir), args.model, args.role)
        else:
            result = load(args.skill_dir) if args.mode == 'status' else set_mode(args.skill_dir, args.mode)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
