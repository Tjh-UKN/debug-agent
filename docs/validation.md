# 接入与长任务恢复验证

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
