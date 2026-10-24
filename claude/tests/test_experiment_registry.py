import sys
from pathlib import Path as _StagePath
sys.path.insert(0, str(_StagePath(__file__).resolve().parents[1]))
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import experiment_registry as registry


class ExperimentRegistryTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[1]
        self.temp = tempfile.TemporaryDirectory(dir=workspace)
        self.root = Path(self.temp.name)
        (self.root / "results").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_import_is_idempotent_and_does_not_infer_success_from_report(self):
        directory = self.root / "results" / "successful-looking-experiment"
        directory.mkdir()
        (directory / "REPORT.md").write_text("success completed accepted", encoding="utf-8")
        (directory / "notes.txt").write_text("must remain unparsed", encoding="utf-8")
        first = registry.import_legacy_results(self.root)
        second = registry.import_legacy_results(self.root)
        events = registry.read_events(self.root)
        self.assertEqual(first["added"], 1)
        self.assertEqual(second["added"], 0)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_type"], "legacy_import")
        self.assertEqual(event["machine_facts"]["legacy_status"], "legacy_unindexed")
        self.assertFalse(event["provenance"]["report_prose_read"])
        self.assertIsNone(event.get("semantic_verdict"))
        self.assertIn("scientific_verdict", event["machine_facts"]["unknown_fields"])

    def test_machine_metadata_is_allowlisted_and_unknown_science_remains_unknown(self):
        directory = self.root / "results" / "partial-run"
        directory.mkdir()
        (directory / "STATUS.json").write_text(json.dumps({
            "status": "stopped", "completed_attempts": 2, "scientific_success": True,
            "private_payload": "do not copy",
        }), encoding="utf-8")
        registry.import_legacy_results(self.root)
        event = registry.read_events(self.root)[0]
        self.assertEqual(event["machine_facts"]["legacy_status"], "stopped")
        imported = event["machine_facts"]["machine_metadata"]["STATUS.json"]
        self.assertEqual(imported, {"status": "stopped", "completed_attempts": 2})
        self.assertIn("scientific_verdict", event["machine_facts"]["unknown_fields"])

    def test_malformed_existing_event_fails_closed_without_appending(self):
        target = registry._registry_path(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"schema_version": 1}\n', encoding="utf-8")
        with self.assertRaisesRegex(registry.RegistryError, "invalid evidence envelope"):
            registry.append_event(self.root, {"anything": "else"})
        self.assertEqual(target.read_text(encoding="utf-8"), '{"schema_version": 1}\n')

    def test_source_existence_and_hash_are_checked_on_append(self):
        source = self.root / "results" / "protocol.json"
        source.write_text('{"frozen": true}', encoding="utf-8")
        event = registry.build_event(
            "exp-one", "protocol_frozen", source_paths=[source],
            provenance={"actor": "test", "method": "manual"},
            machine_facts={"protocol_sha256": registry.make_source_ref(self.root, source)["sha256"]},
            root=self.root,
        )
        source.write_text('{"frozen": false}', encoding="utf-8")
        with self.assertRaisesRegex(registry.RegistryError, "hash changed"):
            registry.append_event(self.root, event)
        self.assertEqual(registry.read_events(self.root), [])

    def test_exact_and_similar_queries_surface_unknowns_and_warn_about_duplicates(self):
        directory = self.root / "results" / "quarterly-contract-case"
        directory.mkdir()
        (directory / "STATUS.json").write_text('{"status":"stopped"}', encoding="utf-8")
        registry.import_legacy_results(self.root)
        exact = registry.query_events(self.root, "results/quarterly-contract-case")
        similar = registry.query_events(self.root, "contract case")
        self.assertEqual(exact["matches"][0]["match_kind"], "exact")
        self.assertTrue(similar["matches"])
        found = similar["matches"][0]["event"]
        self.assertIn("duplicate_identity", found["machine_facts"]["unknown_fields"])
        self.assertIn("no guarantee", similar["duplicate_detection"])

    def test_known_question_and_contract_terms_are_searchable_without_report_text(self):
        directory = self.root / "results" / "case-17"
        directory.mkdir()
        (directory / "QUESTION_FREEZE.json").write_text(json.dumps({
            "question": "Which header contract applies?", "contract_id": "header-v2",
        }), encoding="utf-8")
        (directory / "REPORT.md").write_text("contract-only-report-marker", encoding="utf-8")
        registry.import_legacy_results(self.root)
        question_result = registry.query_events(self.root, "header contract")
        report_only_result = registry.query_events(self.root, "contract-only-report-marker")
        self.assertTrue(question_result["matches"])
        self.assertEqual(report_only_result["matches"], [])

    def test_stopped_and_truncated_are_distinct_append_only_events(self):
        for exp_id, event_type in (("exp-stopped", "stopped"), ("exp-truncated", "truncated")):
            event = registry.build_event(
                exp_id, event_type,
                provenance={"actor": "test", "method": "explicit_record"},
                machine_facts={"reason": "test fixture"}, root=self.root,
            )
            registry.append_event(self.root, event)
        events = registry.read_events(self.root)
        self.assertEqual([e["event_type"] for e in events], ["stopped", "truncated"])
        self.assertEqual(len({e["event_id"] for e in events}), 2)

    def test_semantic_verdict_is_separate_from_machine_facts(self):
        event = registry.build_event(
            "exp-accepted", "acceptance",
            provenance={"actor": "human", "method": "explicit_review"},
            semantic_verdict={"accepted": True, "basis": "review"}, root=self.root,
        )
        registry.append_event(self.root, event)
        saved = registry.read_events(self.root)[0]
        self.assertIn("semantic_verdict", saved)
        self.assertNotIn("machine_facts", saved)


if __name__ == "__main__":
    unittest.main()
