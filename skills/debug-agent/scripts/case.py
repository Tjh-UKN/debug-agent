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
    require(ids and all(state["evidence"][i]["validity"] == "valid" for i in ids), "valid evidence required")


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
        nonempty(data, "observation", "source", "context", "limits")
        require(data.get("validity") in {"valid", "invalid", "uncertain"}, "invalid evidence validity")
    elif kind == "hypothesis":
        nonempty(data, "claim", "basis", "prediction", "reason")
        require(data.get("status") in {"open", "supported", "ruled_out", "unresolved", "confirmed"}, "invalid hypothesis status")
        ids = refs(state, data, "evidence", "evidence")
        parents = refs(state, data, "parents", "hypothesis")
        acyclic(state, kind, data["id"], parents)
        if data["status"] in {"supported", "ruled_out", "confirmed"}:
            valid_evidence(state, ids)
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
    item.update(rev=data["rev"] + 1, updated_at=now())
    state[kind][data["id"]] = item
    return item


def change(state, command, data, kind=None):
    require(state.get("schema") == 1, "unsupported schema")
    require(state["status"] == "active" or command == "reopen", "case closed: use reopen with a reason")
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
            task.update(status="done", review=data["reason"])
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
    with locked(directory):
        if command == "init":
            require(not path.exists(), "case already exists: use show to resume")
            nonempty(data, "title", "goal", "symptom", "acceptance")
            state = {"schema": 1, "rev": 0, "status": "active", "case": data,
                     "updated_at": now(), "closure": None, "history": []}
            state.update({key: {} for key in KINDS})
            atomic_write(path, state)
            return {"case": str(path), "rev": 0}
        state = read_json(path)
        if command == "show":
            require(state.get("schema") == 1, "unsupported schema")
            if not history:
                state.pop("history", None)
            return state
        result = change(state, command, data, kind)
        atomic_write(path, state)
        return {"case_rev": state["rev"], "record": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="case directory, e.g. .debug-agent/nan-001")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "put", "submit", "accept", "close", "reopen"):
        child = commands.add_parser(command)
        child.add_argument("--file", required=True, help="UTF-8 JSON payload path")
        if command == "put":
            child.add_argument("--kind", choices=KINDS, required=True)
    commands.add_parser("show").add_argument("--history", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(args.case, args.command, read_json(args.file) if hasattr(args, "file") else None,
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
