"""Synthetic report evidence and publication tests; no real reader records."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/classic-reading-companion/scripts"
sys.path.insert(0, str(SCRIPTS))
import reading_store as store
import review_document as review


class ReviewDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review-document-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.book = Path(self.temp.name) / "中文 and spaces" / "test-book"
        store.initialize(self.book, "虚构测试材料")
        self.content = Path(self.temp.name) / "文稿 with spaces.md"
        self.content.write_text("# 虚构测试文稿\n\n这只测试封存流程，不是原著总结。\n", encoding="utf-8")

    def update(self, p, u, state):
        return store.save(self.book, p, u, state["progress"]["save_id"], state["state_token"])

    def record(self, record_id, chapter):
        return {"id": record_id, "knowledge_point": "虚构知识点", "location": {"chapter": chapter},
                "current_status": "已解释待检验", "check_applicability": "适用", "status_check_ids": [],
                "question_verbatim": None, "understanding_at_time": None, "checks": [], "history": []}

    def test_empty_records_remain_empty_and_draft_is_not_final(self):
        before = store.load(self.book)
        result = review.prepare(self.book, "book")
        packet = store.parse(Path(result["packet_path"]).read_bytes())
        self.assertEqual(result["status"], "draft")
        self.assertEqual(packet["understanding"]["records"], [])
        self.assertEqual(packet["progress"]["coverage"], [])
        self.assertEqual(packet["selection"]["record_ids"], [])
        self.assertIn(review.MARKER, Path(result["draft_path"]).read_text("utf-8"))
        self.assertEqual(store.load(self.book), before)

    def test_chapter_selection_retains_unknown_and_cross_chapter_ranges(self):
        state = store.load(self.book)
        p, u = deepcopy(state["progress"]), deepcopy(state["understanding"])
        u["records"] = [self.record("r1", "第一章"), self.record("r2", "第二章"), self.record("r3", None)]
        p["coverage"] = [
            {"range": {"start_location": {"chapter": "第一章"}, "end_location": None}},
            {"range": {"start_location": {"chapter": "第一章"}, "end_location": {"chapter": "第三章"}}},
            {"range": {"start_location": {"chapter": "第二章"}, "end_location": None}},
            {"range": "用户只声明全书读完"},
        ]
        self.update(p, u, state)
        result = review.prepare(self.book, "chapter", "第一章")
        scope = result["selection"]
        self.assertEqual(scope["record_ids"], ["r1"])
        self.assertEqual(scope["ambiguous_record_ids"], ["r3"])
        self.assertEqual(scope["excluded_record_ids"], ["r2"])
        self.assertEqual(scope["coverage_indices"], [0])
        self.assertEqual(scope["ambiguous_coverage_indices"], [1, 3])
        packet = store.parse(Path(result["packet_path"]).read_bytes())
        self.assertEqual(len(packet["understanding"]["records"]), 3)

    def test_unknown_chapter_does_not_fall_back_to_whole_book(self):
        state = store.load(self.book)
        p, u = deepcopy(state["progress"]), deepcopy(state["understanding"])
        u["records"] = [self.record("r1", "第一章")]
        self.update(p, u, state)
        result = review.prepare(self.book, "chapter", "不存在的已知标记")
        self.assertEqual(result["selection"]["record_ids"], [])
        self.assertEqual(result["selection"]["excluded_record_ids"], ["r1"])

    def test_kind_and_chapter_must_be_unambiguous(self):
        for kind, chapter in (("chapter", None), ("book", "第一章"), ("invalid", None)):
            with self.subTest(kind=kind), self.assertRaises(store.StoreError):
                review.prepare(self.book, kind, chapter)

    def test_authorship_and_withdrawn_history_are_not_rewritten(self):
        state = store.load(self.book)
        p, u = deepcopy(state["progress"]), deepcopy(state["understanding"])
        record = self.record("r1", "第一章")
        record["understanding_at_time"] = "用户的首次实际表达（虚构测试）"
        record["checks"] = [{"id": "c1", "kind": "提问检查", "target": "虚构目标",
                             "question": "由助手发起", "user_answer": None, "feedback": None,
                             "result": "通过", "validity": "已撤回", "support": "不明", "evidence": []}]
        record["history"] = [{"id": "e1", "kind": "assistant_correction", "basis": "旧评价有误"}]
        u["records"] = [record]
        self.update(p, u, state)
        result = review.prepare(self.book, "book")
        packet = store.parse(Path(result["packet_path"]).read_bytes())
        self.assertEqual(packet["understanding"]["records"][0], record)
        self.assertIsNone(packet["understanding"]["records"][0]["question_verbatim"])

    def test_finalization_writes_hash_manifest_without_state_changes(self):
        prepared = review.prepare(self.book, "book")
        before = store.load(self.book)
        result = review.finalize(self.book, prepared["packet_path"], self.content)
        manifest = store.parse(Path(result["manifest_path"]).read_bytes())
        self.assertEqual(result["status"], "written")
        self.assertEqual(manifest["basis_save_id"], before["progress"]["save_id"])
        self.assertEqual(Path(result["report_path"]).read_text("utf-8"), self.content.read_text("utf-8"))
        for name, expected in manifest["hashes"].items():
            self.assertEqual(store.digest((Path(result["report_path"]).parent / name).read_bytes()), expected)
        self.assertEqual(store.load(self.book), before)

    def test_empty_or_unwritten_template_cannot_be_sealed(self):
        prepared = review.prepare(self.book, "book")
        with self.assertRaises(store.StoreError):
            review.finalize(self.book, prepared["packet_path"], prepared["draft_path"])
        self.content.write_text(" \n", encoding="utf-8")
        with self.assertRaises(store.StoreError):
            review.finalize(self.book, prepared["packet_path"], self.content)

    def test_stale_basis_rejected_without_new_final_folder(self):
        prepared = review.prepare(self.book, "book")
        state = store.load(self.book)
        p, u = deepcopy(state["progress"]), deepcopy(state["understanding"])
        p["recent_session_summary"]["resume_hint"] = "新的实际变化"
        self.update(p, u, state)
        before = set((self.book / "reports").iterdir())
        with self.assertRaises(store.StoreError):
            review.finalize(self.book, prepared["packet_path"], self.content)
        self.assertEqual(set((self.book / "reports").iterdir()), before)

    def test_modified_packet_or_scope_rejected(self):
        prepared = review.prepare(self.book, "book")
        path = Path(prepared["packet_path"])
        original = store.parse(path.read_bytes())
        for field in ("progress", "selection", "basis_hashes", "understanding"):
            packet = deepcopy(original)
            packet[field] = {}
            path.write_bytes(store.encode(packet))
            with self.subTest(field=field), self.assertRaises(store.StoreError):
                review.finalize(self.book, path, self.content)

    def test_manual_mirror_conflict_blocks_reports(self):
        prepared = review.prepare(self.book, "book")
        path = self.book / "progress.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(store.StoreError):
            review.prepare(self.book, "book")
        with self.assertRaises(store.StoreError):
            review.finalize(self.book, prepared["packet_path"], self.content)

    def test_other_book_packet_is_rejected(self):
        prepared = review.prepare(self.book, "book")
        other = Path(self.temp.name) / "other-book"
        store.initialize(other)
        with self.assertRaises(store.StoreError):
            review.finalize(other, prepared["packet_path"], self.content)

    def test_repeat_finalization_does_not_overwrite(self):
        prepared = review.prepare(self.book, "chapter", "第一章")
        first = review.finalize(self.book, prepared["packet_path"], self.content)
        old = Path(first["report_path"]).read_bytes()
        self.content.write_text("# 第二份虚构测试文稿\n", encoding="utf-8")
        second = review.finalize(self.book, prepared["packet_path"], self.content)
        self.assertNotEqual(first["report_path"], second["report_path"])
        self.assertEqual(Path(first["report_path"]).read_bytes(), old)

    def test_write_failure_has_no_completion_manifest_or_state_change(self):
        prepared = review.prepare(self.book, "book")
        before = store.load(self.book)
        original = store.write_sync
        def fail_manifest(path, raw):
            if path.name == "manifest.json":
                raise OSError("synthetic final manifest failure")
            original(path, raw)
        with patch.object(store, "write_sync", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                review.finalize(self.book, prepared["packet_path"], self.content)
        finals = [p for p in (self.book / "reports").iterdir() if not p.name.startswith("draft-")]
        self.assertEqual(len(finals), 1)
        self.assertFalse((finals[0] / "manifest.json").exists())
        self.assertEqual(store.load(self.book), before)

    def test_cli_unicode_paths_and_input_files_are_preserved(self):
        command = [sys.executable, "-X", "utf8", str(SCRIPTS / "review_document.py")]
        run = subprocess.run([*command, "prepare", "--book-dir", str(self.book), "--kind", "book"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        prepared = json.loads(run.stdout)
        packet_path = Path(prepared["packet_path"])
        before = (packet_path.read_bytes(), self.content.read_bytes())
        run = subprocess.run([*command, "finalize", "--book-dir", str(self.book),
                              "--packet", str(packet_path), "--content", str(self.content)],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["ok"])
        self.assertEqual((packet_path.read_bytes(), self.content.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
