"""Read-only projections over the investigation tree and logical dependency DAG.

Two relations answer two different questions and are never mixed here:

- ``investigates``: why was this node examined at all (search lineage). It forms
  the Investigation Tree used for path recovery, pruning projection and
  backtracking. A ruled-out branch only prunes its own subtree.
- ``parents``: why is this conclusion believed (AND-shaped logical
  prerequisites). It drives correction withdrawal via case.reconcile_correction.

Every function takes a state dict and returns plain data. Nothing here writes
state, launches work or creates tasks: branch health is derived on each call
and never persisted, so history keeps its original recorded statuses.
"""
from case import inactive_evidence

COMPLETENESS = ("projection covers registered references only; unregistered prose "
                "premises are invisible and reported as missing, never guessed")


def children(state):
    """Map each investigated hypothesis to the candidates created to investigate it."""
    index = {}
    for hid, node in state.get("hypothesis", {}).items():
        target = node.get("investigates")
        if target:
            index.setdefault(target, []).append(hid)
    return {key: sorted(values) for key, values in index.items()}


def investigation_path(state, hid):
    """Root→hid lineage along investigates only; raises on cycles or broken lineage."""
    hypotheses = state.get("hypothesis", {})
    if hid not in hypotheses:
        raise ValueError(f"unknown hypothesis {hid}")
    path, seen = [], set()
    current = hid
    while current:
        if current in seen:
            raise ValueError("cycle in investigation lineage")
        seen.add(current)
        node = hypotheses.get(current)
        if node is None:
            raise ValueError(f"investigation lineage references missing hypothesis {current}")
        path.append(current)
        current = node.get("investigates")
    path.reverse()
    return path


def logical_dependencies(state, hid):
    """Registered AND-shaped prerequisites of a conclusion (the parents edge)."""
    return sorted(state.get("hypothesis", {}).get(hid, {}).get("parents", []))


def logical_dependents(state, hid):
    """Which conclusions list hid among their registered prerequisites."""
    return sorted(i for i, node in state.get("hypothesis", {}).items()
                  if hid in node.get("parents", []))


def branch_health(state, hid):
    """Derived search projection: active, pruned or stale, plus the blocking node.

    Recorded statuses are never modified. A branch is pruned when it or an
    investigation ancestor was ruled out; stale when a logical prerequisite
    upstream failed (needs_review/unresolved). Siblings are never affected.
    """
    hypotheses = state.get("hypothesis", {})
    current = hid
    while current:
        node = hypotheses.get(current)
        if node is None:
            return {"state": "unknown", "blocked_by": current}
        if node["status"] == "ruled_out":
            return {"state": "pruned", "blocked_by": current}
        if node.get("needs_review") or node["status"] == "unresolved":
            return {"state": "stale", "blocked_by": current}
        current = node.get("investigates")
    return {"state": "active", "blocked_by": None}


def investigation_tree(state):
    """Structured tree projection keeping recorded status plus derived health."""
    hypotheses = state.get("hypothesis", {})
    index = children(state)

    def build(hid):
        node = hypotheses[hid]
        return {"id": hid, "claim": node["claim"], "status": node["status"],
                "investigates": node.get("investigates"),
                "investigation_question": node.get("investigation_question"),
                "branch_health": branch_health(state, hid),
                "children": [build(child) for child in index.get(hid, [])]}

    roots = sorted(hid for hid, node in hypotheses.items() if not node.get("investigates"))
    orphans = sorted(hid for hid, node in hypotheses.items()
                     if node.get("investigates") and node["investigates"] not in hypotheses)
    return {"roots": [build(root) for root in roots],
            "orphans": [build(oid) for oid in orphans]}


def active_frontier(state):
    """Active candidates with no deeper active child; the current search leaves.

    A confirmed node can still sit on the frontier: confirming where the fault
    first appears does not confirm why. Focus hints from the checkpoint only
    reorder presentation elsewhere; they do not change these structural facts.
    """
    index = children(state)
    frontier = []
    for hid in sorted(state.get("hypothesis", {})):
        if branch_health(state, hid)["state"] != "active":
            continue
        if any(branch_health(state, child)["state"] == "active" for child in index.get(hid, [])):
            continue
        node = state["hypothesis"][hid]
        frontier.append({"id": hid, "claim": node["claim"], "status": node["status"],
                         "investigates": node.get("investigates"),
                         "investigation_question": node.get("investigation_question")})
    return frontier


def why_trace(state, hid):
    """Audit path of what makes a conclusion believable: parents + direct evidence.

    Only parents and registered evidence/decision_review references are walked;
    investigation lineage is deliberately ignored here (see investigation_path).
    """
    hypotheses = state.get("hypothesis", {})
    evidence = state.get("evidence", {})
    if hid not in hypotheses:
        raise ValueError(f"unknown hypothesis {hid}")
    inactive = inactive_evidence(state)
    nodes, seen = [], set()

    def walk(current):
        if current in seen or current not in hypotheses:
            return
        seen.add(current)
        node = hypotheses[current]
        review = node.get("decision_review") or {}
        cited = sorted(set(node.get("evidence", [])) | set(review.get("evidence", [])))
        nodes.append({"id": current, "claim": node["claim"], "status": node["status"],
                      "parents": sorted(node.get("parents", [])),
                      "evidence": [{"id": eid,
                                    "validity": evidence[eid]["validity"],
                                    "usable_as_support": eid not in inactive}
                                   for eid in cited if eid in evidence],
                      "missing_evidence": [eid for eid in cited if eid not in evidence],
                      "missing_parents": [pid for pid in node.get("parents", []) if pid not in hypotheses]})
        for parent in sorted(node.get("parents", [])):
            walk(parent)

    walk(hid)
    return {"root": hid, "nodes": nodes, "completeness": COMPLETENESS}


def impact_trace(state, kind, item_id):
    """What would lose support if this evidence or hypothesis failed. No mutation.

    Mirrors the reachability of reconcile_correction over registered references
    only: evidence withdrawal reaches hypotheses, scenarios and tasks; a failing
    hypothesis reaches its transitive logical dependents and their tasks.
    """
    hypotheses = state.get("hypothesis", {})
    if kind not in {"hypothesis", "evidence"}:
        raise ValueError("impact kind must be hypothesis or evidence")
    if kind == "hypothesis":
        if item_id not in hypotheses:
            raise ValueError(f"unknown hypothesis {item_id}")
    elif item_id not in state.get("evidence", {}):
        raise ValueError(f"unknown evidence {item_id}")

    def evidence_cited(record):
        review = record.get("decision_review") or {}
        return set(record.get("evidence", [])) | set(review.get("evidence", []))

    affected_hypotheses = set()
    affected_scenarios = set()
    if kind == "evidence":
        affected_hypotheses.update(hid for hid, node in hypotheses.items() if item_id in evidence_cited(node))
        affected_scenarios.update(sid for sid, node in state.get("scenario", {}).items()
                                  if item_id in node.get("evidence", []))
    else:
        affected_hypotheses.add(item_id)
    while True:
        more = {hid for hid, node in hypotheses.items() if set(node.get("parents", [])) & affected_hypotheses}
        if more <= affected_hypotheses:
            break
        affected_hypotheses.update(more)
    while True:
        more = {sid for sid, node in state.get("scenario", {}).items() if node.get("parent") in affected_scenarios}
        if more <= affected_scenarios:
            break
        affected_scenarios.update(more)
    affected_tasks = set()
    for tid, node in state.get("task", {}).items():
        cited = evidence_cited(node) | set(node.get("result", {}).get("evidence", []))
        if (kind == "evidence" and item_id in cited) \
                or set(node.get("hypotheses", [])) & affected_hypotheses \
                or node.get("scenario") in affected_scenarios:
            affected_tasks.add(tid)
    while True:
        more = {tid for tid, node in state.get("task", {}).items()
                if set(node.get("depends_on", [])) & affected_tasks}
        if more <= affected_tasks:
            break
        affected_tasks.update(more)
    checkpoint = state.get("checkpoint", {}).get("current") or {}
    checkpoint_hit = bool((kind == "evidence" and item_id in set(checkpoint.get("evidence", [])))
                          or (checkpoint.get("baseline") is not None and checkpoint["baseline"] in affected_scenarios))
    closure_hit = bool(state.get("status") == "closed"
                       and (affected_hypotheses or affected_tasks or affected_scenarios or checkpoint_hit))
    return {"kind": kind, "id": item_id,
            "hypotheses": sorted(affected_hypotheses),
            "scenarios": sorted(affected_scenarios),
            "tasks": sorted(affected_tasks),
            "checkpoint_affected": checkpoint_hit,
            "closure_would_reopen": closure_hit,
            "note": COMPLETENESS}
