这是一个训练 loss 从 2 上涨到 8 的合成案例。任务约定：reported_loss 应为有效 token 上的平均 loss。请结合 workload.py 和 records.jsonl 判断指标变化的原因，说明决定性证据、能否确认梯度/参数异常以及合理修复位置。只读分析；不修改文件，不运行设备训练。

records.jsonl 由当前 workload.py 生成，输入和运行代码对应。这里没有 autograd、AMP 或 optimizer，记录的 grad_norm 是独立观测值，不能从它推断未提供的内部机制。
