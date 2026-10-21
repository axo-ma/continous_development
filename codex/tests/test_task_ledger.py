import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))
import task_ledger as ledger
import project_memory as pm
from tests.cd5_fixtures import configure


class TaskLedgerTests(unittest.TestCase):
    def test_summary_ignores_nonobject_artifact_payload(self):
        ledger.record(self.root, self.item("start"), "helper")
        pm.append(self.root, "evidence", {"id": "unrelated-null", "kind": "artifact",
                  "payload": None, "provenance": {"source": "test"}}, "hq")
        self.assertEqual(len(ledger.summary(self.root)), 1)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix=".task-ledger-test-", dir=HERE))
        configure(self.root)
        base = self.root / "coordination" / "cd5"
        base.mkdir(parents=True)
        (base / "OUTLINE.md").write_text("outline", encoding="utf-8")
        mem = {k: "coordination/cd5/" + v for k, v in pm.FILES.items()}
        cp = {"schema_version": 3, "memory": mem, "owner": {"role": "hq", "thread_id": "owner"},
              "user_stop": {"active": False}, "next_action": {"kind": "planner_decision"},
              "continuity": {"quota_stop_used_percent": 90}, "active_task": {"status": "awaiting_review"},
              "pending_context_update": {"status": "deferred"}}
        (base / "CHECKPOINT.json").write_text(json.dumps(cp), encoding="utf-8")
        for name in ("EVIDENCE.jsonl", "KNOWLEDGE.jsonl", "ATTENTION.jsonl"):
            (base / name).write_text("", encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    @staticmethod
    def item(event, task_id="task-a", **overrides):
        data = {"event": event, "task_id": task_id, "title": task_id,
                "goal": "bounded task goal", "result": "done" if event == "finish" else None,
                "parent_task_id": None, "executor": {"agent": "luna_helper_task", "model": "GPT-6 Luna",
                                                       "reasoning": "high"},
                "category": "mechanics", "time": {"active_seconds": None, "waiting_seconds": None,
                                                       "source": "unknown", "complete": False},
                "usage": {"source": "unknown", "kind": "unknown", "complete": False}}
        data.update(overrides)
        return data

    def test_start_finish_roundtrip_and_idempotence(self):
        start = ledger.record(self.root, self.item("start"), "helper")
        self.assertEqual(ledger.record(self.root, self.item("start"), "helper"), start)
        finish = ledger.record(self.root, self.item("finish", started_at=start["payload"]["started_at"],
                                                   time={"active_seconds": 90, "waiting_seconds": 12,
                                                         "source": "agent_report", "complete": True}), "helper")
        view = ledger.summary(self.root, task_filter="task-a")
        self.assertEqual(len(view), 1)
        self.assertEqual(view[0]["status"], "finished")
        self.assertEqual(view[0]["time"]["active_seconds"], 90)
        self.assertEqual(view[0]["event_count"], 2)
        self.assertEqual(pm.select(self.root, "evidence", [finish["id"]], full=True)[0]["payload"]["result"], "done")

    def test_changed_duplicate_requires_revision_and_count_validation(self):
        ledger.record(self.root, self.item("start"), "helper")
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, self.item("start", title="changed"), "helper")
        bad = self.item("finish", usage={"input": 4, "cached_input": 5})
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, bad, "helper")
        bad = self.item("finish", usage={"input": 10, "cached_input": 4, "uncached_input": 7})
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, bad, "helper")
        bad = self.item("finish", usage={"output": 10, "reasoning": 11})
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, bad, "helper")
        bad = self.item("finish", usage={"input": 10, "kind": "cumulative", "complete": True})
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, bad, "helper")

    def test_summary_keeps_unknowns_and_does_not_double_count_parent_child(self):
        parent_start = self.item("start", "parent", category="coordination")
        ledger.record(self.root, parent_start, "hq")
        child_start = self.item("start", "child", parent_task_id="parent")
        ledger.record(self.root, child_start, "executor")
        child_finish = self.item("finish", "child", parent_task_id="parent",
                                 usage={"input": 100, "cached_input": 20, "output": 30,
                                        "reasoning": 10, "source": "agent_report", "kind": "cumulative"})
        ledger.record(self.root, child_finish, "executor")
        rows = ledger.summary(self.root)
        self.assertEqual({row["task_id"] for row in rows}, {"parent", "child"})
        parent = next(row for row in rows if row["task_id"] == "parent")
        child = next(row for row in rows if row["task_id"] == "child")
        self.assertIsNone(parent["usage"]["input"])
        self.assertIsNone(child["usage"]["input"])
        self.assertEqual(child["reported_usage"]["input"], 100)
        self.assertEqual(child["usage"]["kind"], "unknown")
        self.assertIsNone(child["usage"]["delta"]["input"])
        self.assertIsNone(parent["time"]["active_seconds"])
        self.assertEqual(child["category"], "mechanics")

    def test_limit_category_and_parent_validation(self):
        with self.assertRaises(pm.MemoryError):
            ledger.summary(self.root, limit=101)
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, self.item("start", category="other"), "helper")
        with self.assertRaises(pm.MemoryError):
            ledger.record(self.root, self.item("start", "same", parent_task_id="same"), "helper")

    def test_finish_without_start_is_reported_as_incomplete(self):
        ledger.record(self.root, self.item("finish", "orphan"), "executor")
        row = ledger.summary(self.root)[0]
        self.assertEqual(row["status"], "finished_without_start")


if __name__ == "__main__":
    unittest.main()
