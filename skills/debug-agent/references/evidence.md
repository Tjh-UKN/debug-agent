# 关键产物的证据快照

`scripts/evidence.py` 保存**已存在、明确指定**的本地文件，并计算内容哈希。它不执行命令、不连接服务器、不扫描目录，也不要求创建案例账本。通常在获得决定性日志、对照结果或补丁后使用一次。

```sh
python <skill-dir>/scripts/evidence.py capture --out ./evidence/run-01 \
  --file ./run.log --file ./config.json --file ./change.patch
python <skill-dir>/scripts/evidence.py show --bundle ./evidence/run-01 --index 0 --lines 12:18
python <skill-dir>/scripts/evidence.py verify --bundle ./evidence/run-01
```

默认总大小上限 16 MiB，可以用 `--max-bytes` 显式调整。大规模 msprobe dump 使用其 scan/query 工具，保存必要查询输出，不为每次判断反复复制原包。检测到读前后大小或时间变化时 capture 失败，失败目录没有完整 manifest，保留部分产物供检查；重试使用新目录。多个文件依次保存，不是运行进程的一致性快照，最好选取已完成写入的产物。已存在的输出目录永不覆盖。

快照目录内含原始字节副本与 `manifest.json`，自动记录捕获时间、捕获主机、源路径、大小和 SHA256。`show` 先校验所选快照，返回从 1 开始的精确行号，最多 200 行、32 KiB；超限要求缩小范围，不静默截断。

可选 `--context context.json` 附上已执行命令、解释器、实际加载路径、运行 host/配置等上下文。这些字段保存为 `declared_context`：它们来自调用方声明，工具没有执行该命令或证明声明真实。捕获主机和运行主机可能不同，不能混用。不要复制凭据、完整环境变量或无关日志。

`verify` 检查快照字节、大小及路径约束；`--sources` 另外比较当前源文件，源已变更时报告 `intact=true, sources_match=false` 并返回非零。源文件后续变化不会使既有快照自动失效，但也不能再声称它代表当前运行状态。manifest 中的哈希提供一致性校验，不是数字签名，也不证明观察的因果解释。

需要使用已有账本时，将 `source` 指向快照文件及行号，`context` 引用 manifest 与实际运行条件。仍由主 agent 根据证据填写 observation/scope/limits；快照不会自动生成 confirmed 或 root_cause。
