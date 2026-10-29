# 原型验证：2026-10-28

第一版已实现并在既有 WSL/libvirt 6.8 虚拟机通过端到端功能验证。验证的是**明确调用身份进入 NoDrop 事件头，再按调用配置生成审计记录**。没有进行性能优劣排名。

## 环境和来源

- Linux `6.8.0-137-generic`，Node `v22.20.0`，Pi `1.4.0`，应用 UID 1000。
- 来宾为既有 `kmod-noble-68`，使用 QEMU TCG；另一台正在运行的 5.15 来宾未改动。
- NoDrop 取自 Ubuntu-22.04 中最近修改的工作副本，Git 基点 `7ce202412c16b341fc39f88a39dd375b3ed7b511` 加原有未提交改动，详见 `vendor/nodrop-provenance.json`。
- 原型的内核模块与 monitor 在来宾中编译；PKEY 关闭、缓冲 1 MiB。宿主没有加载模块。
- Pi 运行真实 Agent 工具执行循环与真实内置工具，模型流为固定脚本，无真实远端模型请求。

## 验证结果

8 次 Pi 调用覆盖两次并发 write、read/edit、bash 子进程、采用 counts 的 ls、一次预期的 read 错误和错误后的 write。额外直接接口场景检查绑定、解绑、非法策略拒绝，以及父进程切换身份后子进程仍保留创建时身份。

| 检查 | 结果 |
|---|---|
| 并发 write A/B 的系统事件归属 | 正确，两个执行进程，原始 Pi 调用 ID 均保留 |
| read/edit 的异步文件 I/O 归属 | 正确，事件来自实际 I/O 线程 |
| bash 派生子进程的目标文件操作 | 正确继承 shell 调用身份 |
| 工具报错后再次调用 | 后续文件事件归新调用 |
| 显式解绑后的文件操作 | 未进入调用审计记录 |
| 父进程从 A 切到 B 后，释放阻塞子进程 | 子进程文件归 A，父进程文件归 B |
| counts 输出 | 90 个采集事件生成 14 行统计，无该调用的 raw 事件 |
| 记录与内核计数核对 | `2757 raw + 90 histogram = 2847 n_evts` |
| NoDrop 丢失统计 | `drop_evts=0, drop_unsolved=0, drop_overflow=0` |
| 内核异常和卸载 | 新增 dmesg 无 Oops/BUG/panic；`rmmod` 成功 |

完整校验共 19 项通过。raw 文件合计 177502 字节，counts 文件合计 2319 字节。两者是不同调用、不同保留要求，**不能用这两个大小相除声称压缩比或性能收益**。

原始证据在本地 `results/`：`summary.json`、`statistics.txt`、`pi/calls.jsonl`、`pi-agent-events.json`、`pi-transcript.json`、`audit/*.buf`、`audit/*.counts.jsonl`、`events.jsonl`、`dmesg-new.txt`。原始证据不默认纳入 Git；仓库保留复现程序与一份机器可读结果摘要。

## 已实现的机制

1. Pi 执行器保存原始 `toolCallId`、名称、参数、输出策略一次，分配 64 位引用。
2. 常驻专用进程复用 Pi 内置工具，通过进程内 N-API 调用 NoDrop ioctl，提交引用和策略。
3. 内核在采集事件时把引用、策略和 TGID 写入事件头；fork 时复制身份，exec 不丢失身份；绑定以持有引用的 `struct pid` 为键。
4. NoDrop 来源线程中的 monitor 选择写 raw 或生成 counts。输出选择发生在记录写出前；counts 仍基于已经采集的事件。
5. 解码器按捕获的 `call_ref` 连接调用上下文。测试中的文件路径只用于核对预期，生产归属逻辑不使用路径、时间窗口或内容匹配。

## 目前的限制

- 这是一次小规模功能验证，不能据此断言一般负载无丢失、长时间可靠或开销最低。
- 专用常驻进程和 IPC 带来额外成本；每个进程的 libuv I/O 池固定为一个线程。尚未测量进程隔离、身份传递与 NoDrop 本身各自的成本。
- 只覆盖列出的 Pi 内置工具和 NoDrop 当前支持的事件。共享 MCP 服务器、任意自定义后台异步活动和远端工具尚未接入。
- counts 保留直方图及时间范围，丢弃逐事件参数和顺序，无法替代需要完整证据的 raw 审计要求。
- 身份接口依赖合作执行器，未提供对抗恶意身份伪造的保护；不做用户意图一致性分析或业务结果判定。

工具层协议测试另外在 `backend=none` 模式通过，证明 IPC/工具执行功能；它不算内核采集证据。

另用 Pi 自身的 `discoverAndLoadExtensions` 加载 `src/extension.mjs`，确认七个工具均注册，`session_shutdown` 能结束执行进程。此项检查验证扩展加载与收尾，未使用真实远端模型会话。

收尾检查确认模块已卸载、没有遗留工具执行进程，并已请求正常关闭原先处于关机状态的 6.8 来宾。NoDrop 原工作副本全部 77 个文件 SHA-256 未变化，`vendor/pi-nodrop.patch` 在原工作副本通过 `git apply --check`。
