# Debug Agent

**沿着证据，追到原因。**

给 Codex、Pi 和 Claude Code 的 AI 训练与推理诊断 Skill。处理报错、挂死、NaN/Inf、梯度异常、跨设备差异和偶现复读。

## 先试一句

```text
$debug-agent NPU grad norm 比 GPU 大很多。两端 dump 在 ./npu 和 ./gpu，定位原因，只分析已有数据，不重跑训练。
```

给出问题、材料路径和运行限制即可。已有数据足够就直接分析；需要补充取证时，根据当前缺口选择动作。

| 在哪里用 | 在对话中输入 |
|---|---|
| Codex | `$debug-agent <问题描述>` |
| Pi | `/skill:debug-agent <问题描述>` |
| Claude Code | `/debug-agent:debug <问题描述>` |

安装后可显式调用；自动选择由宿主决定。

## 它会做什么

- **对齐证据。** 关联代码、调用栈和运行记录；比较 msprobe dump 时保留跨卡范围、缺失和未匹配项。
- **追查关键问题。** 按需判定异常、追踪依赖、缩小范围或设计取证；复用已有扫描，证据充分即停止。
- **把结论讲清楚。** 给出判断、原始依据、适用范围和未决条件，区分根因确认、修复验证、范围缩小和受阻待续。

普通问题直接推进，长任务按需保存证据和恢复进度。模型选择定位路径，无需固定逐层排查或先建任务树。

工具负责读取、比较和显式判据检查，根因判断仍由宿主模型完成；取证、实验及真实停止遵守用户授权。

## 安装

需要 Python 3.10+，仅依赖标准库。在 Agent 实际运行的环境中安装；Pi 在 WSL 中运行，就在 WSL 中安装。

**Codex / Pi**

```sh
git clone https://github.com/Tjh-UKN/debug-agent.git
cd debug-agent
```

选择对应命令：

| 宿主 | 安装 |
|---|---|
| Codex | `python scripts/install.py codex` |
| Pi | `python3 scripts/install.py pi` |

Linux/WSL 若没有 `python`，使用 `python3`。更新仓库后，安装命令加 `--update`；加 `--check` 可只读核对安装内容。更新先备份差异文件，不修改模型配置。

**Claude Code**

```sh
claude plugin marketplace add Tjh-UKN/debug-agent
claude plugin install debug-agent@debug-agent-marketplace
```

安装位置、更新边界和可选别名见[宿主接入](skills/debug-agent/references/integration.md)。宿主未刷新技能时，重启后再调用。

## 文档与验证

[Skill 入口](skills/debug-agent/SKILL.md) · [诊断结构](docs/diagnostic-architecture.md) · [验证记录](docs/validation.md) · [评估方法](docs/diagnostic-effectiveness.md)

开发检查：

```sh
python -m unittest discover -s tests -t .
```

测试与[公开案例](evals/README.md)留在仓库，不随 Skill 分发。脚本检查通过不代表每次都能正确定位；实际效果与限制见验证记录。
