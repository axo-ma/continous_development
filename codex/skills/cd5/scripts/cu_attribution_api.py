"""Verified source anchors for append-only cost binding and worker assignments."""
import hashlib
try:
    from . import cu_auto_telemetry as auto
    from .cu_cost_ledger import point
except ImportError:
    import cu_auto_telemetry as auto
    from cu_cost_ledger import point


def source_anchor(root, thread, turn_id=None):
    paths=auto._index(root,auto._settings(root),thread).get(thread,[])
    if len(paths)!=1:
        raise ValueError('one unambiguous native source required')
    session=auto._read(paths[0])
    turns=[t for t in session['turns'] if t['id'] and (turn_id is None or t['id']==turn_id)]
    if not turns or (turn_id is not None and len(turns)!=1):
        raise ValueError('exact native turn not found')
    turn=turns[-1];start=turn['start']
    return dict(schema_version=1,thread_id=thread,turn_id=turn['id'],source_file=str(paths[0]),
        start_position=start['_position'],start_sha256=start['_sha256'],prefix_sha256=start['_prefix_sha256'])


def assignment_for_participant(root, person, cu, rows):
    thread,parent=person.get('thread_id'),person.get('parent_thread_id')
    if not thread or not parent:
        return None
    anchor=source_anchor(root,thread)
    paths=auto._index(root,auto._settings(root),thread).get(thread,[])
    session=auto._read(paths[0]);meta=session['meta']
    if meta.get('parent_thread_id')!=parent or auto._spawn(meta).get('parent_thread_id')!=parent:
        raise ValueError('worker native ancestry does not match assignment')
    # Repeating a registration in the same assignment is an idempotent operation.
    previous=[r['payload'].get('assignment') for r in rows if r['payload'].get('assignment',{}).get('thread_id')==thread]
    previous=[p for p in previous if p.get('operation','start')=='start']
    if previous and previous[-1].get('cu_id')==cu:
        return previous[-1]
    parent_anchor=source_anchor(root,parent)
    parent_paths=auto._index(root,auto._settings(root),parent).get(parent,[])
    parent_session=auto._read(parent_paths[0]);parent_turn=parent_session['turns'][-1]
    child_turn=session['turns'][-1]
    if auto._stamp(child_turn['start'].get('timestamp')) < auto._stamp(parent_turn['start'].get('timestamp')):
        raise ValueError('new assignment has no new native worker turn; dispatch it first')
    identity=hashlib.sha256((thread+'\0'+anchor['turn_id']).encode()).hexdigest()
    if previous:
        old_start=point(previous[-1]['start_anchor'],{thread:session})
        new_start=point(anchor,{thread:session})
        if not old_start or new_start[1]<=old_start[1] or not session['turns'][new_start[1]-1]['end']:
            raise ValueError('previous worker assignment has not reached a verified completion boundary')
    result=dict(assignment_id=identity,operation='start',cu_id=cu,thread_id=thread,
                parent_thread_id=parent,start_anchor=anchor,parent_anchor=parent_anchor)
    if previous:
        result.update(previous_assignment_id=previous[-1]['assignment_id'],
                      previous_end_anchor=source_anchor(root,thread,session['turns'][new_start[1]-1]['id']))
    return result


def validate_assignment(root, assignment, cu, rows):
    if not isinstance(assignment,dict) or assignment.get('operation') not in ('start','finish'):
        raise ValueError('explicit start/finish assignment required')
    identity=assignment.get('assignment_id')
    if not isinstance(identity,str) or not identity:
        raise ValueError('stable assignment ID required')
    existing=[r for r in rows if r['payload'].get('assignment',{}).get('assignment_id')==identity]
    if existing and any(r['payload']['cu_id']!=cu for r in existing):
        raise ValueError('an assignment cannot move between CUs')
    if assignment['operation']=='finish' and not existing:
        raise ValueError('assignment start not found')
    key='start_anchor' if assignment['operation']=='start' else 'end_anchor'
    anchor=assignment.get(key,{})
    verified=source_anchor(root,anchor.get('thread_id'),anchor.get('turn_id'))
    if any(anchor.get(k)!=verified[k] for k in ('thread_id','turn_id','start_position','start_sha256','prefix_sha256')):
        raise ValueError('assignment source witness changed')
    if assignment.get('thread_id') != verified['thread_id']:
        raise ValueError('assignment thread does not match source')
    if existing:
        starts=[r['payload']['assignment'] for r in existing if r['payload']['assignment'].get('operation')=='start']
        if not starts:
            raise ValueError('assignment start not found')
        original=starts[0]
        if original['thread_id']!=assignment['thread_id']:
            raise ValueError('assignment source identity cannot change')
        if assignment['operation']=='start' and original['start_anchor']!=anchor:
            raise ValueError('assignment start cannot change')
        if assignment['operation']=='finish':
            paths=auto._index(root,auto._settings(root),assignment['thread_id']).get(assignment['thread_id'],[])
            session=auto._read(paths[0]);a=point(original['start_anchor'],{assignment['thread_id']:session});b=point(anchor,{assignment['thread_id']:session})
            if not a or not b or b[1]<a[1] or not session['turns'][b[1]]['end']:
                raise ValueError('assignment finish needs a completed source turn after its start')
    return assignment


def validate_allocation(root, data, rows):
    anchor=data['turn_anchor'];thread=anchor.get('thread_id')
    known={r.get('provenance',{}).get('caller_thread_id') for r in rows}
    known.update(r['payload'].get('participant',{}).get('thread_id') for r in rows)
    if thread not in known:
        raise ValueError('source identity is not an evidenced project participant')
    verified=source_anchor(root,thread,anchor.get('turn_id'))
    if any(anchor.get(k)!=verified[k] for k in ('thread_id','turn_id','start_position','start_sha256','prefix_sha256')):
        raise ValueError('allocation source witness changed')
    if not isinstance(data.get('reason'),str) or not data['reason'].strip():
        raise ValueError('allocation requires a concrete reason')
    supports=data.get('supports',[])
    if not supports or not set(supports)<={r['id'] for r in rows}:
        raise ValueError('allocation requires existing supporting evidence IDs')
    return verified
