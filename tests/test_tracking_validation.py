"""Synthetic fixtures only: not quotations or real reading records."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/classic-reading-companion/scripts/validate_tracking.py"
SPEC = importlib.util.spec_from_file_location("tracking_validation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    return {
        "schema_version": 1, "book_id": "synthetic-test",
        "records": [{
            "id": "r1", "knowledge_point": "区分必要与充分条件",
            "current_status": "已通过理解检查", "check_applicability": "适用",
            "status_check_ids": ["c1"],
            "checks": [{
                "id": "c1", "kind": "提问检查", "target": "必要条件",
                "question": "满足该条件是否就保证结果？",
                "user_answer": "不保证，它只限定必要条件。",
                "feedback": "本题关系表述准确。",
                "evidence": [{"location": {"paragraph_id": "test-p1"},
                              "paraphrase": "原文仅设置必要条件。"}],
                "result": "通过", "validity": "有效",
                "support": "无本轮定向提示", "supersedes_check_id": None,
            }],
        }],
    }


class TrackingValidationTests(unittest.TestCase):
    def test_empty_template(self):
        path = ROOT / "skills/classic-reading-companion/assets/understanding.template.json"
        self.assertEqual(MODULE.validate(json.loads(path.read_text("utf-8")))["errors"], [])

    def test_supported_pass_and_no_mutation(self):
        data = fixture()
        before = copy.deepcopy(data)
        self.assertEqual(MODULE.validate(data), {"errors": [], "warnings": []})
        self.assertEqual(data, before)

    def test_no_answer_cannot_pass(self):
        data = fixture()
        data["records"][0]["checks"][0]["user_answer"] = None
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_empty_evidence_objects_cannot_pass(self):
        data = fixture()
        data["records"][0]["checks"][0]["evidence"] = [{"location": {}, "quote": None}]
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_source_id_only_is_not_a_passage(self):
        data = fixture()
        data["records"][0]["checks"][0]["evidence"][0]["location"] = {"source_id": "s1"}
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_negative_rating_also_requires_evidence(self):
        data = fixture()
        record = data["records"][0]
        record.update(current_status="待解决", status_check_ids=[])
        record["checks"][0].update(result="需修正", evidence=[])
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_withdrawn_check_cannot_support_current_pass(self):
        for validity in ("已撤回", "待复核"):
            with self.subTest(validity=validity):
                data = fixture()
                data["records"][0]["checks"][0]["validity"] = validity
                self.assertTrue(MODULE.validate(data)["errors"])

    def test_withdrawn_bad_history_can_be_preserved(self):
        data = fixture()
        record = data["records"][0]
        record.update(current_status="已解释待检验", status_check_ids=[])
        record["checks"][0].update(validity="已撤回", user_answer=None)
        report = MODULE.validate(data)
        self.assertFalse(report["errors"])
        self.assertTrue(report["warnings"])

    def test_skip_does_not_erase_prior_valid_pass(self):
        data = fixture()
        skipped = copy.deepcopy(data["records"][0]["checks"][0])
        skipped.update(id="c2", result="已跳过", user_answer=None, feedback=None, evidence=[])
        data["records"][0]["checks"].append(skipped)
        self.assertFalse(MODULE.validate(data)["errors"])

    def test_spontaneous_expression_needs_no_invented_question(self):
        data = fixture()
        data["records"][0]["checks"][0].update(kind="表达评估", question=None, asked_at=None)
        self.assertFalse(MODULE.validate(data)["errors"])

    def test_pending_cannot_support_pass(self):
        data = fixture()
        data["records"][0]["checks"][0].update(result="待回答", user_answer=None)
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_not_applicable_discussion(self):
        data = fixture()
        data["records"][0].update(current_status=None, check_applicability="不适用",
                                  status_check_ids=[], checks=[])
        self.assertFalse(MODULE.validate(data)["errors"])

    def test_cross_record_reference_fails(self):
        data = fixture()
        second = copy.deepcopy(data["records"][0])
        second.update(id="r2", checks=[])
        data["records"].append(second)
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_explicit_null_reference_list_is_not_legacy_absence(self):
        data = fixture()
        data["records"][0]["status_check_ids"] = None
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_duplicate_check_id_fails(self):
        data = fixture()
        data["records"][0]["checks"] *= 2
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_reassessment_links_to_earlier_check(self):
        data = fixture()
        record = data["records"][0]
        revised = copy.deepcopy(record["checks"][0])
        revised.update(id="c2", supersedes_check_id="c1")
        record["checks"][0]["validity"] = "已撤回"
        record["checks"].append(revised)
        record["status_check_ids"] = ["c2"]
        self.assertFalse(MODULE.validate(data)["errors"])
        revised["supersedes_check_id"] = "c2"
        self.assertTrue(MODULE.validate(data)["errors"])

    def test_legacy_warns_without_fabricating_fields(self):
        data = fixture()
        record = data["records"][0]
        del record["status_check_ids"]
        for key in ("kind", "target", "support", "validity"):
            del record["checks"][0][key]
        before = copy.deepcopy(data)
        report = MODULE.validate(data)
        self.assertFalse(report["errors"])
        self.assertTrue(report["warnings"])
        self.assertEqual(data, before)

    def test_malformed_shapes_return_errors(self):
        for data in ([], {"schema_version": True, "records": []},
                     {"schema_version": 1, "records": {}},
                     {"schema_version": 1, "book_id": "test", "records": [None]}):
            with self.subTest(data=data):
                self.assertTrue(MODULE.validate(data)["errors"])
        for field in ("current_status", "check_applicability", "status_check_ids"):
            data = fixture()
            data["records"][0][field] = {"invalid": []}
            self.assertTrue(MODULE.validate(data)["errors"])

    def test_cli_exit_codes_and_read_only(self):
        # Isolated temporary directory; never writes user reading-data.
        with tempfile.TemporaryDirectory(prefix="tracking-validation-", dir=ROOT) as tmp:
            path = Path(tmp) / "记录 with spaces.json"
            for data, code in ((fixture(), 0), ({"schema_version": 1, "records": {}}, 1)):
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                before = path.read_bytes()
                run = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), str(path), "--json"],
                                     capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(run.returncode, code, run.stderr)
                self.assertIn("errors", json.loads(run.stdout))
                self.assertEqual(path.read_bytes(), before)
            path.write_text("{", encoding="utf-8")
            run = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), str(path), "--json"],
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertTrue(json.loads(run.stdout)["errors"])
            missing = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), str(Path(tmp)/"missing.json"), "--json"],
                                     capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(missing.returncode, 2, missing.stderr)


if __name__ == "__main__":
    unittest.main()
