"""Run canonical skill tests in a disposable, isolated project layout.

Usage from the checkout: python claude/run_tests.py
Only Python's standard library is required. Optional Node.js checks skip when
Node is unavailable; the remaining Python tests still run.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--pattern', default='test_*.py', help='unittest file pattern')
    args = parser.parse_args(argv)
    required = [HERE / 'skills/cd5/scripts', HERE / 'install.py', HERE / 'tests']
    if not all(path.exists() for path in required):
        parser.error('checkout is incomplete: claude/skills, install.py and tests are required')
    # Keep all generated projects, journals, installations and caches under one
    # directory. Never use the operator's installed skills or native sessions.
    scratch_parent = str(HERE)
    if os.name == 'nt' and not scratch_parent.startswith('\\\\?\\'):
        scratch_parent = '\\\\?\\' + scratch_parent
    with tempfile.TemporaryDirectory(prefix='.skill-tests-', dir=scratch_parent) as directory:
        fixture = Path(directory)
        shutil.copytree(HERE / 'skills', fixture / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(HERE / 'skills/cd5/scripts', fixture / 'tools', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (fixture / 'tools/__init__.py').touch()
        shutil.copytree(HERE / 'tests', fixture / 'tests', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(HERE / 'install.py', fixture / 'install.py')
        temporary = fixture / 'tmp'
        temporary.mkdir()
        environment = os.environ.copy()
        environment.update(PYTHONDONTWRITEBYTECODE='1',
                           PYTHONUTF8='1', PYTHONPATH=str(fixture),
                           TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary))
        command = [sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover',
                   '-s', str(fixture / 'tests'), '-t', str(fixture), '-p', args.pattern]
        if args.verbose:
            command.append('-v')
        return subprocess.run(command, cwd=fixture, env=environment).returncode


if __name__ == '__main__':
    raise SystemExit(main())
