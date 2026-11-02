# Debug Agent

帮助用户以可复核证据找出 AI 训练与推理的报错、挂死及数值/状态异常根因，包括 loss 上扬、NaN/Inf、grad norm 爆炸、spike、跨设备差异和偶现复读。

以代码和运行证据联合分析，按需组合异常判定、依赖偏序、保真细化、去噪和实验停止判定。模型围绕关键未知选择动作，证据充分即交付，不要求先建任务树。[诊断结构](docs/diagnostic-architecture.md)说明这些操作的关系。

## 日常使用

在原对话中给出症状、代码/数据或已授权的运行环境即可：

| 宿主 | 显式入口 |
|---|---|
| Codex | `$debug-agent <问题描述>` |
| Pi | `/skill:debug-agent <问题描述>` |
| Claude Code | `/debug-agent:debug <问题描述>` |

例如：`$debug-agent 训练在 step 1200 挂死，分析已有各 rank 日志和线程栈，不重启作业。`

也可以只分析已有材料，不运行训练。隐式调用由宿主选择，需要确认加载时使用显式入口。交付区分根因确认、针对性修复验证、范围缩小和受阻待续。

## 按需能力与边界

[核心入口](skills/debug-agent/SKILL.md)路由到相关参考与工具：

| 能力 | 用途 |
|---|---|
| [msprobe](skills/debug-agent/references/msprobe.md) | dump 对齐、比较、缓存查询及可逆差异聚焦 |
| [诊断操作](skills/debug-agent/references/diagnosis.md) | 显式样本判据、依赖 DAG 首异常候选与未知边界 |
| [实验判定](skills/debug-agent/references/experiments.md) | 检查前提、回答/反证、冲突与停止条件 |
| [证据快照](skills/debug-agent/references/evidence.md) | 保存原始字节、校验与精确摘录 |
| [恢复](skills/debug-agent/references/commands.md) | 按需接续已有案例，保留更正与失效前提 |

工具不认证根因，也不直接终止进程；运行权限、执行和真实停止由宿主承接。本项目没有独立模型服务或后台调度器。

## 安装与更新

需要 Python 3.10+，脚本仅依赖标准库。在宿主实际运行的 Windows/Linux/WSL 环境安装；Linux/WSL 若没有 `python`，使用 `python3` 执行下面的命令。

```sh
git clone https://github.com/tjh-ukn/debug-agent.git
cd debug-agent
python scripts/install.py codex          # Codex；Pi 改为 pi
python scripts/install.py codex --update # 备份差异文件后更新
python scripts/install.py codex --check  # 只读检查内容与路由是否一致
```

Codex 安装到 `$CODEX_HOME/skills/debug-agent`（缺省 `~/.codex/skills/debug-agent`）；Pi 安装到 `~/.pi/agent/skills/debug-agent`。仅分发运行文件；`--update` 备份替换和退役文件，失败尝试回滚，不修改模型配置。宿主未刷新技能时重新启动后检查。

Claude Code：

```sh
claude plugin marketplace add tjh-ukn/debug-agent
claude plugin install debug-agent@debug-agent-marketplace
```

可选别名 `/debug-agent`：在保留的克隆中执行 `python scripts/install.py claude-alias`。Claude Code 的启动提醒默认关闭，显式 on/off 可切换；它只提醒读取入口，不启动实验。Codex/Pi 没有同类注入 hook。更多限制见[接入边界](skills/debug-agent/references/integration.md)。

## 验证与维护

```sh
python -m unittest discover -s tests -t .
```

测试集中在 `tests/`，不随 Skill 分发。[评估计划](docs/diagnostic-effectiveness.md)、[验证记录](docs/validation.md)与[合成案例](evals/README.md)分别覆盖工具、诊断行为和实际成本；脚本通过不证明真实定位提速。

旧 panel 卡片接口已退役，原始状态用 `case.py --case <dir> show` 查看；已有 case/schema、恢复、更正传播及 trace 查询保留。私有案例、凭据和本机产物不入库。
