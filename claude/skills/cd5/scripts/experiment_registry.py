#!/usr/bin/env python3
"""Append-only, standard-library experiment registry for a CD5 project.

Legacy imports deliberately index machine metadata only. They never interpret
report prose or infer scientific success from a directory/file name.
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
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
REGISTRY_NAME = "EVIDENCE.jsonl"
LEGACY_REGISTRY_NAME = "results/REGISTRY.jsonl"
EVENT_TYPES = {
    "legacy_import",
    "protocol_frozen",
    "execution_started",
    "execution_completed",
    "technical_failed",
    "stopped",
    "truncated",
    "acceptance",
    "semantic_verdict",
    "note",
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
METADATA_NAMES = {
    "STATUS.json", "METRICS.json", "METRICS_FINAL.json", "FINAL_METRICS.json",
    "MANIFEST.json", "PREFLIGHT.json", "RECEIPT.json", "CHECKPOINT.json",
    "FREEZE.json", "EVALUATOR_FREEZE.json", "AUTHORIZATION.json",
    "summary.json", "summary.partial.json", "RESULTS_TABLE.json",
    "FINAL_CHECKS.json", "final_checks.json", "PROVENANCE_CHECK.json",
    "ENVIRONMENT_CHECK.json", "PRELAUNCH_CHECK.json", "PREPARATION.json",
    "CASES.json", "CASE.json", "QUESTION_FREEZE.json", "questions.json",
    "QUESTIONS.json", "CONTRACT.json", "CONTRACT_FREEZE.json",
}
MACHINE_KEYS = {
    "status", "state", "phase", "completed", "stopped", "truncated",
    "attempts", "planned_attempts", "completed_attempts", "exit_code",
    "started_at", "completed_at", "stopped_at", "recorded_at", "created_at",
    "protocol_sha256", "manifest_sha256", "schema_version",
    "case", "case_id", "case_name", "question", "question_id",
    "contract", "contract_id", "task", "title", "dataset", "sheet",
}
ALWAYS_UNKNOWN_LEGACY = [
    "scientific_success", "scientific_verdict", "protocol_frozen",
    "human_acceptance", "duplicate_identity",
]


class RegistryError(ValueError):
    """Invalid registry data or unsafe source reference."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise RegistryError(f"{label} must be 1-160 safe letters, digits, '.', '_', ':', or '-'")
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path.cwd().resolve()


def _registry_path(root: Path) -> Path:
    return memory_dir(root) / REGISTRY_NAME


def _relative_source(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RegistryError(f"source path is outside workspace: {value}") from exc
    if path == _registry_path(root).resolve():
        raise RegistryError("the registry cannot be registered as its own source")
    if not path.is_file():
        raise RegistryError(f"source file does not exist: {value}")
    return path


def make_source_ref(root: str | Path, source_path: str | Path) -> dict[str, str]:
    """Return a workspace-relative, content-hashed reference to an existing file."""
    base = _root(root)
    path = _relative_source(base, source_path)
    return {"path": path.relative_to(base).as_posix(), "sha256": _sha256_file(path)}


def build_event(
    experiment_id: str,
    event_type: str,
    *,
    source_paths: Iterable[str | Path] = (),
    provenance: dict[str, Any],
    machine_facts: dict[str, Any] | None = None,
    semantic_verdict: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a validated event, hashing each supplied source file."""
    base = _root(root)
    refs = [make_source_ref(base, p) for p in source_paths]
    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "experiment_id": _valid_id(experiment_id, "experiment_id"),
        "event_type": event_type,
        "recorded_at": _now(),
        "source_refs": refs,
        "provenance": provenance,
    }
    if machine_facts is not None:
        event["machine_facts"] = machine_facts
    if semantic_verdict is not None:
        event["semantic_verdict"] = semantic_verdict
    if details is not None:
        event["details"] = details
    _validate_event(event)
    return event


def _validate_event(event: Any) -> None:
    if not isinstance(event, dict):
        raise RegistryError("event must be a JSON object")
    required = {"schema_version", "event_id", "experiment_id", "event_type", "recorded_at", "source_refs", "provenance"}
    missing = required.difference(event)
    if missing:
        raise RegistryError(f"event missing required fields: {', '.join(sorted(missing))}")
    if event["schema_version"] != SCHEMA_VERSION:
        raise RegistryError(f"unsupported schema_version: {event['schema_version']!r}")
    _valid_id(event["event_id"], "event_id")
    _valid_id(event["experiment_id"], "experiment_id")
    if event["event_type"] not in EVENT_TYPES:
        raise RegistryError(f"unsupported event_type: {event['event_type']!r}")
    try:
        parsed = datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise RegistryError("recorded_at must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegistryError("recorded_at must include a timezone")
    if not isinstance(event["provenance"], dict) or not event["provenance"]:
        raise RegistryError("provenance must be a non-empty object")
    if not isinstance(event["source_refs"], list):
        raise RegistryError("source_refs must be a list")
    for ref in event["source_refs"]:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise RegistryError("each source_ref must include a path")
        if not isinstance(ref.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
            raise RegistryError("each source_ref must include a lowercase SHA-256 hash")
    if event["event_type"] == "semantic_verdict":
        verdict = event.get("semantic_verdict")
        if not isinstance(verdict, dict) or not verdict:
            raise RegistryError("semantic_verdict events require a separate semantic_verdict object")
        if "machine_facts" in event:
            raise RegistryError("semantic_verdict events must not mix in machine_facts")
    elif event["event_type"] == "acceptance":
        if not isinstance(event.get("semantic_verdict"), dict) or not event["semantic_verdict"]:
            raise RegistryError("acceptance events require a semantic_verdict object")
        if "machine_facts" in event:
            raise RegistryError("acceptance events must keep semantic_verdict separate from machine_facts")
    elif event["event_type"] != "legacy_import" and not isinstance(event.get("machine_facts"), dict):
        raise RegistryError(f"{event['event_type']} events require machine_facts")


def _read_evidence_records(root: Path) -> list[dict[str, Any]]:
    try:
        from .cu_archive import evidence_rows
    except ImportError:
        from cu_archive import evidence_rows
    try: rows=evidence_rows(root)
    except ValueError as exc: raise RegistryError('invalid evidence envelope: '+str(exc)) from exc
    records=[]
    for line_no,record in enumerate(rows,1):
        if not isinstance(record,dict) or record.get("schema_version")!=1 or not isinstance(record.get("id"),str):
            raise RegistryError(f"invalid evidence envelope at record {line_no}")
        _valid_id(record["id"],"evidence id")
        kind=record.get("kind")
        if kind=="experiment_event":
            event=record.get("payload")
            if not isinstance(event,dict) or record["id"]!=event.get("event_id"):
                raise RegistryError(f"experiment_event id mismatch at record {line_no}")
            try: _validate_event(event)
            except RegistryError as exc: raise RegistryError(f'invalid evidence envelope at record {line_no}: {exc}') from exc
        elif kind in {"artifact","source"}:
            if "payload" not in record or not isinstance(record.get("provenance"),dict):
                raise RegistryError(f"invalid {kind} evidence envelope at record {line_no}")
        else: raise RegistryError(f"unsupported evidence kind at record {line_no}: {kind!r}")
        records.append(record)
    return records


def read_events(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Read and validate canonical EVIDENCE; return experiment events only."""
    base=_root(root)
    return [record["payload"] for record in _read_evidence_records(base) if record["kind"]=="experiment_event"]


def append_event(root: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    """Validate and append one event to canonical EVIDENCE under a shared lock."""
    base=_root(root); target=_registry_path(base); target.parent.mkdir(parents=True,exist_ok=True)
    migration_lock=memory_dir(base)/".memory-migration.lock"
    if migration_lock.exists(): raise RegistryError("five-file migration is in progress; evidence writes are paused")
    lock=target.with_suffix(target.suffix+".lock")
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc: raise RegistryError("canonical evidence append lock exists; inspect before retry") from exc
    try:
        os.close(fd)
        if migration_lock.exists(): raise RegistryError("five-file migration is in progress; evidence writes are paused")
        records=_read_evidence_records(base)
        _validate_event(event)
        if any(record["id"]==event["event_id"] for record in records): raise RegistryError(f"event_id already exists: {event['event_id']}")
        for ref in event["source_refs"]:
            if ref.get("hash_scope")=="sorted_file_path_and_size_inventory":
                path=(base/ref["path"]).resolve()
                try: path.relative_to(base)
                except ValueError as exc: raise RegistryError(f"source path is outside workspace: {ref['path']}") from exc
                if not path.is_dir(): raise RegistryError(f"source directory does not exist: {ref['path']}")
                current_hash=_inventory_hash(base,path)
            else:
                path=_relative_source(base,ref["path"]); current_hash=_sha256_file(path)
            if current_hash!=ref["sha256"]: raise RegistryError(f"source hash changed since event was built: {ref['path']}")
        envelope={"schema_version":1,"id":event["event_id"],"kind":"experiment_event","payload":event,
                  "provenance":{"kind":"runtime_append","source":"tools/experiment_registry.py"}}
        with target.open("ab") as stream:
            stream.write(_json_bytes(envelope)+b"\n"); stream.flush(); os.fsync(stream.fileno())
        return event
    finally: lock.unlink(missing_ok=True)

def _json_safe_machine_value(value: Any, depth: int = 0) -> Any:
    """Keep only small primitive/list/object metadata and a strict key allowlist."""
    if depth > 3:
        return "[omitted]"
    if isinstance(value, dict):
        return {str(k): _json_safe_machine_value(v, depth + 1) for k, v in value.items() if str(k) in MACHINE_KEYS}
    if isinstance(value, list):
        return [_json_safe_machine_value(x, depth + 1) for x in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 240:
            return value[:237] + "..."
        return value
    return str(value)[:240]


def _read_legacy_metadata(directory: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    refs: list[dict[str, Any]] = []
    collected: dict[str, Any] = {}
    issues: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name not in METADATA_NAMES:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                issues.append(f"metadata_too_large:{path.relative_to(directory).as_posix()}")
                continue
            with path.open("r", encoding="utf-8-sig") as stream:
                parsed = json.load(stream)
            if not isinstance(parsed, dict):
                issues.append(f"metadata_not_object:{path.relative_to(directory).as_posix()}")
                continue
            safe = _json_safe_machine_value(parsed)
            if safe:
                collected[path.name] = safe
            refs.append({"path": path.relative_to(directory.parent.parent).as_posix(), "sha256": _sha256_file(path)})
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            issues.append(f"metadata_unparsed:{path.relative_to(directory).as_posix()}:{type(exc).__name__}")
    return refs, collected, issues


def _inventory_ref(root: Path, directory: Path) -> dict[str, str]:
    return {
        "path": directory.relative_to(root).as_posix(),
        "sha256": _inventory_hash(root, directory),
        "hash_scope": "sorted_file_path_and_size_inventory",
    }


def _inventory_hash(root: Path, directory: Path) -> str:
    names = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.resolve() != _registry_path(root).resolve():
            try:
                names.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size})
            except OSError:
                names.append({"path": path.relative_to(root).as_posix(), "size": None})
    return hashlib.sha256(_json_bytes(names)).hexdigest()


def import_legacy_results(root: str | Path | None = None) -> dict[str, Any]:
    """Idempotently index each immediate child directory of results/."""
    base = _root(root)
    results_dir = base / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    events = read_events(base)
    imported_paths = {
        event.get("details", {}).get("legacy_source_path")
        for event in events
        if event["event_type"] == "legacy_import"
    }
    added = 0
    skipped = 0
    for directory in sorted(results_dir.iterdir()):
        if not directory.is_dir() or directory.name == REGISTRY_NAME:
            continue
        rel_dir = directory.relative_to(base).as_posix()
        if rel_dir in imported_paths:
            skipped += 1
            continue
        refs, metadata, issues = _read_legacy_metadata(directory)
        status_values = []
        for value in metadata.values():
            if isinstance(value, dict):
                for key in ("status", "state", "phase"):
                    candidate = value.get(key)
                    if isinstance(candidate, (str, int, bool)) and candidate not in status_values:
                        status_values.append(candidate)
        status = status_values[0] if len(status_values) == 1 else ("unknown" if status_values else "legacy_unindexed")
        refs.append(_inventory_ref(base, directory))
        facts = {
            "legacy_status": status,
            "machine_metadata": metadata,
            "metadata_parse_issues": issues,
            "unknown_fields": ALWAYS_UNKNOWN_LEGACY,
        }
        experiment_id = "legacy-" + hashlib.sha256(rel_dir.encode("utf-8")).hexdigest()[:20]
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": "legacy-import-" + hashlib.sha256(rel_dir.encode("utf-8")).hexdigest()[:24],
            "experiment_id": experiment_id,
            "event_type": "legacy_import",
            "recorded_at": _now(),
            "source_refs": refs,
            "source_path": rel_dir,
            "provenance": {
                "kind": "legacy_index",
                "method": "selective_machine_metadata_and_file_inventory",
                "metadata_allowlist": sorted(METADATA_NAMES),
                "report_prose_read": False,
                "scientific_verdict_inferred": False,
            },
            "machine_facts": facts,
            "details": {
                "legacy_source_path": rel_dir,
                "legacy_directory_name": directory.name,
                "duplicate_detection": "directory_path_only; similar experiments may remain duplicated",
            },
        }
        append_event(base, event)
        added += 1
    return {"added": added, "skipped_existing": skipped, "total_events": len(read_events(base))}


def _event_search_text(event: dict[str, Any]) -> str:
    fields = [event.get("experiment_id", ""), event.get("source_path", ""), json.dumps(event.get("machine_facts", {}), ensure_ascii=False)]
    fields.extend(ref.get("path", "") for ref in event.get("source_refs", []))
    return " ".join(map(str, fields)).casefold()


def query_events(root: str | Path, query: str) -> dict[str, Any]:
    """Exact ID/path first, then best-effort token overlap over indexed machine facts."""
    events = read_events(root)
    q = query.casefold().strip()
    if not q:
        raise RegistryError("query must not be empty")
    exact = [e for e in events if q == str(e.get("experiment_id", "")).casefold()
             or q == str(e.get("source_path", "")).casefold()
             or any(q == str(ref.get("path", "")).casefold() for ref in e.get("source_refs", []))]
    terms = {token for token in re.findall(r"[\w.-]+", q, flags=re.UNICODE) if len(token) > 1}
    ranked = []
    for event in events:
        if event in exact:
            continue
        haystack = _event_search_text(event)
        overlap = sorted(term for term in terms if term in haystack)
        if overlap:
            ranked.append((len(overlap), event, overlap))
    ranked.sort(key=lambda row: (-row[0], row[1]["experiment_id"]))
    matches = [{"match_kind": "exact", "event": e} for e in exact]
    matches.extend({"match_kind": "similar_legacy_or_machine_terms", "matched_terms": overlap, "event": event}
                   for _, event, overlap in ranked)
    return {
        "query": query,
        "matches": matches,
        "duplicate_detection": "best_effort_id_path_and_machine_term_search; no guarantee that similar experiments are deduplicated",
        "search_scope": "experiment IDs, exact indexed paths, and selective machine metadata; report prose is not searched",
    }


def _load_json_arg(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict) or not value:
        raise RegistryError(f"{label} must be a non-empty JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None, help="workspace root (defaults to this script's workspace)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("import-legacy", help="idempotently index immediate results/ directories")
    query_parser = sub.add_parser("query", help="search IDs, exact paths, and indexed machine terms")
    query_parser.add_argument("query")
    append = sub.add_parser("append", help="append one structured event from JSON inputs")
    append.add_argument("--experiment-id", required=True)
    append.add_argument("--event-type", required=True, choices=sorted(EVENT_TYPES - {"legacy_import"}))
    append.add_argument("--source", action="append", default=[], help="workspace-relative source file; may be repeated")
    append.add_argument("--provenance", required=True, help="non-empty provenance JSON object")
    append.add_argument("--machine-facts", help="machine facts JSON object (required except semantic events)")
    append.add_argument("--semantic-verdict", help="separate human/semantic verdict JSON object")
    append.add_argument("--details", help="additional structured details JSON object")
    args = parser.parse_args(argv)
    try:
        base = _root(args.root)
        if args.command == "import-legacy":
            result = import_legacy_results(base)
        elif args.command == "query":
            result = query_events(base, args.query)
        else:
            provenance = _load_json_arg(args.provenance, "provenance")
            facts = _load_json_arg(args.machine_facts, "machine_facts") if args.machine_facts else None
            verdict = _load_json_arg(args.semantic_verdict, "semantic_verdict") if args.semantic_verdict else None
            details = _load_json_arg(args.details, "details") if args.details else None
            event = build_event(args.experiment_id, args.event_type, source_paths=args.source,
                                provenance=provenance, machine_facts=facts,
                                semantic_verdict=verdict, details=details, root=base)
            result = append_event(base, event)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (RegistryError, OSError) as exc:
        print(f"registry error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
