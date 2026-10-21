"""Cooperative task lifecycle ledger stored in the canonical EVIDENCE catalogue."""
from __future__ import annotations

import sys as _cd5_sys
from pathlib import Path as _CD5Path
if str(_CD5Path(__file__).resolve().parent) not in _cd5_sys.path:
    _cd5_sys.path.insert(0, str(_CD5Path(__file__).resolve().parent))
try:
    from .cd5_config import config as cd5_config, memory_dir, memory_map
except ImportError:
    from cd5_config import config as cd5_config, memory_dir, memory_map


import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from . import project_memory as pm
except ImportError:
    import project_memory as pm

EVENTS = {"start", "finish"}
ROLES = {"hq", "executor", "helper", "reviewer"}
CATEGORIES = {"science", "mechanics", "coordination", "heartbeat", "memory_update", "experiment", "report", "explanation"}
COUNT_KEYS = ("input", "cached_input", "uncached_input", "output", "reasoning")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _nonnegative(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise pm.MemoryError(f"{label} must be a nonnegative integer or null")
    return value


def _clean_time(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise pm.MemoryError("time must be an object")
    active = _nonnegative(value.get("active_seconds"), "time.active_seconds")
    waiting = _nonnegative(value.get("waiting_seconds"), "time.waiting_seconds")
    source = value.get("source", "unknown")
    complete = value.get("complete", False)
    if not isinstance(source, str) or not source.strip():
        raise pm.MemoryError("time.source must be a nonempty string")
    if not isinstance(complete, bool):
        raise pm.MemoryError("time.complete must be boolean")
    return {"active_seconds": active, "waiting_seconds": waiting,
            "source": source, "complete": complete}


def _clean_usage(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise pm.MemoryError("usage must be an object")
    counts = {key: _nonnegative(value.get(key), f"usage.{key}") for key in COUNT_KEYS}
    if counts["cached_input"] is not None and counts["input"] is not None and counts["cached_input"] > counts["input"]:
        raise pm.MemoryError("usage.cached_input cannot exceed usage.input")
    if counts["reasoning"] is not None and counts["output"] is not None and counts["reasoning"] > counts["output"]:
        raise pm.MemoryError("usage.reasoning is a subset of output and cannot exceed it")
    if counts["uncached_input"] is not None:
        if counts["input"] is None or counts["cached_input"] is None:
            raise pm.MemoryError("usage.uncached_input requires verified input and cached_input counts")
        if counts["uncached_input"] != counts["input"] - counts["cached_input"]:
            raise pm.MemoryError("usage.uncached_input must equal input minus cached_input")
    source = value.get("source", "unknown")
    source_kind = value.get("kind", "unknown")
    complete = value.get("complete", False)
    if not isinstance(source, str) or not source.strip():
        raise pm.MemoryError("usage.source must be a nonempty string")
    if source_kind not in {"per_task", "cumulative", "unknown"}:
        raise pm.MemoryError("usage.kind must be per_task, cumulative, or unknown")
    if not isinstance(complete, bool):
        raise pm.MemoryError("usage.complete must be boolean")
    baseline_in = value.get("baseline")
    delta_in = value.get("delta")
    baseline: dict[str, int | None] | None = None
    delta: dict[str, int | None] | None = None
    if baseline_in is not None:
        if not isinstance(baseline_in, dict):
            raise pm.MemoryError("usage.baseline must be an object")
        baseline = {key: _nonnegative(baseline_in.get(key), f"usage.baseline.{key}") for key in COUNT_KEYS}
    if delta_in is not None:
        if not isinstance(delta_in, dict):
            raise pm.MemoryError("usage.delta must be an object")
        delta = {key: _nonnegative(delta_in.get(key), f"usage.delta.{key}") for key in COUNT_KEYS}
    if source_kind == "cumulative":
        if baseline is None:
            # Cumulative counters never become task costs by assumption.
            delta = {key: None for key in COUNT_KEYS}
            if complete:
                raise pm.MemoryError("cumulative usage without a baseline cannot be marked complete")
        elif delta is None:
            delta = {key: (counts[key] - baseline[key]
                           if counts[key] is not None and baseline[key] is not None
                           and counts[key] >= baseline[key] else None)
                     for key in COUNT_KEYS}
        elif any(delta[key] is not None and counts[key] is not None and baseline[key] is not None
                 and delta[key] != counts[key] - baseline[key] for key in COUNT_KEYS):
            raise pm.MemoryError("usage.delta disagrees with cumulative counts and baseline")
    return {**counts, "source": source, "kind": source_kind, "complete": complete,
            "baseline": baseline, "delta": delta}


def _record_id(task_id: str, event: str, revision: int) -> str:
    raw = f"{task_id}\0{event}\0{revision}".encode("utf-8")
    return "task-" + hashlib.sha256(raw).hexdigest()


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    event = data.get("event")
    task_id = data.get("task_id")
    if event not in EVENTS:
        raise pm.MemoryError("event must be start or finish")
    pm._safe_id(task_id)
    title, goal = data.get("title"), data.get("goal")
    if not isinstance(title, str) or not title.strip() or not isinstance(goal, str) or not goal.strip():
        raise pm.MemoryError("title and goal must be nonempty strings")
    result = data.get("result")
    if result is not None and not isinstance(result, str):
        raise pm.MemoryError("result must be a string or null")
    parent = data.get("parent_task_id")
    if parent is not None:
        pm._safe_id(parent)
        if parent == task_id:
            raise pm.MemoryError("task cannot be its own parent")
    category = data.get("category")
    if category not in CATEGORIES:
        raise pm.MemoryError("category must be science, mechanics, coordination, or heartbeat")
    executor = data.get("executor")
    if not isinstance(executor, dict):
        raise pm.MemoryError("executor must be an object with agent/model/reasoning facts")
    executor = {key: executor.get(key) for key in ("agent", "model", "reasoning")}
    for key, value in executor.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise pm.MemoryError(f"executor.{key} must be a nonempty string or null")
    started_at, ended_at = data.get("started_at"), data.get("ended_at")
    timestamp_source = data.get("timestamp_source")
    if event == "start" and started_at is None:
        started_at, timestamp_source = _utc_now(), "event_clock"
    if event == "finish" and ended_at is None:
        ended_at, timestamp_source = _utc_now(), "event_clock"
    for label, value in (("started_at", started_at), ("ended_at", ended_at)):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise pm.MemoryError(f"{label} must be a timestamp string or null")
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise pm.MemoryError(f"{label} must be an ISO timestamp") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise pm.MemoryError(f"{label} must include a timezone")
    if started_at is not None and ended_at is not None:
        start_dt = dt.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end_dt = dt.datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        if end_dt < start_dt:
            raise pm.MemoryError("ended_at cannot be earlier than started_at")
    if timestamp_source is not None and (not isinstance(timestamp_source, str) or not timestamp_source.strip()):
        raise pm.MemoryError("timestamp_source must be a nonempty string or null")
    revision = data.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise pm.MemoryError("revision must be a positive integer")
    local = data.get("local_inference")
    if local is not None and not isinstance(local, dict):
        raise pm.MemoryError("local_inference must be an object or null")
    return {"type": "task_lifecycle", "event": event, "task_id": task_id,
            "revision": revision, "title": title.strip(), "goal": goal.strip(), "result": result,
            "parent_task_id": parent, "executor": executor, "category": category,
            "started_at": started_at, "ended_at": ended_at,
            "timestamp_source": timestamp_source,
            "time": _clean_time(data.get("time")), "usage": _clean_usage(data.get("usage")),
            "local_inference": local}


def record(root: str | Path, data: dict[str, Any], role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise pm.MemoryError("role must be hq, executor, helper, or reviewer")
    payload = _payload(data)
    event_id = _record_id(payload["task_id"], payload["event"], payload["revision"])
    row = {"schema_version": 1, "id": event_id, "kind": "artifact",
           "provenance": {"source": "task_ledger_cli", "role": role, "recorded_at": _utc_now()},
           "payload": payload}
    existing = (pm.select(root, "evidence", [event_id], full=True)
                if event_id in _ledger_ids(root) else [])
    if existing:
        old = existing[0]
        # A generated boundary timestamp is a fact captured at the first call; an
        # identical input without an explicit timestamp remains idempotent.
        compare = dict(payload)
        old_payload = dict(old.get("payload", {}))
        if data.get("event") == "start" and data.get("started_at") is None:
            compare["started_at"] = old_payload.get("started_at")
            compare["timestamp_source"] = old_payload.get("timestamp_source")
        if data.get("event") == "finish" and data.get("ended_at") is None:
            compare["ended_at"] = old_payload.get("ended_at")
            compare["timestamp_source"] = old_payload.get("timestamp_source")
        if compare != old_payload:
            raise pm.MemoryError("task event already exists with different content; use a new explicit revision")
        return old
    return pm.append(root, "evidence", row, role)


def _ledger_ids(root: str | Path) -> list[str]:
    return [row['id'] for row in pm.evidence_history(root)
            if isinstance(row.get('payload'), dict) and row['payload'].get('type') == 'task_lifecycle']


def summary(root: str | Path, limit: int = 10, task_filter: str | None = None) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise pm.MemoryError("limit must be between 1 and 100")
    ids = _ledger_ids(root)
    rows = pm.select(root, "evidence", ids, full=True) if ids else []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        payload = row["payload"]
        if task_filter is None or payload["task_id"] == task_filter:
            grouped.setdefault(payload["task_id"], []).append(payload)
    result = []
    for task_id, events in grouped.items():
        events.sort(key=lambda p: (p.get("revision", 1), 0 if p.get("event") == "start" else 1))
        finishes = [p for p in events if p.get("event") == "finish"]
        starts = [p for p in events if p.get("event") == "start"]
        chosen = finishes[-1] if finishes else (starts[-1] if starts else events[-1])
        reported_usage = chosen.get("usage") or {}
        if reported_usage.get("kind") == "per_task":
            task_usage = reported_usage
        elif reported_usage.get("kind") == "cumulative" and reported_usage.get("baseline") is not None:
            delta = reported_usage.get("delta") or {key: None for key in COUNT_KEYS}
            task_usage = {**{key: delta.get(key) for key in COUNT_KEYS}, "source": reported_usage.get("source"),
                          "kind": "baseline_delta", "complete": reported_usage.get("complete", False),
                          "baseline": reported_usage.get("baseline"), "delta": delta}
        else:
            task_usage = {**{key: None for key in COUNT_KEYS}, "source": reported_usage.get("source", "unknown"),
                          "kind": "unknown", "complete": False, "baseline": reported_usage.get("baseline"),
                          "delta": reported_usage.get("delta")}
        result.append({"task_id": task_id, "title": chosen.get("title"), "goal": chosen.get("goal"),
                       "result": chosen.get("result"), "parent_task_id": chosen.get("parent_task_id"),
                       "executor": chosen.get("executor"), "category": chosen.get("category"),
                       "started_at": (starts[-1] if starts else chosen).get("started_at"),
                       "ended_at": (finishes[-1] if finishes else chosen).get("ended_at"),
                       "status": ("finished" if finishes and starts else
                                 "finished_without_start" if finishes else "started_without_finish"),
                       "time": chosen.get("time"), "usage": task_usage, "reported_usage": reported_usage,
                       "local_inference": chosen.get("local_inference"), "event_count": len(events),
                       "evidence_ids": [row["id"] for row in rows if row["payload"]["task_id"] == task_id],
                       "revision_count": len({p.get("revision", 1) for p in events})})
    result.sort(key=lambda item: (item.get("started_at") or "", item["task_id"]), reverse=True)
    telemetry = {}
    for record in pm.evidence_history(root):
        p = record.get('payload')
        if isinstance(p, dict) and p.get('type') == 'task_telemetry':
            telemetry[p.get('task_id')] = {**p, 'evidence_id': record['id']}
    for index, item in enumerate(result[:limit], 1):
        item["index"] = index
        stamp = item.get("started_at")
        item["started_at_moscow"] = (dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                                     .astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat() if stamp else None)
        item["telemetry"] = telemetry.get(item["task_id"])
    return result[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="record one start or finish event from JSON")
    rec.add_argument("--record-file", required=True)
    rec.add_argument("--role", required=True, choices=sorted(ROLES))
    summ = sub.add_parser("summary", help="read-only per-task lifecycle summary")
    summ.add_argument("--limit", type=int, default=10)
    summ.add_argument("--task")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            data = json.loads(Path(args.record_file).read_text(encoding="utf-8"))
            out = record(args.root, data, args.role)
        else:
            out = summary(args.root, args.limit, args.task)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (pm.MemoryError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
