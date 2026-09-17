# 本地任务与状态协议

存在理由：宿主会话、临时 todo 和子 agent 生命周期不能代替持久证据与任务状态。只有本协议的数据依赖有固定顺序，诊断动作顺序仍由模型选择。

本文件是需要持久化或交接时查阅的工具协议，不是诊断流程。task 节点围绕待解决的判断缺口建立；记录已有事实、假设、实验条件、结果和下一步所需信息，不为了填满实体或完成状态流转增加核查。主 agent 始终根据证据推进分析，不能用账本完成率替代定位进展。

## 存储与命令

每个问题一个项目内 `.debug-agent/<case-id>/state.json`，内含假设、证据、场景、任务、当前 checkpoint、结论和变更历史。没有额外数据库或后台服务。日志、补丁、配置及数据保存到案例目录或原项目，账本以路径/远程 URI 引用。

`case.py` 的路径从当前 Skill 目录解析。下面是命令形态；所有 payload 用 UTF-8 JSON 文件传入，避免 shell 转义破坏命令/文本：

```text
python <skill-dir>/scripts/case.py --case <case-dir> init --file init.json
python <skill-dir>/scripts/case.py --case <case-dir> show
python <skill-dir>/scripts/case.py --case <case-dir> put --kind hypothesis --file h1.json
python <skill-dir>/scripts/case.py --case <case-dir> put --kind evidence --file e1.json
python <skill-dir>/scripts/case.py --case <case-dir> put --kind scenario --file s1.json
python <skill-dir>/scripts/case.py --case <case-dir> put --kind task --file t1.json
python <skill-dir>/scripts/case.py --case <case-dir> put --kind checkpoint --file checkpoint.json
python <skill-dir>/scripts/case.py --case <case-dir> submit --file result.json
python <skill-dir>/scripts/case.py --case <case-dir> accept --file review.json
python <skill-dir>/scripts/case.py --case <case-dir> close --file closure.json
python <skill-dir>/scripts/case.py --case <case-dir> reopen --file reopen.json
python <skill-dir>/scripts/case.py --case <case-dir> show --history
```

`show` 默认不输出历史。写入使用 OS 文件锁与原子替换，失败不改变已有状态；锁随进程退出释放。`case busy` 表示另一个短事务未完成，稍后重试；不删除锁文件。账本应存本地磁盘，不依赖网络文件系统的锁语义。

新记录 `rev: 0`；更新带上 `show` 中该记录的当前 rev，成功后增加 1。`put` 是完整记录替换，不是 patch；保留未修改字段。过期版本拒绝写入，重新读取并核对变化，不能盲目递增。不同子任务的版本独立。`close/reopen` 使用案例顶层 rev。

## 初始化与记录

初始 payload：

```json
{"title":"问题名称","goal":"根因定位","symptom":"原始异常表现及来源","acceptance":"什么证据足以完成用户目标"}
```

各类记录共同包含 `id` 和 `rev`。id 使用字母、数字、点、横杠或下划线，以字母/数字开头，最多 80 字符。内容字段支持中文。可附加项目特有字段，但不要存储凭据。

| kind | 必需内容 | 状态与关联 |
|---|---|---|
| hypothesis | claim、basis、prediction、reason | status 为 open/supported/ruled_out/unresolved/confirmed；evidence 为证据 ID 列表，parents 为假设 ID 列表 |
| evidence | observation、source、context、limits、validity | validity 为 valid/invalid/uncertain；source 指向原始来源；context 保存版本、输入、配置、命令与实际加载路径中与解释有关的部分 |
| scenario | description、changes、cost、reason、reproduction | reproduction 为 original/retained/not_observed/different/uncertain；parent 为父场景 ID 或 null；evidence 为证据 ID 列表 |
| task | question、action、acceptance、owner、reason、status | depends_on 为任务 ID 列表，hypotheses 为假设 ID 列表，scenario 为场景 ID 或 null；run 可存运行信息 |
| checkpoint | summary、next_action、reason、environment | id 固定 current；baseline 为当前保留问题表现的场景 ID 或 null；evidence 为关键证据 ID 列表 |

列表缺省为空，单个关联缺省为空。状态判断仍由 agent 负责，脚本只检查结构、关联和转换；脚本不会判断证据是否真实或科学结论是否成立。`limits` 没有已知限制时明确填写，不省略。

证据记录只追加不覆盖。原证据后来发现无效时追加更正记录，在 observation 中引用旧 ID，并由主 agent 修订受影响的假设、任务结论与 checkpoint；历史是当时的判断，不是永远有效的事实。

假设 supported/ruled_out/confirmed、场景 retained 必须引用有效证据。要撤回判断可以更新为 open/unresolved，保留理由。场景缩减未复现不自动改变任何假设。parents、parent、depends_on 不允许形成环；不同假设仍可共享证据。

## 派工、提交和验收

主 agent 创建近期任务，如：

```json
{
  "id":"T1","rev":0,"status":"pending","owner":"待分配",
  "question":"保留相关通信组后，64 卡能否复现原异常表现？",
  "action":"结合配置和代码选择缩减方式，记录连带变化，再运行对照",
  "acceptance":"提供表现对照、实验有效性与结果边界；未复现也可完成该核查",
  "reason":"预计需要多轮实验，当前 4096 卡成本高",
  "depends_on":[],"hypotheses":[],"scenario":null
}
```

派给子 agent 时还需给出：案例绝对路径、task ID、输入材料、可修改范围、可用设备/预算、结果提交方式。候选假设是待验证内容，不是预设答案。用宿主实际提供的 subagent 工具；独立任务可并行，共享资源或依赖任务串行。

执行者更新自己任务的 owner/status/run。启动昂贵实验前落盘计划的 command/cwd/host/output 路径；启动后立即补充 job_id 或 PID、启动时间和产物位置，恢复时据此核实，不直接再提交。无运行工具时可以将核查任务转 blocked，说明缺口，主 agent 继续其他可行路径。

状态转换：pending → running/blocked/cancelled；running → blocked/cancelled/通过 submit 进入 submitted；blocked → pending/running/cancelled/通过 submit 进入 submitted；submitted 由主 agent accept → done。创建任务始于 pending。依赖任务 done 后才可 running。取消状态不负责终止真实作业，必须核实作业已结束或已交接，不丢弃运行资源。

提交可以原子加入新证据并关联结果：

```json
{
  "task_id":"T1","rev":2,
  "new_evidence":[
    {"id":"E1","rev":0,"observation":"实际观察到的结果","source":"日志绝对路径或远程 URI","context":"实际命令、输入、配置、代码版本和加载路径","limits":"结果解释范围","validity":"valid"}
  ],
  "result":{"outcome":"observation","summary":"回答任务问题并说明对候选假设的影响","evidence":["E1"],"limitations":"保留的不确定性"}
}
```

outcome 可选 supports/contradicts/inconclusive/invalid/observation。前两项必须有有效证据。可直接引用已有证据，不必重复登记。子 agent 只修改分配给自己的任务、追加证据并 submit；不修改全局假设、checkpoint 或案例结论。这是协作约定，不是隔离不可信进程的安全机制。

主 agent 核查结果后：`{"task_id":"T1","rev":3,"reason":"验收依据及保留的限制"}` → accept。done 表示本次核查完成，不代表假设成立。结果无效或未决也可以验收为“已完成的无效/未决尝试”；需要重试时创建新任务并引用此前任务，保留尝试历史，不覆盖原结果。

## 恢复与闭环

恢复先读 show：当前 checkpoint、活跃假设、baseline、running/blocked/submitted 任务。核实正在运行的作业与产物是否属于当前版本；旧 checkpoint 是恢复线索，不是免核实的事实。没有正在执行的任务且状态明确时，直接继续 next_action。

优先使用 `python <skill-dir>/scripts/recovery.py resume --case <case-dir>` 汇总上述信息；它不会变更状态或启动作业。`show` 本身也不创建锁文件，只有写入需要锁。恢复提示会指出 checkpoint 之后的更新、已失效的基线和待验收结果。没有明确案例时使用 `recovery.py list --project <cwd>`，不从多个候选中猜选。

主 agent 在证据、关键决策、环境或基线变化时更新 checkpoint，而不是每个命令都记录一次。

闭环 payload：

```json
{
  "rev":12,"outcome":"root_cause","route":"evidence_chain",
  "conclusion":"具体原因与机制","scope":"当前小场景及适用条件",
  "evidence":["E1"],"acceptance_check":"说明如何满足用户验收",
  "limitations":"原大场景未验证，后续可以补充，不阻碍当前闭环"
}
```

成功 outcome 为 root_cause/fix_verified，route 为 evidence_chain/targeted_fix，两条路径任选其一。必须有有效证据和验收说明，无运行中或待验收任务；剩余非必要任务应说明理由后取消，不为关账伪造完成。未完成可用 narrowed/blocked，说明下一步与缺失条件，不称为成功。

新证据推翻旧结论时，`{"rev":13,"reason":"新证据及重开原因"}` → reopen；旧结论仍在 history 中，然后修订受影响记录。
