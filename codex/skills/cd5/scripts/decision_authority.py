"""Separate evidenced user/system requirements from decisions delegated to HQ.

References are workflow evidence, not cryptographic proof. The owner must verify
the cited instruction/permission requirement; an agent label alone is insufficient.
"""


def human_requirement(record):
    if not isinstance(record, dict):
        return False
    source = record.get('constraint_source')
    evidence = record.get('human_constraint_evidence')
    if source not in {'user', 'human', 'direct_user', 'system', 'system_permission', 'safety'}:
        return False
    return (isinstance(evidence, str) and bool(evidence.strip()) or
            isinstance(evidence, list) and bool(evidence) and
            all(isinstance(item, str) and item.strip() for item in evidence))


def whole_plan_complete(state):
    """Never promote a closed CU, stage or execution attempt to whole-plan success."""
    return (state.get('goal_status') == 'verified_complete' or
            state.get('whole_plan_complete') is True)
