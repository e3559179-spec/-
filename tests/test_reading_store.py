"""Persistence tests with synthetic data, isolated from personal reading records."""

from copy import deepcopy
import json
import os
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


class ReadingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reading-store-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "中文 and spaces" / "test-book"
        self.initial = store.initialize(self.directory, "虚构测试材料")

    def proposal(self, state=None, hint="本次续读提示"):
        state = state or store.load(self.directory)
        p, u = deepcopy(state["progress"]), deepcopy(state["understanding"])
        p["recent_session_summary"]["resume_hint"] = hint
        return p, u

    def save(self, pair, state=None):
        state = state or store.load(self.directory)
        return store.save(self.directory, *pair, state["progress"]["save_id"], state["state_token"])

    def cli(self, command, *args):
        run = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "reading_store.py"), command,
                              "--book-dir", str(self.directory), *args],
                             capture_output=True, text=True, encoding="utf-8")
        return run, json.loads(run.stdout)

    def test_round_trip_and_process_independent_resume(self):
        p, u = self.proposal()
        p["book"]["unknown_extension"] = {"kept": True}
        p["sources"] = [{"id": "s1", "kind": "user_text", "locator": "虚构输入"}]
        p["current_source_id"] = "s1"
        p["user_confirmed_read_position"] = {"source_id": "s1", "paragraph_id": "p1"}
        saved = self.save((p, u))
        run, loaded = self.cli("load")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(loaded["progress"], saved["progress"])
        self.assertEqual(loaded["understanding"], saved["understanding"])
        self.assertIsNone(loaded["progress"]["last_explained_position"])
        self.assertEqual(len(store.history(self.directory)["snapshots"]), 2)

    def test_no_reinitialization(self):
        before = store.state_token(self.directory)
        with self.assertRaises(store.StoreError):
            store.initialize(self.directory)
        self.assertEqual(store.state_token(self.directory), before)

    def test_stale_writer_does_not_overwrite(self):
        old = store.load(self.directory)
        self.save(self.proposal(old, "会话 A"), old)
        before = store.state_token(self.directory)
        with self.assertRaises(store.StoreError):
            self.save(self.proposal(old, "会话 B"), old)
        self.assertEqual(store.state_token(self.directory), before)

    def test_manual_edit_detected_and_archived_on_explicit_repair(self):
        path = self.directory / "progress.json"
        raw = path.read_bytes() + b" "
        path.write_bytes(raw)
        state = store.load(self.directory)
        self.assertEqual(state["mirror_state"], "conflict")
        with self.assertRaises(store.StoreError):
            self.save(self.proposal(state), state)
        repaired = store.repair(self.directory, state["state_token"])
        self.assertEqual(repaired["mirror_state"], "consistent")
        self.assertEqual((Path(repaired["archived_files"]) / "progress.json.raw").read_bytes(), raw)

    def test_failure_before_commit_keeps_old_current(self):
        original = store.atomic_write
        def fail_head(path, raw):
            if path.name == ".current.json":
                raise OSError("synthetic pre-commit failure")
            return original(path, raw)
        with patch.object(store, "atomic_write", side_effect=fail_head):
            with self.assertRaises(OSError):
                self.save(self.proposal())
        loaded = store.load(self.directory)
        self.assertEqual(loaded["progress"]["save_id"], self.initial["progress"]["save_id"])
        self.assertEqual(loaded["mirror_state"], "consistent")
        self.assertEqual(len(store.history(self.directory)["snapshots"]), 2)

    def test_failure_between_mirrors_reads_new_snapshot_and_repairs(self):
        original = store.atomic_write
        def fail_second(path, raw):
            if path.name == "understanding.json":
                raise OSError("synthetic interrupted mirror")
            return original(path, raw)
        with patch.object(store, "atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.save(self.proposal(hint="新的已提交内容"))
        loaded = store.load(self.directory)
        self.assertEqual(loaded["mirror_state"], "interrupted")
        self.assertEqual(loaded["progress"]["recent_session_summary"]["resume_hint"], "新的已提交内容")
        fixed = store.repair(self.directory, loaded["state_token"])
        self.assertEqual(fixed["progress"]["save_id"], loaded["progress"]["save_id"])
        self.assertEqual(fixed["mirror_state"], "consistent")

    def test_process_death_after_commit_releases_lock(self):
        code = (
            "import sys,os; sys.path.insert(0,sys.argv[1]); import reading_store as s; "
            "d=sys.argv[2]; st=s.load(d); p=st['progress']; u=st['understanding']; "
            "p['recent_session_summary']['resume_hint']='crash-test'; original=s.atomic_write\n"
            "def abrupt(path,raw):\n"
            " original(path,raw)\n"
            " if path.name=='.current.json': os._exit(17)\n"
            "s.atomic_write=abrupt\n"
            "s.save(d,p,u,st['progress']['save_id'],st['state_token'])\n"
        )
        run = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(SCRIPTS), str(self.directory)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 17, run.stderr)
        state = store.load(self.directory)
        self.assertEqual(state["mirror_state"], "interrupted")
        self.assertEqual(state["progress"]["recent_session_summary"]["resume_hint"], "crash-test")
        self.assertEqual(store.repair(self.directory, state["state_token"])["mirror_state"], "consistent")

    def test_other_process_is_excluded_by_lock(self):
        with store.locked(self.directory):
            run, result = self.cli("load")
            self.assertEqual(run.returncode, 1)
            self.assertEqual(result["code"], "busy")
        run, _ = self.cli("load")
        self.assertEqual(run.returncode, 0)

    def test_corrupted_head_can_restore_selected_snapshot(self):
        self.save(self.proposal())
        (self.directory / ".current.json").write_bytes(b"{")
        with self.assertRaises(ValueError):
            store.load(self.directory)
        info = store.history(self.directory)
        self.assertIsNotNone(info["head_error"])
        restored = store.restore(self.directory, self.initial["progress"]["save_id"], info["state_token"], "测试选定旧快照")
        self.assertNotEqual(restored["progress"]["save_id"], self.initial["progress"]["save_id"])
        self.assertEqual(restored["progress"]["previous_save_id"], self.initial["progress"]["save_id"])
        self.assertEqual(restored["progress"]["progress_history"][-1]["field"], "storage_recovery")
        self.assertEqual((Path(restored["archived_files"]) / ".current.json.raw").read_bytes(), b"{")

    def test_snapshot_corruption_is_not_silently_accepted(self):
        current = self.save(self.proposal())
        folder = store.snapshot_dir(self.directory, current["progress"]["save_id"])
        (folder / "progress.json").write_bytes(b"{}")
        with self.assertRaises(store.StoreError):
            store.load(self.directory)
        info = store.history(self.directory)
        self.assertEqual(sum(not s["valid"] for s in info["snapshots"]), 1)
        restored = store.restore(self.directory, self.initial["progress"]["save_id"], info["state_token"], "损坏恢复测试")
        self.assertEqual(restored["mirror_state"], "consistent")

    def test_missing_mirror_is_recoverable(self):
        (self.directory / "progress.json").unlink()
        loaded = store.load(self.directory)
        self.assertEqual(loaded["mirror_state"], "interrupted")
        self.assertEqual(store.repair(self.directory, loaded["state_token"])["mirror_state"], "consistent")

    def test_repair_token_prevents_new_manual_edit_loss(self):
        path = self.directory / "progress.json"
        path.write_bytes(b"first edit")
        loaded = store.load(self.directory)
        path.write_bytes(b"second edit")
        with self.assertRaises(store.StoreError):
            store.repair(self.directory, loaded["state_token"])
        self.assertEqual(path.read_bytes(), b"second edit")

    def test_legacy_import_preserves_values_and_original_bytes(self):
        legacy = Path(self.temp.name) / "legacy-book"
        legacy.mkdir()
        pair = [deepcopy(self.initial[n]) for n in ("progress", "understanding")]
        for value, name in zip(pair, store.NAMES):
            value["book_id"] = legacy.name
            (legacy / name).write_bytes(store.encode(value))
        loaded = store.load(legacy)
        self.assertEqual(loaded["storage"], "legacy")
        imported = store.import_legacy(legacy, loaded["state_token"])
        self.assertEqual(imported["progress"], pair[0])
        self.assertEqual(imported["understanding"], pair[1])
        self.assertEqual(len(list((legacy / ".repairs").iterdir())), 1)

    def test_invalid_pair_and_references_leave_current_untouched(self):
        baseline = store.state_token(self.directory)
        for change in ("book", "save", "source", "record", "schema"):
            p, u = self.proposal()
            if change == "book":
                p["book_id"] = u["book_id"] = "different-edition"
            elif change == "save":
                u["save_id"] = "different"
            elif change == "source":
                p["current_source_id"] = "missing"
            elif change == "record":
                p["recent_session_summary"]["key_record_ids"] = ["missing"]
            else:
                p["schema_version"] = u["schema_version"] = 2
            with self.subTest(change=change), self.assertRaises(store.StoreError):
                self.save((p, u))
            self.assertEqual(store.state_token(self.directory), baseline)

    def test_no_deletion_of_existing_records_or_history(self):
        p, u = self.proposal()
        u["records"] = [{"id": "r1", "knowledge_point": "虚构测试点", "current_status": "待解决",
            "check_applicability": "适用", "checks": [], "history": [{"id": "e1", "basis": "虚构事件"}],
            "explanations": [], "understanding_changes": [], "question_verbatim": "虚构问题"}]
        saved = self.save((p, u))
        for action in ("delete", "history", "question", "status"):
            pair = self.proposal(saved)
            if action == "delete":
                pair[1]["records"] = []
            elif action == "history":
                pair[1]["records"][0]["history"] = []
            elif action == "question":
                pair[1]["records"][0]["question_verbatim"] = "改写"
            else:
                pair[1]["records"][0]["current_status"] = "已解释待检验"
            with self.subTest(action=action), self.assertRaises(store.StoreError):
                self.save(pair, saved)

    def test_unknown_top_level_fields_cannot_be_omitted(self):
        p, u = self.proposal()
        p["custom_extension"] = {"information": "kept"}
        saved = self.save((p, u))
        pair = self.proposal(saved)
        del pair[0]["custom_extension"]
        with self.assertRaises(store.StoreError):
            self.save(pair, saved)

    def test_malformed_nested_history_is_rejected(self):
        p, u = self.proposal()
        u["records"] = [{"id": "r1", "knowledge_point": "虚构测试点", "current_status": "待解决",
                         "check_applicability": "适用", "checks": [], "history": None}]
        before = store.state_token(self.directory)
        with self.assertRaises(store.StoreError):
            self.save((p, u))
        self.assertEqual(store.state_token(self.directory), before)

    def test_pending_check_can_be_completed_without_rewriting_question(self):
        p, u = self.proposal()
        u["records"] = [{"id": "r1", "knowledge_point": "虚构测试点", "current_status": "已解释待检验",
            "check_applicability": "适用", "status_check_ids": [], "history": [],
            "question_verbatim": None, "understanding_at_time": None,
            "checks": [{"id": "c1", "kind": "提问检查", "target": "目标关系",
                        "question": "解释此处的条件", "result": "待回答", "user_answer": None,
                        "validity": "有效", "support": "无本轮定向提示"}]}]
        saved = self.save((p, u))
        p, u = self.proposal(saved)
        rec = u["records"][0]
        rec["checks"][0].update(user_answer="虚构但完整的回答", result="通过", feedback="对应本题关系",
                                evidence=[{"location": {"paragraph_id": "test-p1"}, "paraphrase": "虚构依据"}])
        rec.update(current_status="已通过理解检查", status_check_ids=["c1"])
        rec["history"].append({"id": "e1", "basis": "本题实际回答及评价"})
        finished = self.save((p, u), saved)
        self.assertEqual(finished["understanding"]["records"][0]["current_status"], "已通过理解检查")
        p, u = self.proposal(finished)
        u["records"][0]["checks"][0]["question"] = "换一道题"
        with self.assertRaises(store.StoreError):
            self.save((p, u), finished)

    def test_store_inside_skill_is_rejected_before_writing(self):
        path = store.SKILL / "test-data-should-not-exist"
        with self.assertRaises(store.StoreError):
            store.initialize(path)
        self.assertFalse(path.exists())

    def test_snapshot_path_traversal_is_rejected(self):
        with self.assertRaises(store.StoreError):
            store.read_snapshot(self.directory, "../../other")

    def test_cli_save_and_bad_json_do_not_use_chat_memory(self):
        p, u = self.proposal(hint="跨进程续读摘要")
        ppath, upath = Path(self.temp.name)/"进度 input.json", Path(self.temp.name)/"理解 input.json"
        ppath.write_bytes(store.encode(p))
        upath.write_bytes(store.encode(u))
        before_inputs = (ppath.read_bytes(), upath.read_bytes())
        run, result = self.cli("save", "--progress-input", str(ppath), "--understanding-input", str(upath),
                               "--expected-save-id", self.initial["progress"]["save_id"],
                               "--expected-token", self.initial["state_token"])
        self.assertEqual(run.returncode, 0, result)
        _, resumed = self.cli("load")
        self.assertEqual(resumed["progress"]["recent_session_summary"]["resume_hint"], "跨进程续读摘要")
        self.assertEqual((ppath.read_bytes(), upath.read_bytes()), before_inputs)
        ppath.write_bytes(b'{"x":1,"x":2}')
        stable = store.state_token(self.directory)
        run, result = self.cli("save", "--progress-input", str(ppath), "--understanding-input", str(upath),
                               "--expected-save-id", resumed["progress"]["save_id"], "--expected-token", resumed["state_token"])
        self.assertEqual(run.returncode, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(store.state_token(self.directory), stable)


if __name__ == "__main__":
    unittest.main()
