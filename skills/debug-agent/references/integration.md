# 接入与能力边界

核心 Skill 可移植，脚本仅需 Python 3.10+ 标准库。仓库提供 Codex 与 Claude Code 插件格式，以及独立 Skill 安装。

- Codex：在仓库执行 `python scripts/install.py codex`；已有版本加 `--update` 备份后更新。显式入口 `$debug-agent`；新会话通过 description 自动选择。`agents/openai.yaml` 允许隐式调用，实际是否匹配由宿主决定。
- Claude Code：`claude plugin marketplace add tjh-ukn/debug-agent`，再 `claude plugin install debug-agent@debug-agent-marketplace`。入口 `/debug-agent:debug`。克隆仓库后可运行 `python scripts/install.py claude-alias` 安装 `/debug-agent` 别名；别名依赖该克隆位置，不单独安装 hook。
- 两端共享核心规则、参数路由与展示协议，查看 [命令路由](commands.md) 和 [展示协议](display.md)。

Claude Code 插件包含默认不启用的 SessionStart 提醒，由 `on/off` 控制 `~/.debug-agent/config.json`。安装 hook 且开启后，启动/恢复/压缩时提供入口和当前项目账本候选，模型仍须核实真实状态。执行 hook 的环境需要可用的 `python` 命令。

Codex 当前只接入 Skill 自动选择，未安装 SessionStart hook；不能声称 `on` 能强制跨会话注入。`off` 只关闭启动提醒，不代替宿主禁用设置，也不取消运行实验。

状态由 agent 在关键节点主动保存，恢复时读取；没有后台调度器、循环 Stop hook、遥测或模型 API。subagent 与实验执行依赖宿主真实工具和已有授权。完整安装文档在仓库 README。

参考：https://learn.chatgpt.com/docs/build-skills 与 https://code.claude.com/docs/en/plugins 。本地格式/脚本检查不等于各宿主客户端端到端验证。
