# 宿主接入边界

| 宿主 | 显式入口 | 安装方式 |
|---|---|---|
| Codex | `$debug-agent <问题>` | 源码仓库 `python scripts/install.py codex` |
| Pi | `/skill:debug-agent <问题>` | 在实际 Pi 环境执行 `python3 scripts/install.py pi` |
| Claude Code | `/debug-agent:debug <问题>` | 插件市场安装；可选别名由 `scripts/install.py claude-alias` 创建 |

脚本需 Python 3.10+，仅依赖标准库。更新加 `--update`，旧文件会备份；`--check` 只读比较受管理文件的内容与本地路由。详细安装命令在源码仓库 README。

隐式选择由宿主决定，不保证触发。Claude Code 的 SessionStart 提醒默认关闭，on/off 只保存提醒偏好；Codex/Pi 未实现同类 hook。别名指向本地克隆，移动克隆后需重装。更改提醒不启动或停止实验，也不改变授权。

实验、远程连接与子 agent 使用宿主已有能力。本项目不提供模型服务、设备权限、后台调度或自动重提作业；恢复须核实实际状态。
