# 功能验证报告：2026-10-28

本实验验证 Pi 工具调用身份进入 NoDrop 事件头，以及按调用配置生成原始审计记录或事件统计的端到端流程。

## 实验配置

| 项目 | 配置 |
|---|---|
| Linux 内核 | `6.8.0-137-generic` |
| 虚拟化 | QEMU TCG，由 WSL/libvirt 管理 |
| Node.js / Pi | `22.20.0` / `1.4.0` |
| 应用 UID | 1000 |
| NoDrop 缓冲 | 每线程 1 MiB |
| PKEY | 关闭 |
| 工具执行 | Pi Agent 执行循环与内置工具 |
| 模型流 | 确定性脚本 |

NoDrop 内核模块与 monitor 均在虚拟机中构建和运行。基线与文件校验值见[来源清单](../vendor/nodrop-provenance.json)。

## 测试场景

8 次 Pi 调用覆盖并发 write、read/edit、bash 子进程、采用 `counts` 的 ls、read 错误及后续 write。直接接口测试覆盖身份绑定、解绑、非法策略校验，以及父进程切换身份后的子进程归属。

| 检查 | 结果 |
|---|---|
| 并发 write A/B | 两个执行进程分别关联原始 Pi 调用 ID |
| read/edit 异步文件 I/O | I/O 线程的事件关联到对应调用 |
| bash 派生子进程 | 目标文件操作继承 shell 调用身份 |
| 工具报错后的再次调用 | 后续文件事件关联到新调用 |
| 显式解绑后的文件操作 | 调用审计记录中对应事件数为 0 |
| 父进程从 A 切到 B 后释放阻塞子进程 | 子进程文件事件归 A，父进程文件事件归 B |
| `counts` 输出 | 90 个采集事件生成 14 行统计 |
| 事件计数核对 | `2757 raw + 90 histogram = 2847 n_evts` |
| NoDrop 丢失计数 | `drop_evts=0, drop_unsolved=0, drop_overflow=0` |
| 模块清理 | 卸载成功，新增内核日志中 Oops/BUG/panic 数量为 0 |

全部 19 项校验通过。各输出策略的数据如下，分别来自采用该策略的工具调用：

| 输出策略 | 采集事件数 | 保留记录数 | 文件大小 |
|---|---:|---:|---:|
| `raw` | 2757 | 2757 | 177502 字节 |
| `counts` | 90 | 14 | 2319 字节 |

`raw` 保留逐事件数据；`counts` 保留事件类型直方图与时间范围。二者对应不同调用与信息保留粒度。

## 验证方式

1. 执行器记录原始 `toolCallId`、工具名、参数和策略，并分配 64 位调用引用。
2. 进程内 N-API 将调用引用与策略提交给 NoDrop ioctl。
3. 内核事件头记录调用引用、策略和 TGID；子进程继承创建时的身份。
4. 来源线程中的 monitor 根据策略生成 `raw` 或 `counts` 输出。
5. 解码器通过 `call_ref` 连接调用元数据与系统事件，测试程序通过预设文件操作核对归属和计数。

工具协议测试在 `backend=none` 模式下验证 IPC、并发执行和错误恢复。Pi 的 `discoverAndLoadExtensions` 测试确认七个工具均注册，`session_shutdown` 正常结束执行进程。内核集成测试验证事件身份、继承和输出策略。

## 数据与复现

[机器可读结果摘要](result-summary-20261028.json)包含全部检查结果与统计值。[复现步骤](../README.md#构建与复现)生成以下实验文件：

- `results/pi/calls.jsonl`：工具调用上下文与身份映射。
- `results/audit/*.buf`：原始事件。
- `results/audit/*.counts.jsonl`：统计记录。
- `results/events.jsonl`：解码后的事件。
- `results/summary.json`、`results/statistics.txt`：校验结果与内核计数。
- `results/pi-agent-events.json`、`results/pi-transcript.json`：Pi 执行记录。
- `results/dmesg-new.txt`、`results/cleanup.json`：内核运行与模块清理记录。

本报告记录 QEMU TCG 环境下、七个内置工具与单线程 libuv I/O 池配置的功能测试结果。执行器按进程隔离工具调用，审计接口采用协作执行器模型。
