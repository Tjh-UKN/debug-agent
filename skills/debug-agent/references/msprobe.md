# msprobe 数据契约与诊断入口

msprobe 是已知输入协议。以下规则直接用于分析，不把执行序、栈关联或全卡覆盖当作每次重新猜测的假设。

## 四条基础约束

1. `dump.json["data"]` 的记录顺序就是执行序。按原顺序保留前向、反向和 `is_recompute`，不按 API 名或编号重新排序；反向期间的重计算仍是前向记录，不把它数成新的模型层。
2. `stack.json` 是 `组号 -> [API 名列表, 栈帧列表]`。组号是不透明标识；API 与栈通过列表中的显式名字关联，绝不是 `list(dump)[int(组号)]`。同组可以有多个 API。
3. 两端 API 对应必须满足调用栈与 shape 对应，再比较同角色的输入/输出。API 编号可能不同，不能仅凭同名/同号匹配。同栈同 shape 的重复调用用执行序与出现次数消歧；次数不同不能强行 zip 后宣称对齐。未对齐项必须保留。
4. 完整精度定位考察所有卡：先取得全卡对齐与差异概览，再选有判别力的卡/节点深入。局部发现回到全卡验证，不能默认 rank0 代表全体。用户只要求查看某卡某条记录时可以局部查询，但不作全局结论。

## 直接使用的工具

Python 3.10+，标准库即可。输入可为压缩包（tar/tgz/zip）、解包目录或单个 dump.json；压缩包只读，不解包、不执行内容。目录中的 `stepN/rankN` 或 `step_N/rank_N` 用于识别范围。重复 step/rank 报错；没有这些标识时标为 unknown，不默认为 rank0。

两端比较先运行一次全卡扫描（`<new-output-dir>` 必须是新目录）：

```sh
python <skill-dir>/scripts/msprobe.py scan --left <npu-data> --right <gpu-data> --out <new-output-dir>
```

- `summary.json`：每个 step/rank 的原始文件与 SHA256、记录数、匹配/未匹配数、按执行序的首批差异、各卡较大的 Norm 差异、缺卡/读取错误。所有卡都会扫描，top 列表仅是导航，不是覆盖范围。
- `alignment.jsonl`：完整对应表及未对齐项（含单边缺卡时已有端的全部记录），带两端 API 名、各自执行序位置、方向/重计算标记和源文件路径。表以左端次序为主、追加右端未匹配项，不是联合执行轨迹；原始位置始终以各自 `position` 为准。summary 的 `alignment_line` 是该文件的一基行号。
- `coverage_complete` 只表示已提供并可识别的 step/rank 对齐覆盖、且已观测 DTensor mesh 没有缺卡，不等于所有 API 已匹配，也不证明输入包之外没有其他运行材料。必须同时阅读 errors、missing_rank_pairs、missing_mesh_ranks、unscoped_sources 及每卡的未匹配数。
- 不把小差异自动归为噪声；默认不丢弃任何有限数值差异。记录顺序上的首个差异不是已经证明的因果起点。
- 新扫描的 matched 行带 `boundary_evidence`：分开统计 input/output 记录中的相等、不同、缺失、非有限字段，保留各组绝对/相对 Norm 差异较大项和元数据变化。这是摘要导航，不给算子判定正常/异常；输入槽也可能是权重或执行前目的缓冲。
- Norm 差异分别按前向、反向和重计算标记展示绝对/相对较大项，避免前向量级掩盖反向异常。`comparison` 同时列出实际比较统计数、缺失统计数与需要核查端口的记录数；只匹配到 shape 但无统计，不算完成精度比较。大包可使用已有解包目录减少压缩包随机读取开销。

对选定卡与调用深入比较（`--api` 使用左端 API 名，右端由对应表规则解析）：

```sh
python <skill-dir>/scripts/msprobe.py compare --left <npu-data> --right <gpu-data> --rank <rank> --step <step> --api <left-api>
python <skill-dir>/scripts/msprobe.py inspect --data <one-side-data> --rank <rank> --step <step> --api <api>
```

单个 step 时可省略 `--step`。inspect 返回原始记录、字段路径、执行序邻近项、显式关联的原始调用栈和分片元数据；compare 返回匹配依据和对应字段的统计/配置差异。遇到缺栈、shape 不对应或重复调用无法消歧，输出未对齐，不能把其当成“两端计算相同”或“该端没有执行”。

调用栈匹配只归一化 Python 安装前缀与行号偏移，保留模块路径、函数和源代码行文本；原始栈始终保留。项目 checkout 根路径不同时，显式传 `--left-code-root`、`--right-code-root`，不靠丢掉文件路径来勉强匹配。实质分支/代码不同导致不匹配时，inspect 原始栈并核查代码关系。

backward 没有独立栈时，工具使用本端同名 forward（仅替换末尾方向）的显式栈作为调用点，并在 `stack_api` 标出来源；跨端仍按栈、forward shape、backward 首个梯度输入槽 shape、方向及执行序匹配，不按两端编号直接配对。端口布局不同时 `role_check_required=true`；共有字段的统计可以查看，但在核实端口语义前不能把输出槽命名为 dQ/dK/dW 来作因果推断。

dtype、mask 类型/值、scale 等配置差异是诊断线索，不作为相同 shape 调用的剔除条件。DTensor 的记录 shape/统计是本地视图，工具保留 mesh/placement，不擅自乘卡数、乘 √卡数或自动推算“全局参数”。不兼容的分片/视图不直接比较数值。工具比较统计摘要，不加载原始张量；摘要相等不证明逐元素相等，非有限值与缺失统计单独标记。

## 复用扫描按问题查询

已有可信扫描时直接复用，不为每个子任务重新解包或遍历原包。下面在所有已扫描 step/rank 中查询一类调用；API 通配符应加引号，任一端名字符合即可返回：

```sh
python <skill-dir>/scripts/msprobe.py query --scan <scan-dir> --api '*linear*' --phase backward --limit 3
```

- `--phase forward/backward/recompute` 区分普通前向、反向和前向重计算；省略表示全部阶段。可用 `--step`、`--rank` 缩小范围，默认保留所有卡，包括符合条件记录为零的卡。
- `--limit` 与 `--offset` **按每张卡的每个 step 分页**，结果保留总命中数、各对应状态计数与 `next_offset`。不会因 rank0 占满页面就漏掉后续卡；没有命中不等于该卡没有执行。
- 每行带 `alignment_line`、两端原始位置/来源、对齐依据与 `role_check_required`；缺卡、未匹配和旧扫描缺少输入输出证据的情况保留。元数据变化最多展示 8 条，并给出总数及截断标志；完整字段用 compare/inspect。
- query 只读 summary/alignment 文件，不重开原包，不检查原包是否已更新。结果引用扫描时的 source hashes；它是存档证据，不是当前文件的实时状态。旧扫描仍可查位置，但 `matched_rows_without_boundary_evidence` 非零时不能把缺少证据当成没有差异，针对需要的调用用 compare/inspect 即可。

## 端口与问题范围

概览和查询给出记录范围，不建立数据依赖。将选定调用的来源、栈与端口用于当前问题，已解决的边界可作为存档复用。

- 原地操作与 collective 要区分真正的输入和执行前的目的缓冲；例如 all_gather/reduce_scatter 的 output_tensor 在写入前的统计，不应当作该算子计算结果的差异。结合接口/栈代码核实角色后使用执行后的记录。
- 局部反向量与参数 `.grad` 可能分属本地贡献、完整参数、分片或归约/累积后结果；重建全局量需要实际参与卡和对应关系。
- 反向输入槽通常记录该 API 的 grad_output，其他端口角色依采集方式和计算结构核实，不由槽位编号命名为 dQ/dK/dW。

派工保留 summary/相关 alignment 行、原始 source/API/字段路径和本节点待回答的问题，按 [任务协议](tasks.md) 交接；疑似读取错误可用 inspect 的原始字段复核。

工具不确认根因，结论等级按 [完成边界](../SKILL.md#完成边界) 交付。
