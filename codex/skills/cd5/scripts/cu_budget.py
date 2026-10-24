"""CU forecast/limit records and Decimal comparisons; no spending enforcement."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import datetime as dt


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('WU amount must be a nonnegative decimal')
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('WU amount must be a nonnegative decimal') from error
    if not number.is_finite() or number < 0 or number.adjusted() > 18 or number.as_tuple().exponent < -18:
        raise ValueError('WU amount must be finite, nonnegative and within supported precision')
    if number == 0:
        return '0'
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _date(value):
    if not isinstance(value, str):
        raise ValueError('dated WU basis required')
    return dt.date.fromisoformat(value).isoformat()


def normalize_patch(data):
    """Normalize only explicitly supplied values; null clears, omission preserves."""
    try:
        from .work_units import load_rates
    except ImportError:
        from work_units import load_rates
    rate_date = load_rates()['rate_date']
    out = {}
    if 'forecast' in data:
        forecast = data['forecast']
        if forecast is None:
            out['forecast'] = None
        else:
            if not isinstance(forecast, dict):
                raise ValueError('forecast requires low/high/confidence')
            low, high = amount(forecast.get('low')), amount(forecast.get('high'))
            if Decimal(low) > Decimal(high):
                raise ValueError('forecast low must not exceed high')
            confidence = forecast.get('confidence', 'low')
            if confidence not in {'low', 'medium', 'high'}:
                raise ValueError('forecast confidence must be low, medium or high')
            out['forecast'] = {'low': low, 'high': high, 'confidence': confidence,
                               'rate_date': _date(forecast.get('rate_date', rate_date))}
    if 'limit' in data:
        out['limit'] = None if data['limit'] is None else amount(data['limit'])
        out['limit_rate_date'] = _date(data.get('limit_rate_date', rate_date))
    if 'forecast_unknown_reason' in data:
        reason = data['forecast_unknown_reason']
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode('utf-8')) > 4096:
            raise ValueError('forecast_unknown_reason must be nonempty short text')
        if data.get('forecast') is not None:
            raise ValueError('supply a forecast range or an unknown reason, not both')
        out.update(forecast=None, forecast_unknown_reason=reason)
    if not out:
        raise ValueError('supply a forecast or a separate limit')
    reason = data.get('reason', '')
    if not isinstance(reason, str) or len(reason.encode('utf-8')) > 4096:
        raise ValueError('budget reason must be short text')
    out['reason'] = reason
    return out


def initial_budget():
    return {'unit': 'WU', 'scope': 'whole_team', 'basis': 'standard_short_context_estimate',
            'forecast': None, 'original_forecast': None, 'limit': None, 'limit_rate_date': None, 'history': []}


def apply_patch(current, patch, *, at, event_id, initial=False):
    out = deepcopy(current)
    if 'forecast' in patch:
        out['forecast'] = deepcopy(patch['forecast'])
        out.pop('forecast_unknown_reason', None)
        if initial:
            out['original_forecast'] = deepcopy(patch['forecast'])
    if 'forecast_unknown_reason' in patch:
        out['forecast_unknown_reason'] = patch['forecast_unknown_reason']
    for key in ('limit', 'limit_rate_date'):
        if key in patch:
            out[key] = patch[key]
    out['history'].append({'at': at, 'event_id': event_id, 'initial': initial, **deepcopy(patch)})
    return out


def compare_budget(unit):
    with localcontext() as context:
        context.prec = 80
        return _compare_budget(unit)


def _compare_budget(unit):
    """Compare complete actuals only. Original prediction remains calibration baseline."""
    result = {'forecast_status': 'unknown', 'limit_status': 'unknown', 'forecast_basis': 'original',
              'actual_complete': False, 'forecast_difference': None, 'limit_remaining': None}
    cost, budget = unit.get('work_units') or {}, unit.get('budget') or {}
    if cost.get('status') != 'complete' or cost.get('value') is None:
        return result
    actual = Decimal(amount(cost['value']))
    result['actual_complete'] = True
    if (cost.get('basis') != 'standard_short_context_estimate' or budget.get('basis') != cost.get('basis')
            or budget.get('unit') != 'WU' or budget.get('scope') != 'whole_team'):
        return result
    forecast = budget.get('original_forecast')
    if forecast and forecast.get('rate_date') == cost.get('rate_date'):
        lo, hi = Decimal(amount(forecast['low'])), Decimal(amount(forecast['high']))
        # An unfinished CU can exceed a prediction, but cannot finish under it yet.
        if actual > hi:
            result['forecast_status'] = 'above'
            result['forecast_difference'] = amount(actual - hi)
        elif unit.get('status') == 'completed':
            result['forecast_status'] = 'below' if actual < lo else 'within'
            result['forecast_difference'] = amount(lo - actual) if actual < lo else '0'
    if budget.get('limit') is not None and budget.get('limit_rate_date') == cost.get('rate_date'):
        limit = Decimal(amount(budget['limit']))
        result['limit_status'] = 'exceeded' if actual > limit else ('at' if actual == limit else 'below')
        remaining = limit - actual
        result['limit_remaining'] = ('-' + amount(-remaining)) if remaining < 0 else amount(remaining)
    return result
