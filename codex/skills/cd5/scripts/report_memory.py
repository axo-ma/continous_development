"""Read-only current memory snapshots for the offline progress report."""
import datetime as dt
import hashlib
import json
from pathlib import Path

try:
    from .cd5_config import memory_dir
except ImportError:
    from cd5_config import memory_dir


def snapshot(root, filename):
    root = Path(root).resolve()
    path = memory_dir(root) / filename
    result = {'path': path.relative_to(root).as_posix()}
    try:
        if not path.resolve().is_relative_to(root):
            raise ValueError('source escapes project')
        raw = path.read_bytes()
        result.update(status='available', sha256=hashlib.sha256(raw).hexdigest(),
                      modified_at=dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat())
        text = raw.decode('utf-8-sig')
        if filename.endswith('.md'):
            result['markdown'] = text
        elif filename.endswith('.json'):
            result['raw'] = json.loads(text)
            if not isinstance(result['raw'], dict):
                raise ValueError('expected an object')
        else:
            rows, errors = [], []
            for number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('expected an object')
                    rows.append(row)
                except ValueError:
                    errors.append(number)
            result['rows'] = rows
            if errors:
                result.update(status='partial', message='Не прочитаны строки: ' + ', '.join(map(str, errors)))
    except FileNotFoundError:
        result.update(status='missing', message='Файл пока отсутствует.')
    except (OSError, ValueError, UnicodeError) as exc:
        result.pop('raw', None)
        result.update(status='invalid', message='Не удалось прочитать источник: ' + type(exc).__name__)
    return result


def normalize(row):
    payload = row.get('payload', row.get('event', {}))
    record = {**(payload if isinstance(payload, dict) else {}), **row}
    for key in ('text', 'title', 'meaning', 'limitations'):
        alternatives = {'text': ('text', 'result', 'conclusion', 'observation', 'summary', 'claim'),
                        'title': ('title', 'goal', 'question', 'kind', 'id'),
                        'meaning': ('meaning', 'interpretation'), 'limitations': ('limitations', 'limits')}
        record[key] = next((record[k] for k in alternatives[key] if record.get(k)), '')
    record['sources'] = []
    for source in (row, payload if isinstance(payload, dict) else {}):
        for key in ('sources', 'source_refs', 'refs', 'evidence_refs'):
            values = source.get(key, [])
            if isinstance(values, list):
                record['sources'].extend({'label': value} if isinstance(value, str) else value
                                         for value in values if isinstance(value, (str, dict)))
    record['raw'] = row
    return record


def project_snapshots(root):
    data = {key: snapshot(root, name) for key, name in (
        ('outline', 'OUTLINE.md'), ('checkpoint', 'CHECKPOINT.json'),
        ('knowledge', 'KNOWLEDGE.jsonl'), ('attention', 'ATTENTION.jsonl'))}
    cp = data['checkpoint'].get('raw', {})
    data['checkpoint']['state'] = {**cp, 'milestone': cp.get('current_milestone', cp.get('milestone')),
                                   'user_stop': cp.get('user_stop', {}).get('active') if isinstance(cp.get('user_stop'), dict) else cp.get('user_stop')}
    data['knowledge']['entries'] = [normalize(row) for row in reversed(data['knowledge'].pop('rows', []))]
    opened, history = [], []
    for row in reversed(data['attention'].pop('rows', [])):
        record = normalize(row)
        # Resolve only canonical, hash-verified attention archive references.
        if row.get('kind') == 'attention_archive_ref':
            try:
                try:
                    from .project_memory import _archived_attention
                except ImportError:
                    from project_memory import _archived_attention
                record = normalize(_archived_attention(Path(root).resolve(), row))
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as exc:
                record['description'] = 'Архив недоступен: ' + type(exc).__name__
                data['attention'].update(status='partial', message='Не все записи истории внимания доступны; см. диагностику записи.')
        payload = row.get('payload', row.get('event', {}))
        closed = (record.get('status') in {'closed', 'resolved', 'cancelled', 'nonblocking', 'superseded'}
                  or (isinstance(payload, dict) and payload.get('status') == 'nonblocking')
                  or row.get('kind') == 'attention_archive_ref')
        (history if closed else opened).append(record)
    data['attention'].update(open=opened, history=history)
    return data
