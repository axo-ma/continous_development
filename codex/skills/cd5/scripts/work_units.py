"""Exact, versioned API-base Work Units. No model calls, subscription estimates or live rates."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import json
import importlib.util
from pathlib import Path

try:
    from .cu_budget import compare_budget
except ImportError:
    try:
        from cu_budget import compare_budget
    except ModuleNotFoundError as error:
        if error.name != 'cu_budget':
            raise
        _spec = importlib.util.spec_from_file_location('cu_budget', Path(__file__).with_name('cu_budget.py'))
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        compare_budget = _module.compare_budget

FIELDS = ('cached_input', 'uncached_input', 'output')
BASIS = 'standard_short_context_estimate'


def _decimal(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a tariff')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('tariff must be a nonnegative decimal') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('tariff must be a finite nonnegative decimal')
    return result


def _text(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def load_rates(path=None):
    data = json.loads(Path(path or Path(__file__).with_name('work_units_rates.json')).read_text(encoding='utf-8-sig'))
    if data.get('unit') != 'WU' or not isinstance(data.get('rate_date'), str):
        raise ValueError('dated WU tariff configuration required')
    if _decimal(data.get('basis_usd')) != Decimal('0.10'):
        raise ValueError('WU denomination is fixed at $0.10; version rates, not the unit')
    rates = data.get('rates_per_million')
    if not isinstance(rates, dict) or not rates:
        raise ValueError('nonempty model tariffs required')
    for model, row in rates.items():
        if not isinstance(model, str) or not isinstance(row, dict):
            raise ValueError('invalid model tariff')
        for field in FIELDS:
            _decimal(row.get(field))
    return data


def _cost(value, status, known, rates, notes=()):
    return {'value': _text(value) if value is not None else None,
            'known_value': _text(known) if known is not None else None,
            'status': status, 'basis': BASIS, 'rate_date': rates['rate_date'], 'notes': list(dict.fromkeys(notes))}


def price_usage(model, usage, *, coverage='complete', rates=None):
    """Price three observed token columns once. Reasoning and effort add no extra term."""
    rates = rates or load_rates()
    tariff = rates['rates_per_million'].get(model) if isinstance(model, str) else None
    if tariff is None:
        return _cost(None, 'unknown', None, rates, ['unknown_model'])
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in FIELDS):
        return _cost(None, 'unknown', None, rates, ['missing_or_invalid_token_counts'])
    # If optional total/reasoning data is present, refuse contradictory counters.
    input_count = usage.get('input', usage.get('input_tokens'))
    if input_count is not None and (type(input_count) is not int or input_count != usage['cached_input'] + usage['uncached_input']):
        return _cost(None, 'unknown', None, rates, ['inconsistent_input_counts'])
    reasoning = usage.get('reasoning', usage.get('reasoning_output_tokens'))
    if reasoning is not None and (type(reasoning) is not int or reasoning < 0 or reasoning > usage['output']):
        return _cost(None, 'unknown', None, rates, ['inconsistent_reasoning_counts'])
    with localcontext() as context:
        context.prec = max(50, max(len(str(usage[k])) for k in FIELDS) + 30)
        value = sum((Decimal(usage[k]) * _decimal(tariff[k]) for k in FIELDS), Decimal(0)) / Decimal(1_000_000)
    if coverage != 'complete':
        return _cost(None, 'partial', value, rates, ['partial_token_coverage'])
    return _cost(value, 'complete', value, rates)


def _sum(values):
    numbers = [Decimal(v) for v in values if v is not None]
    if not numbers:
        return None
    with localcontext() as context:
        context.prec = max(50, max(len(str(v)) for v in numbers) + len(str(len(numbers))) + 10)
        return sum(numbers, Decimal(0))


def _unit_cost(unit, rates):
    people = unit.get('participants') or []
    seen = set(); seen_threads = set(); identities_known = True
    for person in people:
        identity = person.get('participant_id') or person.get('thread_id')
        if not isinstance(identity, str) or not identity:
            identities_known = False
        elif identity in seen:
            raise ValueError('duplicate participant identity in Control Unit: '+identity)
        else:
            seen.add(identity)
        thread = person.get('thread_id')
        if thread:
            if thread in seen_threads:
                raise ValueError('duplicate participant thread in Control Unit: '+thread)
            seen_threads.add(thread)
        person['work_units'] = price_usage(person.get('model'), person.get('usage'),
                                            coverage=person.get('coverage', 'unknown'), rates=rates)
        if len(set(person.get('models_observed') or [])) > 1:
            person['work_units'] = _cost(None, 'unknown', None, rates, ['mixed_models_without_token_split'])
        elif person.get('models_observed') and person['models_observed'][0] != person.get('model'):
            person['work_units'] = _cost(None, 'unknown', None, rates, ['contradictory_model_identity'])
    independent = (identities_known and bool(people) and unit.get('usage_status') == 'complete'
                   and all(p.get('exclusive_scope') is True for p in people))
    complete = independent and all(p['work_units']['status'] == 'complete' for p in people)
    if complete:
        value = _sum(p['work_units']['value'] for p in people)
        return _cost(value, 'complete', value, rates)
    # A subtotal is safe only for explicitly independent counters, never an
    # invented zero or sum of potentially parent-inclusive counters.
    known = _sum(p['work_units']['known_value'] for p in people
                 if p.get('exclusive_scope') is True and p['work_units']['status'] in {'complete', 'partial'})
    notes = ['incomplete_team_coverage']
    if not independent:
        notes.append('unknown_or_overlapping_accounting_scope')
    if not identities_known:
        notes.append('participant_identity_unknown')
    return _cost(None, 'partial' if known is not None else 'unknown', known, rates, notes)


def _annotate(data, rates):
    if not isinstance(data, dict) or not isinstance(data.get('units'), list):
        raise ValueError('report data requires a units list')
    out = deepcopy(data); seen = set()
    for unit in out['units']:
        identity = unit.get('cu_id')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('Control Unit IDs must be present and unique in a selection')
        seen.add(identity)
        unit['work_units'] = _unit_cost(unit, rates)
        unit['budget_comparison'] = compare_budget(unit)
    costs = [u['work_units'] for u in out['units']]
    if costs and all(c['status'] == 'complete' for c in costs):
        value = _sum(c['value'] for c in costs)
        total = _cost(value, 'complete', value, rates)
    else:
        known = _sum(c['known_value'] for c in costs)
        total = _cost(None, 'partial' if known is not None else 'unknown', known, rates,
                      ['incomplete_selection' if costs else 'no_recorded_units'])
    accounting=out.get('accounting')
    if isinstance(accounting,dict):
        unique={}
        for event in accounting.get('events',[]):
            key=event['source_key']
            if key in unique and unique[key]!=event:
                raise ValueError('conflicting duplicate source cost key')
            unique[key]=event
        accounting['events']=[unique[k] for k in sorted(unique)]
        for event in accounting['events']:
            event['work_units']=price_usage(event.get('model'),event.get('usage'),
                coverage=event.get('coverage','unknown'),rates=rates)
        def ledger_total(events, empty_zero=True):
            if not events:
                return _cost(_decimal('0') if empty_zero else None,'complete' if empty_zero else 'unknown',
                             _decimal('0') if empty_zero else None,rates,[] if empty_zero else ['no_verified_source_events'])
            safe=[e for e in events if e.get('exclusive_scope') is True]
            complete=len(safe)==len(events) and all(e['work_units']['status']=='complete' for e in safe)
            known=_sum(e['work_units']['known_value'] for e in safe)
            return _cost(known if complete else None,'complete' if complete else ('partial' if known is not None else 'unknown'),known,rates,
                         [] if complete else ['missing_source_measurement_or_independent_scope'])
        rows=accounting['events']
        accounting['totals']=dict(project=ledger_total(rows,False),
            allocated=ledger_total([e for e in rows if e.get('cu_id') is not None]),
            unallocated=ledger_total([e for e in rows if e.get('cu_id') is None]))
        total=accounting['totals']['project']
        if accounting.get('manual_units_requiring_reconciliation'):
            # Manual rows stay visible on their CUs. Their overlap with the native
            # source ledger is not proven, so never add them a second time.
            total=_cost(None,'partial' if total.get('known_value') is not None else 'unknown',
                _decimal(total['known_value']) if total.get('known_value') is not None else None,
                rates,['manual_and_native_source_overlap_not_reconciled'])
            accounting['totals']['project']=total
    out['work_units'] = {k: deepcopy(rates[k]) for k in ('unit', 'name', 'basis_usd', 'rate_date', 'basis', 'source_url')}
    out['work_units'].update(total=total, excluded_adjustments=rates.get('excluded_adjustments', []),
                             subscription_note=rates.get('subscription_note', ''),
                             rates=[{'model': model, **{k: _text(_decimal(row[k])) for k in FIELDS}}
                                    for model, row in rates['rates_per_million'].items()])
    quota = out.get('quota_usage')
    if isinstance(quota, dict):
        def price_rows(rows):
            for row in rows:
                models = row.get('models') or []
                model = row.get('model') or (models[0] if len(models) == 1 else None)
                if len(set(models)) > 1:
                    model = None
                row['work_units'] = price_usage(model, row.get('usage'),
                                                coverage=row.get('coverage', 'unknown'), rates=rates)
        def actors_from(rows, fallback):
            # Rebuild actor cards from their per-model, per-turn request rows.
            # This preserves valid model splits and applies the selected rates.
            if rows and all(row.get('thread_id') and isinstance(row.get('usage'), dict)
                            and all(type(row['usage'].get(k)) is int for k in FIELDS) for row in rows):
                try:
                    from .quota_usage import _actors
                except ImportError:
                    from quota_usage import _actors
                normalized = [{**row, 'request_count': row.get('request_count', 0),
                               'observed_from': row.get('observed_from'),
                               'observed_through': row.get('observed_through')} for row in rows]
                return _actors(normalized, rates)
            price_rows(fallback)
            return fallback
        for window in quota.get('windows', []):
            rows = window.get('assignments', [])
            price_rows(rows)
            window['actors'] = actors_from(rows, window.get('actors', []))
        rows = quota.get('unassigned', [])
        price_rows(rows)
        quota['unassigned_actors'] = actors_from(rows, quota.get('unassigned_actors', []))
    if 'views' in out:
        if not isinstance(out['views'], list):
            raise ValueError('report views must be a list')
        view_ids = set()
        for view in out['views']:
            if not isinstance(view, dict) or not isinstance(view.get('id'), str) or view['id'] in view_ids:
                raise ValueError('report view IDs must be present and unique')
            if 'views' in view:
                raise ValueError('nested report views are not supported')
            view_ids.add(view['id'])
        out['views'] = [_annotate(view, rates) for view in out['views']]
    return out


def annotate_report(data, rate_path=None):
    """Recompute derived WU from raw participants, leaving original evidence unchanged."""
    return _annotate(data, load_rates(rate_path))
