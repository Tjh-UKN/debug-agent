# Debug Agent

帮助模型以可复核证据定位 AI 训练与推理正确性问题：NaN/Inf、跨设备差异、梯度异常、状态相关错误和偶现复读。

产品核心是**数据与代码联合分析、有效取证和准确收敛**。模型决定具体分析、工具和实验；Skill 提供必要的数据契约与判断边界，不要求先建任务树、先缩减实验或完成固定检查表。

## 日常使用

在原对话中给出症状、代码/数据或已授权的运行环境即可：

| 宿主 | 显式入口 |
|---|---|
| Codex | `$debug-agent <问题描述>` |
| Pi | `/skill:debug-agent <问题描述>` |
| Claude Code | `/debug-agent:debug <问题描述>` |

例如：`$debug-agent 分析两端 dump 的 grad norm 差异，只使用已有材料，不运行训练。`

隐式调用由宿主选择；需要确认加载时使用显式入口。通常直接汇报判断与证据，结果区分根因确认、针对性修复验证、范围已缩小和受阻待续。

## 能力边界

| 能力 | 实际作用 |
|---|---|
| [诊断决策](skills/debug-agent/SKILL.md) | 分析后判断证据充分性，按缺口选择观察/对照/缩减；检查步骤是否改变关键判断，允许纠错回溯 |
| [msprobe 工具](skills/debug-agent/references/msprobe.md) | 按执行序、显式栈与 shape 对应读取所有提供卡，保留未匹配与采集边界，复用 scan/query |
| [运行时取证](skills/debug-agent/references/runtime.md) | 核对加载身份、对象生命周期、异步完成和插桩扰动 |
| [产物快照](skills/debug-agent/references/evidence.md) | 保存指定日志/配置/补丁的原始字节与 SHA256，校验后输出精确摘录；不证明因果解释 |
| [按需接续](skills/debug-agent/references/commands.md) | 恢复已有证据和作业记录；多节点交接才启用账本协议，兼容旧案例 |

没有独立模型服务、远程执行器或后台调度器。运行工具与权限来自宿主，用户约束优先。原场景能直接取证时无需另构造实验；代码和证据已经充分时直接交付。

## 安装与更新

需要 Python 3.10+，脚本仅依赖标准库。在宿主实际运行的 Windows/Linux/WSL 环境安装。

```sh
git clone https://github.com/tjh-ukn/debug-agent.git
cd debug-agent
python scripts/install.py codex          # Codex；Pi 改为 pi
python scripts/install.py codex --update # 备份差异文件后更新
python scripts/install.py codex --check  # 只读检查内容与路由是否一致
```

Codex 安装到 `$CODEX_HOME/skills/debug-agent`（缺省 `~/.codex/skills/debug-agent`）；Pi 安装到 `~/.pi/agent/skills/debug-agent`。安装器不修改模型配置，失败尝试回滚。宿主未刷新技能时重新启动后检查。

Claude Code：

```sh
claude plugin marketplace add tjh-ukn/debug-agent
claude plugin install debug-agent@debug-agent-marketplace
```

可选别名 `/debug-agent`：在保留的克隆中执行 `python scripts/install.py claude-alias`。Claude Code 的启动提醒默认关闭，显式 on/off 可切换；它只提醒读取入口，不启动实验。Codex/Pi 没有同类注入 hook。更多限制见[接入边界](skills/debug-agent/references/integration.md)。

## 验证与维护

```sh
python -m unittest discover -s skills/debug-agent/scripts -p 'test_*.py'
python -m unittest discover -s scripts -p 'test_*.py'
```

[产品目标与评估计划](docs/diagnostic-effectiveness.md)说明保留和裁剪能力的标准；[验证记录](docs/validation.md)区分工具测试、接入检查和诊断行为实验。当前没有完成真实案例的同条件对照，不能宣称已证明定位更快、更准。

私有案例、凭据和本机产物不入库。旧版 panel/trace/control 接口保留兼容，卡片展示与调查树不属于默认诊断路径。
