# Debug Agent

假设驱动的 AI 精度诊断 Agent。以现象、事实和代码为依据，选择能区分假设的核查，按需缩减实验，并通过证据链或针对性修复验证完成闭环。

交互形式参考 [PUA](https://github.com/tanweai/pua)：可安装的 Skill/插件、命令入口、启动卡、进度卡、证据卡与简短旁白。内容保持专业诊断风格，不使用施压措辞或自评绩效分数。

```text
DEBUG AGENT · 诊断进度
已知任务 █████░░░░░ 1/2（非定位完成度）
┌──────┬────────────────────┬────────────┐
│ 任务 │ 核查问题           │ 状态       │
├──────┼────────────────────┼────────────┤
│ T1   │ 缩减后是否仍复现   │ 已验收     │
│ T2   │ 修复点是否有效     │ 运行中     │
└──────┴────────────────────┴────────────┘
▎ 小场景已保留原问题表现，下一步在该场景验证修复。
```

上面是 UI 示例，不是一次真实实验。

## 安装

需要 Python 3.10+，示例使用 `python` 命令，无第三方运行依赖。仓库为私有时，需要拥有访问权限。

### Codex

```sh
git clone https://github.com/tjh-ukn/debug-agent.git
cd debug-agent
python scripts/install.py codex
```

安装到 `$CODEX_HOME/skills/debug-agent`，未设置时为 `~/.codex/skills/debug-agent`。已有不同版本时使用 `--update`，旧文件会先备份。新会话中可显式调用 `$debug-agent`；Skill description 允许宿主自动选择，具体是否命中由宿主判断。

### Claude Code

```sh
claude plugin marketplace add tjh-ukn/debug-agent
claude plugin install debug-agent@debug-agent-marketplace
```

使用 `/debug-agent:debug`。需要与 PUA 裸命令相同的简短入口时，在保留的本地克隆目录执行：

```sh
python scripts/install.py claude-alias
```

随后可用 `/debug-agent`。别名指向本地克隆中的核心 Skill，移动目录后需要重新安装。插件与别名应保持同一版本。安装别名本身不会安装插件或会话 hook。

## 命令

下表以 Claude Code 裸别名为例；不安装别名时使用 `/debug-agent:debug`，Codex 使用 `$debug-agent`，后面的参数相同。

| 命令 | 行为 |
|---|---|
| `/debug-agent <问题描述>` | 启动诊断，按证据选择下一步 |
| `/debug-agent status` | 只读显示任务、假设、场景及下一步 |
| `/debug-agent evidence` | 显示证据、来源、有效性和范围 |
| `/debug-agent again` | 重新选择有区分度的核查 |
| `/debug-agent done-check` | 对照目标检查结论及证据 |
| `/debug-agent resume` | 核实运行状态后恢复，避免重复提交实验 |
| `/debug-agent on` | 开启已安装 Claude Code hook 的会话启动提醒 |
| `/debug-agent off` | 关闭该启动提醒，不取消实验或禁用显式调用 |
| `/debug-agent help` | 显示可用命令 |

Claude Code 插件的 `SessionStart` hook 默认关闭，通过 `on` 开启后，在启动、恢复和压缩后提供诊断接入与账本位置提示。hook 只读本地数据，不联网、不启动实验、不阻塞结束。宿主执行 hook 的环境需要能够找到 `python`。

Codex 当前通过 Skill 自动选择接入，未实现同等的 SessionStart 注入；`on/off` 在其中只能保存偏好。自动选择、会话提醒、持久化恢复和后台持续运行是不同能力，本包没有后台调度器。

## 诊断约定

- 假设有事实或代码依据，记录可核查预测；允许多个原因并存、回溯和重新打开。
- 下一步考虑区分能力、成本与结果可信度，不规定固定排查顺序。
- 频繁昂贵实验时考虑缩减，保留原问题表现即可；小场景可闭环，大场景验证不是完成前提。
- 优先利用代码和已有现象，针对实际证据缺口补采中间数据。
- 任务完成、假设成立和修复成功分别记录；无效、未决与反证不得混淆。
- 主 agent 维护整体判断，subagent 执行有边界的任务。短小核查无需为框架制造任务。

长任务状态存项目 `.debug-agent/<case-id>/state.json`，包含假设、证据引用、复现场景、任务、checkpoint 与历史。Python 工具提供并发锁、原子提交和版本冲突检查；它们不判断证据真实性，也不执行模型调用。

## 验证与维护

```sh
python -B skills/debug-agent/scripts/test_case.py
python -B scripts/test_integration.py
```

验证覆盖账本可靠性、命令偏好、会话提醒、基于真实状态的面板和隔离安装。已有独立 agent 在合成 CPU 精度案例中完成定位与修复闭环；它不证明真实硬件诊断效果。真实问题集应同时评价最终结论和关键决策节点，见 [评估约定](skills/debug-agent/references/evaluation.md)。

本轮验证运行于 Windows/Python 3.13；未进行 Claude Code 客户端端到端测试或 Linux 运行验证。插件格式及 hook 协议依据 [Claude Code 插件文档](https://code.claude.com/docs/en/plugins) 与 [Hooks 文档](https://code.claude.com/docs/en/hooks)。

## 目录

```text
.claude-plugin/      Claude Code 插件及 marketplace
.codex-plugin/       Codex 插件描述
commands/           Claude Code 命令入口
hooks/              可选会话启动提醒
skills/debug-agent/ 核心规则、按需资料与状态/展示工具
scripts/            安装与接入测试
```

私有任务、实验日志、设备数据、凭据和本机验证产物不属于发布内容。各宿主权限与用户授权始终优先，Skill 不扩展权限。
