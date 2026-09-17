"""Render fact-only diagnostic cards from a persisted case, without mutation."""
import argparse
import sys
import unicodedata

from case import execute

STATUS = {"pending": "待执行", "running": "运行中", "blocked": "受阻", "submitted": "待验收",
          "done": "已验收", "cancelled": "已取消", "open": "待核查", "supported": "有支持证据",
          "ruled_out": "已排除", "unresolved": "未决", "confirmed": "已确认",
          "valid": "有效", "invalid": "无效", "uncertain": "未确认"}
OUTCOMES = {"root_cause": "根因已确认", "fix_verified": "修复已验证", "narrowed": "范围已缩小", "blocked": "受阻待续"}


def width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def clean(text):
    return " ".join("".join(c if not unicodedata.category(c).startswith("C") else " " for c in str(text)).split())


def fit(text, limit):
    value = clean(text)
    if width(value) > limit:
        clipped = ""
        for character in value:
            if width(clipped + character) > limit - 1:
                break
            clipped += character
        value = clipped + "…"
    return value + " " * max(0, limit - width(value))


def table(rows, widths):
    edge = lambda left, mid, right: left + mid.join("─" * (w + 2) for w in widths) + right
    lines = [edge("┌", "┬", "┐")]
    for index, row in enumerate(rows):
        lines.append("│ " + " │ ".join(fit(cell, w) for cell, w in zip(row, widths)) + " │")
        if index == 0 and len(rows) > 1:
            lines.append(edge("├", "┼", "┤"))
    lines.append(edge("└", "┴", "┘"))
    return "\n".join(lines)


def render(state, view="status"):
    checkpoint = state.get("checkpoint", {}).get("current", {})
    scenario_id = checkpoint.get("baseline")
    scenario = state.get("scenario", {}).get(scenario_id, {})
    closure = state.get("closure") or {}
    result = OUTCOMES.get(closure.get("outcome"), "进行中")
    lines = ["DEBUG AGENT · " + {"start": "诊断启动", "status": "诊断进度", "evidence": "证据卡", "done": "验收卡"}[view]]
    if view == "start":
        lines.append(table([("问题", state["case"]["title"]), ("目标", state["case"]["goal"]),
                            ("场景", scenario.get("description", "未登记")),
                            ("下一步", checkpoint.get("next_action", "根据现象和代码确定"))], (8, 64)))
    elif view == "evidence":
        records = state.get("evidence", {})
        if not records:
            lines.append("▎ 尚无已登记证据。")
        for eid, record in records.items():
            lines.append(table([("证据", eid), ("观察", record["observation"]),
                                ("有效性", STATUS[record["validity"]]), ("范围", record["limits"])], (8, 64)))
            lines.append("来源：" + clean(record["source"]))
    elif view == "done":
        lines.append(table([("结果", result), ("结论", closure.get("conclusion", "尚未提交闭环结论")),
                            ("路线", {"evidence_chain": "严谨证据链", "targeted_fix": "针对性修复验证"}.get(closure.get("route"), "未登记")),
                            ("范围", closure.get("scope", "未登记")), ("限制", closure.get("limitations", "未登记"))], (8, 64)))
        lines.append("证据：" + (", ".join(closure.get("evidence", [])) or "未关联"))
        lines.append("▎ 状态卡仅展示已登记结论；证据充分性由主 agent 按用户目标核查。")
    else:
        tasks = list(state.get("task", {}).values())
        done = sum(t["status"] == "done" for t in tasks)
        cancelled = sum(t["status"] == "cancelled" for t in tasks)
        if tasks:
            count = done * 10 // len(tasks)
            lines.append(f"已知任务 {'█' * count}{'░' * (10 - count)} {done}/{len(tasks)}；取消 {cancelled}（非定位完成度）")
            lines.append(table([("任务", "核查问题", "状态")] + [(t["id"], t["question"], STATUS[t["status"]]) for t in tasks], (8, 48, 12)))
        else:
            lines.append("▎ 尚无已登记任务，不生成完成百分比。")
        hypotheses = list(state.get("hypothesis", {}).values())
        if hypotheses:
            lines.append(table([("假设", "解释", "状态")] + [(h["id"], h["claim"], STATUS[h["status"]]) for h in hypotheses], (8, 48, 12)))
        lines.append("▎ 当前结果：" + result + "；下一步：" + clean(checkpoint.get("next_action", "未登记")))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--view", choices=("start", "status", "evidence", "done"), default="status")
    args = parser.parse_args()
    try:
        print(render(execute(args.case, "show"), args.view))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Panel unavailable: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    sys.exit(main())
