# pi-nodrop

将 Pi 工具调用上下文直接接入 NoDrop 系统调用采集的研究原型，支持调用归属、审计配置选择和审计记录生成。

```text
Pi toolCallId + 工具名 + 参数
        │ 调用上下文写入 calls.jsonl
        ▼
专用执行进程（每个进程同时执行一个调用）
        │ 进程内 N-API → ioctl：call_ref + policy_id
        ▼
NoDrop 内核采集
        │ 事件头保存 call_ref / policy_id / tgid
        ▼
事件来源线程中的 NoDrop monitor
        ├─ raw：带调用身份的原始事件
        └─ counts：按调用、事件类型汇总的统计记录
```

每次调用分配一个随机 64 位 `call_ref`，在调用元数据中记录其与 Pi 原始 `toolCallId` 的对应关系。解码器通过 `call_ref` 连接上下文与系统事件。每个事件头增加 16 字节：调用引用 8 字节、输出策略 4 字节、TGID 4 字节。

## 工作机制

Pi 扩展复用 `bash`、`read`、`write`、`edit`、`grep`、`find`、`ls` 七个内置工具的定义与执行逻辑。两个常驻执行进程通过 IPC 接收调用；进程内 N-API 将调用引用与审计策略提交给 NoDrop。

内核按进程保存身份，覆盖主线程及 libuv I/O 线程。子进程在 `sched_process_fork` 时继承身份，并在 `exec` 后保留。身份表以持有引用的 `struct pid` 为键。调用结束时，执行器排空 I/O 线程和主线程的审计缓冲，随后清除执行进程身份；已派生的子进程保留创建时的调用身份。

输出策略在采集时写入事件头，由来源线程中的 NoDrop monitor 在写出记录时采用：

| 策略 | 保留内容 | 适用数据需求 |
|---|---|---|
| `raw` | 带调用身份的逐事件记录、参数及顺序 | 逐事件审计与回溯 |
| `counts` | 按调用与事件类型汇总的计数、时间范围 | 事件量统计 |

两种策略使用同一采集链路，区别在于最终保留的信息粒度。

## 环境要求

- 构建主机：Linux 或 WSL，Python 3.12+、Node.js 22.19+、npm、GCC、Make、SSH 客户端。
- 实验虚拟机：x86-64 Linux 6.8，Python 3.12+、CMake、GCC/G++、Make、pkg-config，以及运行内核对应的 headers。
- 虚拟机中 UID 1000 的实验用户，以及用于加载模块、运行测试的 sudo 权限。
- 依赖版本：Pi 1.4.0、musl 1.2.3、Lua 5.4.6、zlib 1.3.1。

当前执行器的每个进程使用一个 libuv I/O 线程，采集范围为 UID 1000。身份接口面向协作执行器，二进制事件格式采用 magic `0x50494e44`，配套使用本仓库解码器。

## 构建与复现

克隆仓库：

```bash
git clone https://github.com/ckyanos/pi-nodrop.git
cd pi-nodrop
```

在构建主机配置虚拟机连接。`PI_NODROP_SSH_TARGET` 可以使用 SSH 配置中的主机别名，认证和主机密钥校验沿用 OpenSSH 配置。`PI_NODROP_GUEST_DIR` 指定虚拟机中的项目绝对目录。

```bash
export PI_NODROP_SSH_TARGET=pi-nodrop-vm
export PI_NODROP_GUEST_DIR="$(ssh "$PI_NODROP_SSH_TARGET" 'printf "%s/pi-nodrop" "$HOME"')"

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

脚本将主机构建文件保存在 `build/`，将实验记录保存在 `results/`。每轮实验使用独立结果目录；重新运行前将上一轮 `results/` 移出虚拟机项目目录。测试脚本在退出时卸载模块。

可选配置：

| 环境变量 | 用途 | 默认值 |
|---|---|---|
| `PI_NODROP_HOST_STAGE` | 主机依赖与构建目录 | `build/host` |
| `PI_NODROP_NODE_INCLUDE` | Node.js C 头文件目录 | Node.js 安装前缀下的 `include/node` |
| `PI_NODROP_VM_NAME` | libvirt 探测与关机命令使用的虚拟机名称 | 由运行者设置 |

## 在 Pi 中使用

在虚拟机项目目录中完成构建并加载 NoDrop 后，以 UID 1000 的用户运行：

```bash
PI_NODROP_OUTPUT=results/pi \
PI_NODROP_POLICIES='{"ls":"counts"}' \
  ./node node_modules/@earendil-works/pi-coding-agent/dist/cli.js -e ./src/extension.mjs
```

`PI_NODROP_WORKERS` 设置执行进程数，默认 2。默认输出策略为 `raw`；`PI_NODROP_POLICIES` 按工具名选择 `raw` 或 `counts`。调用元数据与 NoDrop 采集记录共同构成完整输出。

## 测试结果

Linux `6.8.0-137-generic`、Node.js `22.20.0`、QEMU TCG 环境下的功能测试通过全部 19 项检查，覆盖并发调用、异步文件 I/O、子进程身份继承、错误恢复和统计输出。测试使用真实 Pi Agent 工具执行循环及内置工具，模型流由确定性脚本提供。

详细数据见[实验报告](docs/experiment-report.md)和[机器可读摘要](docs/result-summary-20261028.json)。

## 源码与许可

Pi 依赖锁定在 `package-lock.json`。NoDrop 基线采用提交 `7ce202412c16b341fc39f88a39dd375b3ed7b511` 及配套基线补丁。

- [来源清单](vendor/nodrop-provenance.json)：基线文件 SHA-256、修改时间与 Git 状态。
- [基线补丁](vendor/nodrop-baseline.patch)：相对 NoDrop 基点的修改。
- [原型补丁](vendor/pi-nodrop.patch)：调用身份与输出策略扩展。
- [NoDrop 许可](vendor/nodrop/LICENSE)：上游研究用途许可。
