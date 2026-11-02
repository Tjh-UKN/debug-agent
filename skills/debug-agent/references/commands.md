# 状态与恢复

普通诊断复用当前会话与笔记。status/evidence/again/done-check 分别汇报进展、证据、调整路径或验收，不自动建账本或重跑实验。

已有案例用 `python <skill-dir>/scripts/recovery.py resume --case <case-dir>` 只读恢复，核实保存的运行身份、版本、失效前提和待验收结果；历史 running 不代表实时状态。仅在未知案例路径且确需寻找时用 `recovery.py list --project <cwd>`，多个候选不能猜选。

需要持久写入或节点交接再读[账本协议](tasks.md)。`trace.py --case <dir> tree|path|why|impact|frontier` 可只读查询调查来源、结论前提与更正影响；它与运行依赖偏序不同。旧 panel 卡片接口已退役，查看原始状态可用 `case.py --case <dir> show`。

on/off 使用 `control.py on|off`，只控制 Claude Code 的可选启动提醒；help 参见[接入边界](integration.md)。
