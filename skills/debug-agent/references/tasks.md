# 账本与交接协议

仅用于恢复已有案例、确需持久状态或多个独立节点交接。普通诊断直接推进，现有笔记足够时复用。协议保留旧案例兼容性；它管理记录，不选择实验或证明根因。

## 存储与操作

每例位于项目 `.debug-agent/<case-id>/state.json`，schema=1。原始产物单独保存，账本引用路径。脚本需 Python 3.10+；payload 用 UTF-8 JSON 文件，避免 shell 转义。

```text
python <skill-dir>/scripts/case.py --case <dir> init --file init.json
python <skill-dir>/scripts/case.py --case <dir> show [--history]
python <skill-dir>/scripts/case.py --case <dir> put --kind <kind> --file record.json
python <skill-dir>/scripts/case.py --case <dir> prepare-task --file task.json
python <skill-dir>/scripts/case.py --case <dir> handoff --task T1
python <skill-dir>/scripts/case.py --case <dir> submit --file result.json
python <skill-dir>/scripts/case.py --case <dir> accept --file review.json
python <skill-dir>/scripts/case.py --case <dir> close --file closure.json
python <skill-dir>/scripts/case.py --case <dir> reopen --file reason.json
```

init 必需 title、goal、symptom、acceptance，可选 materials 路径列表。新记录 rev=0；更新使用 show 返回的记录 rev，close/reopen 使用案例顶层 rev。put 是完整替换，保留未改字段；冲突后重新读取，不能盲增版本。id 用字母/数字开头，限字母、数字、点、横杠、下划线，最长 80 字符。

show/handoff 只读。写入在本地磁盘使用 OS 锁与原子替换；case busy 时稍后重试，不删除锁。失败不提交半个状态。证据只能追加，其他记录可按状态约束更新。

## 记录字段

各记录共同需要 id、rev；以下文本字段必须非空，引用列表缺省为空，具体检查范围写进 scope。

| kind | 内容字段 | 状态与引用 |
|---|---|---|
| hypothesis | claim、basis、prediction、reason | status: open/supported/ruled_out/unresolved/confirmed；evidence、parents、investigates、investigation_question |
| evidence | observation、source、scope、context、limits | validity: valid/invalid/uncertain；depends_on、supersedes、correction_reason、inspected |
| scenario | description、changes、cost、reason | reproduction: original/retained/not_observed/different/uncertain；parent、evidence |
| task | question、action、acceptance、owner、reason | status: pending/running/blocked/submitted/done/cancelled；depends_on、hypotheses、scenario、run |
| checkpoint | summary、next_action、reason、environment | id 固定 current；baseline、evidence、focus_hypotheses |

supported/ruled_out/confirmed 和 retained 场景必须引用当前有效证据。ruled_out/confirmed 还需要 decision_review（见下文）。baseline 只能引用 original/retained 场景。所有依赖关系禁止自指和环。

- parents 是结论成立的必要前提，多项按 AND 解释。
- investigates 是调查来源，非空时必须附 investigation_question。调查子树剪枝不自动撤回父/兄弟判断；不从此关系推导 parents。旧案例缺少调查关系时不从自然语言猜补。
- materials 仅用于定位用户提供的原始材料；可用 materials.py 枚举指定目录或压缩包，不代表文件已检查。inspected 是 agent 自报访问记录，实际范围仍看 scope。

证据 source 可引用[快照](evidence.md)及行号。工具只校验结构和显式关系，valid/confirmed 与 context 仍需原始材料支持。

## 更正与恢复

错误观察用新 evidence 的 supersedes 引用旧 ID，并填写 correction_reason；依赖证据通过 depends_on 显式登记。旧观察保留，不能继续支持结论。更正沿证据依赖和 parents 撤回判断，场景可能转 uncertain、已完成任务转 submitted、活动任务标 needs_review；已闭环案例重开。不会停止或重提真实作业，也不自动证明相反结论。

用 `recovery.py resume --case <dir>` 读取 checkpoint、调查前沿、待验收结果、失效证据和运行信息；核实 host/job_id/PID、版本与产物后继续。已知旧进展不要重做；无现行案例时才用 `recovery.py list --project <cwd>` 寻找存档，多个候选不能猜选。

`trace.py --case <dir> tree|path|why|impact|frontier` 只读查询：path 沿 investigates，why 沿 parents/证据，impact 只计算显式依赖。未登记的文字前提仍由 agent 判断。

## 节点交接

已有账本下，新委派节点用 prepare-task 保存新 ID、rev=0、status=pending；返回 execution_started=false 与交接材料，实际派工由宿主执行。已有节点用 handoff。传递原始问题、材料、观察范围、待回答问题、权限/资源边界，不能只转述上游结论。允许执行者发现前提不成立。

task 状态约束：pending → running/blocked/cancelled；running → blocked/cancelled；blocked → pending/running/cancelled；running/blocked 用 submit → submitted；主 agent 用 accept → done。依赖任务 done 后才可 running；新尝试建新 task，不覆盖旧结果。

run 保存命令、cwd、host、job_id/PID 和产物路径；昂贵作业启动前留计划，启动后补实际标识。取消账本任务不会取消真实进程，须核实停止或交接。执行者只更新分配的 task、追加证据并 submit，主 agent 管理整体结论。

```json
{"task_id":"T1","rev":2,"new_evidence":[],"result":{"outcome":"observation","summary":"观察及其对待核查问题的影响","evidence":["E1"],"limitations":"已检查范围以外未验证"}}
```

result.outcome 为 supports/contradicts/inconclusive/invalid/observation；前两者须有有效证据。accept 使用 task_id、rev、reason，可选 disposition=usable/not_usable。失效支持结果只能按 not_usable 验收，需要继续则建新核查。done 表示子问题已处理，不代表原因成立；引用同一来源的多份报告不是独立印证。

## 结案契约

核心[完成边界](../SKILL.md#完成边界)决定是否交付，以下字段只是已有账本的写入约束：

```json
{"rev":12,"outcome":"root_cause","route":"evidence_chain","conclusion":"具体原因","scope":"实测覆盖范围","limitations":"仅外推边界","hypotheses":["H_ROOT"],"evidence":["E1"],"acceptance_check":"与原目标的对应","decision_review":{"scope_check":"范围依据","causal_link":"具体机制及必要前提","countercheck":"关键替代解释的核查依据","evidence":["E1"],"open_issues":[]}}
```

- outcome: root_cause/fix_verified/narrowed/blocked。成功 route: evidence_chain/targeted_fix，需有效证据、acceptance_check 和 decision_review；root_cause + evidence_chain 另需至少一个 confirmed 根因假设。confirmed/ruled_out 假设也用同结构 decision_review。
- decision_review 的 scope_check/causal_link/countercheck 必须非空、evidence 有效、open_issues 为空。应先解决当前判断的关键缺口，不能为了通过校验把它清空或藏入 limitations。
- close 时不能有 running/submitted 任务，成功时所有 task 须 done/cancelled；取消不必要的剩余工作要有理由，不能伪造完成。reopen 使用案例 rev 与 reason，历史结论保留。

schema 1 的旧案例仍可读取。新写入遵守上述校验；恢复不要求补齐全树、登记所有候选或重新确认所有历史观察。
