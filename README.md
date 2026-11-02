# pi-nodrop

将 Pi 工具调用上下文直接接入 NoDrop 系统调用采集的研究原型，支持调用归属、审计配置选择和审计记录生成。

[Documentation index](docs/README.md) · [Current NoDrop validation](docs/nodrop-update-20261102.md)

The current NoDrop baseline builds on Linux 6.8 and passes protocol checks, but
its native integration test fails with a kernel `scheduling while atomic`
warning. Earlier successful experiments use their recorded historical versions.

```text
Pi toolCallId + 工具名 + 业务参数 + audit_policy
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

Pi 扩展默认复用 `read`、`bash`、`edit`、`write` 四个内置工具，向原工具参数增加必填的 `audit_policy`。`PI_NODROP_TOOLS` 可显式选择包含 `grep`、`find`、`ls` 在内的已有工具。Agent 在生成工具调用时，同时提交业务参数和这次调用的审计策略：

```json
{
  "name": "read",
  "arguments": {
    "path": "src/main.py",
    "audit_policy": "raw"
  }
}
```

同一工具的另一次调用可以选择 `counts`。执行器校验策略，在调用元数据中保存原始 JSON，并在交给原工具前移除 `audit_policy`。两个常驻执行进程通过 IPC 接收业务参数；进程内 N-API 在执行前将调用引用与策略提交给 NoDrop。

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
PI_NODROP_CONTROL_MODE=agent \
  ./node node_modules/@earendil-works/pi-coding-agent/dist/cli.js -e ./src/extension.mjs
```

`PI_NODROP_WORKERS` 设置执行进程数，默认 2。Pi 扩展的 `PI_NODROP_CONTROL_MODE` 默认值为 `agent`。调用元数据与 NoDrop 采集记录共同构成完整输出。

大段工具输出默认保存为文件和索引，模型先收到预览和引用，通过原 `read` 工具的 `output_page` 参数按需读取。`PI_NODROP_OUTPUT_MODE=inline` 可沿用原返回方式；配置和检查见[工具输出引用](docs/output-references.md)。

| 模式 | 策略来源 |
|---|---|
| `agent` | Agent 在每次工具调用的 `audit_policy` 字段中选择 `raw/counts` |
| `agent-names` | Agent 选择 `_raw/_counts` 工具入口，由 harness 映射到原工具及策略 |
| `configured` | `PI_NODROP_POLICIES` 按工具名提供静态配置，未配置工具采用 `raw` |
| `fixed-raw` | 所有调用固定采用 `raw` |

四种模式均保留调用身份和 NoDrop 采集。`agent` 模式通过 schema 和执行器校验必填字段及策略取值，在原工具运行前完成提交；新增 schema 与策略字段进入模型请求和调用历史，其 token 用量随实际请求记录。策略选择与业务工具调用在同一次模型响应中提交。

`agent-names` 保留为历史实验模式，每个选定业务工具对应两个策略入口。当前 Harbor 三组对照默认使用 `baseline/fixed-raw/agent`，有控制面条件通过原调用 JSON 中的字段选择策略。历史工具名接口的实现、schema 开销和会话记录见[工具名策略实验](docs/policy-tool-names.md)。

## 测试结果

iBrain 测试默认使用 `project-ak-api`，个人凭证需显式选择；配置说明见[测试凭证](docs/test-credentials.md)。

Linux `6.8.0-137-generic`、Node.js `22.20.0`、QEMU TCG 环境下的功能测试通过全部 19 项检查，覆盖并发调用、异步文件 I/O、子进程身份继承、错误恢复和统计输出。测试使用真实 Pi Agent 工具执行循环及内置工具，模型流由确定性脚本提供。

详细数据见[实验报告](docs/experiment-report.md)和[机器可读摘要](docs/result-summary-20261028.json)。

官方 Harbor 四工具字段接口的三组实测见[字段接口对照结果](docs/harbor-field-comparison.md)。运行方式及历史工具名接口结果见 [Harbor 接入检查](docs/harbor-comparison.md)。

以下记录来自历史自定义运行器。任务清单、运行配置与复现步骤见 [Terminal-Bench 小规模实验](docs/terminal-bench.md)。

3 个任务的审计开关、模型请求核对及 token 用量见[开关对照实验](docs/token-comparison.md)。

保留 NoDrop 采集的固定全量与按工具配置对照见[工具回放实验](docs/control-comparison.md)。

Agent 随工具调用提交策略的协议与内核输出核对见[策略接入检查](docs/agent-policy.md)。

Agent 自主选择策略的 3 个真实模型任务结果、字段用量及审计输出见[策略选择实验](docs/live-agent-policy.md)。

共享策略说明与简短错误反馈的字节计量及原生检查见[上下文优化](docs/agent-policy-optimization.md)。

优化后的 3 项真实模型复测、首轮输入增量及四组用量对照见[优化后实际运行](docs/live-agent-policy-optimized.md)。

相同模型及输出配置下，纯 Pi、固定全量和 Agent 选择策略的累计 token 与审计记录对照见[三组实际运行对照](docs/three-way-comparison.md)。

统一采用输出引用与分页后，重新运行全部 9 次任务的 token、策略和上下文对照见[输出引用模式三组实验](docs/reference-comparison.md)。

工具级策略示例、严格参数接口探测及漏填复测见[策略生成接入](docs/policy-generation.md)。

工具名承载策略后，baseline、固定 raw 与 Agent 选择策略的 9 次全新运行对照见[Harness 三组实验](docs/harness-comparison.md)。

固定全量模式下的 3 个真实模型任务结果见[按 API 配置运行的实际执行实验](docs/api-managed-fixed-raw.md)。采用累计阈值的批次见[历史结果](docs/live-fixed-raw.md)。

当前真实模型运行器仅统计累计 token、响应轮数和工具调用数。模型响应沿用 Pi 中选定模型的配置，任务保留运行超时。

## 源码与许可

Pi 依赖锁定在 `package-lock.json`。NoDrop 基线采用上游 `dev` 提交 `f80c9a82c162aa58cb3344b8078f6211d52cdf58`（`update for stable version`），Pi 调用上下文和输出策略适配见独立补丁。

- [来源清单](vendor/nodrop-provenance.json)：基线文件 SHA-256、修改时间与 Git 状态。
- [基线补丁](vendor/nodrop-baseline.patch)：相对 NoDrop 基点的修改。
- [Upstream update](docs/nodrop-update-20261102.md): baseline version and integration changes.
- [原型补丁](vendor/pi-nodrop.patch)：调用身份与输出策略扩展。
- [NoDrop 许可](vendor/nodrop/LICENSE)：上游研究用途许可。
