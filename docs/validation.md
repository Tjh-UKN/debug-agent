# 机制、接入与长任务恢复验证

## 0.7.0 调查树与回溯（2026-09-21）

依据《Debug Agent Investigation Trace & Backtracking》设计文档与开发者实施指南，在不重构现有账本的前提下补齐两类关系的显式区分：`investigates` 记录“为什么会调查这个节点”（调查树），`parents` 只记录逻辑必要前提（AND 型依赖 DAG）。两者禁止互相推导，由脚本校验与投影分则保证。

落地内容：`case.py` 新增 hypothesis 的 investigates/investigation_question 校验（存在性、非自指、lineage 无环、非空时问题必填）、checkpoint 的 focus_hypotheses 引用校验，以及新 close 约定——root_cause + evidence_chain 必须关联至少一个 confirmed 根因假设（narrowed/blocked/fix_verified 不强制，历史已关闭案例读取兼容）。`reconcile_correction` 未改动：撤回仍只沿 parents 与证据引用传播，调查子树是否当前有效由投影动态计算，不写回 state.json。

新增纯投影模块 `investigation.py`（children/investigation_path/logical_dependencies/logical_dependents/branch_health/active_frontier/investigation_tree/why_trace/impact_trace）与只读 CLI `trace.py`（tree/path/why/impact/frontier，JSON 输出）。path 只沿 investigates，why 只沿 parents 与已登记证据，impact 只计算显式引用可达的影响范围；缺失关系如实标注，不猜测。`recovery.py` resume 返回 investigation 段（focus、当前定位路径、frontier、pruned、stale、未登记 lineage），恢复调查状态而不只是执行队列；`panel.py` 在状态卡增加紧凑的定位路径与来源候选分支，交付卡对 evidence_chain 闭环显示根因节点。文档同步：SKILL.md 新增“调查与回溯”，tasks.md 写明两类关系的正确用法与回溯规则，display/commands/README 补充展示与追踪入口。

验证：Python 3.12（WSL）全部 85 项检查通过，包括原 65 项（13 账本 + 10 机制 + 22 msprobe + 20 接入）与新增 20 项调查测试，覆盖设计指南的 T1–T10 矩阵：lineage/环检测原子性/兄弟独立性/后代剪枝不落盘/两类关系分离传播/why-path 分则/闭环根因契约/legacy 可读/恢复投影，及三个合成行为场景（confirmed 位置不 closure、单候选排除不污染兄弟、逻辑前提失效沿 parents 撤回）。另以合成“高并发 aclgraph layer28 NaN”案例端到端冒烟：建树、排除 H10 仅剪该子树、trace path/impact、resume 恢复 focus/frontier/pruned、面板展示均符合设计第 13/15 节示例。

旧测试中有两处 close fixture 按新契约更新（补 confirmed 根因假设与 hypotheses 字段）；这是 T8 明确要求的契约变化，非行为回归。边界：不回填历史 investigates，旧案例显示“未登记调查来源”；branch health 是派生投影，不写入 state；impact 只覆盖显式引用，自然语言中的隐藏前提仍需主 agent 补查；put 是完整记录替换，更新假设时需携带已有 lineage 字段。本轮未运行真实训练、未重跑真实长程诊断，不宣称模型定位能力已提升。

## 0.6.1 围绕问题边界精简（2026-09-18）

按用户最新约定，核心仅保留整体问题、已知/未知、子问题边界与当前关键问题的组织方式，以及完成标准和工具入口。删除“三类关键判断”推理教学、重复的模型补偿提醒和场景排查步骤；数值参考缩为证据范围表，训练参考缩为材料索引，评估约定合并重复内容。问题概况复用现有 checkpoint.summary/next_action，不新增 schema、状态或必填表格。

相对 0.6.0，核心正文由 3,966 字符降至约 1,650（约减少 58%，按 Unicode 字符计，不是 token 性能指标）。保留 msprobe 四条数据契约、缓存查询及全部脚本，保留实际派工/恢复协议和静态证据链、小场景闭环标准。

本轮仅修改文档和版本标记。核查 Skill 格式、本地引用与章节锚点、插件 JSON、git diff，以及更新后 Codex/WSL Pi 安装文件与源码的一致性；未改脚本、未重跑训练或原诊断案例。减小上下文负担不等于已经证明定位效果提升。

## 0.6.0 训练定位知识与缓存证据查询（2026-09-18）

依据用户提供的 Ascend/msprobe 训练精度定位指南，新增按异常时机、随机性和观测扰动选择核查的参考入口。保留来源与读取快照哈希，不照搬统一阈值、默认升级、CPU 绝对真值或全套采集前置条件；已有材料优先，无实验条件仍可分析。

新增 `msprobe.py query --scan <dir> --api '<glob>' --phase backward --limit 3`，只读已有 summary/alignment，不重开原包。新 scan 保存输入/输出分组统计、Norm 差异与元数据变化；query 按每个 step/rank 分页，保留零命中卡、未匹配、端口角色警告及缓存来源。旧扫描缺少分组证据时显式提示；缓存行数与 summary 不一致时拒绝返回覆盖完整的结果。

验证：Windows 与 WSL 各通过 22 项读取/查询检查和 20 项安装/接入检查；Skill 格式、引用、git diff 检查通过。Codex 与 WSL Pi 安装后各 19 个文件与源码一致，安装前已有文件均按既有规则备份。账本逻辑未改动，未重复运行其余旧检查。

独立审查使用合成多步多卡、未对齐/缺卡、非有限值与真实旧版扫描；原 ZIP 移走后查询仍可执行。发现根输出张量 `/output` 被错分到输入组，已修复并增加回归，定向复核通过。新增缓存截断检查也验证了“未选中的卡被截断”不能静默通过。

原始两包只读验证：仍覆盖全部 8 卡、50,842 条匹配，原包 SHA256 未改变。一次缓存查询返回 8 卡各一条相关调用，并核对输入/输出字段与类型差异；旧存档同样可查询但不会伪造其缺少的证据。本机单次观测：首次扫描约 30.1 秒，缓存查询 Windows 约 1.5 秒、WSL 挂载目录约 3.6 秒。这是取证操作的功能与成本记录，不是根因定位提速的对照试验。

本轮未运行训练、模型复现或 Pi 整轮诊断，不宣称模型诊断能力已提升。私有输入、输出数值与本地分析产物不入库。

## 关键判断逻辑约束（2026-09-18）

本次只修订 Skill 的判断与评估说明，不更改读取器、账本 schema 或状态转换。核心增加三处决策约束：排除前核实必要预测；确认前区分相容证据与因果判别；结案对照原始目标，不能将尚会改变根因归属的候选移入 limitations。保留充分静态证据可以闭环、有效小场景不强求大场景验证的原约定。

核查结果：UTF-8 Skill 格式校验通过；4 份改动文档中的 10 个本地引用及新增核心章节锚点有效；git diff --check 通过；Windows Codex 与 WSL Pi 安装后各 18 个文件与源码逐字节一致，旧安装已备份。可执行脚本未修改，本次未重复运行既有 58 项脚本检查。

小范围行为对照：两个隔离的 Codex subagent 继承同一宿主模型，分别读取旧基线 77c45e7 和本次规则快照，回答相同的三个合成节点；仅提供事实与待审提议，不提供预期答案或运行中纠正。旧/新两组都正确拒绝“整体 Norm 接近即可排除局部实现错误”，都拒绝“未区分起因但确认放大链后成功结案”，也都在实际加载代码、完整输入和接口契约足够时接受静态根因确认，没有强制实验。

因此只能确认这三个短节点未发现行为回归，不能证明新条款带来增益。这不是 Pi/GLM 的模型对照，也未重跑真实长程案例；当前模型、完整流程及多次运行上的效果仍未验证。本地保留两份独立回答与对应输入，未把真实案例答案写入技能。

## 0.5.0 msprobe 数据语义与流程整改（2026-09-18）

四条输入契约落实到 `scripts/msprobe.py`：保持 dump 原始执行序；按 stack 的 API 名列表关联；按调用栈、shape、方向/重计算及重复调用执行序建立两端对应；扫描全部提供的卡并核对 mesh 所示参与卡。未匹配、缺卡、统计缺失与端口布局差异均保留，dtype/mask 差异不用于筛掉记录。

流程改动：关键推断先核可比性与必要条件；区分起因、传播、放大；新任务通过 prepare-task 在派工前保存 pending 节点并生成交接；子任务完成问题即返回；reviewer 的读取器也接受原始条目核查；narrowed 在卡片和报告中都表示根因未确认。新增 Pi 安装入口，沿用备份/原子更新，不改变模型配置。

验证命令：

```sh
python -B skills/debug-agent/scripts/test_case.py
python -B skills/debug-agent/scripts/test_mechanisms.py
python -B skills/debug-agent/scripts/test_msprobe.py
python -B scripts/test_integration.py
```

Windows/Python 3.13 与 WSL/Python 3 的检查分别覆盖 13 项账本、10 项机制、15 项 msprobe、20 项接入/安装，共 58 项。核心格式以 UTF-8 模式验证。

真实材料只读回归：两端各 8 rank，读取覆盖完整；50,842 条调用满足自动对应规则；左端 488、右端 256 条未匹配记录均显式保留。非零卡的前向与反向差异可从 compare 直接取得，调用栈按显式 API 成员关联。绝对/相对差异按前向、反向、重计算标记分别汇总；较大差异列表只用于导航，不替代完整对应表或确认根因。

独立 agent 在不读取旧诊断答案、不重跑真实全卡 scan 的条件下，实际核查真实包的 inspect/compare，并构造重复调用、缺卡与非有限值场景。发现单边缺卡的现存 API 未写入完整表，已修复并在两端平台验证；全卡范围未因此被静默误报。另覆盖 shape 匹配但没有统计的场景，确保概览明确比较数为零。

本轮不运行训练/复现实验，也未再启动 Pi 的整轮长程诊断。上述检查证明读取、对应和状态机制的行为，不证明模型已能稳定得出正确根因；宿主真实派工与最终因果判断仍需真实案例验收。私有原包、数字、调用栈及本机回归产物不加入仓库。

## 0.4.0 诊断机制改进（2026-09-17）

改进依据是完整加载 Skill、启动两个真实 pi subagent 后仍出现的诊断错误：把局部观察扩大到全部材料、派工固定错误前提、将未记录当未执行、复算数字代替因果验收。本轮不重跑真实诊断，不将机制测试通过等同于定位能力通过。

改动集中于：保留证据范围；只扫描给定路径的材料目录；带原始问题与目录的只读 handoff；以 supersedes/depends_on 撤回依赖判断；重要排除及成功闭环的 decision_review。领域提示补充统计量、分片/归约、采集覆盖和实际执行路径的解释边界。

验证命令：

```sh
python -B skills/debug-agent/scripts/test_case.py
python -B skills/debug-agent/scripts/test_mechanisms.py
python -B scripts/test_integration.py
```

Windows/Python 3.13 与 WSL Ubuntu/Python 3 均通过全部 41 项：13 项原账本检查、9 项机制回归、19 项接入检查。机制回归覆盖材料遗漏、只读交接、错误证据及衍生结论撤回、过期写入拒绝、场景/任务/基线依赖、旧结果不得重新支持结论、无关更正不反复打开废弃结果，以及合法小场景证据链仍可闭环。Skill 格式使用 UTF-8 模式验证通过；Windows 默认 GBK 运行验证器会报解码错误，使用 `python -X utf8`。

独立 agent 仅使用临时合成数据实际调用 CLI，验证派工范围、撤回、旧证据拒绝、局部闭环和关闭后重开；发现的场景关联传播遗漏、废弃结果重复验收已修正并加入回归。该检查未运行用户训练或模型实验。

材料目录工具另在用户两份原始压缩包上只读验证：48 个 JSON，覆盖两端 rank0–7，无读取错误。没有将原始数据、文件内容、评估答案或本机诊断报告加入仓库。

边界：inspected 是 agent 自报的源文件访问记录，scope/decision_review 的语义真实性由主 agent 判断。脚本仅能撤回已登记的依赖，不能识别隐藏在自然语言中的所有前提。schema 1 历史可读，新证据和新决定采用更严格字段；未自动把历史结论认证成新机制下有效。

## 0.3.0 接入验证

验证日期：2026-09-17。发布版本：0.3.0。

## 环境与结果

| 环节 | 环境 | 结果 |
|---|---|---|
| 状态/接入脚本 | Windows，Python 3.13.3 | 13 项账本 + 19 项接入检查通过 |
| 状态/接入脚本 | WSL Ubuntu 24.04，Python 3.12.3 | 相同 32 项检查通过 |
| Claude 插件/marketplace | Claude Code 2.1.247，WSL login shell，Node 22.23.1 | `plugin validate --strict` 分别通过 |
| Claude 实际会话 | 用户现有模型配置；以 `--plugin-dir` 加载本地源码 | 命令发现、SessionStart 注入、恢复脚本执行和卡片输出通过 |
| Codex Skill | 本机安装副本与源码同步、格式验证 | 通过 |
| Codex 独立 CLI 会话 | 桌面自带 0.154.0-alpha.6.2，ephemeral/read-only | 无输出超时，停止测试进程，未记为通过 |

没有通过修改模型、重装用户客户端或开放额外写权限来绕过接入问题。Claude 实际会话保持用户原有模型配置。本次不验证远程计算设备、真实精度根因或跨会话自动选择率。

## 验证命令

从仓库根目录执行；Linux/WSL 使用 `python3`，Windows 使用 `python`：

```sh
python3 -B skills/debug-agent/scripts/test_case.py
python3 -B scripts/test_integration.py
claude plugin validate --strict .claude-plugin/plugin.json
claude plugin validate --strict .claude-plugin/marketplace.json
```

结果分别为 `Ran 13 tests ... OK`、`Ran 19 tests ... OK` 和两次 `Validation passed`。

## 实际 Claude 会话

使用独立合成案例：一项任务保存为 running，带合成 host/job_id/命令/产物；另一项任务已 submitted、尚未验收；checkpoint 后场景从 original 改为 different。没有真实实验或远程主机。

在案例项目的 `src/` 子目录启动会话，设置 `DEBUG_AGENT_CONFIG` 指向独立的 `{"always_on":true}` 文件，使用 `--plugin-dir`，保留真实用户启动环境。限制为只读工具和指定恢复/面板命令前缀，`--permission-mode dontAsk`，不允许编辑文件。显式请求：

```text
/debug-agent:debug resume <case-dir>
这是只读恢复检查，请汇报真实持久状态，不启动实验、不连接远端、不写文件。
```

观察到：

1. 客户端发现 `debug-agent:debug` 和核心 Skill；SessionStart 返回 `[Debug Agent ON]` 上下文，退出码 0。
2. 从 `src/` 找到项目根的活跃账本。
3. Agent 实际读取核心、路由、任务与展示协议，然后调用：

   ```sh
   python3 <plugin-dir>/skills/debug-agent/scripts/recovery.py resume --case <case-dir>
   ```

4. 返回成功，无工具权限拒绝；以方框卡展示案例及任务，并明确历史 running 不是实时状态。
5. 输出四类恢复提醒：checkpoint 后记录变化、基线失效、运行记录待核实、结果已提交待验收。
6. 会话前后 `state.json` 字节完全一致；没有运行账本中的合成实验命令。

第一次会话暴露了额外目录探测被拒绝后跳过恢复脚本的问题；路由改为已知路径直接调用受支持入口后，第二次通过。保留第一次失败事实，不将只读文件降级访问误算为脚本路径已验证。

## 本轮修复依据

- WSL 实际不存在 `python`，原 hook 会失败：启动器改为优先 `python3`。
- 子目录启动找不到账本；旧的十条上限可能遮住活跃案例：增加共享发现工具，按活跃/关闭/损坏分类，到仓库边界停止。
- 状态读取原先需要写锁文件：改为读取原子替换后的完整快照，只读目录也可使用。
- 展示省略号会裁掉结论限制：关键长文本在卡片下完整补出。
- 更新文件中途写入失败会留下新旧混合安装：逐文件原子替换，异常时恢复已写入文件；回滚失败明确报告备份。

后三类恢复风险由测试覆盖：多个案例不猜选，损坏案例不遮蔽健康案例，旧 checkpoint/失效基线不再被静默视为可靠下一步。脚本只呈现数据和提示，不代替 agent 判断实际作业或证据真实性。
