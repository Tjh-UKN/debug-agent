这是一个分布式训练停顿的合成案例。请结合 workload.py 和 records.jsonl 定位已提供材料能确认的原因，指出决定性记录、适用范围及仍不知道的事情。只读分析即可；不要启动真实训练、改源码或联系外部环境。

records.jsonl 是 workload.py 模拟同一作业两个 rank 产生的完整相关记录。每个 rank 的 seq 是同一 process group 内的 collective 调用次序，事件含 submitted/completed。异常文本只是等待的表现。源码与记录已确认对应；模拟不包含网络传输。
