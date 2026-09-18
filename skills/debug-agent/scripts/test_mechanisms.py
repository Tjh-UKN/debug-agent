"""Regression checks for evidence scope, handoffs and correction propagation."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

import case
from materials import inventory
from panel import render
from recovery import snapshot


class MechanismTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "data.tgz"
        with tarfile.open(self.archive, "w:gz") as bundle:
            for rank in range(3):
                data = json.dumps({"value": rank + 1}).encode()
                member = tarfile.TarInfo(f"step2/rank{rank}/dump.json")
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))
        self.directory = self.root / "case"
        case.execute(self.directory, "init", {"title": "合成案例", "goal": "解释分区差异",
                     "symptom": "全局输出异常", "acceptance": "有范围的证据链", "materials": [str(self.archive)]})

    def state(self):
        return case.execute(self.directory, "show", history=True)

    def put(self, kind, record):
        return case.execute(self.directory, "put", record, kind)["record"]

    def evidence(self, eid="E1", **extra):
        return {"id": eid, "rev": 0, "observation": "合成观察", "source": str(self.archive),
                "scope": "仅分区0的value字段", "context": "模拟数据", "limits": "不外推其他分区",
                "validity": "valid", **extra}

    def review(self, eid="E1", **extra):
        return {"scope_check": "只限分区0", "causal_link": "合成局部映射", "countercheck": "已核对该映射的输入及输出",
                "evidence": [eid], "open_issues": [], **extra}

    def hypothesis(self, hid="H1", eid="E1", **extra):
        return {"id": hid, "rev": 0, "claim": "合成解释", "basis": "记录", "prediction": "可核对",
                "reason": "合成核查完成", "status": "confirmed", "evidence": [eid],
                "decision_review": self.review(eid), **extra}

    def task(self):
        return {"id": "T1", "rev": 0, "status": "pending", "owner": "worker", "question": "解释为何成立？",
                "action": "核查前提", "acceptance": "前提被推翻也可完成", "reason": "有判别力", "hypotheses": ["H1"]}

    def closure(self, eid="E1", **extra):
        return {"rev": self.state()["rev"], "outcome": "root_cause", "route": "evidence_chain",
                "conclusion": "合成局部原因", "scope": "分区0", "limitations": "未验证大场景",
                "acceptance_check": "局部证据链", "evidence": [eid], "decision_review": self.review(eid), **extra}

    def correct(self):
        return self.put("evidence", self.evidence("E3", supersedes=["E1"], correction_reason="原观察范围错误"))

    def test_handoff_cli_keeps_original_problem_and_unexamined_partitions(self):
        source = inventory([self.archive])["items"][0]["source"]
        self.put("evidence", self.evidence(inspected=[source]))
        self.put("hypothesis", self.hypothesis())
        self.put("task", self.task())
        before = (self.directory / "state.json").read_bytes()
        result = subprocess.run([sys.executable, str(Path(case.__file__)), "--case", str(self.directory),
                                 "handoff", "--task", "T1"], capture_output=True, encoding="utf-8", check=True)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["original_problem"]["symptom"], "全局输出异常")
        self.assertEqual(len(packet["available_materials"]["items"]), 3)
        self.assertEqual(packet["coverage"]["reported_inspected"], [source])
        self.assertEqual(len(packet["coverage"]["not_reported_inspected"]), 2)
        self.assertEqual(packet["recorded_observations"]["E1"]["scope"], "仅分区0的value字段")
        self.assertIn("H1", packet["hypotheses_to_check"])
        self.assertEqual(before, (self.directory / "state.json").read_bytes())

    def test_prepare_task_persists_pending_before_delegation_without_launching(self):
        self.put("evidence", self.evidence())
        self.put("hypothesis", self.hypothesis())
        packet = case.execute(self.directory, "prepare-task", self.task())
        self.assertFalse(packet["execution_started"])
        self.assertEqual(packet["task"]["id"], "T1")
        self.assertEqual(self.state()["task"]["T1"]["status"], "pending")
        self.assertEqual(len(packet["available_materials"]["items"]), 3)
        before = self.state()
        with self.assertRaisesRegex(ValueError, "already exists"):
            case.execute(self.directory, "prepare-task", self.task())
        self.assertEqual(self.state(), before)

    def test_correction_reopens_closed_case_and_transitive_decisions(self):
        original = self.put("evidence", self.evidence())
        self.put("evidence", self.evidence("E2", depends_on=["E1"]))
        self.put("hypothesis", self.hypothesis(eid="E2"))
        self.put("hypothesis", self.hypothesis("H2", eid="E2", parents=["H1"]))
        case.execute(self.directory, "close", self.closure("E2"))
        self.correct()
        state = self.state()
        self.assertEqual(state["evidence"]["E1"], original)
        self.assertEqual(case.inactive_evidence(state), {"E1", "E2"})
        self.assertEqual(state["status"], "active")
        self.assertIsNone(state["closure"])
        self.assertEqual([item["status"] for item in state["hypothesis"].values()], ["unresolved", "unresolved"])
        self.assertTrue(any(item["command"] == "close" for item in state["history"]))
        for eid in ("E1", "E2"):
            with self.assertRaisesRegex(ValueError, "valid evidence"):
                case.execute(self.directory, "close", self.closure(eid))
        case.execute(self.directory, "close", self.closure("E3"))
        self.assertEqual(self.state()["status"], "closed")

    def test_dependent_task_requires_reacceptance_without_rerun(self):
        self.put("evidence", self.evidence())
        self.put("hypothesis", self.hypothesis())
        task = self.put("task", self.task())
        task = self.put("task", {**task, "status": "running", "run": {"job_id": "already-finished"}})
        task = case.execute(self.directory, "submit", {"task_id": "T1", "rev": task["rev"], "result": {
            "summary": "支持旧前提", "limitations": "仅局部", "outcome": "supports", "evidence": ["E1"]}})["record"]
        case.execute(self.directory, "accept", {"task_id": "T1", "rev": task["rev"], "reason": "旧验收"})
        child = self.put("task", {**self.task(), "id": "T2", "hypotheses": [], "depends_on": ["T1"]})
        child = self.put("task", {**child, "status": "running"})
        child = case.execute(self.directory, "submit", {"task_id": "T2", "rev": child["rev"], "result": {
            "summary": "依赖前次结果的解释", "limitations": "继承前提", "outcome": "observation"}})["record"]
        case.execute(self.directory, "accept", {"task_id": "T2", "rev": child["rev"], "reason": "旧验收"})
        self.correct()
        task = self.state()["task"]["T1"]
        self.assertEqual(task["status"], "submitted")
        self.assertEqual(task["run"]["job_id"], "already-finished")
        self.assertEqual(self.state()["task"]["T2"]["status"], "submitted")
        with self.assertRaisesRegex(ValueError, "valid evidence"):
            case.execute(self.directory, "accept", {"task_id": "T1", "rev": task["rev"], "reason": "仍可用"})
        case.execute(self.directory, "accept", {"task_id": "T1", "rev": task["rev"], "reason": "前提撤回，旧结果不用",
                     "disposition": "not_usable"})
        self.assertEqual(self.state()["task"]["T1"]["disposition"], "not_usable")
        # A later correction to unrelated evidence must not re-review discarded work.
        self.put("evidence", self.evidence("E4", supersedes=["E3"], correction_reason="另一项观察更正"))
        self.assertEqual(self.state()["task"]["T1"]["status"], "done")

    def test_scope_required_for_new_evidence_but_legacy_case_readable(self):
        old = self.evidence()
        del old["scope"]
        with self.assertRaisesRegex(ValueError, "scope"):
            self.put("evidence", old)
        state = self.state()
        state["evidence"]["E1"] = old
        case.atomic_write(self.directory / "state.json", state)
        self.assertIn("E1", self.state()["evidence"])

    def test_decisive_review_rejects_missing_checks_and_material_gaps(self):
        self.put("evidence", self.evidence())
        for review in (None, self.review(open_issues=["还有一个分区会改变结论"]), self.review(evidence=[])):
            with self.assertRaises(ValueError):
                self.put("hypothesis", self.hypothesis(decision_review=review))
            with self.assertRaises(ValueError):
                case.execute(self.directory, "close", self.closure(decision_review=review))
        # An unresolved hypothesis and a narrowed result need no fake successful review.
        self.put("hypothesis", self.hypothesis(status="unresolved", decision_review=None))
        case.execute(self.directory, "close", self.closure(outcome="narrowed", decision_review=None))

    def test_correction_updates_scenario_and_recovery_and_evidence_display(self):
        self.put("evidence", self.evidence())
        self.put("scenario", {"id": "S1", "rev": 0, "description": "局部场景", "changes": "减少分区", "cost": "低",
                              "reason": "原判定保留", "reproduction": "retained", "evidence": ["E1"]})
        self.put("checkpoint", {"id": "current", "rev": 0, "summary": "继续", "next_action": "旧动作", "reason": "旧证据",
                                "environment": "合成", "baseline": "S1", "evidence": ["E1"]})
        self.correct()
        state = self.state()
        self.assertEqual(state["scenario"]["S1"]["reproduction"], "uncertain")
        self.assertTrue(state["checkpoint"]["current"]["needs_review"])
        self.assertIn("E1", snapshot(state)["inactive_evidence"])
        self.assertIn("不可用于支持结论", render(state, "evidence"))

    def test_bad_correction_is_atomic_and_stale_writes_rejected(self):
        self.put("evidence", self.evidence())
        old = self.put("hypothesis", self.hypothesis())
        before = self.state()
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            self.put("evidence", self.evidence("E2", supersedes=["missing"], correction_reason="bad"))
        self.assertEqual(before, self.state())
        self.correct()
        with self.assertRaisesRegex(ValueError, "revision conflict"):
            self.put("hypothesis", old)

    def test_scenario_only_dependencies_are_flagged_without_stopping_jobs(self):
        self.put("evidence", self.evidence())
        base = {"id": "S1", "rev": 0, "description": "局部", "changes": "减小", "cost": "低",
                "reason": "保留表现", "reproduction": "retained", "evidence": ["E1"]}
        self.put("scenario", base)
        self.put("scenario", {**base, "id": "S2", "parent": "S1"})
        task = self.put("task", {**self.task(), "hypotheses": [], "scenario": "S2"})
        self.put("task", {**task, "status": "running", "run": {"job_id": "keep-running"}})
        self.put("checkpoint", {"id": "current", "rev": 0, "summary": "继续", "next_action": "旧动作",
                                "reason": "基线", "environment": "fixture", "baseline": "S2"})
        self.correct()
        state = self.state()
        self.assertTrue(state["checkpoint"]["current"]["needs_review"])
        self.assertTrue(state["task"]["T1"]["needs_review"])
        self.assertEqual(state["task"]["T1"]["status"], "running")
        self.assertEqual(state["task"]["T1"]["run"]["job_id"], "keep-running")
        self.assertEqual(case.handoff(state, "T1")["scenario"]["reproduction"], "uncertain")

    def test_inventory_zip_and_errors_do_not_pretend_complete(self):
        archive = self.root / "more.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("rank9/dump.json", "{}")
        missing = self.root / "missing"
        result = inventory([archive, missing])
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertFalse((self.root / "rank9").exists())
        corrupt = self.root / "broken.tgz"
        corrupt.write_bytes(b"not an archive")
        self.assertFalse(inventory([corrupt])["complete"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
