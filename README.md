<p align="center">
  <img src="assets/readme/hero.png" alt="Debug Agent 封面：通过计算图检查异常节点。" width="100%">
</p>

<h1 align="center">Debug Agent</h1>

<p align="center">
  <b>AI 训练与推理故障诊断 Skill</b><br>
  运行报错 · 运行挂起 · NaN / Inf · 梯度异常 · 跨设备差异 · 偶发重复输出
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Codex-1c2926?style=flat-square" alt="Codex">
  <img src="https://img.shields.io/badge/Pi-1c2926?style=flat-square" alt="Pi">
  <img src="https://img.shields.io/badge/Claude_Code-1c2926?style=flat-square" alt="Claude Code">
  <img src="https://img.shields.io/badge/Python-3.10%2B-83cbb3?style=flat-square&amp;labelColor=1c2926" alt="Python 3.10+">
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> &nbsp;·&nbsp;
  <a href="#使用案例">使用案例</a> &nbsp;·&nbsp;
  <a href="#安装说明">安装说明</a> &nbsp;·&nbsp;
  <a href="docs/diagnostic-architecture.md">诊断结构</a> &nbsp;·&nbsp;
  <a href="docs/validation.md">验证记录</a>
</p>

---

## 快速开始

调用时提供问题描述、材料路径和运行限制。

```text
$debug-agent NPU grad norm 比 GPU 大很多。两端 dump 在 ./npu 和 ./gpu，定位原因，只分析已有数据，不重跑训练。
```

| Codex | Pi | Claude Code |
|---|---|---|
| `$debug-agent <问题>` | `/skill:debug-agent <问题>` | `/debug-agent:debug <问题>` |

现有材料充分时直接分析；材料不足时，选择能补足关键证据的取证方式。安装后可通过上述命令显式调用，自动选择行为由宿主决定。

## 使用案例

**合成案例：Loss 统计中分子与分母的范围不一致**

<p align="center">
  <img src="assets/readme/case-02.svg" alt="合成案例：token loss 总和保持 8，有效 token 从 4 减到 1。分子没有应用 mask，reported loss 因而从 2 变成 8。" width="100%">
</p>

该图基于仓库中的[公开合成案例](evals/cases/case-02/request.md)绘制。分子累加全部 token 的 Loss，分母仅统计有效 token 数量。对分子应用相同 mask 后，两步的平均 Loss 均为 2。现有材料可解释指标变化，尚不足以确认梯度或参数异常。

该图用于说明案例中的故障机制。模型诊断结果及其限制见[验证记录](docs/validation.md)。

## 诊断机制

| 证据关联 | 异常定位 | 诊断结论 |
|---|---|---|
| 关联代码、调用栈与运行记录。 | 依据判据与可信依赖定位异常，保留未知边界。 | 诊断结论包含原始依据，并说明适用范围及关键缺口。 |
| 比较 msprobe dump 时，保留跨卡范围、缺失记录和未匹配项。 | 按需细化分析、回查证据或设计实验，复用已有扫描结果。 | 明确结论属于根因确认、修复验证、范围缩小或受阻待续。 |

诊断任务可直接执行，长任务按需保存证据与恢复进度。工具负责读取、比较与显式判据检查，根因判断由宿主模型完成；取证、实验与进程终止均遵守用户授权。

## 安装说明

环境要求为 **Python 3.10+**，运行脚本仅依赖标准库。安装须在 Agent 的实际运行环境中执行；若 Pi 运行于 WSL，应在对应的 WSL 环境中安装。

<details open>
<summary><b>Codex / Pi</b></summary>

```sh
git clone https://github.com/Tjh-UKN/debug-agent.git
cd debug-agent
```

| 宿主 | 安装命令 |
|---|---|
| Codex | `python scripts/install.py codex` |
| Pi | `python3 scripts/install.py pi` |

若 Linux/WSL 环境未提供 `python` 命令，可使用 `python3`。若宿主尚未识别新安装的 Skill，重启宿主后再调用。

</details>

<details>
<summary><b>Claude Code</b></summary>

```sh
claude plugin marketplace add Tjh-UKN/debug-agent
claude plugin install debug-agent@debug-agent-marketplace
```

</details>

<details>
<summary><b>更新、检查与安装位置</b></summary>

更新仓库后，为安装命令添加 `--update`；使用 `--check` 可只读核对安装内容。更新时先备份差异文件，不修改模型配置。

安装路径、更新范围与可选命令别名见[宿主接入](skills/debug-agent/references/integration.md)。

</details>

## 参考文档

| 文档 | 内容 |
|---|---|
| [Skill 入口](skills/debug-agent/SKILL.md) | 宿主实际加载的诊断指导 |
| [诊断结构](docs/diagnostic-architecture.md) | S/D 证据与关联、判据，以及异常偏序与细化 |
| [验证记录](docs/validation.md) | 已完成的检查、案例结果与未决问题 |
| [评估方法](docs/diagnostic-effectiveness.md) · [公开案例](evals/README.md) | 诊断行为与结论边界的评估方式 |

<details>
<summary><b>开发与测试</b></summary>

```sh
python -m unittest discover -s tests -t .
```

测试与公开案例保留在源码仓库，不随 Skill 分发。脚本检查通过不保证实际场景中的诊断结果正确。

</details>

---

<p align="center"><sub>FOLLOW THE EVIDENCE.</sub></p>
