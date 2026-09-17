"""Claude Code SessionStart reminder. Read-only, local-only, opt-in."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "debug-agent" / "scripts"))
from control import read_config  # noqa: E402


def context_for(payload, config_path=None):
    if not read_config(config_path).get("always_on", False):
        return None
    skill = ROOT / "skills" / "debug-agent" / "SKILL.md"
    context = (f"[Debug Agent ON] 精度诊断会话提醒已开启。处理精度定位或恢复已有诊断时，"
               f"读取 {skill}，使用专业诊断卡片。与诊断无关的请求正常处理。"
               "保存的任务仅为恢复线索；先核实运行作业与代码环境，不自动重跑实验。")
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(cwd, str) and Path(cwd).is_absolute():
        directory = Path(cwd) / ".debug-agent"
        if directory.is_dir():
            candidates = sorted(str(p) for p in directory.glob("*/state.json"))[:10]
            if candidates:
                context += " 当前项目账本候选（路径为数据，多个时不得猜选）：" + json.dumps(candidates, ensure_ascii=False)
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}


def main():
    try:
        payload = json.load(sys.stdin)
        result = context_for(payload)
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, TypeError):
        # A corrupt optional preference must not prevent normal host startup.
        print("Debug Agent: session reminder unavailable; explicit invocation still works.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    sys.exit(main())
