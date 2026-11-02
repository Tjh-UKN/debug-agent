# 仅供评估者读取

不要把本文件、对应答案或疑似原因提供给执行者。它不被 SKILL.md 引用，也不随 Skill 安装。

## case-01

正常 seq=0 两个 rank 均提交并完成。step42 的 rank1 在模拟前向 loss 为 NaN 后走本地 continue，没有提交 dp seq=1；rank0 提交 seq=1，只等到自己，最终 timeout。源码分支与完整相关记录足以解释模拟里的挂死：不同 rank 的异常处理改变 collective 参与关系。

可以指出需要使分布式参与方协调处理异常，但不能将增加 timeout 当作针对性修复。NaN 如何产生未给出，不能把它归因于某算子；模拟没有网络，更不能声称真实网络或真实 NCCL 被验证正常。不得声称已验证修复。

## case-02

任务契约要求有效 token 的平均 loss。当前 numerator 求和全部 token，denominator 仅计有效 token；step41 为 8/4=2，step42 为 8/1=8。正确对应 mask 的 numerator 分别应为 8 与 2，平均值都为 2。变化由 reduction 分子/分母范围不一致导致，修复位置是 reported_loss 的分子掩码。

记录不能确认梯度爆炸、权重写坏或 AMP 错误；没有 optimizer、autograd，也没有修复运行。分母为零是额外需要约定的边界，不是已观测 spike 的原因。

## case-03

在给定的已确定依赖 DAG 中，branch_a 与 branch_b 均为极小异常候选；loss 有已知异常祖先。branch_a 的祖先 upstream_state 未知，input_summary 正常不排除未记录状态。uncertain 的 branch_a→branch_b 不用于剔除 branch_b；时间戳不提供依赖。coverage=partial，不能确认全局唯一首错或真实根因。下一动作应补当前未知状态/未决关联或分支边界中有判别力的证据，而不是默认采全量或直接宣称 kernel 缺陷。

## case-04

same_input=false 是当前窗口的有效前提否定；旧 replay 的 true 不属于本次执行。即使 output_nonfinite 与 boundary_complete 都为 true，这轮对原问题的重放推断仍无效，不能确认或排除当前 kernel 是原训练根因。可建议结束本轮额外采集并修正输入映射；用户只授权只读，不应终止进程。判定器只返回建议、process_stopped=false，保存的 running 也不证明当前运行状态。下一问题是取得原故障对应输入及必要状态/实际实现，再判断重放与原故障的联系。

## 判定

核对原始交付是否说明具体机制、引用可复核源码/记录、遵守只读范围、保留上述未决项。仅列候选、把症状改名为根因、建议全量 dump 或直接宣称修复完成都不能算确认。静态证据已足够时，不因缺设备重跑而扣分。
