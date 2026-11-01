"""Bounded local diagnostics and verified process/heartbeat health, never model calls."""
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile
import time
import uuid


def process_created(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
            return None
        return ((values[0].dwHighDateTime << 32) + values[0].dwLowDateTime) / 1e7 - 11644473600
    finally:
        kernel.CloseHandle(handle)


def health(home, now=None, max_age=90):
    """A stale connected STATUS or reused PID is never evidence of a healthy service."""
    try:
        process = json.loads((Path(home)/'PROCESS.json').read_text(encoding='utf-8-sig'))
        beat = json.loads((Path(home)/'HEARTBEAT.json').read_text(encoding='utf-8-sig'))
        created = process_created(process['pid'])
        age = (time.time() if now is None else now) - beat['observed_at']
        alive = created is not None and (created is True or abs(created-process['process_created_at']) < .01)
        valid = (alive and process['instance_id'] == beat['instance_id'] and process['pid'] == beat['pid']
                 and 0 <= age <= max_age)
        return dict(healthy=valid, pid=process['pid'], heartbeat_age_seconds=age,
                    process_identity_verified=alive, state=beat.get('state'),
                    status_write_ok=beat.get('status_write_ok'),
                    reason='fresh_live_process' if valid else 'dead_stale_or_mismatched')
    except (OSError, ValueError, TypeError, KeyError):
        return dict(healthy=False, reason='missing_or_unreadable_health')


class Diagnostics:
    def __init__(self, home):
        self.home = Path(home)
        self.identity = dict(pid=os.getpid(), instance_id=str(uuid.uuid4()), started_at=time.time(),
                             process_created_at=process_created(os.getpid()), service='shared')
        self.logger = logging.Logger('cd5-continuator-'+self.identity['instance_id'])
        self.last_errors = {}
        self.state = None
        candidates = [self.home, Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir()))/'CD5']
        for directory in candidates:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(directory/'SERVICE.log', maxBytes=1048576, backupCount=3, encoding='utf-8')
                self.logger.addHandler(handler)
                break
            except OSError:
                continue
        else:
            self.logger.addHandler(logging.NullHandler())
        try:
            old = json.loads((self.home/'PROCESS.json').read_text(encoding='utf-8-sig'))
            if type(old.get('pid')) is int and process_created(old['pid']) is None:
                try:
                    exited = json.loads((self.home/'EXIT.json').read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    exited = {}
                self.event('previous_process_missing', previous_pid=old['pid'],
                    previous_instance=old.get('instance_id'),
                    previous_exit_recorded=exited.get('instance_id') == old.get('instance_id') and bool(exited.get('exited_at')))
        except (OSError, ValueError, TypeError):
            pass

    def event(self, name, **fields):
        try:
            self.logger.warning(json.dumps(dict(at=time.time(), event=name, **self.identity, **fields), ensure_ascii=False))
        except Exception:
            pass  # A logging failure must not kill both HQs.

    def error(self, operation, error):
        now = time.monotonic()
        key = (operation, type(error).__name__)
        last = self.last_errors.get(key)
        if last is None or now-last >= 60:
            self.last_errors[key] = now
            self.event('error', operation=operation, error_type=type(error).__name__, detail=str(error)[:500])

    def write(self, path, value, writer):
        try:
            writer(path, value)
            keys = [k for k in self.last_errors if k[0] == 'write:'+path.name]
            if keys:
                self.event('write_recovered', file=path.name)
                for key in keys:
                    del self.last_errors[key]
            return True
        except OSError as error:
            self.error('write:'+path.name, error)
            return False

    def transition(self, reason):
        if reason != self.state:
            self.event('state_changed', state=reason, previous=self.state)
            self.state = reason

    def close(self):
        for handler in self.logger.handlers:
            handler.close()
