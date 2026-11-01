"""Read-only MCP attention card adapter. No model/report is run while rendering."""
from __future__ import annotations

import sys as _cd5_sys
from pathlib import Path as _CD5Path
if str(_CD5Path(__file__).resolve().parent) not in _cd5_sys.path:
    _cd5_sys.path.insert(0, str(_CD5Path(__file__).resolve().parent))
try:
    from .cd5_config import config as cd5_config, memory_dir, memory_map
except ImportError:
    from cd5_config import config as cd5_config, memory_dir, memory_map


import json
from pathlib import Path
import runpy


def card_payload(root: str | Path, event_id: str) -> dict:
    root = Path(root).resolve(strict=True)
    # Prefer a currently open canonical question. Legacy immutable explainer events
    # remain available through the compatibility branch below.
    memory = runpy.run_path(str(Path(__file__).with_name("project_memory.py")))
    try:
        rows = memory["select"](root, "attention", [event_id], full=True, include_closed=True)
    except ValueError as exc:
        if not str(exc).startswith("unknown IDs:"):
            raise
        rows = []
    if rows:
        row = rows[0]
        if row.get("status") == "closed" or row.get("kind") == "attention_archive_ref":
            return {"ready": False, "mode": "duet-attention", "event_id": event_id,
                    "title": "Этот пункт уже закрыт", "question": "Обновите список открытых вопросов.",
                    "request_prompt": "", "status": "closed"}
        # Explicit requests for a historic compatibility event remain supported;
        # the canonical pending list still excludes these informational rows.
        if not (row.get("status") == "nonblocking" and isinstance(row.get("event"), dict)):
            board = runpy.run_path(str(Path(__file__).with_name("attention.py")))
            try:
                item = board["show_item"](root, event_id)
            except ValueError:
                return {"ready": False, "mode": "duet-attention", "event_id": event_id,
                        "title": "Пункт не требует ответа", "question": "Обновите список открытых вопросов.",
                        "request_prompt": "", "status": row.get("status", "open")}
            return {
                "ready": True,
                "mode": "duet-attention",
                "event_id": item["id"],
                "title": item["title"],
                "question": item["question"],
                "status": item["status"],
                "source_refs": item["source_refs"],
                "owner": item["owner"],
                "diagnostic": item.get("diagnostic"),
                "request_prompt": item["request_prompt"],
            }
    api = runpy.run_path(str(Path(__file__).with_name("duet_attention.py")))
    event = api["read_event"](root, event_id)
    return {
        "ready": True,
        "mode": "duet-attention",
        "event_id": event["event_id"],
        "title": event["title"],
        "status": event["status"],
        "snapshot_sha256": event["snapshot_sha256"],
        "request_prompt": (
            f"[duet-explain:{event['event_id']}] "
            "Разъясни именно сохранённое событие с этим ID. "
            "Сначала зарегистрируй явный запрос через установленный scripts/duet_attention.py request, "
            "проверь report-cache и context. При готовом неизменном отчёте дай ссылку. "
            "Иначе объясни, что было известно при показе маркера и что выяснилось позже. "
            "Если готовых материалов хватает, ответь сам; помощник нужен только "
            "для ограниченного сбора недостающих фактов, затем проверь вывод. "
            "Сохрани MD через finalize и дай абсолютную ссылку. "
            "Сам запрос разъяснения не расширяет порученный план и не является человеческой оценкой. Уже порученные шаги и внутренние решения остаются полномочиями HQ."
        ),
    }


def resource_html(root: str | Path, legacy_html: str) -> str:
    template = Path(__file__).with_name("duet_attention_widget.html").read_text(encoding="utf-8")
    return template.replace("<!--LEGACY-PROBE-->", legacy_html)

