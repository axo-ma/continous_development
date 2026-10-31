"""Owner-authorized, append-only recovery of unique exact historical turn marks."""
import argparse
import json
from pathlib import Path
try:
    from . import control_units as cu, cu_auto_telemetry as auto
    from .cu_assignment_candidates import candidates
    from .cu_attribution_api import source_anchor
except ImportError:
    import control_units as cu
    import cu_auto_telemetry as auto
    from cu_assignment_candidates import candidates
    from cu_attribution_api import source_anchor


def reconcile(root, caller, apply=False):
    root=Path(root);cu._owner(root,caller)
    events=cu._events(root);sessions=auto._sessions(root,auto._settings(root),events)
    proposals=candidates(events,sessions);written=[];skipped=[]
    existing={r['provenance'].get('event_id') for r in events}
    for item in proposals:
        target=item['confirmed_candidate']
        source=next(t for t in sessions[item['thread_id']]['turns'] if t['id']==item['turn_id'])
        identity='recover-exact-turn-'+item['source_key']
        if not target or not source['end']:
            skipped.append(dict(source_key=item['source_key'],reason='conflicting_marks' if not target else 'source_turn_not_closed'))
            continue
        if identity in existing:
            continue
        if apply:
            cu.record(root,dict(action='allocation',cu_id=target,event_id=identity,
                turn_anchor=source_anchor(root,item['thread_id'],item['turn_id']),
                reason='Восстановлено по единственному точному проверенному событию работы; открытые интервалы не используются.',
                supports=item['candidates'][target]),caller)
        written.append(dict(source_key=item['source_key'],cu_id=target))
    return dict(applied=apply,recovered=written,unresolved=skipped,source_journals_changed=False,
                work_statuses_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--caller-thread',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();print(json.dumps(reconcile(a.root,a.caller_thread,a.apply),ensure_ascii=False))


if __name__=='__main__':main()
