"""Read-only deterministic routing helper for the Duet planner/generator pair."""
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
import json
from pathlib import Path
from typing import Any


ACTIVE = {"active", "inprogress", "in_progress", "running", "working"}
IDLE = {"idle", "completed", "notloaded", "not_loaded", "done"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _get(data: dict, *keys: str, default=None):
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def decide(state: dict, provisioning: dict, planner_status: str,
           generator_status: str, used_percent: float | None,
           ordinary_allowed: bool | None, controller_role: str = "none",
           control_only: bool = False) -> dict:
    """Return {action, reason}; never reads/writes outside supplied inputs."""
    # v2 retires pair provisioning and the permanent generator. STOP takes priority
    # even for legacy state whose old pair records no longer match.
    if (state.get("user_stop", {}).get("active") is True or state.get("phase") == "user_stopped"
            or state.get("user_stopped") is True
            or _norm(state.get("goal_status")) in {"stopped", "paused_by_user"}):
        return {"action": "wait_user_stop", "reason": "explicit user stop is recorded"}
    if state.get("schema_version") in (2, 3):
        try:
            from .experiment_control import route
        except ImportError:
            from experiment_control import route
        return route(state, planner_status=planner_status, executor_status=generator_status,
                     used_percent=used_percent, ordinary_allowed=ordinary_allowed,
                     control_only=control_only and controller_role == "planner")
    ready = _norm(provisioning.get("status")) == "ready"
    state_ids = {
        "planner": _get(state, "planner", "thread_id"),
        "generator": _get(state, "generator", "thread_id") or _get(state, "executor", "thread_id"),
    }
    provisioning_ids = {role: _get(provisioning, role, "thread_id") for role in ("planner", "generator")}
    ids_match = all(state_ids[r] and provisioning_ids[r] and state_ids[r] == provisioning_ids[r]
                    for r in ("planner", "generator"))
    if not ready or not ids_match:
        return {"action": "wait_provisioning", "reason": "provisioning is not ready or pair IDs mismatch"}

    if state.get("user_stopped") is True or _norm(state.get("goal_status")) in {"stopped", "paused_by_user"}:
        return {"action": "wait_user_stop", "reason": "explicit user stop is recorded"}
    if ordinary_allowed is False:
        return {"action": "wait_quota", "reason": "ordinary usage is not allowed"}
    if ordinary_allowed is None or used_percent is None:
        return {"action": "quota_unknown", "reason": "fresh quota or ordinary-usage status is unavailable"}
    if used_percent >= 90:
        return {"action": "schedule_quota_resume", "reason": "usage reached the 90% resume-wakeup threshold"}

    ps, gs = _norm(planner_status), _norm(generator_status)
    active_planner = ps in ACTIVE and not (control_only and _norm(controller_role) == "planner")
    active_generator = gs in ACTIVE and not (control_only and _norm(controller_role) == "generator")
    if active_planner or active_generator:
        return {"action": "wait_active", "reason": "a participant is already active; avoid duplicate work"}
    planner_status_unknown = ps not in IDLE and not (control_only and _norm(controller_role) == "planner" and ps in ACTIVE)
    generator_status_unknown = gs not in IDLE and not (control_only and _norm(controller_role) == "generator" and gs in ACTIVE)
    if planner_status_unknown or generator_status_unknown:
        return {"action": "inspect_status", "reason": "one or both native participant statuses are unknown"}

    verified = state.get("entire_goal_verified_complete") is True
    if verified:
        return {"action": "complete", "reason": "the entire goal is explicitly verified complete"}

    handoff = _norm(state.get("handoff_status"))
    delivery = _norm(state.get("planner_delivery"))
    if handoff in {"failed", "denied", "rejected", "delivery_failed"} or delivery.startswith(
        ("blocked", "failed", "denied", "rejected", "delivery_failed")
    ):
        return {"action": "blocked_delivery", "reason": "handoff failed or was denied; no automatic retry"}

    blocker = state.get("blocker")
    if isinstance(blocker, dict) and blocker.get("awaiting_user_decision") is True:
        source = _norm(blocker.get("source"))
        evidence = blocker.get("human_constraint_evidence")
        if source in {"user", "human", "direct_user"} and evidence:
            return {"action": "wait_blocker", "reason": "explicit human decision is required: " + str(blocker.get("reason", "unspecified blocker"))}

    assigned = state.get("assigned_task")
    assignment_status = _norm(assigned.get("status")) if isinstance(assigned, dict) else ""
    if (isinstance(assigned, dict) and assigned.get("task_id")
            and assigned.get("handoff_confirmed") is True
            and assignment_status in {"assigned", "pending", "runnable"}
            and _norm(assigned.get("status")) not in {"completed", "cancelled"}
            and _norm(assigned.get("owner", "generator")) == "generator"):
        return {"action": "wake_generator", "reason": "confirmed runnable assignment is waiting for the idle generator"}

    # Legacy stage closure, including original_pilot_complete=false and a next_step
    # phrased as separately authorized, does not prove the user blocked the goal.
    return {"action": "planner_decision", "reason": "goal remains open without a verified human blocker"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--provisioning", required=True, type=Path)
    ap.add_argument("--planner-status", required=True)
    ap.add_argument("--generator-status", required=True)
    ap.add_argument("--used-percent", type=float)
    ap.add_argument("--ordinary-allowed", choices=("true", "false", "unknown"), default="unknown")
    ap.add_argument("--controller-role", choices=("planner", "generator", "none"), default="none")
    ap.add_argument("--control-only", action="store_true",
                    help="Ignore this controller's active status only for a control-only heartbeat, not concurrent project work.")
    args = ap.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    provisioning = json.loads(args.provisioning.read_text(encoding="utf-8"))
    ordinary = {"true": True, "false": False, "unknown": None}[args.ordinary_allowed]
    print(json.dumps(decide(state, provisioning, args.planner_status,
                            args.generator_status, args.used_percent, ordinary,
                            args.controller_role, args.control_only),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
