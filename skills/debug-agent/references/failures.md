# 报错与挂死证据

在需要解释异常链、停顿或跨 rank 等待时读取相关部分。材料含义、采集方法和能力取决于实际运行版本；以下不规定先后顺序，也不将 timeout、OOM 或异常文本直接当成根因。

| 材料 | 可以回答的问题 | 解释边界 |
|---|---|---|
| 原始异常链、stderr 与退出记录 | 哪个进程首先报告何种失败，哪个调用暴露它 | 包装异常可能只转述 worker 失败；异步设备错误可能在后续同步处暴露。源码以实际加载实现为准 |
| 进程身份、存活与最近进展 | 被观察的作业/PID/rank 是否仍在运行，最后完成的工作是什么 | 保存的 running 标签、PID 单独存在或设备利用率不能证明作业健康；PID 会复用 |
| 线程栈与重复观察 | 当前线程等待什么，观察期间是否推进 | 一次栈快照不区分快速瞬间、缓慢工作和永久等待；Python 栈不自动给出设备或 C++ 内部状态 |
| 各 rank 的 collective trace | 同一 process group 的参与方、序号、操作与完成情况是否对应 | 序号只在对应组和运行内可比；提交不等于完成。异步 overlap、缺失或截断记录不能直接认定执行分叉 |
| 数据加载/队列/锁的生产与消费记录 | 等待者需要谁提供数据或释放资源 | 等待栈只说明消费者停在哪里，仍需生产者状态或实际代码解释为什么无法推进 |

## 按现场选用的取证手段

已有日志或 trace 能解释问题时直接分析。缺少线程状态时，Python 的 [faulthandler](https://docs.python.org/3/library/faulthandler.html) 可在目标进程中输出线程栈。安装它、向进程发信号或定时采集都应适配本次权限和生命周期，不向任意进程发送未注册信号。

下面是可嵌入目标进程的短时观察示例，不是通用启动要求。它会替换该进程已有的 faulthandler 定时任务；已有定时器时应复用或另选手段。日志描述符需要在采集期间保持打开：

```python
import faulthandler

with open("threads.log", "w", encoding="utf-8") as trace_file:
    faulthandler.dump_traceback_later(30, repeat=False, file=trace_file, exit=False)
    try:
        run_observed_region()  # 替换为本次相关执行区间
    finally:
        faulthandler.cancel_dump_traceback_later()
```

已观察区间提前返回时不会产生超时栈。`exit=False` 保留现场，不主动终止作业；信号注册能力不支持 Windows，版本特有的 C 栈能力也不能默认存在。

PyTorch/NCCL 作业可按当前版本使用 [Flight Recorder](https://docs.pytorch.org/tutorials/unstable/flight_recorder_tutorial.html) 已有采集与分析能力。它提供 collective 记录，需同时核对对应进程组、参与方、环形缓冲覆盖和记录状态；不在此固化易漂移的开关组合。其他通信后端使用现场实际支持的记录，不能套用 NCCL 的环境变量。未知来源的 pickle 不直接反序列化，可要求受信任环境导出相关文本记录。

## 从等待位置关联实际代码

若完整记录显示同组某 rank 没有参与其他 rank 正在等待的 collective，可以针对实际加载代码核对该 rank 的分支、退出和异常处理；这不自动证明网络正常，也不证明该 rank 未执行任何通信。若等待源于数据或资源，则观察对应生产者。只补当前还缺少的事实，不要求所有作业先采全栈或全卡 dump。

运行身份、异步依赖与插桩扰动见 [运行时取证边界](runtime.md)；需要保存已取得的关键产物时使用 [证据快照](evidence.md)。
