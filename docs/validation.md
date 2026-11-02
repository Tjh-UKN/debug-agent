# 机制、接入与长任务恢复验证

## Pi 历史案例回放：短任务、无总超时（2026-11-02）

对 0.9.1（代码提交 f05e234，测试时 HEAD 为 2cd388c）进行一次历史统计 dump 案例回放。仅提供症状、数据路径、纯分析约束和报告要求，并显式加载当前 Skill；不提供历史结论或中途定位提示。案例数据和原始报告留在本机，不纳入仓库。

Pi 0.84.1 使用当前默认 volcengine/deepseek-v4.1-flash、thinking=high，外层无总超时。606.555 秒后自然退出，退出码 0，49 次工具调用。它自主调用 msprobe 全卡扫描，覆盖 8 rank、无缺卡或读取错误，并将 SDPA/mask 处理列为最强候选。数据、Skill 和模型配置未改变。

评价为方向命中、范围缩小；报告仍有从统计摘要扩大排除、将推测的后端与因果链写得过于确定等问题，不能认定可靠根因闭环。此次不是同模型有无 Skill 的对照，不据此宣称整体定位质量或速度提升。

## Pi 单案例接入与行为检查（2026-11-02）

被测代码为提交 `f05e234`（0.9.1）。先在 Windows 运行统一脚本检查，147 项通过，再将当前 Skill 用原安装器更新到 WSL Ubuntu 的 Pi 环境；`python3 scripts/install.py pi --check` 返回 managed_files=22、missing/changed/obsolete 为空、matches=true。模型配置保持不变。

实际运行：Pi 0.84.1，Node v22.23.1，默认 provider `volcengine-ark`、model `volcengine/deepseek-v4.1-flash`、thinking=high；最终模型消息中的 provider/model 与默认配置一致。Pi 入口是 `/home/tjh/.nvm/versions/node/v22.23.1/bin/pi`，实际读取 Skill 为 `/home/tjh/.pi/agent/skills/debug-agent/SKILL.md`。默认非交互 PATH 中没有 pi，因此仅在本次子进程的 PATH 加入已有 Node bin，没有修改 shell、模型或凭据配置。

将 case-04 的 request、plan、events 和 runner.log 复制到新的 `/tmp/debug-agent-pi-case04-*` 目录。只提供案例请求与已安装 Skill，禁止读取评估答案、维护文档、历史会话和其他个人文件；本次明确要求调用实验判定器，因此属于工具接入与行为冒烟，不是自由选择工具的效率对照。

```text
pi --offline --no-session --no-extensions --no-skills \
  --skill /home/tjh/.pi/agent/skills/debug-agent \
  --no-prompt-templates --no-context-files --no-themes --no-approve \
  --tools read,bash,grep,find,ls --mode json --print <case-request>
```

`--no-skills` 关闭自动发现，显式 `--skill` 仍加载指定资源，按本机 Pi resource-loader 实现核实。`--offline` 仅关闭启动时网络操作，正常模型请求仍使用用户当前配置。允许 bash 以运行只读判定器；读取范围和禁止修改由请求约束，未声称有额外文件系统沙箱。

决定性实际调用：

```sh
python3 /home/tjh/.pi/agent/skills/debug-agent/scripts/diagnosis.py \
  evaluate --plan plan.json --events events.jsonl
# decision=stop, reason=invalid, invalid_preconditions=[same_input]
# matching_rules=[bad_output], selected_events=4, ignored_events=1
# process_stopped=false
```

Pi 正确解释：当前输入字节不匹配使重放失效，已有 NaN 不能确认或排除 kernel 对原训练的因果责任；旧运行的 same_input=true 不可借用；停止建议针对额外采集，历史 running 不是实时状态。实际退出码 0、无工具错误；案例、安装 Skill、settings.json/models.json 在运行前后内容一致，没有训练或真实进程停止动作。

本次墙钟 35.941 秒，10 次 assistant 消息结束事件、15 次工具调用（read=9、ls=3、bash=3）。模型报告累计 input=10,463、output=3,419、cacheRead=39,936、totalTokens=53,818；这是多轮请求的累计用量，含重复缓存读取，不是单次上下文长度，也不是独立核对的账单。

核心案例判定通过，但有可见瑕疵：已获得 invalid 后又用 `--finished` 重复判定，读取了额外参考；从“字节不同”进一步断言数值不同，并提及未提供的“原始账本”，表达超出给定证据。故不记为所有诊断表述均准确，也不据此给整个产品成功率或提速结论。单个已知开发案例无 A/B 对照，没有重跑或据一次输出增加通用规则。

命令、脱敏事件、原始回答和逐项判定保存在本机 `.work/pi-case04-20261102/`，不提交运行日志或凭据；测试结果只记录于本文。源代码提交与本次验证记录分开保留。

## 0.9.1 结构与分发瘦身（2026-10-22，本地升级，未发布）

删除 panel.py 卡片渲染器及 display/evaluation 两份无调用的兼容占位参考；状态查询复用 case show/recovery resume。调查来源、前提依赖、证据更正和已有 case/schema 仍有恢复用途，保留其实现与回归。S/D、判定/偏序/保真细化、去噪及实验判定的详细参考和工具保留。

七个测试模块集中到仓库 tests/，不再随任何宿主的 Skill 源目录分发；移除八项纯卡片展示检查，机制检查保留，新增五项分发/迁移检查。安装器只识别明确列出的九个历史受管理路径，更新前备份、清理失败回滚；不按通配符删除用户自建文件，不修改案例数据或模型配置。旧 panel 接口退役，使用 `case.py --case <dir> show` 查看原始状态。

| 度量 | 瘦身前 | 瘦身后 | 变化 |
|---|---:|---:|---:|
| 安装受管理文件 | 31 | 22 | 减少 9 个 |
| 分发内容原始字节数 | 284,716 | 162,683 | 减少 42.9% |
| SKILL.md Unicode 字符数 | 1,716 | 1,245 | 减少 27.4% |

字节数按受管理源文件原始字节相加，不含 pycache、备份或用户额外文件；字符数包括 frontmatter，不是 token、定位速度或质量测量。瘦身前快照和逐文件清单保存在本机任务产物中。

```sh
python -B -X utf8 -m unittest discover -s tests -t .
# 147 passed；统一测试入口
python -B -X utf8 <skill-creator>/scripts/quick_validate.py skills/debug-agent
# Skill is valid!
git diff --check
# passed；保留已有 CRLF 规范化提示
```

迁移回归实际覆盖：安装包不含测试与退役模块；旧残留的只读检查；更新前备份九个历史文件；用户自建 test_custom.py 和已有案例保留；删除中途失败后还原先前删除与修改；Claude 别名不清理相邻目录；异常同名目录不被当文件删除。没有重复运行模型行为对照或设备作业，不能从瘦身比例推断诊断提速。

本机 Codex 已通过 `scripts/install.py codex --update` 同步，随后 `--check` 返回 managed_files=22、missing/changed/obsolete 均为空、matches=true。从安装目录实际导入九个运行模块，并调用 frontier 保留两个异常候选；九个退役文件在安装中均已移除，备份字节与瘦身前快照一致。实际路径与输出保存在本机任务产物中，未发布远程版本。

## 0.9.0 诊断结构与局部确定性操作（2026-10-22，本地升级，未发布）

进化分析与组件关系见 [diagnostic-architecture.md](diagnostic-architecture.md)。本轮将 S/D 信息与关联、三值判定、异常偏序、保真细化、去噪、主动诊断和序贯停止组织到短入口及两份按需参考，保留用户选择路径与证据充分即交付的约定。hypothesis 不是调查起点的必填条件；原有账本/schema、恢复与默认查询保留。

新增 `diagnosis.py`：judge 对显式样本和容差执行 finite/close/range，缺条件保持 unknown；frontier 计算有来源的依赖 DAG 的极小已观测异常，保留未知祖先和未决边；evaluate 在对应执行窗口内区分回答、反证、无效、未决与预算，只给继续/停止建议。有效前提优先于预期现象，同事实冲突不取最后值。没有进程控制或根因认证副作用。

msprobe query 增加 `--focus differences`：仅折叠无变化且无缺失/警告的已比较摘要，保留有限小差异、元数据、双方异常、旧缓存未知与未匹配，按聚焦后结果分页，所有卡和折叠计数仍返回，原始 alignment 可回查。没有新增后台服务或远程执行器。

### 确定性检查

Windows，Python 3.13.3：

```sh
python -B -X utf8 -m unittest discover -s skills/debug-agent/scripts -p 'test_*.py'
# 最终 126 passed：本轮起点 97 + 26 项 diagnosis + 3 项差异聚焦回归
python -B -X utf8 -m unittest discover -s scripts -p 'test_*.py'
# 24 passed：隔离安装、更新、回滚、路由与旧接口
python -B -X utf8 <skill-creator>/scripts/quick_validate.py skills/debug-agent
# Skill is valid!
git diff --check
# passed；已有 precision.md 出现 CRLF 将被规范为 LF 的提示，无空白错误
```

累计 150 项不同脚本检查通过。judge 覆盖部分样本的有效违规、缺失/错误参考、上下文未验证、禁止默认容差、大整数及浮点溢出边界；frontier 覆盖并发来源、跨正常节点的未知祖先、推测边不剪枝、循环拒绝及来源保留；实验检查覆盖跨运行混入、前提否定/未知、冲突、预算、明确范围的反证、只读 CLI 和受控合成采集循环早停。循环在第四个必要事件后结束，没有继续处理后续无关事件；这是合作式接线检查，不是 GPU/NPU 作业停止或节省时间的实测。

另核对 Skill 路由、README/架构/评估文档链接和两个插件 JSON 版本，均可解析。未重跑真实训练、远程复现、通信任务或性能基准。

### 隔离前向使用检查

新增公开合成 case-03/04，答案仅在 evals/expected.md，不进入 Skill 路由和安装范围。一个未继承本轮讨论的独立执行者只取得对应请求、原始材料、更新后的 Skill 及相关工具；明确禁止读取维护文档、答案、历史结果和工作快照。它按两个请求分别处理，实际读取 diagnosis/experiments 参考并调用 frontier/evaluate；两次 CLI 均退出 0，无工具错误，无文件修改或真实作业动作。

- case-03：返回 branch_a/branch_b 两个极小异常候选，保留 upstream_state、partial 覆盖及未决控制边，未用时间戳排序或正常摘要排除上游；没有宣称全局唯一首错或根因。
- case-04：以本次输入字节不匹配判重放 invalid，忽略旧运行的相反记录；即使已有 NaN 仍未确认或排除 kernel 对原训练的因果责任。区分停止额外采集建议与真实进程控制，保留 process_stopped=false，未将历史 running 当作现场事实。

这是一个上下文中的两个开发回归，没有同条件 A/B 对照、重复样本、精确用量和可比耗时，不能据此宣称诊断准确率或速度提升。

### 本机安装与实际入口

通过原安装器将当前工作区 Skill 同步到本机 Codex；安装器先备份已有差异文件，没有修改模型配置或其他宿主。

```sh
python -B -X utf8 scripts/install.py codex --update
# Installed；旧受管理文件已备份
python -B -X utf8 scripts/install.py codex --check
# managed_files=31，missing=[]，changed=[]，matches=true
```

实际以安装目录的 diagnosis.py 执行三个入口：judge 返回 normal/unknown/abnormal；frontier 返回两个分支并保留未知祖先；evaluate 返回 invalid，忽略 1 条外来窗口记录，process_stopped=false。命令、解析输出和实际脚本路径保存在本机任务产物中，不进入 Skill 安装。内容一致与脚本调用不证明宿主在新会话中的隐式选择率，也未发布到远程市场。

## 生命周期调整、协议修复与公开回归（2026-10-13，未发布）

基于源码基线 `60f5e73` 修改工作区，保持插件版本 0.8.0，本轮未提交、发布或同步用户已安装副本。

入口改为 AI 训练/推理的报错、挂死、数值与状态异常诊断。SKILL.md 保留目标、证据边界、完成契约及短路由；移除通用诊断决策教程，不增加固定实验或账本前置要求。训练参考提供度量语义和局部取证边界；报错/挂死参考解释异常链、线程栈、collective 与等待关系，附可适配的 faulthandler 示例。维护侧按 A→B 的工具收益、B→C 的指导收益分别验收，并说明模型/框架升级后的更新与退役条件。

确定性修复：

- msprobe 保留 nan_check 的顶层 is_nan、任务/采集级别与每侧首次已报告异常；标志不同、双方异常、缺失和非法值分别表达，不从缺少统计推断正常。新旧 scan/query 缓存均可读取。
- 支持 L0/mix 模块 forward.N/backward.N、parameters 与 parameters_grad.N；参数梯度计数按 grad_fn 触发次数解释，不借同号 forward 建立虚假对应。缺独立栈时保持未匹配，但 inspect 仍保留梯度统计。
- 必要前提的主张、关系或状态变化沿 parents 撤回依赖判断；恢复能识别失效前提，成功结案拒绝不可用必要前提。investigates 保持独立，旧原始证据、结果、运行标识和 schema 保留。

实际检查（Windows，Python 3.13.3）：

```sh
python -B -X utf8 -m unittest discover -s skills/debug-agent/scripts -p 'test_*.py'
# 97 passed；原 78 + 12 项 msprobe + 7 项前提传播回归
python -B -m unittest discover -s scripts -p 'test_*.py'
# 24 passed；临时目录内安装、更新、回滚与路由检查
python -X utf8 <skill-creator>/scripts/quick_validate.py skills/debug-agent
# Skill is valid!
git diff --check
# passed
```

另核对仓库本地 Markdown 路由、插件 JSON 和 UI metadata；两个公开案例的脚本输出与固定 records.jsonl 逐字节一致。faulthandler 示例在临时目录、短超时下实际输出等待线程栈，随后取消定时器，进程正常退出；没有设备作业或外部写入。

### 独立上下文的合成行为对照

公开材料在 [evals](../evals/README.md)。三个新的执行者均未继承本次修改与审核历史，只取得同样的两份 request、对应源码和完整相关记录；禁止读取评估答案及维护文档。A 没有插件资源，B 可选工具及协议说明，C 可用当前 Skill 和按需参考。每组在一个上下文中依次处理两例，共六份诊断；不是每例多次重复的统计试验。未设置模型覆盖，实际模型 ID、采样参数、精确用量与可比耗时未获取，不能将缺失成本填为 0。

| 组别 | case-01：停顿 | case-02：loss 上涨 | 实际读取与动作 |
|---|---|---|---|
| A：直接诊断 | 正确关联 rank1 NaN 分支、缺席 dp seq=1 和 rank0 等待；保留 NaN 来源未决 | 正确指出分子未 mask、分母只计有效 token；不推断梯度/参数机制 | 六份原始文件，只读 |
| B：工具与协议可选 | 同样正确解释模拟中的参与缺失，不归因于真实网络 | 同样正确解释 8/4→8/1，并保留零有效 token 的额外契约问题 | 六份原始文件；未调用或读取可选工具，因为静态材料足够 |
| C：当前 Skill | 正确解释具体分支和对应记录，限定合成范围 | 正确解释指标计算错误，未宣称修复已验证 | 六份原始文件，另读 SKILL.md、failures.md、training.md；只读 |

三组都没有修改案例、运行训练/通信、访问外部环境或宣称真实修复完成。逐例判断引用源码/记录及具体机制，不以答案关键词或步骤数量评分。

这个结果支持：新版入口和按需参考在这两个静态小案例上没有观察到诊断退化。A 已能正确完成，B 的工具没有被需要，C 增加了三份阅读，故本轮**没有证明工具或指导提升定位质量/速度**，也不足以判定资料应全部退役。后续需要真实取证缺口、正常行为反例和未参与设计的案例，按消融结果裁剪；不把本轮六份诊断当作真实设备验收或总体成功率。

## 0.8.0 默认直接诊断与产物校验（2026-09-29）

同日产品整理：把诊断决策集中到 SKILL.md；runtime.md 只保留运行身份、对象复用、异步依赖和插桩的特殊边界。删除卡片教程与重复诊断示例，display/evaluation 旧路径只留简短兼容说明；评估设计统一放在仓库 docs 中。commands 与 tasks 压缩为按需接口说明，旧脚本、schema 和用户数据不删除。msprobe 明确已有 scan 可直接 query，局部查询无需强制全卡重扫，局部结论不外推。

相对本轮整理前的工作区快照，Skill 入口与 references 文档总字符数从 26,550 降到约 15,328（减少 42%）；README 从 5,647 降到 2,199（减少 61%）。仅是文字量，不是定位性能结果。全部 102 项测试再次通过，另检查 frontmatter、本地文件路由与 diff；本轮没有新增模型行为实验或重新运行设备任务。

默认入口改为直接诊断、按需读取工具；移除根文件内的调查树字段教学，普通问题不要求建账本或显示卡片。commands、display、SessionStart 提醒与别名入口同步调整，既有账本/调查树实现和旧案例格式保持不变。SKILL 正文从 2,204 个 Unicode 字符降至 1,039（约减少 53%，不含 frontmatter；不是 token 或实际耗时测量）。

新增按需运行时取证参考：实际加载身份、对象复用、异步完成、插桩扰动、局部干预和重复实验的判别边界；不把某个案例的 `-1`、固定层或 A/B/A 变成通用强制流程。后续按用户反馈补明确：相关执行路径理解与局部 review 的边界；原场景补观察、独立对照、场景缩减的分别适用条件；由模型比较已有 trace、工具和局部插桩，不设固定升级顺序。进一步区分“联合分析后的充分性判断”和“步骤有效性”：重要核查需要明确改变了哪个关键未知，允许纠正前提后扩大范围，不把单调缩小或完成工具调用视为诊断进展。这些指导只做静态一致性校验，行为收益仍未验证。新增 `evidence.py capture/show/verify`：仅复制明确指定的已有产物，保存大小、SHA256 与捕获信息，校验后输出有行号的摘录；不执行命令、不连接服务器、不自动登记 confirmed。调用方提供的上下文显式标为 declared_context。

安装器新增只读 `--check`，比较所有受管理文件实际内容及检查本地 Markdown 文件路由，修复原核心指向不存在 commands.md 的路由。插件版本和描述同步到 0.8.0。安装核查发现旧 Codex 副本缺少本轮文件及 0.7.0 的 investigation/trace；通过原有备份更新流程同步本机 Codex，26 个受管理文件与源码一致。未更新其他宿主或外部插件市场。

验证命令与结果：

```sh
python -X utf8 -m unittest discover -s skills/debug-agent/scripts -p 'test_*.py'
# 78 passed：原有 65 项 + 13 项产物快照测试
python -X utf8 -m unittest discover -s scripts -p 'test_*.py'
# 24 passed：原有 20 项 + 4 项安装/路由校验
python -X utf8 scripts/install.py codex --check
# matches=true；26 managed files
```

另通过 Skill frontmatter 校验、插件 JSON 解析和 git diff --check。真实已有产物只读检查：使用上轮案例的统计 JSON、指标日志及候选补丁，保存 3 个文件共 5,951 字节，verify 报 intact=true/sources_match=true；show 精确返回指标日志第 3、4 行，两条 engine 的 preemptions 均为 0。原文件哈希未变化，没有重新运行模型或远程实验。私有原始产物和本地输出不入库。

独立行为对照尝试：已在仓库外准备三份相同 CPU 小案例，分别指定“直接诊断”“工具与必要资料”“新版 Skill”，使用独立上下文且不向执行者提供答案。三个子 agent 都因账户用量限制在启动阶段失败，未产生报告。故本轮行为对照为**未执行**，没有定位质量、调用次数或耗时比较；不能宣称已证明更稳定或更快。后续完整案例与成本评价见 [改进目标与验证计划](diagnostic-effectiveness.md)。

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
