"""Read-only historical proposals from exact verified anchors, never CU intervals.

This is a migration primitive, not a replacement for the report collector yet.
It writes neither assignments nor measurements and never resolves conflicts by age.
"""
import hashlib
try:
    from .cu_auto_telemetry import _anchor
except ImportError:
    from cu_auto_telemetry import _anchor


def candidates(events, sessions):
    found = {}
    for row in events:
        payload = row.get('payload', {})
        if payload.get('type') != 'control_unit_event' or payload.get('historical'):
            continue
        point = _anchor(row, sessions)
        if point is None:
            continue
        thread, index = point
        turn = sessions[thread]['turns'][index]
        identity = hashlib.sha256((thread+'\0'+turn['id']).encode()).hexdigest()
        item = found.setdefault(identity, dict(source_key=identity, thread_id=thread,
            turn_id=turn['id'], candidates={}, start_sha256=turn['start']['_sha256']))
        item['candidates'].setdefault(payload['cu_id'], set()).add(row['id'])
    result = []
    for identity in sorted(found):
        item = found[identity]
        item['candidates'] = {cu: sorted(ids) for cu, ids in sorted(item['candidates'].items())}
        item['confirmed_candidate'] = next(iter(item['candidates'])) if len(item['candidates']) == 1 else None
        item['reason'] = 'exact_verified_event_anchor' if item['confirmed_candidate'] else 'conflicting_exact_event_anchors'
        result.append(item)
    return result
