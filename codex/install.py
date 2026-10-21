"""Install CD5/MAC from this bundle, preserving existing local settings and backups."""
import argparse
import datetime
import json
from pathlib import Path
import shutil


def install(source, destination, names=('cd5', 'mac')):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('installation source and destination must be separate')
    destination.mkdir(parents=True, exist_ok=True)
    backup = destination.parent/'skill-backups'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True)
    plans = []
    prepared = []
    for name in names:
        if name not in {'cd5', 'mac'} or not (source/name/'SKILL.md').is_file():
            raise ValueError('invalid skill source')
        target = destination/name
        if target.is_symlink() or not target.resolve().is_relative_to(destination):
            raise ValueError('skill target escapes installation')
        preserved = None
        if name == 'mac' and (target/'settings.json').exists():
            preserved = json.loads((target/'settings.json').read_text(encoding='utf-8-sig'))
            if (not isinstance(preserved, dict) or preserved.get('schema_version') != 1
                    or preserved.get('mode') not in {'auto', 'off'} or 'enabled' in preserved or 'mac' in preserved):
                raise ValueError('existing MAC settings need explicit migration')
        stage = destination/('.'+name+'-install-stage')
        if stage.exists():
            raise ValueError('staging directory exists; inspect previous installation')
        prepared.append((name, target, stage, preserved))
    try:
        for name, target, stage, preserved in prepared:
            plans.append((name, target, stage))
            shutil.copytree(source/name, stage)
            if preserved is not None:
                (stage/'settings.json').write_text(json.dumps(preserved, ensure_ascii=False, indent=2), encoding='utf-8')
    except BaseException:
        for _, _, stage in plans:
            if stage.exists() and not stage.is_symlink() and stage.parent == destination:
                shutil.rmtree(stage)
        raise
    applied = []
    try:
        for name, target, stage in plans:
            existed = target.exists()
            if existed:
                target.rename(backup/name)
            try:
                stage.rename(target)
            except BaseException:
                if existed:
                    (backup/name).rename(target)
                raise
            applied.append((name, target, existed))
    except BaseException:
        for name, target, existed in reversed(applied):
            target.rename(destination/('.'+name+'-failed-install'))
            if existed:
                (backup/name).rename(target)
        for _, _, stage in plans:
            if stage.exists() and not stage.is_symlink() and stage.parent == destination:
                shutil.rmtree(stage)
        raise
    return {'installed': [n for n, _, _ in plans], 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', type=Path, required=True, help='your configured Codex skill directory')
    parser.add_argument('--only', choices=['cd5', 'mac'])
    args = parser.parse_args()
    try:
        print(json.dumps(install(Path(__file__).parent/'skills', args.skills_dir,
                                 (args.only,) if args.only else ('cd5','mac')), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
