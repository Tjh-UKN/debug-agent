"""Read-only case discovery and recovery snapshots; never launches or changes jobs."""
import argparse
import json
from pathlib import Path
import sys

from case import execute, inactive_evidence, read_json
import investigation


def discover(start):
    start = Path(start).expanduser().resolve()
    if not start.is_dir():
        raise ValueError("project directory does not exist")
    project = None
    for directory in (start, *start.parents):
        if (directory / ".debug-agent").is_dir():
            project = directory
            break
        if (directory / ".git").exists() or directory == Path.home():
            break
    result = {"project": str(project) if project else None, "active": [], "closed": [], "errors": []}
    if project is None:
        return result
    for path in sorted((project / ".debug-agent").glob("*/state.json")):
        try:
            data = read_json(path)
            if data.get("schema") != 1 or data.get("status") not in {"active", "closed"}:
                raise ValueError("unsupported case schema/status")
            if not isinstance(data.get("case"), dict):
                raise ValueError("missing case metadata")
            result[data["status"]].append({"path": str(path), "title": data["case"].get("title", path.parent.name),
                                           "outcome": (data.get("closure") or {}).get("outcome"),
                                           "updated_at": data.get("updated_at", "")})
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            result["errors"].append({"path": str(path), "error": str(exc)})
    for status in ("active", "closed"):
        result[status].sort(key=lambda entry: str(entry["updated_at"]), reverse=True)
    return result


def investigation_snapshot(state):
    """Where the search stands: focus paths, frontier, pruned and stale branches.

    Recovers the investigation state, not just the execution queue. Read-only:
    branch health is derived and never written back; legacy cases without
    registered lineages show only what exists and never get paths guessed.
    """
    hypotheses = state.get("hypothesis", {})
    health = {hid: investigation.branch_health(state, hid) for hid in hypotheses}
    focus = [hid for hid in (state.get("checkpoint", {}).get("current") or {}).get("focus_hypotheses") or []
             if hid in hypotheses]
    frontier = investigation.active_frontier(state)
    pruned = sorted(hid for hid, item in health.items() if item["state"] == "pruned")
    stale = sorted(hid for hid, item in health.items() if item["state"] == "stale")
    dangling = sorted(hid for hid, node in hypotheses.items()
                      if node.get("investigates") and node["investigates"] not in hypotheses)
    targets = focus or [node["id"] for node in frontier]
    paths, broken = [], []
    for hid in targets:
        try:
            paths.append(investigation.investigation_path(state, hid))
        except ValueError:
            broken.append(hid)
    return {"focus": focus,
            "frontier": frontier,
            "pruned": pruned,
            "stale": stale,
            "current_paths": paths,
            "unregistered_lineage": sorted(set(broken) | set(dangling)),
            "note": "paths come from registered investigates edges only; missing lineages are listed, never inferred"}


def snapshot(state):
    checkpoint = state.get("checkpoint", {}).get("current")
    baseline_id = (checkpoint or {}).get("baseline")
    baseline = state.get("scenario", {}).get(baseline_id)
    pending = {status: [] for status in ("running", "submitted", "blocked", "pending")}
    for task in state.get("task", {}).values():
        if task["status"] in pending:
            pending[task["status"]].append(task)
    warnings = []
    inactive = sorted(inactive_evidence(state))
    if inactive:
        warnings.append("以下证据无效、已撤回或依赖失效前提，不能继续支持结论：" + ", ".join(inactive))
    review = [f"{kind}:{key}" for kind in ("hypothesis", "task", "scenario", "checkpoint")
              for key, item in state.get(kind, {}).items() if item.get("needs_review")]
    if review:
        warnings.append("证据更正影响以下判断；先重审前提，不自动重跑：" + ", ".join(review))
    if state["status"] == "closed":
        warnings.append("案例已关闭；若用户要求继续，先核对旧结论并说明重开原因。")
    if not checkpoint:
        warnings.append("没有 checkpoint；从已有任务与证据恢复，不自动创建新案例。")
    else:
        saved_at = checkpoint.get("updated_at", "")
        changed = [f"{kind}:{key}" for kind in ("task", "hypothesis", "evidence", "scenario")
                   for key, record in state.get(kind, {}).items() if record.get("updated_at", "") > saved_at]
        if changed:
            warnings.append("checkpoint 后有记录变化，重新核对下一步：" + ", ".join(changed))
    if baseline_id and (not baseline or baseline.get("reproduction") not in {"original", "retained"}):
        warnings.append("checkpoint 的基线已不再确认保留原问题表现，需重选或核查场景。")
    if pending["running"]:
        warnings.append("running 是保存时的状态，不代表作业当前仍活着；核实 host/job_id/产物与版本后再行动，禁止仅凭恢复动作重提实验。")
    if pending["submitted"]:
        warnings.append("存在已提交未验收的结果，先审查原始证据，不重跑已完成的核查。")
    return {"case": state["case"], "case_rev": state["rev"], "status": state["status"],
            "closure": state.get("closure"), "checkpoint": checkpoint, "baseline": baseline,
            "tasks": pending, "hypotheses": state.get("hypothesis", {}),
            "evidence": state.get("evidence", {}), "inactive_evidence": inactive, "warnings": warnings,
            "investigation": investigation_snapshot(state),
            "job_execution": "none; read-only snapshot"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list").add_argument("--project", default=".")
    commands.add_parser("resume").add_argument("--case", required=True)
    args = parser.parse_args()
    try:
        result = discover(args.project) if args.command == "list" else snapshot(execute(args.case, "show"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    sys.exit(main())
