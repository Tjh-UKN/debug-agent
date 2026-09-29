# 状态与恢复

普通问题按 [核心 Skill](../SKILL.md) 直接诊断。以下为用户显式请求时的辅助入口，不因读取本文件自动建账本、检查全部状态或展示卡片。

| 参数 | 行为 |
|---|---|
| status / 状态 | 说明当前已知、关键未知和下一步；有账本时只读其状态 |
| evidence / 证据 | 给出观察、原始来源、范围与结论关联 |
| again / 换个方法 | 根据未解决的缺口调整核查，不机械重跑或重启调查 |
| done-check / 验收 | 对照目标与决定性证据检查是否完成，不靠任务计数判断 |
| resume / 继续 | 读取已有记录，核实作业、版本和产物后继续 |
| on / off | `scripts/control.py on|off`；仅控制已安装 Claude Code hook 的启动提醒 |
| help / 帮助 | 说明当前宿主实际支持的入口，见[接入边界](integration.md) |

默认用简短文字汇报，没有账本时复用对话与现有笔记。案例路径采用用户指定或会话已确认的路径；确需寻找存档才运行 `python <skill-dir>/scripts/recovery.py list --project <cwd>`。多个候选无法区分时让用户选择。

已知案例用 `python <skill-dir>/scripts/recovery.py resume --case <case-dir>` 读取恢复摘要；它不执行任务。处理版本变化、失效证据和待验收结果，不能把保存时的 running 当作当前运行事实。需持久写入或节点交接再读[账本协议](tasks.md)。

兼容工具：`panel.py --case <case-dir> --view start|status|evidence|done` 展示已有账本；`trace.py --case <case-dir> tree|path|why|impact|frontier` 查询调查来源、结论依据和依赖影响。两者只读，不是诊断前置步骤；完整参数用各脚本 `--help`。
