# Debug Agent

面向 AI 训练与推理精度问题的 Skill：为模型提供 **msprobe 取证工具、领域数据契约和可接续的诊断上下文**。

适用于 NaN/Inf、梯度范数异常、跨 CPU/GPU/NPU 结果不一致，以及高成本复现场景缩减。围绕整体问题明确已知、未知与子问题边界，选择当前最关键的问题，用证据缩小候选范围。具体推理和核查路径由模型选择。

## 使用入口与自动触发

安装后，在原来的 Pi、Codex 或 Claude Code 对话中使用，无需独立界面。

| 宿主 | 显式调用 | 自动加载方式 |
|---|---|---|
| Pi | `/skill:debug-agent <问题描述>` | 正常启用 Skill 发现时，模型根据描述选择读取技能 |
| Codex | `$debug-agent <问题描述>` | 已允许隐式调用，由模型根据任务内容选择 |
| Claude Code | `/debug-agent:debug <问题描述>` | 插件 Skill 可供选择；另有可选的会话启动提醒 |

例如，在 Pi 中输入：

```text
/skill:debug-agent 对比 ./left.tgz 和 ./right.tgz，分析两端 grad norm 不一致的原因。只分析已有数据，不做实验。
```

也可以直接描述精度问题，让模型自行选择技能。**自动选择可能漏触发，需要确定加载时使用显式入口。** 宿主通常先提供技能名称和描述，模型选中后读取核心规则，再按需读取参考资料。

当前没有监听界面、命中关键词就强制注入的组件，也不保证固定显示“检测到问题，已自动注入”。已有完整加载测试不等于自然对话中的自动触发可靠性已经通过验收。

## 对话中会看到什么

展示采用与 [PUA](https://github.com/tanweai/pua) 相近的文本卡片和简短旁白，保持专业诊断风格。在开始、重要证据变化和交付时说明当前判断，不为每次工具调用重复展示卡片。

以下只是输出形式示意，内容随实际问题变化：

```text
DEBUG AGENT · 诊断启动
┌──────────┬────────────────────────────────┐
│ 整体问题 │ 两端梯度范数不一致             │
│ 已知     │ 已有两端同一步的 dump          │
│ 关键未知 │ 差异在哪个计算边界出现         │
│ 下一步   │ 核对全卡对应调用的输入与输出   │
└──────────┴────────────────────────────────┘
```

长任务可显示节点进度、证据和恢复信息。任务完成比例只表示执行进度，不代表根因定位完成度。最终区分根因确认、修复验证、范围已缩小与受阻待续。

## 安装与更新

需要 Python 3.10+；仓库脚本仅依赖标准库。Linux/WSL 通常使用 `python3`，Windows 可使用 `python`。在**实际运行宿主的环境**中安装：Pi 或 Claude Code 在 WSL 运行时，就在 WSL 安装。

### Codex / Pi：安装本地 Skill

先取得仓库：

```sh
git clone https://github.com/tjh-ukn/debug-agent.git
cd debug-agent
```

按所用宿主选择一个安装命令：

```sh
# Codex
python scripts/install.py codex

# Pi（在 Pi 所在环境执行）
python3 scripts/install.py pi
```

| 宿主 | 本项目安装器的目标目录 |
|---|---|
| Codex | `$CODEX_HOME/skills/debug-agent`；未设置时为 `~/.codex/skills/debug-agent` |
| Pi | `~/.pi/agent/skills/debug-agent` |

更新时先拉取仓库，再给对应安装命令加 `--update`。安装器备份已有差异文件，不修改模型配置；写入失败会尝试回滚并报告备份位置。若宿主未显示新技能或更新，重新启动宿主后检查显式入口。

Pi 的 subagent 能力由宿主扩展提供；安装本 Skill 不会自动安装该扩展。没有可用 subagent 工具时，可由主 agent 执行核查。

### Claude Code：安装插件

```sh
claude plugin marketplace add tjh-ukn/debug-agent
claude plugin install debug-agent@debug-agent-marketplace
```

安装后使用 `/debug-agent:debug`。若需要简短的 `/debug-agent` 别名，在保留的本地克隆目录执行 `python scripts/install.py claude-alias`；别名指向该克隆，移动目录后需重新安装，且应与插件保持同一版本。别名本身不安装插件或 hook。

**可选启动提醒**：在 Claude Code 对话中执行 `/debug-agent:debug on`，关闭用 `/debug-agent:debug off`。提醒默认关闭；启用后，在会话启动、恢复或压缩后提供技能入口和当前项目账本候选。这是入口提醒，不会自动加载全部资料、启动实验或后台运行任务。

本项目尚未为 Codex/Pi 实现对应的会话注入 hook；`on/off` 不能在这些宿主中开启强制注入。详细边界见 [接入说明](skills/debug-agent/references/integration.md)。

## 常用参数

以下参数接在所用宿主的入口之后，例如 `/skill:debug-agent resume`、`$debug-agent evidence`、`/debug-agent:debug status`。

| 参数 | 用途 |
|---|---|
| 问题描述 | 分析并推进当前问题 |
| `status` | 查看任务、假设、场景与下一步 |
| `evidence` | 查看证据来源、范围与有效性 |
| `again` | 重新选择有区分度的核查 |
| `done-check` | 对照原始目标与证据检查是否完成 |
| `resume` | 恢复已有案例，核实作业和产物后继续 |
| `help` | 查看入口和支持的命令 |

`status/evidence` 只读查看，`resume` 接续已有案例。`on/off` 仅用于上面的 Claude Code 启动提醒，不是后台任务开关。

## 提供哪些能力

| 能力 | 当前实现与边界 |
|---|---|
| msprobe 取证 | 按原始执行序读取，按显式 API 列表关联栈，按栈与 shape 对应两端调用，覆盖全部提供的卡；保留未匹配、缺卡和端口差异 |
| 问题与证据接续 | 保存已知、未知、当前问题边界、证据来源和下一步；调查树记录“怎么定位到这里”，parents 记录“结论凭什么成立”；可复用存档，证据更正只沿逻辑前提撤回，不影响兄弟分支 |
| 任务协作 | 主 agent 维护整体问题，subagent 回答有边界的节点；实际委派由宿主执行，短核查无需建立任务树 |
| 领域参考 | 提供训练异常对应的材料窗口与数值证据范围，按需查阅；不要求完成固定排查清单 |
| 实验与缩减 | 由模型结合资源和证据设计；无实验条件可纯分析，保留原表现的小场景可以闭环 |

工具不会自动证明根因。根因定位可通过严谨证据链或针对性修复验证完成；只解释了局部过程、仍有关键起因未决时，应报告范围已缩小。

## 直接使用 msprobe 工具

通常由 agent 按需调用，也可以手动执行。以下命令在仓库目录运行，请替换输入路径、rank 和 API 名；多步数据的 compare/inspect 还需指定 `--step`。`scan` 的输出目录必须是新目录，已有可信扫描可以直接查询。

```sh
python skills/debug-agent/scripts/msprobe.py scan --left ./left.tgz --right ./right.tgz --out ./scan
python skills/debug-agent/scripts/msprobe.py query --scan ./scan --api '*linear*' --phase backward --limit 3
python skills/debug-agent/scripts/msprobe.py compare --left ./left.tgz --right ./right.tgz --rank 0 --api Functional.linear.0.forward
python skills/debug-agent/scripts/msprobe.py inspect --data ./left.tgz --rank 0 --api Functional.linear.0.forward
```

支持 tar/tgz/zip、解包目录或单个 dump.json；只读原始材料。扫描生成 `summary.json` 和 `alignment.jsonl`。`query` 只读缓存，默认覆盖所有已扫描卡，`--limit` 按每个 step/rank 分页；缓存代表扫描时的快照，不自动确认原包是否更新。

统计摘要相同不证明逐元素相同，执行序相邻不证明数据依赖。完整参数和解释范围见 [msprobe 数据契约](skills/debug-agent/references/msprobe.md)。

## 长任务与恢复

状态保存在项目 `.debug-agent/<case-id>/state.json`，包含问题、假设、证据、场景、任务、checkpoint 和历史。恢复会提示待验收结果、失效证据及基线变化，避免重复已完成工作，并返回当前定位路径、活跃前沿和已排除分支。`trace.py tree|path|why|impact|frontier` 只读回答“为什么调查到这里/凭什么成立/失效影响谁”。

`running` 是保存时的状态，恢复后仍需核实真实作业。项目不提供后台调度器、设备权限或断网后自动重启进程；任务和存档不等于持续执行服务。交接、状态转换与恢复工具见 [任务协议](skills/debug-agent/references/tasks.md)。

## 验证与项目资料

脚本检查覆盖读取与对应、缓存查询、状态、安装及接入。**这些检查不等于已证明根因定位更快或更准确**；自然触发、长程诊断和不同模型的收益需要分别验证。

- [核心 Skill](skills/debug-agent/SKILL.md)：问题组织方式与完成标准。
- [训练资料索引](skills/debug-agent/references/training.md)：材料窗口和官方参考。
- [数值证据范围](skills/debug-agent/references/precision.md)：比较对象与采集语义。
- [展示协议](skills/debug-agent/references/display.md)：启动、进度、证据与交付卡片。
- [评估约定](skills/debug-agent/references/evaluation.md)：同模型对照、已知案例回归和未见案例验证。
- [验证记录](docs/validation.md)：检查命令、实际结果及未通过或未验证的边界。

私有案例、设备数据、凭据和本机分析产物不属于发布内容。Skill 沿用宿主权限与用户授权。
