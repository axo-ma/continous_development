"""Lossless cold evidence storage; active-memory budgets never truncate prose."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from .cd5_config import config, memory_dir
except ImportError:
    from cd5_config import config, memory_dir

LIMITS = {'OUTLINE.md': 32768, 'CHECKPOINT.json': 65536,
          'KNOWLEDGE.jsonl': 262144, 'EVIDENCE.jsonl': 524288,
          'ATTENTION.jsonl': 65536}


def _pm():
    try:
        from . import project_memory
    except ImportError:
        import project_memory
    return project_memory


def _inside(root, path):
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError('archive path escapes project root')
    return path


def _bytes(rows):
    return ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                              separators=(',', ':')) + '\n' for row in rows).encode('utf-8')


def evidence_rows(root):
    """Read all history, tolerating identical copies left by an interrupted move."""
    root = Path(root).resolve()
    directory = _inside(root, memory_dir(root) / 'archive/evidence-store')
    paths = sorted(directory.rglob('*.jsonl')) if directory.exists() else []
    paths.append(memory_dir(root) / 'EVIDENCE.jsonl')
    seen = {}
    pm = _pm()
    for path in paths:
        path = _inside(root, path)
        digest = path.stem.rsplit('-', 1)[-1]
        if path != memory_dir(root)/'EVIDENCE.jsonl' and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise pm.MemoryError('archive content hash mismatch: '+path.name)
        for row in pm._jsonl(_inside(root, path)):
            rid = row['id']
            if rid in seen and seen[rid] != row:
                raise pm.MemoryError(f'conflicting duplicate evidence id {rid}')
            if rid not in seen:
                seen[rid] = row
    order_path = directory/'_order.json'
    if order_path.exists():
        order = json.loads(order_path.read_text(encoding='utf-8'))
        if not isinstance(order, list) or any(not isinstance(i, str) for i in order) or len(order) != len(set(order)):
            raise pm.MemoryError('invalid archive order metadata')
        positions = {key: index for index, key in enumerate(order)}
        return sorted(seen.values(), key=lambda r: positions.get(r['id'], len(positions)))
    return list(seen.values())


def _supported(row):
    return (type(row.get('schema_version')) is int and row['schema_version'] == 1
            and row.get('kind') in {'experiment_event', 'artifact', 'source'}
            and isinstance(row.get('provenance'), dict) and 'payload' in row
            and (row['kind'] != 'experiment_event' or
                 (isinstance(row['payload'], dict) and row['payload'].get('event_id') == row['id'])))


def archive_evidence(root, keep_records=500, max_bytes=512 * 1024, *,
                     cu_only=False, apply=False):
    """Move oldest eligible envelopes to verified immutable content-hash storage."""
    for name, value in [('keep_records', keep_records), ('max_bytes', max_bytes)]:
        if type(value) is not int or value < 0:
            raise ValueError(f'{name} must be a nonnegative integer')
    root = Path(root).resolve()
    pm = _pm()
    active = _inside(root, memory_dir(root) / 'EVIDENCE.jsonl')
    lock = None
    if apply:
        pm._assert_no_migration(root)
        lock = pm._lock(active)
    try:
        if apply:
            pm._assert_no_migration(root)
        rows = pm._jsonl(active)
        # Detect historical conflicts before making either write.
        history = evidence_rows(root)
        unsupported = [row['id'] for row in rows if not _supported(row)]
        eligible = [row for row in rows if _supported(row) and
                    (not cu_only or (isinstance(row.get('payload'), dict) and
                     isinstance(row['payload'].get('type'), str) and
                     row['payload']['type'].startswith('control_unit')))]
        sizes = [len(_bytes([row])) for row in eligible]
        remaining = sum(sizes)
        cut = 0
        while len(eligible) - cut > keep_records or remaining > max_bytes:
            remaining -= sizes[cut]
            cut += 1
        cold = eligible[:cut]
        cold_ids = {row['id'] for row in cold}
        hot = [row for row in rows if row['id'] not in cold_ids]
        data = _bytes(cold)
        archive = None
        if cold:
            directory = _inside(root, memory_dir(root)/'archive/evidence-store')
            digest = hashlib.sha256(data).hexdigest()
            matches = sorted(directory.glob('*'+digest+'.jsonl')) if directory.exists() else []
            sequence = max((int(p.name.split('-',1)[0]) for p in directory.glob('*.jsonl')
                            if '-' in p.name and p.name.split('-',1)[0].isdigit()), default=0) if directory.exists() else 0
            archive = matches[0] if matches else directory/(f'{sequence+1:012d}-'+digest+'.jsonl')
        before_bytes = active.stat().st_size if active.exists() else 0
        result = {'active_before': {'count': len(rows), 'bytes': before_bytes},
                  'active_after': {'count': len(hot), 'bytes': len(_bytes(hot)) if cold else before_bytes},
                  'archived': len(cold), 'archive_path': str(archive) if archive else None,
                  'applied': bool(apply), 'unsupported_records': unsupported,
                  'eligible_after': {'count': len(eligible) - cut, 'bytes': remaining}}
        if apply and cold:
            # This cold, derived index preserves mixed CU-only/full archival order.
            # Write before moving rows: a crash leaves active history intact.
            pm._atomic(archive.parent/'_order.json', json.dumps([r['id'] for r in history]).encode('utf-8'))
            if archive.exists():
                if archive.read_bytes() != data:
                    raise pm.MemoryError('archive hash path contains different bytes')
            else:
                pm._atomic(archive, data)
            if archive.read_bytes() != data or pm._jsonl(archive) != cold:
                raise pm.MemoryError('archive verification failed')
            pm._atomic(active, _bytes(hot))
        return result
    finally:
        if lock is not None:
            lock.unlink()


def memory_budget(root):
    root = Path(root).resolve()
    overrides = config(root).get('memory_limits_bytes', {})
    if not isinstance(overrides, dict):
        raise ValueError('memory_limits_bytes must be an object')
    files = {}
    for name, default in LIMITS.items():
        limit = overrides.get(name, overrides.get(name.split('.')[0].lower(), default))
        if type(limit) is not int or limit < 0:
            raise ValueError(f'invalid memory limit for {name}')
        path = _inside(root, memory_dir(root) / name)
        size = path.stat().st_size if path.exists() else 0
        files[name] = {'bytes': size, 'limit_bytes': limit, 'over_limit': size > limit,
                       'action_needed': size > limit}
    return {'files': files, 'action_needed': any(x['over_limit'] for x in files.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('budget')
    compact = sub.add_parser('compact')
    compact.add_argument('--keep-records', type=int, default=500)
    compact.add_argument('--max-bytes', type=int, default=512 * 1024)
    compact.add_argument('--cu-only', action='store_true')
    compact.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = (memory_budget(args.root) if args.command == 'budget' else
              archive_evidence(args.root, args.keep_records, args.max_bytes,
                               cu_only=args.cu_only, apply=args.apply))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
