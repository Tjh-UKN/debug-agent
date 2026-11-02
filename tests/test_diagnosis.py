"""Decision boundaries: unknowns, independent anomalies, invalid runs and early stopping."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from diagnosis import anomaly_frontier, evaluate_experiment, judge_nodes
import diagnosis


def observation(check, **extra):
    return {"id": "x", "source": "sample.log:3", "scope": "run42/step8/rank0",
            "context_valid": True, "coverage": "complete", "check": check, **extra}


def judge(check, **extra):
    return judge_nodes({"nodes": [observation(check, **extra)]})["nodes"][0]


def graph(verdicts, links):
    return {"coverage": "partial", "nodes": [{"id": key, "verdict": verdict} for key, verdict in verdicts.items()],
            "edges": [{"from": a, "to": b, "kind": "data", "basis": "observed", "source": "trace:3"}
                      for a, b in links]}


def plan():
    return {"question": "Does this replay produce a nonfinite output under the same input/state?",
            "context": {"run_id": "r42", "window_id": "step8/rank0"},
            "preconditions": ["same_input", "same_state"], "stop_target": "collection",
            "rules": [{"id": "output", "when": {"bad_output": True, "boundary_complete": True},
                       "outcome": "answered", "conclusion": "Nonfinite output observed in this replay"}]}


def event(fact, value=True, **extra):
    return {"context": plan()["context"], "fact": fact, "value": value,
            "validity": "valid", "source": f"checks.log:{fact}", **extra}


class JudgeTests(unittest.TestCase):
    def test_explicit_tolerance_applies_to_same_shaped_samples(self):
        self.assertEqual(judge({"kind": "close", "actual": [1.01, 2], "expected": [1, 2],
                                "atol": 0.02, "rtol": 0})["verdict"], "normal")
        bad = judge({"kind": "close", "actual": [1.1, 2], "expected": [1, 2], "atol": 0.02, "rtol": 0})
        self.assertEqual(bad["verdict"], "abnormal")
        self.assertEqual(bad["witness_indices"], [0])

    def test_missing_reference_shape_mismatch_and_ragged_are_unknown(self):
        for expected in (None, [1, 2], ["NaN"]):
            self.assertEqual(judge({"kind": "close", "actual": [1], "expected": expected,
                                   "atol": 0, "rtol": 0})["verdict"], "unknown")
        self.assertEqual(judge({"kind": "finite", "values": [[1], [1, 2]]})["verdict"], "unknown")

    def test_no_automatic_tolerance(self):
        for tol in ({}, {"atol": -1, "rtol": 0}, {"atol": 0, "rtol": True}):
            with self.assertRaises(ValueError):
                judge({"kind": "close", "actual": [1], "expected": [1], **tol})

    def test_missing_or_partial_observation_is_not_normal(self):
        for values in ([], None, [True], [1, None]):
            self.assertEqual(judge({"kind": "finite", "values": values})["verdict"], "unknown")
        self.assertEqual(judge({"kind": "finite", "values": [1]}, coverage="partial")["verdict"], "unknown")

    def test_valid_violation_remains_visible_with_partial_coverage(self):
        result = judge({"kind": "finite", "values": [1, "NaN", None]}, coverage="partial")
        self.assertEqual(result["verdict"], "abnormal")
        self.assertEqual(result["witness_indices"], [1])

    def test_unverified_context_cannot_certify_even_nan(self):
        for extra in ({"context_valid": None}, {"context_valid": False}, {"source": ""}):
            self.assertEqual(judge({"kind": "finite", "values": ["NaN"]}, **extra)["verdict"], "unknown")

    def test_range_needs_explicit_valid_bounds(self):
        self.assertEqual(judge({"kind": "range", "values": [0, 1], "min": 0, "max": 1})["verdict"], "normal")
        self.assertEqual(judge({"kind": "range", "values": [2], "min": 0, "max": 1})["verdict"], "abnormal")
        with self.assertRaises(ValueError):
            judge({"kind": "range", "values": [1], "min": 2, "max": 0})

    def test_global_normal_does_not_remove_local_bad_sample(self):
        global_norm = observation({"kind": "close", "actual": 1, "expected": 1, "atol": 0, "rtol": 0})
        local = observation({"kind": "range", "values": [10], "min": -1, "max": 1}, id="local")
        self.assertEqual([r["verdict"] for r in judge_nodes({"nodes": [global_norm, local]})["nodes"]],
                         ["normal", "abnormal"])

    def test_large_integers_and_finite_float_overflow_do_not_hide_difference(self):
        self.assertEqual(judge({"kind": "close", "actual": 2**53 + 1, "expected": 2**53,
                               "atol": 0, "rtol": 0})["verdict"], "abnormal")
        self.assertEqual(judge({"kind": "close", "actual": 1e308, "expected": -1e308,
                               "atol": 1e308, "rtol": 1})["verdict"], "normal")
        self.assertEqual(judge({"kind": "finite", "values": [10**400, "Infinity"]})["verdict"], "abnormal")


class FrontierTests(unittest.TestCase):
    def test_two_independent_sources_and_downstream_propagation(self):
        result = anomaly_frontier(graph({"a": "abnormal", "b": "abnormal", "c": "abnormal"}, [("a", "c")]))
        self.assertEqual([v["id"] for v in result["candidates"]], ["a", "b"])
        self.assertEqual(result["downstream_anomalies"][0]["abnormal_ancestors"], ["a"])

    def test_unknown_upstream_survives_and_normal_parent_does_not_prune(self):
        result = anomaly_frontier(graph({"u": "unknown", "n": "normal", "a": "abnormal"}, [("u", "n"), ("n", "a")]))
        self.assertEqual(result["candidates"], [{"id": "a", "abnormal_ancestors": [], "unknown_ancestors": ["u"]}])
        self.assertEqual(result["unknown_nodes"], ["u"])

    def test_judged_samples_feed_frontier_without_losing_declared_sources(self):
        checked = judge_nodes({"nodes": [
            observation({"kind": "finite", "values": [None]}, id="input"),
            observation({"kind": "finite", "values": ["NaN"]}, id="output")]})
        link = {"from": "input", "to": "output", "kind": "data", "basis": "observed", "source": "trace:8"}
        result = anomaly_frontier({"nodes": checked["nodes"], "edges": [link]})
        self.assertEqual(result["candidates"][0]["unknown_ancestors"], ["input"])
        self.assertEqual(result["node_sources"]["output"], "sample.log:3")
        self.assertEqual(result["used_relations"], [link])

    def test_uncertain_relation_does_not_exclude_candidate(self):
        data = graph({"a": "abnormal", "b": "abnormal"}, [("a", "b")])
        data["edges"][0]["basis"] = "uncertain"
        result = anomaly_frontier(data)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(len(result["unresolved_relations"]), 1)

    def test_input_order_and_timestamps_do_not_supply_dependency_edges(self):
        data = graph({"late": "abnormal", "early": "abnormal"}, [])
        data["nodes"][0]["timestamp"] = 200
        data["nodes"][1]["timestamp"] = 1
        self.assertEqual(len(anomaly_frontier(data)["candidates"]), 2)

    def test_cycle_missing_endpoints_and_unproven_edge_types_rejected(self):
        for data in (graph({"a": "abnormal", "b": "normal"}, [("a", "b"), ("b", "a")]),
                     graph({"a": "abnormal"}, [("a", "missing")])):
            with self.assertRaises(ValueError):
                anomaly_frontier(data)
        data = graph({"a": "abnormal", "b": "normal"}, [("a", "b")])
        data["edges"][0]["kind"] = "timestamp"
        with self.assertRaises(ValueError):
            anomaly_frontier(data)


class ExperimentTests(unittest.TestCase):
    def test_expected_phenomenon_without_preconditions_cannot_answer(self):
        result = evaluate_experiment(plan(), [event("bad_output"), event("boundary_complete")])
        self.assertEqual(result["decision"], "continue")
        self.assertEqual(result["missing_preconditions"], ["same_input", "same_state"])

    def test_mismatch_invalidates_even_if_expected_phenomenon_present(self):
        events = [event("same_input", False), event("same_state"), event("bad_output"), event("boundary_complete")]
        result = evaluate_experiment(plan(), events)
        self.assertEqual(result["reason"], "invalid")
        self.assertFalse(result["process_stopped"])
        self.assertNotIn("conclusion", result)

    def test_incremental_controlled_collection_stops_when_question_answered(self):
        events = []
        sequence = [event("same_input"), event("same_state"), event("bad_output"), event("boundary_complete")]
        # This loop owns the synthetic collection; the evaluator itself never kills anything.
        for item in sequence + [event("irrelevant_later_fact")]:
            events.append(item)
            decision = evaluate_experiment(plan(), events)
            if decision["decision"] == "stop":
                break
        self.assertEqual(len(events), 4)
        self.assertEqual(decision["reason"], "answered")
        self.assertFalse(decision["process_stopped"])

    def test_foreign_runs_windows_and_extra_context_do_not_satisfy_rules(self):
        for context in ({"run_id": "other", "window_id": "step8/rank0"},
                        {"run_id": "r42", "window_id": "other"},
                        {**plan()["context"], "rank": "0"}):
            result = evaluate_experiment(plan(), [event("same_input", context=context)])
            self.assertEqual(result["ignored_events"], 1)
            self.assertEqual(result["facts"], {})

    def test_invalid_uncertain_sourceless_and_null_events_do_not_satisfy_precondition(self):
        for extra in ({"validity": "invalid"}, {"validity": "uncertain"}, {"source": ""}, {"value": None}):
            result = evaluate_experiment(plan(), [event("same_input", **extra)], finished=True)
            self.assertEqual(result["reason"], "inconclusive")
            self.assertIn("same_input", result["missing_preconditions"])

    def test_conflicting_fact_does_not_use_latest_value(self):
        events = [event("same_input"), event("same_input", False), event("same_state"),
                  event("bad_output"), event("boundary_complete")]
        for ordered in (events, list(reversed(events))):
            result = evaluate_experiment(plan(), ordered, finished=True)
            self.assertEqual(result["reason"], "inconclusive")
            self.assertEqual(result["conflicts"], ["same_input"])

    def test_conflicting_answers_are_not_arbitrarily_selected(self):
        data = plan()
        data["rules"].append({"id": "other", "when": {"boundary_complete": True},
                              "outcome": "refuted", "conclusion": "Opposite answer"})
        result = evaluate_experiment(data, [event(key) for key in
            ("same_input", "same_state", "bad_output", "boundary_complete")], finished=True)
        self.assertTrue(result["rule_conflict"])
        self.assertEqual(result["reason"], "inconclusive")

    def test_budget_and_end_of_collection_do_not_refute_unobserved_failure(self):
        data = plan()
        data["max_events"] = 1
        self.assertEqual(evaluate_experiment(data, [event("same_input")])["reason"], "budget")
        self.assertEqual(evaluate_experiment(plan(), [], finished=True)["reason"], "inconclusive")

    def test_valid_refutation_requires_explicit_rule_and_all_conditions(self):
        data = plan()
        data["rules"] = [{"id": "negative", "when": {"bad_output": False, "boundary_complete": True},
                          "outcome": "refuted", "conclusion": "This bounded replay did not produce a nonfinite output"}]
        events = [event("same_input"), event("same_state"), event("bad_output", False), event("boundary_complete")]
        self.assertEqual(evaluate_experiment(data, events)["reason"], "refuted")

    def test_evaluation_is_read_only_and_has_no_mandatory_hypothesis(self):
        data, events = plan(), [event("same_input")]
        before = deepcopy((data, events))
        evaluate_experiment(data, events)
        self.assertEqual((data, events), before)
        self.assertNotIn("hypothesis", data)

    def test_cli_reads_bom_and_returns_structured_decision_without_editing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p, e = folder / "plan.json", folder / "events.jsonl"
            p.write_text(json.dumps(plan()), encoding="utf-8-sig")
            e.write_text(json.dumps(event("same_input", False)) + "\n", encoding="utf-8-sig")
            before = (p.read_bytes(), e.read_bytes())
            result = subprocess.run([sys.executable, diagnosis.__file__,
                "evaluate", "--plan", str(p), "--events", str(e)], capture_output=True, encoding="utf-8", check=True)
            self.assertEqual(json.loads(result.stdout)["reason"], "invalid")
            self.assertEqual((p.read_bytes(), e.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
