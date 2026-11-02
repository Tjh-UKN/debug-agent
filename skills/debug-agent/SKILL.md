---
name: debug-agent
description: "Diagnose AI training and inference failures or correctness issues: 报错、挂死、loss 异常、NaN/Inf、梯度异常、跨设备差异和状态错误. Provides evidence tools and runtime references."
---

# AI 运行与精度诊断

以代码和运行证据解释具体触发原因，用尽量少的有效取证回答用户问题。围绕关键未知选择动作，不要求先猜根因、建立账本或固定逐层排查。

## 诊断结构

- 将静态 S 与动态 D 通过静态结构、实际执行映射及数据/控制/同步依赖关联，区分观测、推导与待证因果。
- 明确对象、上下文与判据后判定正常/异常/未知；按可信依赖找首异常候选，保留未知边界并按需细化、跨层或回退。首次观测和异常暴露不自动成为根因。
- 按问题查询和折叠材料，保留来源、反例、缺失与回查入口；去噪不等于排除。按能否改变判断及实际成本选动作，昂贵取证应明确有效前提和停止条件。

## 按需资料与工具

| 当前问题 | 入口 |
|---|---|
| 关联、判据、偏序、细化或去噪 | [诊断模型](references/diagnosis.md)；diagnosis.py judge/frontier |
| 重放、长实验、持续观察或早停 | [实验判定](references/experiments.md)；diagnosis.py evaluate |
| 异常链、停顿或跨 rank 等待 | [报错与挂死](references/failures.md) |
| loss、NaN、grad norm 或参数更新 | [训练观察对象](references/training.md) |
| msprobe 对应、统计与缓存查询 | [数据契约](references/msprobe.md)；复用 scan/query |
| 统计、分片或比较范围 | [数值语义](references/precision.md) |
| 实际加载、对象复用、异步或插桩 | [运行时边界](references/runtime.md) |
| 固定已有产物与精确摘录 | [证据快照](references/evidence.md) |
| 用户要求状态、恢复或交接 | [状态与恢复](references/commands.md) |

## 完成边界

用户的材料、运行和修改约束优先，资料按需读取。缺记录、未复现或摘要相等不能越过采集与比较范围作结论；工具输出不自行证明因果。

交付区分根因确认、针对性修复验证、范围缩小和受阻待续，附决定性证据、适用范围及关键缺口。子问题回答、实验停止和规避有效不冒充整体根因确认。可靠静态证据或保留原机制的小场景可按其范围完成；证据充分即停止。
