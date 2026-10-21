"""Render a portable, offline Control Unit progress report (stdlib only)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import importlib.util
import os
from pathlib import Path
import tempfile
import uuid


def render_report(data: dict, *, fragment: bool = False, rate_path: Path | None = None) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("units"), list):
        raise ValueError("Report data must be an object with a units list")
    try:
        from work_units import annotate_report
    except ModuleNotFoundError as error:
        if error.name != 'work_units':
            raise
        spec = importlib.util.spec_from_file_location('work_units', Path(__file__).with_name('work_units.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        annotate_report = module.annotate_report
    data = annotate_report(data, rate_path=rate_path)
    # Script data is inert JSON; escaping '<' prevents closing the script element.
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
    if template.count("__REPORT_DATA__") != 1:
        raise ValueError("Report template must contain exactly one data sentinel")
    rendered = template.replace('cd5-wu-report', 'cd5-wu-report-' + uuid.uuid4().hex).replace("__REPORT_DATA__", payload)
    if fragment:
        return rendered.split('<!--REPORT_FRAGMENT_START-->', 1)[1].split('<!--REPORT_FRAGMENT_END-->', 1)[0]
    return rendered


def write_report(data: dict, output: Path, *, fragment: bool = False, rate_path: Path | None = None) -> None:
    html = render_report(data, fragment=fragment, rate_path=rate_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output.parent, prefix=".cu-report-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(html)
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def select_data(data: dict, *, limit=10, all_units=False, since=None, until=None) -> dict:
    """Apply the same inclusive Moscow calendar/lifetime overlap as report_data."""
    zone = dt.timezone(dt.timedelta(hours=3))
    lo = dt.datetime.combine(dt.date.fromisoformat(since), dt.time.min, zone) if since else None
    hi = dt.datetime.combine(dt.date.fromisoformat(until) + dt.timedelta(days=1), dt.time.min, zone) if until else None
    if lo and hi and lo >= hi:
        raise ValueError('since must not be after until')
    rows = [unit for unit in data['units']
            if (not lo or not unit.get('ended_at') or dt.datetime.fromisoformat(unit['ended_at'].replace('Z', '+00:00')) >= lo)
            and (not hi or dt.datetime.fromisoformat(unit['started_at'].replace('Z', '+00:00')) < hi)]
    if not (all_units or since or until):
        rows = rows[:limit]
    label = f'{since or "начала истории"} — {until or "сегодня"}' if since or until else ('За всё время' if all_units else f'Последние {limit} CU')
    selected = {**data, 'units': rows, 'scope': {'label': label, 'since': since, 'until': until,
                'total_units': len(rows), 'usage_label': 'Расход выбранных CU за всё выполнение'}}
    if isinstance(data.get('views'), list):
        selected['views'] = [select_data({key: value for key, value in view.items() if key != 'views'},
                             limit=limit, all_units=all_units, since=since, until=until) for view in data['views']]
    return selected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path)
    source.add_argument("--data-file", type=Path)
    parser.add_argument("--limit", type=int, default=10, help="Rows per page (all selected history remains available)")
    parser.add_argument("--all", action="store_true", dest="all_units", help="Compatibility alias: all history is loaded by default")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fragment", action="store_true", help="Emit an inline artifact fragment")
    parser.add_argument("--rates", type=Path, help="Dated Work Units tariff configuration")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.data_file:
        data = json.loads(args.data_file.read_text(encoding="utf-8-sig"))
        data = select_data(data, limit=args.limit, all_units=True, since=args.since, until=args.until)
    else:
        from control_units import report_data
        data = report_data(args.root, all_units=True, since=args.since, until=args.until)
    def configure_pages(dataset):
        dataset = {**dataset, 'page_size': args.limit}
        if dataset['units'] and all(unit.get('started_at') for unit in dataset['units']):
            dataset['units'] = sorted(dataset['units'], key=lambda unit: dt.datetime.fromisoformat(unit['started_at'].replace('Z', '+00:00')), reverse=True)
        if isinstance(dataset.get('views'), list):
            dataset['views'] = [configure_pages(view) for view in dataset['views']]
        return dataset
    data = configure_pages(data)
    write_report(data, args.output, fragment=args.fragment, rate_path=args.rates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
