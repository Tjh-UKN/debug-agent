"""Behavioral tests for durable state and collaboration, no device experiments."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import case


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "中文案例"
        case.execute(self.root, "init", {"title": "精度", "goal": "定位", "symptom": "输出偏差", "acceptance": "证据链或修复验证"})

    def tearDown(self):
        self.temp.cleanup()

    def show(self):
        return case.execute(self.root, "show", history=True)

    def put(self, kind, value):
        return case.execute(self.root, "put", value, kind)["record"]

    def evidence(self, eid="E1", validity="valid"):
        return {"id": eid, "rev": 0, "observation": "原表现保留", "source": "fixture.log:2", "context": "模拟场景，非真实设备实验", "limits": "仅合成测试", "validity": validity}

    def hypothesis(self, hid="H1"):
        return {"id": hid, "rev": 0, "claim": "原因 A", "basis": "源码分支", "prediction": "局部修改应改变结果", "reason": "可核查", "status": "open"}

    def task(self, tid="T1", **extra):
        return {"id": tid, "rev": 0, "question": "核查 A", "action": "对照", "acceptance": "提供结果及有效性", "owner": "worker", "reason": "区分原因", "status": "pending", **extra}

    def running(self, tid="T1"):
        task = self.put("task", self.task(tid))
        task.update(status="running", run={"job_id": "job-123", "host": "fixture-host", "command": "fixture-command"})
        return self.put("task", task)

    def test_init_never_overwrites(self):
        before = (self.root / "state.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            case.execute(self.root, "init", {})
        self.assertEqual(before, (self.root / "state.json").read_bytes())

    def test_stale_writer_rejected(self):
        first = self.put("hypothesis", self.hypothesis())
        newer = copy.deepcopy(first)
        newer["reason"] = "新增证据前先复核"
        self.put("hypothesis", newer)
        with self.assertRaisesRegex(ValueError, "revision conflict"):
            self.put("hypothesis", first)
        self.assertEqual(self.show()["hypothesis"]["H1"]["reason"], newer["reason"])

    def test_evidence_immutable_and_invalid_not_support(self):
        record = self.put("evidence", self.evidence(validity="invalid"))
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.put("evidence", record)
        hypothesis = self.hypothesis()
        hypothesis.update(status="confirmed", evidence=["E1"])
        with self.assertRaisesRegex(ValueError, "valid evidence"):
            self.put("hypothesis", hypothesis)

    def test_task_completion_not_hypothesis_confirmation(self):
        self.put("hypothesis", self.hypothesis())
        task = self.running()
        submitted = case.execute(self.root, "submit", {"task_id": "T1", "rev": task["rev"], "new_evidence": [self.evidence()], "result": {"outcome": "inconclusive", "summary": "未区分候选原因", "limitations": "需其他核查", "evidence": ["E1"]}})["record"]
        self.assertEqual(submitted["status"], "submitted")
        case.execute(self.root, "accept", {"task_id": "T1", "rev": submitted["rev"], "reason": "核查完成但未决"})
        state = self.show()
        self.assertEqual(state["task"]["T1"]["status"], "done")
        self.assertEqual(state["hypothesis"]["H1"]["status"], "open")

    def test_failed_submission_rolls_back_new_evidence(self):
        task = self.running()
        before = self.show()
        with self.assertRaisesRegex(ValueError, "outcome"):
            case.execute(self.root, "submit", {"task_id": "T1", "rev": task["rev"], "new_evidence": [self.evidence()], "result": {"summary": "x", "limitations": "x", "outcome": "bad"}})
        self.assertEqual(self.show(), before)

    def test_cycles_and_dependencies(self):
        first = self.put("task", self.task())
        second = self.put("task", self.task("T2", depends_on=["T1"]))
        second["status"] = "running"
        with self.assertRaisesRegex(ValueError, "dependencies"):
            self.put("task", second)
        first["depends_on"] = ["T2"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.put("task", first)
        h1 = self.put("hypothesis", self.hypothesis())
        self.put("hypothesis", {**self.hypothesis("H2"), "parents": ["H1"]})
        h1["parents"] = ["H2"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.put("hypothesis", h1)

    def test_small_scene_closure_and_reopen_history(self):
        self.put("evidence", self.evidence())
        self.put("scenario", {"id": "S64", "rev": 0, "description": "64 卡", "changes": "减少规模", "cost": "低", "reason": "表现一致", "reproduction": "retained", "evidence": ["E1"]})
        self.put("checkpoint", {"id": "current", "rev": 0, "summary": "小场景闭环", "next_action": "交付", "reason": "足够证据", "environment": "fixture", "baseline": "S64"})
        closure = {"rev": self.show()["rev"], "outcome": "root_cause", "route": "evidence_chain", "conclusion": "原因 A", "scope": "64 卡", "limitations": "4096 卡无权限", "acceptance_check": "证据链满足定位要求", "evidence": ["E1"]}
        case.execute(self.root, "close", closure)
        self.assertEqual(self.show()["status"], "closed")
        with self.assertRaisesRegex(ValueError, "case closed"):
            self.put("hypothesis", self.hypothesis())
        case.execute(self.root, "reopen", {"rev": self.show()["rev"], "reason": "新证据需回溯"})
        self.assertEqual(self.show()["status"], "active")
        self.assertTrue(any(e["command"] == "close" for e in self.show()["history"]))

    def test_unknown_refs_and_unproven_baseline(self):
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            self.put("hypothesis", {**self.hypothesis(), "evidence": ["missing"]})
        self.put("scenario", {"id": "S16", "rev": 0, "description": "16 卡", "changes": "减卡", "cost": "低", "reason": "阴性结果", "reproduction": "not_observed"})
        with self.assertRaisesRegex(ValueError, "baseline"):
            self.put("checkpoint", {"id": "current", "rev": 0, "summary": "未复现", "next_action": "回查", "reason": "未决", "environment": "fixture", "baseline": "S16"})

    def test_atomic_failure_preserves_old_state(self):
        before = (self.root / "state.json").read_bytes()
        with patch.object(case.os, "replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                self.put("hypothesis", self.hypothesis())
        self.assertEqual(before, (self.root / "state.json").read_bytes())
        self.assertEqual(list(self.root.glob(".state-*.tmp")), [])

    def test_running_job_restored_and_blocks_closure(self):
        self.running()
        script = str(Path(case.__file__).resolve())
        completed = subprocess.run([sys.executable, script, "--case", str(self.root), "show"], capture_output=True, encoding="utf-8", check=True)
        state = json.loads(completed.stdout)
        self.assertEqual(state["task"]["T1"]["run"]["job_id"], "job-123")
        with self.assertRaisesRegex(ValueError, "running/submitted"):
            case.execute(self.root, "close", {"rev": state["rev"], "outcome": "blocked", "conclusion": "等待", "scope": "fixture", "limitations": "未结束"})

    def test_process_lock_rejects_other_writer_then_releases(self):
        script = str(Path(case.__file__).resolve())
        payload = self.root / "payload.json"
        payload.write_text(json.dumps(self.evidence()), encoding="utf-8")
        args = [sys.executable, script, "--case", str(self.root), "put", "--kind", "evidence", "--file", str(payload)]
        with case.locked(self.root):
            busy = subprocess.run(args, capture_output=True, encoding="utf-8")
            self.assertEqual(busy.returncode, 2)
            self.assertIn("case busy", busy.stderr)
            self.assertEqual(case.execute(self.root, "show")["rev"], 0)
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)

    def test_read_only_show_does_not_create_lock(self):
        (self.root / ".lock").unlink()
        before = (self.root / "state.json").read_bytes()
        case.execute(self.root, "show")
        self.assertFalse((self.root / ".lock").exists())
        self.assertEqual(before, (self.root / "state.json").read_bytes())

    def test_no_direct_task_done(self):
        task = self.running()
        task["status"] = "done"
        with self.assertRaisesRegex(ValueError, "submit/accept"):
            self.put("task", task)


if __name__ == "__main__":
    unittest.main(verbosity=2)
