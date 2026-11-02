"""Read-only explicit checks, dependency frontiers and experiment decisions.

judge --file checks.json: nodes require id/source/scope/context_valid/coverage/check.
Check kinds: finite(values), close(actual, expected, atol, rtol), range(values, min, max).
frontier --file graph.json: nodes use normal/abnormal/unknown; edges require
from/to/kind(data|control|synchronization)/basis(observed|derived|uncertain)/source.
evaluate --plan plan.json --events events.jsonl [--finished]: evaluate a coherent
run_id/window_id with boolean facts, validity and sources. Never stops a process.
"""
import argparse
from collections import deque
from fractions import Fraction
import json
import math
from pathlib import Path
import sys


VERDICTS = {"normal", "abnormal", "unknown"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def label(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name} must be nonempty text")
    return value


def unique(values, name):
    require(isinstance(values, list), f"{name} must be a list")
    for value in values:
        label(value, name)
    require(len(set(values)) == len(values), f"duplicate {name}")
    return values


def number(value):
    if type(value) in (int, float):
        return value
    if isinstance(value, str):
        return {"nan": math.nan, "inf": math.inf, "+inf": math.inf,
                "-inf": -math.inf, "infinity": math.inf, "+infinity": math.inf,
                "-infinity": -math.inf}.get(value.lower())
    return None


def finite(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def samples(value):
    if isinstance(value, list):
        children = [samples(item) for item in value]
        require(not children or all(s == children[0][0] for s, _ in children), "ragged sample shape")
        return (len(value),) + (children[0][0] if children else ()), [v for _, vals in children for v in vals]
    return (), [number(value)]


def judge_nodes(data):
    require(isinstance(data.get("nodes"), list), "nodes must be a list")
    unique([node.get("id") for node in data["nodes"]], "node ids")
    results = []
    for node in data["nodes"]:
        result = {key: node.get(key) for key in ("id", "source", "scope", "coverage")}
        result.update(verdict="unknown", reason="unverified_context", witness_indices=[])
        check = node.get("check")
        require(isinstance(check, dict), "check must be an object")
        kind = check.get("kind")
        require(kind in {"finite", "close", "range"}, "unsupported check kind")
        if node.get("context_valid") is not True or not node.get("source") or not node.get("scope"):
            results.append(result)
            continue
        require(node.get("coverage") in {"complete", "partial", "unknown"}, "invalid coverage")
        try:
            shape, actual = samples(check.get("actual") if kind == "close" else check.get("values"))
            if kind == "close":
                tolerances = [number(check.get(key)) for key in ("atol", "rtol")]
                require(all(finite(v) and v >= 0 for v in tolerances),
                        "close requires explicit finite nonnegative atol and rtol")
                expected_shape, expected = samples(check.get("expected"))
                if shape != expected_shape or not all(finite(v) for v in expected):
                    result["reason"] = "incomparable_or_missing_reference"
                    results.append(result)
                    continue
                atol, rtol = tolerances
                bad = [i for i, (x, y) in enumerate(zip(actual, expected)) if x is not None and
                       (not finite(x) or abs(Fraction(x) - Fraction(y)) >
                        Fraction(atol) + Fraction(rtol) * abs(Fraction(y)))]
            elif kind == "range":
                lo, hi = number(check.get("min")), number(check.get("max"))
                require(finite(lo) and finite(hi)
                        and lo <= hi, "range requires finite min <= max")
                bad = [i for i, x in enumerate(actual) if x is not None and
                       (not finite(x) or not lo <= x <= hi)]
            else:
                bad = [i for i, x in enumerate(actual) if x is not None and not finite(x)]
            result.update(samples=len(actual), witness_indices=bad)
            if bad:
                result.update(verdict="abnormal", reason="observed_constraint_violation")
            elif not actual or any(x is None for x in actual) or node["coverage"] != "complete":
                result["reason"] = "incomplete_observation"
            else:
                result.update(verdict="normal", reason="satisfies_declared_check_in_scope")
        except ValueError as exc:
            if str(exc) != "ragged sample shape":
                raise
            result["reason"] = "incomparable_sample_shape"
        results.append(result)
    return {"nodes": results, "meaning": "Declared checks and context only; normal is limited to supplied samples/scope. "
            "No runtime identity, tensor-wide correctness or causal mechanism is certified."}


def anomaly_frontier(data):
    nodes = data.get("nodes")
    require(isinstance(nodes, list), "nodes must be a list")
    ids = unique([node.get("id") for node in nodes], "node ids")
    by_id = {node["id"]: node for node in nodes}
    require(all(node.get("verdict") in VERDICTS for node in nodes), "invalid node verdict")
    predecessors, successors = {key: set() for key in ids}, {key: set() for key in ids}
    edges = data.get("edges", [])
    require(isinstance(edges, list), "edges must be a list")
    unresolved = []
    for edge in edges:
        a, b = edge.get("from"), edge.get("to")
        require(a in by_id and b in by_id and a != b, "edge needs distinct existing endpoints")
        require(edge.get("kind") in {"data", "control", "synchronization"}, "invalid dependency kind")
        require(edge.get("basis") in {"observed", "derived", "uncertain"}, "invalid edge basis")
        label(edge.get("source"), "edge source")
        if edge["basis"] == "uncertain":
            unresolved.append(edge)
        else:
            predecessors[b].add(a)
            successors[a].add(b)
    indegree = {key: len(value) for key, value in predecessors.items()}
    ready = deque(key for key in ids if not indegree[key])
    visited = 0
    while ready:
        key = ready.popleft()
        visited += 1
        for child in successors[key]:
            indegree[child] -= 1
            if not indegree[child]:
                ready.append(child)
    require(visited == len(ids), "dependency cycle: not a partial order; distinguish execution instances or analyze wait cycles")
    candidates, downstream = [], []
    for key in ids:
        if by_id[key]["verdict"] != "abnormal":
            continue
        ancestors, todo = set(), list(predecessors[key])
        while todo:
            parent = todo.pop()
            if parent not in ancestors:
                ancestors.add(parent)
                todo.extend(predecessors[parent])
        bad = [p for p in ids if p in ancestors and by_id[p]["verdict"] == "abnormal"]
        unknown = [p for p in ids if p in ancestors and by_id[p]["verdict"] == "unknown"]
        item = {"id": key, "abnormal_ancestors": bad, "unknown_ancestors": unknown}
        (downstream if bad else candidates).append(item)
    return {"candidates": candidates, "downstream_anomalies": downstream,
            "unknown_nodes": [key for key in ids if by_id[key]["verdict"] == "unknown"],
            "node_sources": {key: by_id[key].get("source") for key in ids},
            "used_relations": [edge for edge in edges if edge["basis"] != "uncertain"],
            "unresolved_relations": unresolved, "declared_coverage": data.get("coverage", "unknown"),
            "meaning": "Minimal observed anomalies in the supplied dependency DAG only. "
                       "Uncertain relations are not used to exclude candidates; no global first error or root cause is certified."}


def evaluate_experiment(plan, events, finished=False):
    label(plan.get("question"), "question")
    context = plan.get("context")
    require(isinstance(context, dict) and set(context) == {"run_id", "window_id"},
            "context requires exactly run_id and window_id")
    for key, value in context.items():
        label(value, key)
    prerequisites = unique(plan.get("preconditions"), "preconditions")
    require(prerequisites, "declare at least one experiment precondition")
    require(plan.get("stop_target") in {"collection", "owned_experiment"}, "invalid stop_target")
    budget = plan.get("max_events")
    require(budget is None or type(budget) is int and budget > 0, "max_events must be a positive integer")
    rules = plan.get("rules")
    require(isinstance(rules, list) and rules, "rules must be a nonempty list")
    unique([rule.get("id") for rule in rules], "rule ids")
    for rule in rules:
        require(rule.get("outcome") in {"answered", "refuted"}, "invalid rule outcome")
        label(rule.get("conclusion"), "rule conclusion")
        conditions = rule.get("when")
        require(isinstance(conditions, dict) and conditions, "rule when must be nonempty")
        for fact, value in conditions.items():
            label(fact, "fact")
            require(type(value) is bool, "rule values must be boolean")
    observed, sources, selected, ignored = {}, {}, 0, 0
    for event in events:
        require(isinstance(event, dict), "event must be an object")
        if event.get("context") != context:
            ignored += 1
            continue
        selected += 1
        fact = label(event.get("fact"), "event fact")
        value = event.get("value")
        require(value is None or type(value) is bool, "event value must be boolean or null")
        require(event.get("validity") in {"valid", "invalid", "uncertain"}, "invalid event validity")
        values = observed.setdefault(fact, set())
        if event["validity"] == "valid" and type(value) is bool and isinstance(event.get("source"), str) and event["source"].strip():
            values.add(value)
            sources.setdefault(fact, []).append(event["source"])
    facts = {key: next(iter(values)) if len(values) == 1 else None for key, values in observed.items()}
    conflicts = [key for key, values in observed.items() if len(values) > 1]
    invalid = [key for key in prerequisites if facts.get(key) is False]
    missing = [key for key in prerequisites if facts.get(key) is None]
    matching = [rule for rule in rules if all(facts.get(key) is value for key, value in rule["when"].items())]
    signatures = {(rule["outcome"], rule["conclusion"]) for rule in matching}
    result = {"question": plan["question"], "context": context, "decision": "continue", "reason": "inconclusive",
              "stop_target": plan["stop_target"], "facts": facts, "sources": sources, "conflicts": conflicts,
              "invalid_preconditions": invalid, "missing_preconditions": missing,
              "matching_rules": [rule["id"] for rule in matching], "rule_conflict": len(signatures) > 1,
              "selected_events": selected, "ignored_events": ignored, "process_stopped": False,
              "meaning": "Decision from declared facts and rules; no command, signal, runtime verification or RCA certification."}
    if invalid:
        result.update(decision="stop", reason="invalid")
    elif not missing and matching and len(signatures) == 1:
        outcome, conclusion = next(iter(signatures))
        result.update(decision="stop", reason=outcome, conclusion=conclusion)
    elif budget is not None and selected >= budget:
        result.update(decision="stop", reason="budget")
    elif finished:
        result.update(decision="stop", reason="inconclusive")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("judge", "frontier"):
        commands.add_parser(name).add_argument("--file", required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--events", required=True)
    evaluate.add_argument("--finished", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "evaluate":
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8-sig"))
            with Path(args.events).open(encoding="utf-8-sig") as stream:
                events = [json.loads(line) for line in stream if line.strip()]
            result = evaluate_experiment(plan, events, args.finished)
        else:
            data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
            result = judge_nodes(data) if args.command == "judge" else anomaly_frontier(data)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
