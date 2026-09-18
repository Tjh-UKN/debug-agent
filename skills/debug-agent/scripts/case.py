#!/usr/bin/env python3
"""Local, atomic diagnostic case ledger. Python 3.10+, standard library only."""
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile

KINDS = ("hypothesis", "evidence", "scenario", "task", "checkpoint")
TASK_STATES = {"pending", "running", "blocked", "submitted", "done", "cancelled"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    with open(path, encoding="utf-8-sig") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), "JSON must be an object")
    return value


def nonempty(data, *fields):
    for field in fields:
        require(isinstance(data.get(field), str) and data[field].strip(), f"{field}: nonempty text required")


def refs(state, data, field, kind):
    values = data.get(field, [])
    require(isinstance(values, list) and all(isinstance(v, str) for v in values), f"{field}: list of IDs required")
    require(all(v in state[kind] for v in values), f"{field}: unknown {kind} ID")
    return values


def valid_evidence(state, ids):
    invalid = inactive_evidence(state)
    require(ids and all(i not in invalid for i in ids), "valid evidence required (not superseded or dependent on inactive evidence)")


def inactive_evidence(state):
    """Keep observations immutable; compute whether they can still support a claim."""
    records = state.get("evidence", {})
    inactive = {eid for eid, item in records.items() if item["validity"] != "valid"}
    inactive.update(eid for item in records.values() for eid in item.get("supersedes", []))
    while True:
        more = {eid for eid, item in records.items() if set(item.get("depends_on", [])) & inactive}
        if more <= inactive:
            return inactive
        inactive.update(more)


def decision_review(state, data):
    review = data.get("decision_review")
    require(isinstance(review, dict), "decision_review required for exclusion, confirmation or successful closure")
    nonempty(review, "scope_check", "causal_link", "countercheck")
    ids = refs(state, review, "evidence", "evidence")
    valid_evidence(state, ids)
    require(review.get("open_issues") == [], "resolve material open_issues before a decisive conclusion")


def record_evidence(item):
    review = item.get("decision_review")
    return set(item.get("evidence", [])) | set(review.get("evidence", []) if isinstance(review, dict) else [])


def reconcile_correction(state, correction, newly_inactive):
    """Withdraw dependent decisions, not historical work or the raw observations."""
    inactive = newly_inactive
    affected = set()
    while True:
        more = {hid for hid, item in state["hypothesis"].items()
                if record_evidence(item) & inactive or set(item.get("parents", [])) & affected}
        if more <= affected:
            break
        affected.update(more)
    affected_scenarios = {sid for sid, item in state["scenario"].items() if record_evidence(item) & inactive}
    while True:
        more = {sid for sid, item in state["scenario"].items() if item.get("parent") in affected_scenarios}
        if more <= affected_scenarios:
            break
        affected_scenarios.update(more)
    affected_tasks = {tid for tid, item in state["task"].items()
                      if (record_evidence(item) | set(item.get("result", {}).get("evidence", []))) & inactive
                      or set(item.get("hypotheses", [])) & affected or item.get("scenario") in affected_scenarios}
    while True:
        more = {tid for tid, item in state["task"].items() if set(item.get("depends_on", [])) & affected_tasks}
        if more <= affected_tasks:
            break
        affected_tasks.update(more)
    reason = "Evidence correction " + correction + "; reassess dependent conclusions"
    for kind in ("hypothesis", "task", "scenario", "checkpoint"):
        for item_id, item in state[kind].items():
            refs_used = record_evidence(item) | set(item.get("result", {}).get("evidence", []))
            hit = refs_used & inactive or (kind == "hypothesis" and item_id in affected)
            hit = hit or (kind == "task" and item_id in affected_tasks)
            hit = hit or (kind == "scenario" and item_id in affected_scenarios)
            hit = hit or (kind == "checkpoint" and item.get("baseline") in affected_scenarios)
            if not hit:
                continue
            item.update(needs_review=reason, rev=item["rev"] + 1, updated_at=now())
            if kind == "hypothesis":
                item["status"] = "unresolved"
                item.pop("decision_review", None)
            elif kind == "scenario" and item["reproduction"] == "retained":
                item["reproduction"] = "uncertain"
            elif kind == "task" and item["status"] == "done":
                item["status"] = "submitted"
    if state["status"] == "closed":
        # The old closure remains in history. A correction is a reason to review,
        # not proof that the opposite conclusion is true.
        state.update(status="active", closure=None)


def handoff(state, task_id):
    from materials import inventory
    require(task_id in state["task"], "unknown task")
    task = state["task"][task_id]
    paths = state["case"].get("materials", [])
    material_list = inventory(paths)
    inactive = inactive_evidence(state)
    observations = {eid: {**item, "usable_as_support": eid not in inactive}
                    for eid, item in state["evidence"].items()}
    available = {item["source"] for item in material_list["items"]}
    inspected = {source for eid, item in state["evidence"].items() if eid not in inactive
                 for source in item.get("inspected", [])}
    return {"original_problem": state["case"], "case_rev": state["rev"], "task": task,
            "scenario": state["scenario"].get(task.get("scenario")),
            "available_materials": material_list, "recorded_observations": observations,
            "coverage": {"reported_inspected": sorted(inspected),
                         "not_reported_inspected": sorted(available - inspected),
                         "unlisted_inspections": sorted(inspected - available),
                         "meaning": "Agent-reported source visits only; read each observation's scope for actual fields/ranks examined."},
            "hypotheses_to_check": {hid: state["hypothesis"][hid] for hid in task.get("hypotheses", [])},
            "instructions": "Read source scope and limits. Recorded validity is an agent assessment, not a guarantee. "
                            "Challenge task premises; an unsupported premise is a valid finding. Report observations, "
                            "inferences, counterexamples and unexamined scope separately. Do not infer missing data "
                            "from a parent agent's selection. Shared sources are not independent confirmations.",
            "warnings": ([] if paths else ["No material paths registered; obtain the original input inventory before generalizing."])}


def version_matches(old, data):
    require(type(data.get("rev")) is int and data["rev"] == (old or {}).get("rev", 0),
            "revision conflict: read show, reconcile changes, then retry with current rev")


def acyclic(state, kind, item_id, parents):
    pending, seen = list(parents), set()
    while pending:
        node = pending.pop()
        require(node != item_id, f"cycle in {kind}")
        if node in seen:
            continue
        seen.add(node)
        item = state[kind][node]
        pending.extend(item.get("parents", []) if kind == "hypothesis" else
                       item.get("depends_on", []) if kind == "task" else
                       [item["parent"]] if item.get("parent") else [])


def put(state, kind, data):
    require(isinstance(data, dict), "record must be an object")
    nonempty(data, "id")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", data["id"]), "invalid record ID")
    old = state[kind].get(data["id"])
    version_matches(old, data)
    if kind == "evidence":
        require(old is None, "evidence is immutable: append a correction with a new ID")
        nonempty(data, "observation", "source", "scope", "context", "limits")
        require(isinstance(data.get("inspected", []), list) and
                all(isinstance(v, str) and v.strip() for v in data.get("inspected", [])), "inspected: list of inventory source IDs required")
        require(data.get("validity") in {"valid", "invalid", "uncertain"}, "invalid evidence validity")
        refs(state, data, "depends_on", "evidence")
        supersedes = refs(state, data, "supersedes", "evidence")
        require(not set(supersedes) & set(data.get("depends_on", [])), "correction cannot depend on evidence it supersedes")
        if supersedes:
            nonempty(data, "correction_reason")
    elif kind == "hypothesis":
        nonempty(data, "claim", "basis", "prediction", "reason")
        require(data.get("status") in {"open", "supported", "ruled_out", "unresolved", "confirmed"}, "invalid hypothesis status")
        ids = refs(state, data, "evidence", "evidence")
        parents = refs(state, data, "parents", "hypothesis")
        acyclic(state, kind, data["id"], parents)
        if data["status"] in {"supported", "ruled_out", "confirmed"}:
            valid_evidence(state, ids)
        if data["status"] in {"ruled_out", "confirmed"}:
            decision_review(state, data)
    elif kind == "scenario":
        nonempty(data, "description", "changes", "cost", "reason")
        require(data.get("reproduction") in {"original", "retained", "not_observed", "different", "uncertain"}, "invalid reproduction state")
        parent = data.get("parent")
        require(parent is None or isinstance(parent, str) and parent in state[kind], "unknown parent scenario")
        acyclic(state, kind, data["id"], [parent] if parent else [])
        ids = refs(state, data, "evidence", "evidence")
        if data["reproduction"] == "retained":
            valid_evidence(state, ids)
    elif kind == "task":
        nonempty(data, "question", "action", "acceptance", "owner", "reason")
        require(data.get("status") in TASK_STATES, "invalid task status")
        transitions = {None: {"pending"}, "pending": {"pending", "running", "blocked", "cancelled"},
                       "running": {"running", "blocked", "cancelled"},
                       "blocked": {"blocked", "pending", "running", "cancelled"}}
        require(data["status"] in transitions.get((old or {}).get("status"), set()),
                "invalid transition: use submit/accept for results; create a new task for another attempt")
        require("result" not in data and "review" not in data, "result/review reserved for submit/accept")
        deps = refs(state, data, "depends_on", "task")
        acyclic(state, kind, data["id"], deps)
        refs(state, data, "hypotheses", "hypothesis")
        scenario = data.get("scenario")
        require(scenario is None or isinstance(scenario, str) and scenario in state["scenario"], "unknown scenario")
        if data["status"] == "running":
            require(all(state["task"][dep]["status"] == "done" for dep in deps), "dependencies not accepted")
        if "run" in data:
            require(isinstance(data["run"], dict), "run must be an object")
    else:
        require(data["id"] == "current", "checkpoint ID must be current")
        nonempty(data, "summary", "next_action", "reason", "environment")
        refs(state, data, "evidence", "evidence")
        baseline = data.get("baseline")
        require(baseline is None or isinstance(baseline, str) and baseline in state["scenario"], "unknown baseline")
        if baseline:
            require(state["scenario"][baseline]["reproduction"] in {"original", "retained"}, "baseline must preserve the problem")
    item = copy.deepcopy(data)
    if kind != "evidence":
        item.pop("needs_review", None)
    item.update(rev=data["rev"] + 1, updated_at=now())
    before = inactive_evidence(state) if kind == "evidence" and data.get("supersedes") else set()
    state[kind][data["id"]] = item
    if kind == "evidence" and data.get("supersedes"):
        reconcile_correction(state, data["id"], inactive_evidence(state) - before)
    return item


def change(state, command, data, kind=None):
    require(state.get("schema") == 1, "unsupported schema")
    correction = command == "put" and kind == "evidence" and data.get("supersedes")
    require(state["status"] == "active" or command == "reopen" or correction, "case closed: use reopen with a reason")
    if command == "put":
        result = put(state, kind, data)
    elif command in {"submit", "accept"}:
        nonempty(data, "task_id")
        task = state["task"].get(data["task_id"])
        require(task is not None, "unknown task")
        version_matches(task, data)
        if command == "submit":
            require(task["status"] in {"running", "blocked"}, "task must be running or blocked")
            evidence = data.get("new_evidence", [])
            require(isinstance(evidence, list), "new_evidence must be a list")
            for item in evidence:
                put(state, "evidence", item)
            result = data.get("result")
            require(isinstance(result, dict), "result required")
            nonempty(result, "summary", "limitations")
            require(result.get("outcome") in {"supports", "contradicts", "inconclusive", "invalid", "observation"}, "invalid outcome")
            ids = refs(state, result, "evidence", "evidence")
            if result["outcome"] in {"supports", "contradicts"}:
                valid_evidence(state, ids)
            task.update(status="submitted", result=copy.deepcopy(result))
        else:
            require(task["status"] == "submitted", "task must be submitted")
            nonempty(data, "reason")
            disposition = data.get("disposition", "usable")
            require(disposition in {"usable", "not_usable"}, "invalid review disposition")
            if disposition == "usable" and task["result"]["outcome"] in {"supports", "contradicts"}:
                valid_evidence(state, task["result"].get("evidence", []))
            task.update(status="done", review=data["reason"], disposition=disposition)
            task.pop("needs_review", None)
        task.update(rev=task["rev"] + 1, updated_at=now())
        result = task
    elif command == "close":
        version_matches({"rev": state["rev"]}, data)
        nonempty(data, "conclusion", "scope", "limitations")
        require(data.get("outcome") in {"root_cause", "fix_verified", "narrowed", "blocked"}, "invalid case outcome")
        require(not any(t["status"] in {"running", "submitted"} for t in state["task"].values()),
                "reconcile running/submitted tasks before closing")
        ids = refs(state, data, "evidence", "evidence")
        if data["outcome"] in {"root_cause", "fix_verified"}:
            valid_evidence(state, ids)
            require(data.get("route") in {"evidence_chain", "targeted_fix"}, "closure route required")
            nonempty(data, "acceptance_check")
            decision_review(state, data)
            require(all(t["status"] in {"done", "cancelled"} for t in state["task"].values()),
                    "finish or explicitly cancel remaining tasks before successful closure")
        state.update(status="closed", closure=copy.deepcopy(data))
        result = state["closure"]
    elif command == "reopen":
        version_matches({"rev": state["rev"]}, data)
        require(state["status"] == "closed", "case is already active")
        nonempty(data, "reason")
        state.update(status="active", closure=None)
        result = {"reason": data["reason"]}
    else:
        raise ValueError("unknown command")
    state["rev"] += 1
    state["updated_at"] = now()
    state["history"].append({"rev": state["rev"], "at": state["updated_at"],
                             "command": command, "kind": kind, "input": copy.deepcopy(data)})
    return result


@contextmanager
def locked(directory):
    """OS lock released on process death; no stale-lock deletion needed."""
    with open(directory / ".lock", "a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            acquire = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: (stream.seek(0), msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1))
        else:
            import fcntl
            acquire = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as exc:
            raise ValueError("case busy: another writer is committing; retry after it finishes") from exc
        try:
            yield
        finally:
            release()


def atomic_write(path, state):
    fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(directory, command, data=None, kind=None, history=False):
    directory = Path(directory).resolve()
    if command == "init":
        directory.mkdir(parents=True, exist_ok=True)
    require(directory.is_dir(), "case directory does not exist; use init")
    path = directory / "state.json"
    if command in {"show", "handoff"}:
        # Writers replace a complete JSON file atomically. Readers need no write
        # permission or lock file and can inspect an in-flight case snapshot.
        state = read_json(path)
        require(state.get("schema") == 1, "unsupported schema")
        if command == "handoff":
            return {"case_path": str(directory), **handoff(state, data["task_id"])}
        if not history:
            state.pop("history", None)
        return state
    with locked(directory):
        if command == "init":
            require(not path.exists(), "case already exists: use show to resume")
            nonempty(data, "title", "goal", "symptom", "acceptance")
            data = copy.deepcopy(data)
            if "materials" in data:
                require(isinstance(data["materials"], list) and all(isinstance(p, str) and p.strip() for p in data["materials"]),
                        "materials must be a list of supplied local paths")
                data["materials"] = [str(Path(p).expanduser().resolve()) for p in data["materials"]]
            state = {"schema": 1, "rev": 0, "status": "active", "case": data,
                     "updated_at": now(), "closure": None, "history": []}
            state.update({key: {} for key in KINDS})
            atomic_write(path, state)
            return {"case": str(path), "rev": 0}
        state = read_json(path)
        if command == "prepare-task":
            require(data.get("rev") == 0 and data.get("status") == "pending", "prepare-task creates a new pending task")
            require(data.get("id") not in state["task"], "task already exists; use handoff to resume")
            change(state, "put", data, "task")
            atomic_write(path, state)
            return {"case_path": str(directory), "execution_started": False, **handoff(state, data["id"])}
        result = change(state, command, data, kind)
        atomic_write(path, state)
        return {"case_rev": state["rev"], "record": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="case directory, e.g. .debug-agent/nan-001")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "put", "submit", "accept", "close", "reopen", "prepare-task"):
        child = commands.add_parser(command)
        child.add_argument("--file", required=True, help="UTF-8 JSON payload path")
        if command == "put":
            child.add_argument("--kind", choices=KINDS, required=True)
    commands.add_parser("show").add_argument("--history", action="store_true")
    commands.add_parser("handoff").add_argument("--task", required=True)
    args = parser.parse_args()
    try:
        data = read_json(args.file) if hasattr(args, "file") else {"task_id": args.task} if hasattr(args, "task") else None
        result = execute(args.case, args.command, data,
                         getattr(args, "kind", None), getattr(args, "history", False))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    sys.exit(main())
