# pi-nodrop

Pi 工具调用身份直接接入 NoDrop 的研究原型。范围是**调用归属、审计配置选择和审计记录生成**。

```text
Pi toolCallId + 工具名 + 参数
        │ 完整上下文在 calls.jsonl 保存一次
        ▼
专用执行进程（同一时刻只执行一个调用）
        │ 进程内 N-API → ioctl：call_ref + policy_id
        ▼
NoDrop 内核采集
        │ 事件头直接保存 call_ref / policy_id / tgid
        ▼
NoDrop 事件来源线程中的 monitor
        ├─ raw：保留带身份的原始事件
        └─ counts：生成按调用、事件类型统计的记录
```

`call_ref` 是每次调用随机分配的 64 位引用，与 Pi 的原始 `toolCallId` 明确对应。归属通过这个引用连接，时间戳和工具参数不参与归属判断。完整参数不会逐事件复制。扩展事件头增加 16 字节：引用 8 字节、输出策略 4 字节、TGID 4 字节。

## 源码基线

- Pi：`@earendil-works/pi-coding-agent@1.4.0`，依赖锁定在 `package-lock.json`。
- NoDrop：从 **WSL Ubuntu-22.04** 的 `/root/nodrop-latest-20261009/NoDrop` 保存的工作副本；Git 基点 `7ce202412c16b341fc39f88a39dd375b3ed7b511`，包含原有未提交修改。选取依据是实际源文件修改时间，最新为 2026-10-28，早先的 Ubuntu-24.04 同名副本未采用。
- `vendor/nodrop-provenance.json`：复制前每个源文件的 SHA-256、mtime 和 Git 状态。
- `vendor/nodrop-baseline.patch`：复制时工作副本相对 Git 基点的修改。原目录未修改。
- `vendor/pi-nodrop.patch`：本原型相对上述工作副本的 NoDrop 修改，便于单独审查。
- NoDrop 的原有许可保存在 `vendor/nodrop/LICENSE`；本项目用于研究实验。

## 实现边界

扩展覆盖 Pi 的 `bash/read/write/edit/grep/find/ls`，复用 Pi 原有工具定义、执行、输出截断和错误处理。使用两个常驻执行进程处理并发调用；每个进程同一时刻只接收一个调用。工具参数和结果通过本地 IPC 传输，因此进程隔离本身也有成本，尚未进行性能结论。

内核身份按**进程**保存，覆盖该进程的既有线程，包括异步文件操作使用的 libuv 线程。子进程在 `sched_process_fork` 时复制身份，`exec` 后身份继续存在。身份表持有 `struct pid` 引用，避免数值 PID 重用导致串号。调用返回后清除执行进程身份；已经派生的后台子进程保留原调用身份。

原型把每个执行进程的 `UV_THREADPOOL_SIZE` 固定为 1，在调用结束前分别排空该 I/O 线程与主线程的 NoDrop 缓冲。这是明确的实验约束；没有声称支持任意线程池、任意自定义工具或共享的常驻 MCP 服务器。专用执行进程中的运行时活动也可能进入该调用的审计记录。

`counts` 保留事件类型计数和时间范围，**不保留逐事件顺序与参数**；它是另一种明确的信息保留要求，不是原始审计日志的无损压缩。策略在采集时随身份写入每条事件，随后由来源线程中的 NoDrop monitor 选择最终输出。它减少最终保留记录，不减少内核已采集的事件数量。

沿用选定 NoDrop 基线的 UID 1000 采集范围。原型接口建立在合作执行器和隔离实验环境上，不提供抵抗同 UID 恶意代码伪造身份的保证。二进制事件 magic 已改为 `0x50494e44`；解码需使用本仓库工具，与原版事件 ABI 不兼容。

## 实验环境及复现

目标是 WSL Ubuntu-24.04 管理的既有 libvirt 虚拟机 `kmod-noble-68`，Linux `6.8.0-137-generic`。内核模块只在来宾加载。虚拟机使用 QEMU TCG，结果可用于功能验证，不能外推原生机器性能。

在 WSL 宿主运行（脚本记录了现有实验机 SSH 路径，不包含私钥）：

```bash
cd /mnt/d/桌面/pi-nodrop
python3 scripts/prepare_host.py
python3 scripts/build_musl_host.py
python3 scripts/test_host.py
python3 scripts/lab.py sync
python3 scripts/lab.py runtime
python3 scripts/lab.py exec 'python3 scripts/build_guest.py'
python3 scripts/lab.py exec 'sudo -n python3 scripts/run_guest.py'
python3 scripts/lab.py fetch
python3 scripts/verify_results.py results
```

构建需要 guest 中的 CMake、GCC、C++ 编译器、当前内核 headers；依赖 musl 1.2.3、Lua 5.4.6、zlib 1.3.1。下载包 SHA-256 保存在 `vendor/dependencies.json`。`run_guest.py` 拒绝覆盖已有结果，使用前先保留旧实验目录；测试退出时卸载模块。

功能测试运行真实 Pi Agent 工具执行循环和真实工具实现，模型输出使用确定性的本地脚本，不消耗远端 API，也不评价模型任务能力。`tests/protocol.test.mjs` 的 `backend=none` 检查只验证工具执行和 IPC；内核归属由虚拟机集成测试单独验证。

## 在 Pi 中加载

在虚拟机中完成构建并加载本原型的 NoDrop 后，作为 UID 1000 的用户运行：

```bash
PI_NODROP_OUTPUT=/path/to/calls \
PI_NODROP_POLICIES='{"ls":"counts"}' \
  ./node node_modules/@earendil-works/pi-coding-agent/dist/cli.js -e ./src/extension.mjs
```

`PI_NODROP_WORKERS` 默认 2。默认全部采用 `raw`；`PI_NODROP_POLICIES` 根据工具名显式选择 `raw` 或 `counts`。采集输出目录在 NoDrop 构建配置中指定；元数据与采集日志应一起保留。

本地仓库：`D:\桌面\pi-nodrop`。远端：<https://github.com/ckyanos/pi-nodrop>。

实验结果与当前验证状态见 `docs/experiment-report.md`。
