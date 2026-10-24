"""Install CD5/MAC skills for Claude Code from this bundle, keeping backups of previous versions.

Other skills in the target directory (for example new-hq) are never touched.
"""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import uuid

SKILLS = ('cd5', 'mac')


def install(source, destination, names=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('installation source and destination must be separate')
    if names is None:
        names = tuple(n for n in SKILLS if (source/n/'SKILL.md').is_file())
        if not names:
            raise ValueError('no skills found in source')
    destination.mkdir(parents=True, exist_ok=True)
    backup = destination.parent/'skill-backups'/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    plans = []
    prepared = []
    for name in names:
        if name not in SKILLS or not (source/name/'SKILL.md').is_file():
            raise ValueError('invalid skill source')
        target = destination/name
        if target.is_symlink() or not target.resolve().is_relative_to(destination):
            raise ValueError('skill target escapes installation')
        stage = destination/('.'+name+'-install-stage')
        if stage.exists():
            raise ValueError('staging directory exists; inspect previous installation')
        prepared.append((name, target, stage))
    try:
        for name, target, stage in prepared:
            plans.append((name, target, stage))
            shutil.copytree(source/name, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
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
    parser.add_argument('--skills-dir', type=Path, default=Path.home()/'.claude'/'skills',
                        help='Claude Code skills directory (default: ~/.claude/skills)')
    parser.add_argument('--only', choices=list(SKILLS))
    args = parser.parse_args()
    try:
        print(json.dumps(install(Path(__file__).parent/'skills', args.skills_dir,
                                 (args.only,) if args.only else None), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
