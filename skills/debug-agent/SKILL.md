---
name: debug-agent
description: Diagnose AI training or inference accuracy problems, numerical divergence, NaN/Inf, CPU/GPU/NPU mismatches, msprobe dump comparisons, and distributed-scale precision anomalies. Use when investigating causes, checking a diagnosis, designing diagnostic experiments, or reducing an expensive reproducer; 中文场景包括精度定位、msprobe 数据对比、溢出定位、结果不一致和复现场景缩减. Does not apply to ordinary feature development, generic code review, or simple syntax fixes.
---

# 精度诊断 Agent

本 Skill 提供本项目的 msprobe 数据契约、取证工具、交接方式与完成标准，减少重复读取和长任务中的上下文丢失。核心约定是围绕重要未知缩小问题范围；具体推理与执行路径由模型选择。

## 当前问题

根据现有材料维护简短的问题概况，在证据变化时更新；短任务直接表述，长任务复用现有 checkpoint，无需新增表单。

| 内容 | 需要明确的边界 |
|---|---|
| 整体问题 | 用户最关心的异常、期望结果、适用场景，以及最终要解释或修复什么。 |
| 已知 | 已核实的事实、已解决的问题、证据来源和适用范围；存档中的有效结果可直接复用。 |
| 未知 | 尚未确认的前提、仍有依据的解释及影响判断的材料缺口。 |
| 问题边界 | 当前问题涉及哪些对象、阶段和范围，依赖哪些已知；回答它能说明什么，哪些问题仍在范围外。 |
| 当前关键问题 | 哪个未知最影响整体目标；回答后会怎样改变候选范围、下一步或修复位置。 |

有限的问题应当区分一组解释，而非逐个枚举所有猜想。能被同一核查区分的解释可一起处理，暂时无法区分的保留为一组；明确尚未覆盖的范围，不宣称已穷尽全部可能。原因可以共存，分类无需预设互斥。

下一步的价值按缩小重要未知的程度、结果可判别性和代价衡量。优先使用已有代码、数据和实验现象；仅在关键缺口需要时补采证据。每次结果回到整体问题：已回答什么、范围如何变化、当前最重要的未知是什么。无判别力的结果不算问题已解决；前提被修正时更新已知及相关边界。

## 完成边界

- 默认目标为根因定位。当前范围内，严谨证据链指向具体原因，或针对性修复验证解决问题，均可闭环；不强制同时采用两种方式。
- 子问题完成只覆盖自身边界。仍会改变根因归属或修复位置的关键未知，不能移入 limitations 后把整个案例标为 root_cause；仅缩小范围时交付 narrowed 及具体缺口。
- 频繁实验成本高时可缩减场景。保留原问题表现即可在小场景闭环，不强求绝对最小或原大场景复验。无实验条件时继续使用现有材料。
- 报告、卡片与账本使用同一结论等级；已知事实和未验证解释分开，关键前提被修正时重审依赖结果。

## 工具与长任务

msprobe 遵循本项目四条契约：dump 原始顺序是执行序；stack 用显式 API 列表关联；两端调用按栈与 shape 对应；完整定位覆盖所有卡。读取和查询使用 [msprobe 工具](references/msprobe.md)；已有可信扫描优先复用。其他多文件输入可用 [材料目录工具](scripts/materials.py)。

跨轮、委派或持续实验时使用 [任务协议](references/tasks.md) 保存问题与证据。主 agent 维护整体问题，subagent 只回答有明确边界的节点；回传应说明哪些未知已解决、哪些仍未覆盖。实际派工前使用 prepare-task，已有节点使用 handoff；短小核查直接完成。恢复时核实运行记录与产物，避免重复提交。

## 按需资料

- 比较统计、分片或引用框架代码时：[数值证据范围](references/precision.md)。
- 需要训练现象对应的材料窗口或官方说明时：[训练资料索引](references/training.md)。
- 评价项目是否帮助定位时：[评估约定](references/evaluation.md)。
- 显式参数为 status/evidence/again/done-check/resume/on/off/help 时：[命令路由](references/commands.md)；展示使用 [专业卡片](references/display.md)。
- 安装与宿主能力：[接入说明](references/integration.md)。本项目不提供后台调度器或设备权限。
