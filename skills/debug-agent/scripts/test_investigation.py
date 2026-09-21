"""Tests for investigation lineage, logical dependency separation and trace views."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import case
import investigation
from panel import render
from recovery import snapshot


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "case"
        case.execute(self.root, "init", {"title": "NaN 定位", "goal": "根因定位",
                                         "symptom": "输出 NaN", "acceptance": "证据链指向根因"})

    def show(self):
        return case.execute(self.root, "show", history=True)

    def put(self, kind, record):
        return case.execute(self.root, "put", record, kind)["record"]

    def evidence(self, eid="E1", **extra):
        return {"id": eid, "rev": 0, "observation": "合成观察", "source": "fixture.log:2",
                "scope": "合成局部场景", "context": "模拟，非真实设备", "limits": "仅合成测试",
                "validity": "valid", **extra}

    def review(self, eid="E1"):
        return {"scope_check": "仅合成小场景", "causal_link": "合成机制映射",
                "countercheck": "已核查合成反例", "evidence": [eid], "open_issues": []}

    def hypothesis(self, hid="H1", **extra):
        return {"id": hid, "rev": 0, "claim": f"解释 {hid}", "basis": "源码分支",
                "prediction": "局部修改应改变结果", "reason": "可核查", "status": "open", **extra}

    def confirmed(self, hid, eid="E1", **extra):
        return {**self.hypothesis(hid), "status": "confirmed", "evidence": [eid],
                "decision_review": self.review(eid), **extra}

    def exclude(self, hid, eid):
        """Rule out from the stored record: put replaces the whole record, so
        registered lineage fields must be carried forward, never rebuilt."""
        stored = self.show()["hypothesis"][hid]
        return self.put("hypothesis", {**stored, "status": "ruled_out", "evidence": [eid],
                                       "decision_review": self.review(eid)})

    def trace(self, *args):
        script = str(Path(case.__file__).parent / "trace.py")
        return subprocess.run([sys.executable, script, "--case", str(self.root), *args],
                              capture_output=True, encoding="utf-8")

    # --- T1: lineage -------------------------------------------------------
    def test_path_follows_investigates_only(self):
        self.put("hypothesis", self.confirmed("H1", self.put("evidence", self.evidence())["id"]))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="H1 从哪里来？"))
        self.put("hypothesis", self.hypothesis("H3", investigates="H2", investigation_question="H2 从哪里来？"))
        self.assertEqual(investigation.investigation_path(self.show(), "H3"), ["H1", "H2", "H3"])
        self.assertEqual(investigation.children(self.show()), {"H1": ["H2"], "H2": ["H3"]})
        self.assertEqual(investigation.logical_dependencies(self.show(), "H3"), [])
        # path must not leak in parents: give H3 an unrelated logical parent too;
        # put replaces the whole record, so the stored lineage fields must survive
        self.put("hypothesis", self.confirmed("H9", self.put("evidence", self.evidence("E9"))["id"]))
        stored = self.show()["hypothesis"]["H3"]
        self.put("hypothesis", {**stored, "parents": ["H9"]})
        self.assertEqual(self.show()["hypothesis"]["H3"]["investigates"], "H2")
        self.assertEqual(investigation.investigation_path(self.show(), "H3"), ["H1", "H2", "H3"])

    # --- T2: cycles rejected atomically ------------------------------------
    def test_investigation_cycle_and_self_reference_rejected(self):
        self.put("hypothesis", self.hypothesis("H1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="？"))
        before = (self.root / "state.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "cycle in investigation lineage"):
            self.put("hypothesis", {**self.hypothesis("H1"), "rev": 1, "investigates": "H2",
                                    "investigation_question": "？"})
        with self.assertRaisesRegex(ValueError, "cycle in investigation lineage"):
            self.put("hypothesis", {**self.show()["hypothesis"]["H2"], "investigates": "H2"})
        with self.assertRaisesRegex(ValueError, "unknown hypothesis"):
            self.put("hypothesis", self.hypothesis("H4", investigates="missing", investigation_question="？"))
        with self.assertRaisesRegex(ValueError, "investigation_question"):
            self.put("hypothesis", self.hypothesis("H5", investigates="H1"))
        self.assertEqual(before, (self.root / "state.json").read_bytes())

    # --- T3: sibling independence ------------------------------------------
    def test_ruled_out_branch_leaves_siblings_untouched(self):
        self.put("evidence", self.evidence("E1"))
        self.put("evidence", self.evidence("E2"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="来源？"))
        self.put("hypothesis", self.hypothesis("H3", investigates="H1", investigation_question="来源？"))
        sibling = self.show()["hypothesis"]["H3"]
        self.exclude("H2", "E2")
        after = self.show()["hypothesis"]["H3"]
        self.assertEqual(after, sibling)
        self.assertEqual(after["status"], "open")
        self.assertNotIn("needs_review", after)

    # --- T4: descendant pruning is derived, not persisted -------------------
    def test_descendant_history_kept_but_branch_pruned(self):
        self.put("evidence", self.evidence("E1"))
        self.put("evidence", self.evidence("E2"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="来源？"))
        self.put("hypothesis", self.hypothesis("H21", investigates="H2", investigation_question="细分子分支？"))
        self.exclude("H2", "E2")
        state = self.show()
        self.assertEqual(state["hypothesis"]["H21"]["status"], "open")
        self.assertEqual(investigation.branch_health(state, "H21"), {"state": "pruned", "blocked_by": "H2"})
        self.assertEqual(investigation.branch_health(state, "H1"), {"state": "active", "blocked_by": None})
        self.assertEqual([node["id"] for node in investigation.active_frontier(state)], ["H1"])
        tree = investigation.investigation_tree(state)
        child = tree["roots"][0]["children"][0]
        self.assertEqual((child["status"], child["branch_health"]["state"]), ("ruled_out", "pruned"))

    # --- T5 + scenario C: investigates is not a logical dependency ----------
    def test_correction_does_not_withdraw_investigation_children(self):
        self.put("evidence", self.evidence("E1"))
        self.put("evidence", self.evidence("E2"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="来源？"))
        self.put("evidence", self.evidence("E3", supersedes=["E1"], correction_reason="原观察范围错误"))
        state = self.show()
        self.assertEqual(state["hypothesis"]["H1"]["status"], "unresolved")
        self.assertEqual(state["hypothesis"]["H2"]["status"], "open")
        self.assertNotIn("needs_review", state["hypothesis"]["H2"])
        # Derived view flags the branch for re-review without touching history.
        self.assertEqual(investigation.branch_health(state, "H2"), {"state": "stale", "blocked_by": "H1"})

    # --- T6: parents keep the old correction propagation --------------------
    def test_logical_parents_still_withdraw_on_correction(self):
        self.put("evidence", self.evidence("E1"))
        self.put("evidence", self.evidence("E2"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.confirmed("H2", "E2", parents=["H1"]))
        self.put("evidence", self.evidence("E3", supersedes=["E1"], correction_reason="原观察范围错误"))
        state = self.show()
        self.assertEqual(state["hypothesis"]["H2"]["status"], "unresolved")
        self.assertEqual(investigation.logical_dependents(state, "H1"), ["H2"])

    # --- T7: path and why answer different questions ------------------------
    def test_why_walks_parents_and_evidence_not_investigation(self):
        self.put("evidence", self.evidence("E1"))
        self.put("evidence", self.evidence("E2"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.confirmed("H2", "E2"))
        self.put("hypothesis", self.confirmed("H3", "E2", parents=["H2"],
                                              investigates="H1", investigation_question="来源？"))
        state = self.show()
        self.assertEqual(investigation.investigation_path(state, "H3"), ["H1", "H3"])
        trace = investigation.why_trace(state, "H3")
        self.assertEqual([node["id"] for node in trace["nodes"]], ["H3", "H2"])
        self.assertEqual(trace["nodes"][0]["evidence"][0]["id"], "E2")
        self.assertNotIn("H1", [node["id"] for node in trace["nodes"]])

    # --- T8: closure root hypothesis contract -------------------------------
    def test_evidence_chain_closure_requires_confirmed_root(self):
        self.put("evidence", self.evidence("E1"))
        self.put("hypothesis", self.hypothesis("H1"))
        base = {"rev": self.show()["rev"], "outcome": "root_cause", "route": "evidence_chain",
                "conclusion": "原因 A", "scope": "局部", "limitations": "未验证大场景",
                "acceptance_check": "证据链满足", "evidence": ["E1"], "decision_review": self.review()}
        with self.assertRaisesRegex(ValueError, "confirmed root hypothesis required"):
            case.execute(self.root, "close", base)
        with self.assertRaisesRegex(ValueError, "closure hypotheses must be confirmed"):
            case.execute(self.root, "close", dict(base, hypotheses=["H1"]))
        self.put("hypothesis", self.confirmed("H1", "E1", rev=1))
        case.execute(self.root, "close", dict(base, rev=self.show()["rev"], hypotheses=["H1"]))
        self.assertEqual(self.show()["closure"]["hypotheses"], ["H1"])

    def test_narrowed_and_legacy_routes_do_not_require_root(self):
        self.put("evidence", self.evidence("E1"))
        case.execute(self.root, "close", {"rev": self.show()["rev"], "outcome": "narrowed",
                                          "conclusion": "缩小到算子", "scope": "局部", "limitations": "未定位"})
        self.assertEqual(self.show()["status"], "closed")

    # --- T9 + T10: legacy readability and recovery projection ---------------
    def test_legacy_case_without_new_fields_still_reads(self):
        self.put("evidence", self.evidence())
        self.put("hypothesis", self.hypothesis())
        state = self.show()
        state["checkpoint"] = {"current": {"id": "current", "summary": "旧 checkpoint", "rev": 0,
                                           "next_action": "继续", "reason": "旧", "environment": "fixture"}}
        case.atomic_write(self.root / "state.json", state)
        result = snapshot(case.execute(self.root, "show"))
        self.assertEqual(result["investigation"]["focus"], [])
        self.assertEqual([node["id"] for node in result["investigation"]["frontier"]], ["H1"])
        self.assertEqual(result["investigation"]["current_paths"], [["H1"]])

    def test_dangling_lineage_is_reported_not_guessed(self):
        self.put("evidence", self.evidence())
        self.put("hypothesis", self.hypothesis())
        state = self.show()
        state["hypothesis"]["H1"]["investigates"] = "HX"
        case.atomic_write(self.root / "state.json", state)
        result = snapshot(case.execute(self.root, "show"))
        self.assertIn("H1", result["investigation"]["unregistered_lineage"])
        self.assertEqual(investigation.branch_health(state, "H1")["state"], "unknown")

    def test_recovery_restores_focus_paths_frontier_and_pruned(self):
        for eid in ("E1", "E2", "E3", "E4"):
            self.put("evidence", self.evidence(eid))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="来源？"))
        self.put("hypothesis", self.hypothesis("H21", investigates="H2", investigation_question="细分？"))
        self.put("hypothesis", self.hypothesis("H3", investigates="H1", investigation_question="来源？"))
        self.put("hypothesis", self.confirmed("H4", "E4", investigates="H1", investigation_question="来源？"))
        self.exclude("H2", "E2")
        self.put("checkpoint", {"id": "current", "rev": 0, "summary": "定位到 H1 来源",
                                "next_action": "区分 H3/H4", "reason": "前沿明确",
                                "environment": "fixture", "focus_hypotheses": ["H3"]})
        result = snapshot(self.show())
        section = result["investigation"]
        self.assertEqual(section["focus"], ["H3"])
        self.assertEqual(section["current_paths"], [["H1", "H3"]])
        frontier = {node["id"] for node in section["frontier"]}
        self.assertEqual(frontier, {"H3", "H4"})
        self.assertEqual(section["pruned"], ["H2", "H21"])
        self.assertEqual(section["stale"], [])
        self.assertEqual(self.show()["hypothesis"]["H21"]["status"], "open")

    def test_focus_hypotheses_validated_and_do_not_change_structure(self):
        self.put("evidence", self.evidence())
        self.put("hypothesis", self.hypothesis())
        with self.assertRaisesRegex(ValueError, "unknown hypothesis ID"):
            self.put("checkpoint", {"id": "current", "rev": 0, "summary": "s", "next_action": "n",
                                    "reason": "r", "environment": "e", "focus_hypotheses": ["missing"]})
        before = [node["id"] for node in investigation.active_frontier(self.show())]
        self.put("checkpoint", {"id": "current", "rev": 0, "summary": "s", "next_action": "n",
                                "reason": "r", "environment": "e", "focus_hypotheses": ["H1"]})
        self.assertEqual([node["id"] for node in investigation.active_frontier(self.show())], before)

    # --- scenario A: confirmed location is not a confirmed cause ------------
    def test_confirmed_leaf_stays_on_frontier_and_blocks_premature_closure(self):
        self.put("evidence", self.evidence())
        self.put("hypothesis", self.confirmed("H1", "E1"))
        state = self.show()
        frontier = investigation.active_frontier(state)
        self.assertEqual([node["id"] for node in frontier], ["H1"])
        self.assertEqual(frontier[0]["status"], "confirmed")
        with self.assertRaisesRegex(ValueError, "confirmed root hypothesis required"):
            case.execute(self.root, "close", {"rev": state["rev"], "outcome": "root_cause",
                                              "route": "evidence_chain", "conclusion": "只确认了位置",
                                              "scope": "局部", "limitations": "未定位来源",
                                              "acceptance_check": "不满足", "evidence": ["E1"],
                                              "decision_review": self.review()})

    # --- why/impact evidence awareness --------------------------------------
    def test_why_trace_marks_withdrawn_and_missing_evidence(self):
        self.put("evidence", self.evidence("E1"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("evidence", self.evidence("E2", supersedes=["E1"], correction_reason="范围错误"))
        trace = investigation.why_trace(self.show(), "H1")
        self.assertFalse(trace["nodes"][0]["evidence"][0]["usable_as_support"])
        self.assertEqual(trace["nodes"][0]["missing_evidence"], [])
        state = self.show()
        state["hypothesis"]["H1"]["evidence"] = ["E1", "gone"]
        self.assertEqual(investigation.why_trace(state, "H1")["nodes"][0]["missing_evidence"], ["gone"])

    def test_impact_trace_projects_registered_reach_without_mutation(self):
        for eid in ("E1", "E2"):
            self.put("evidence", self.evidence(eid))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.confirmed("H2", "E2", parents=["H1"]))
        self.put("scenario", {"id": "S1", "rev": 0, "description": "小场景", "changes": "减卡",
                              "cost": "低", "reason": "保留表现", "reproduction": "retained", "evidence": ["E1"]})
        self.put("task", {"id": "T1", "rev": 0, "status": "pending", "owner": "worker",
                          "question": "q", "action": "a", "acceptance": "acc", "reason": "r",
                          "hypotheses": ["H2"]})
        self.put("checkpoint", {"id": "current", "rev": 0, "summary": "s", "next_action": "n",
                                "reason": "r", "environment": "e", "baseline": "S1"})
        before = (self.root / "state.json").read_bytes()
        impact = investigation.impact_trace(self.show(), "evidence", "E1")
        self.assertEqual(impact["hypotheses"], ["H1", "H2"])
        self.assertEqual(impact["scenarios"], ["S1"])
        self.assertEqual(impact["tasks"], ["T1"])
        self.assertTrue(impact["checkpoint_affected"])
        self.assertFalse(impact["closure_would_reopen"])
        self.assertEqual(before, (self.root / "state.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            investigation.impact_trace(self.show(), "evidence", "missing")
        with self.assertRaisesRegex(ValueError, "unknown hypothesis"):
            investigation.impact_trace(self.show(), "hypothesis", "missing")

    def test_impact_trace_flags_closed_case_reopen(self):
        self.put("evidence", self.evidence("E1"))
        self.put("evidence", self.evidence("E2"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        case.execute(self.root, "close", {"rev": self.show()["rev"], "outcome": "root_cause",
                                          "route": "evidence_chain", "conclusion": "原因 A",
                                          "scope": "局部", "limitations": "未验证大场景",
                                          "hypotheses": ["H1"], "acceptance_check": "满足",
                                          "evidence": ["E1"], "decision_review": self.review()})
        self.assertTrue(investigation.impact_trace(self.show(), "evidence", "E1")["closure_would_reopen"])
        self.assertFalse(investigation.impact_trace(self.show(), "evidence", "E2")["closure_would_reopen"])

    # --- trace CLI -----------------------------------------------------------
    def test_trace_cli_json_and_error_handling(self):
        self.put("evidence", self.evidence("E1"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="来源？"))
        completed = self.trace("path", "--hypothesis", "H2")
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["path"], ["H1", "H2"])
        frontier = json.loads(self.trace("frontier").stdout)
        self.assertEqual({node["id"] for node in frontier["frontier"]}, {"H2"})
        tree = json.loads(self.trace("tree").stdout)
        self.assertEqual(tree["roots"][0]["children"][0]["investigates"], "H1")
        why = json.loads(self.trace("why", "--hypothesis", "H1").stdout)
        self.assertEqual(why["root"], "H1")
        impact = json.loads(self.trace("impact", "--kind", "evidence", "--id", "E1").stdout)
        self.assertEqual(impact["hypotheses"], ["H1"])
        failed = self.trace("path", "--hypothesis", "missing")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("error", json.loads(failed.stderr))

    # --- panel keeps the compact path/branch projection ----------------------
    def test_panel_shows_compact_path_and_branch(self):
        for eid in ("E1", "E2"):
            self.put("evidence", self.evidence(eid))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        self.put("hypothesis", self.hypothesis("H2", investigates="H1", investigation_question="来源？"))
        self.put("hypothesis", self.hypothesis("H3", investigates="H1", investigation_question="来源？"))
        self.exclude("H2", "E2")
        output = render(self.show(), "status")
        self.assertIn("当前定位路径", output)
        self.assertIn("H1", output)
        self.assertIn("来源候选", output)
        self.assertIn("已排除", output)

    def test_done_view_names_root_hypothesis_node(self):
        self.put("evidence", self.evidence("E1"))
        self.put("hypothesis", self.confirmed("H1", "E1"))
        data = self.show()
        data["status"] = "closed"
        data["closure"] = {"outcome": "root_cause", "route": "evidence_chain", "hypotheses": ["H1"],
                           "conclusion": "原因 A", "scope": "局部", "limitations": "未验证", "evidence": ["E1"]}
        output = render(data, "done")
        self.assertIn("根因节点：H1", output)
        data["closure"].pop("hypotheses")
        self.assertNotIn("根因节点", render(data, "done"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
