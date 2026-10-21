"""On-demand, immutable evidence snapshots and explainer request lifecycle for Duet.

This module stores event metadata only. It never starts a model or reads source bodies
for an explanation; a caller must explicitly request an event before report creation.
"""
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
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .project_memory import append as append_memory, select as select_memory, record_attention_click
except ImportError:
    from project_memory import append as append_memory, select as select_memory, record_attention_click


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_MAX_REFS = 20
_MAX_SUMMARY = 500


class AttentionError(ValueError):
    """Invalid event, reference, or lifecycle transition."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(event_id: str) -> str:
    if not isinstance(event_id, str) or not _ID_RE.fullmatch(event_id):
        raise AttentionError("event_id must contain 1-80 letters, digits, '_' or '-'")
    return event_id


def _root(root: str | Path) -> Path:
    path = Path(root).resolve(strict=True)
    if not path.is_dir():
        raise AttentionError("workspace root must be a directory")
    return path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(root: Path, reference: str | Path) -> tuple[str, Path]:
    raw = Path(reference)
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise AttentionError(f"reference must resolve to an existing file inside workspace: {reference}") from exc
    if not resolved.is_file():
        raise AttentionError(f"reference is not a file: {reference}")
    return relative.as_posix(), resolved


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttentionError(f"cannot read saved record: {path}") from exc
    if not isinstance(value, dict):
        raise AttentionError(f"saved record is not an object: {path}")
    return value


def _event_path(root: Path, event_id: str) -> Path:
    return memory_dir(root) / "attention" / "events" / f"{_safe_id(event_id)}.json"


def _record_path(root: Path, bucket: str, event_id: str) -> Path:
    return memory_dir(root) / "attention" / bucket / f"{_safe_id(event_id)}.json"


def register_event(root: str | Path, event_id: str, title: str, status: str,
                   evidence: Iterable[str | Path], summary: str, planner_id: str) -> dict:
    """Register a canonical attention item; planner_id is an asserted caller role."""
    base = _root(root); event_id = _safe_id(event_id)
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise AttentionError("title must be non-empty and at most 200 characters")
    if not isinstance(status, str) or not status.strip() or len(status) > 80:
        raise AttentionError("status must be non-empty and at most 80 characters")
    if not isinstance(summary, str) or len(summary) > _MAX_SUMMARY:
        raise AttentionError(f"summary must be text of at most {_MAX_SUMMARY} characters")
    if not isinstance(planner_id, str) or not planner_id.strip() or len(planner_id) > 200:
        raise AttentionError("planner_id must be non-empty and at most 200 characters")
    evidence=list(evidence)
    if len(evidence)>_MAX_REFS: raise AttentionError(f"at most {_MAX_REFS} evidence references are allowed")
    refs=[]
    for ref in evidence:
        rel, path = _reference(base, ref); refs.append({"path":rel,"sha256":_hash_file(path)})
    snapshot={"schema_version":1,"event_id":event_id,"created_at":_now(),"title":title.strip(),
              "status":status.strip(),"summary":summary,"planner_id":planner_id.strip(),"evidence":refs}
    snapshot["snapshot_sha256"] = hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    row={"schema_version":1,"id":event_id,"kind":"attention_item","status":"open","event":snapshot,
         "request_record":None,"interpretation":"click_or_seen_is_not_approval_or_human_gold",
         "provenance":{"kind":"attention_registration","planner_id":planner_id.strip()}}
    try:
        existing=select_memory(base,"attention",[event_id],full=True)
        if existing:
            previous=existing[0].get("event",{})
            new=dict(snapshot); old=dict(previous)
            new.pop("created_at",None); new.pop("snapshot_sha256",None)
            old.pop("created_at",None); old.pop("snapshot_sha256",None)
            if new != old: raise AttentionError("event_id already has a different immutable snapshot")
            return previous
    except ValueError: pass
    try:
        append_memory(base,"attention",row,"hq")
        return snapshot
    except ValueError as exc: raise AttentionError(str(exc)) from exc

def show_event(root: str | Path, event_id: str) -> dict:
    """Read one canonical attention item without reading evidence source bodies."""
    try:
        rows=select_memory(_root(root),"attention",[_safe_id(event_id)],full=True)
        row=rows[0]
    except (ValueError, IndexError) as exc: raise AttentionError(str(exc)) from exc
    if isinstance(row.get("event"),dict): return row["event"]
    if isinstance(row.get("payload"),dict): return row["payload"]
    raise AttentionError("canonical attention record has no event snapshot")

def read_event(root: str | Path, event_id: str) -> dict:
    """Public read-only alias for adapters that display an attention card."""
    return show_event(root, event_id)


def request_event(root: str | Path, event_id: str) -> dict:
    """Record a request click in canonical attention; never signals approval."""
    base=_root(root); event_id=_safe_id(event_id); event=show_event(base,event_id)
    try: row=record_attention_click(base,event_id)
    except ValueError as exc: raise AttentionError(str(exc)) from exc
    return row["request_record"]

def _source_signatures(base: Path, event: dict) -> list[dict]:
    current = []
    for item in event.get("evidence", []):
        rel = item["path"]
        try:
            _, path = _reference(base, rel)
            digest = _hash_file(path)
            current.append({"path": rel, "status": "present", "sha256": digest,
                            "changed": digest != item.get("sha256")})
        except AttentionError:
            current.append({"path": rel, "status": "missing", "sha256": None,
                            "changed": True})
    return current


def event_context(root: str | Path, event_id: str) -> dict:
    """Return canonical snapshot and current ref signatures after an explicit click."""
    base=_root(root); event=show_event(base,event_id)
    rows=select_memory(base,"attention",[event_id],full=True); request=rows[0].get("request_record")
    if not isinstance(request,dict) or request.get("status")!="requested":
        raise AttentionError("event context is available only after an explicit request")
    return {"event":event,"requested_at":request.get("requested_at"),
            "source_signatures_now":_source_signatures(base,event),
            "interpretation":"request click is not approval or human gold; event fields are historical snapshot"}

def report_cache_status(root: str | Path, event_id: str) -> dict:
    """Report whether a saved explanation can be reused without silent staleness."""
    base = _root(root)
    event = show_event(base, event_id)
    md = base / "reports" / "attention" / f"{_safe_id(event_id)}.md"
    metadata_path = base / "reports" / "attention" / f"{event_id}.json"
    if not md.exists() or not metadata_path.exists():
        return {"status": "missing", "path": str(md)}
    metadata = _load_json(metadata_path)
    signatures = _source_signatures(base, event)
    unchanged = (metadata.get("markdown_sha256") == _hash_file(md)
                 and metadata.get("event_snapshot_sha256") == event.get("snapshot_sha256")
                 and metadata.get("source_signatures") == signatures)
    return {"status": "ready" if unchanged else "stale", "path": str(md),
            "event_snapshot_matches": metadata.get("event_snapshot_sha256") == event.get("snapshot_sha256"),
            "source_signatures_match": metadata.get("source_signatures") == signatures}


def finalize_report(root: str | Path, event_id: str, markdown: str) -> dict:
    """Persist an explanation only for a requested event, with source provenance."""
    base = _root(root)
    context = event_context(base, event_id)
    if not isinstance(markdown, str) or not markdown.strip():
        raise AttentionError("markdown must be non-empty text")
    report_dir = base / "reports" / "attention"
    md_path = report_dir / f"{_safe_id(event_id)}.md"
    metadata_path = report_dir / f"{event_id}.json"
    report_dir.mkdir(parents=True, exist_ok=True)
    # Write markdown atomically, then metadata. Missing metadata makes an interrupted write unusable.
    fd, temporary = tempfile.mkstemp(prefix=f".{md_path.name}.", suffix=".tmp", dir=report_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown.rstrip() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, md_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    metadata = {"schema_version": 1, "event_id": event_id, "saved_at": _now(),
                "event_snapshot_sha256": context["event"]["snapshot_sha256"],
                "markdown_sha256": _hash_file(md_path),
                "source_signatures": context["source_signatures_now"]}
    _atomic_json(metadata_path, metadata)
    return {"status": "saved", "path": str(md_path), "metadata": metadata}


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--root", required=True)
    reg.add_argument("--event-json", required=True, help="JSON object: event_id,title,status,evidence,summary,planner_id")
    for name in ("show", "request", "context", "report-cache"):
        command = sub.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--event-id", required=True)
    fin = sub.add_parser("finalize")
    fin.add_argument("--root", required=True)
    fin.add_argument("--event-id", required=True)
    fin.add_argument("--markdown-file", required=True)
    args = parser.parse_args()
    try:
        if args.command == "register":
            payload = json.loads(Path(args.event_json).read_text(encoding="utf-8"))
            result = register_event(args.root, payload["event_id"], payload["title"], payload["status"],
                                   payload["evidence"], payload["summary"], payload["planner_id"])
        elif args.command == "show": result = show_event(args.root, args.event_id)
        elif args.command == "request": result = request_event(args.root, args.event_id)
        elif args.command == "context": result = event_context(args.root, args.event_id)
        elif args.command == "report-cache": result = report_cache_status(args.root, args.event_id)
        else:
            result = finalize_report(args.root, args.event_id,
                                     Path(args.markdown_file).read_text(encoding="utf-8"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AttentionError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
