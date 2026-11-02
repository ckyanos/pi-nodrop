# Terminal-Bench 小规模实验

本实验使用真实模型驱动 Pi 执行 Terminal-Bench 任务，记录工具调用、NoDrop 系统事件和任务验证结果。

## 2026-10-29 结果

初始组使用每响应 2048 token 的配置，运行结果如下。执行调用数来自执行器的开始记录，事件数为实际保留的原始记录。

| 任务 | 原始测试 | 执行调用数 | 保留事件数 | 未处理事件数 |
|---|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 通过 | 21 | 60781 | 0 |
| `log-summary-date-ranges` | 通过 | 7 | 55707 | 290 |
| `polyglot-c-py` | 未通过 | 0 | 0 | 0 |
| `fix-git` | 通过 | 12 | 15981 | 0 |
| `sqlite-db-truncate` | 未通过 | 4 | 4926 | 0 |
| `cancel-async-tasks` | 未通过 | 6 | 30680 | 3186 |

初始组共执行 50 次调用，保留 168075 个系统事件，所有保留事件均关联到声明的调用引用。内核计数与保留记录及未处理事件的关系为 `171551 = 168075 + 3476`。

每响应 16384 token 的复测组结果如下：

| 任务 | 原始测试 | 执行调用数 | 保留事件数 | 未处理事件数 |
|---|---|---:|---:|---:|
| `polyglot-c-py` | 通过 | 27 | 286422 | 26866 |
| `sqlite-db-truncate` | 通过 | 13 | 460437 | 24999 |
| `cancel-async-tasks` | 未通过，触及累计 token 预算 | 20 | 48845 | 2776 |

证书任务另有一轮统一输出挂载配置的复核：测试通过，10 次执行调用、25037 个保留事件、0 个未处理事件。

共记录 6 个不同任务、10 轮运行，5 个任务至少有一轮通过原始测试。120 次执行调用产生的保留记录共 988816 个，每条记录均关联到声明的调用引用；内核未处理计数合计 58117，满足 `1046933 = 988816 + 58117`。各轮 `drop_evts` 和 `drop_overflow` 均为 0。

原始记录共 76184072 字节，调用元数据共 142079 字节。这两个数分别统计 `audit/*.buf` 和 `pi/calls.jsonl`；模型会话记录与解码 JSON 单独保存。各轮时长包含模型请求、工具执行和验证步骤。

完整数据见[机器可读结果](terminal-bench-results-20261029.json)。可由原始结果重新汇总：

```bash
python3 scripts/summarize_terminal_bench.py results/terminal-bench \
  --legacy-output-tokens 2048 --output build/terminal-bench-results.json
```

## 任务集

任务来自 [Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1)，源码固定为 `7131e4375048a0e408a8fb404b5f499d726b695b`。文件 SHA-256 与镜像 digest 见[实验清单](../experiments/terminal-bench.json)。

| 任务 | 工作负载 |
|---|---|
| `openssl-selfsigned-cert` | 生成证书、设置文件权限、编写验证程序 |
| `log-summary-date-ranges` | 扫描日志、日期筛选、生成 CSV |
| `polyglot-c-py` | 编写同时支持 C 与 Python 的程序、编译与执行 |
| `fix-git` | 查找游离提交、恢复文件、合并分支 |
| `sqlite-db-truncate` | 分析数据库二进制内容、恢复记录、生成 JSON |
| `cancel-async-tasks` | 编写异步任务调度与取消清理逻辑 |

## 运行配置

- 虚拟机内核：Linux `6.8.0-137-generic`，QEMU TCG，4 vCPU、4 GiB 内存。
- Pi：`1.4.0`；模型：`deepseek-v4.1-flash-al`，OpenAI-compatible 接口，`medium` thinking level。
- 执行器：两个常驻进程，每个进程一个 libuv I/O 线程。
- 任务环境：官方镜像导出的独立根文件系统，使用 `chroot` 和 UID 1000；任务文件归该用户所有。
- 审计配置：每线程 1 MiB 缓冲，PKEY 关闭，所有调用采用 `raw`。
- 单任务预算：900 秒、40 个模型响应、100 次工具调用、累计 200000 个报告 token；运行器在事件回调中检查预算，在响应结束后检查累计 token。
- 单响应输出预算：初始组为配置中的 2048 token，复测组为 16384 token；各轮保留实际预算与模型结束原因。
- 验证器：Python 3.13、pytest `8.4.1`、pytest-json-ctrf `0.3.5`，执行原始 `tests/test_outputs.py`；异步任务额外使用原始 `tests/test.py`。

这是采用 UID 1000 与 chroot 的工作负载实验。任务文件、模型配置、运行预算和验证驱动均在上述配置下执行，结果按任务分别报告。

## 数据链路

Pi 加载 `src/extension.mjs`，由模型实际选择并调用工具。执行器分配调用引用，通过进程内 N-API 提交至 NoDrop。系统事件在采集时获得调用引用，解码器据此关联原始工具调用。

NoDrop monitor 写出时使用虚拟机根文件系统。运行器将该输出目录绑定到本轮 `audit/`，并将 Pi 调用元数据写入同轮 `pi/`。任务验证文件在 Agent 退出、采集模块卸载后挂入任务环境。

## 准备与运行

先按照 [README](../README.md#构建与复现)准备 Pi 与 NoDrop。构建主机安装 Git、Docker 和 Python 3.12+ 后，运行：

```bash
python3 scripts/prepare_terminal_bench.py
```

脚本在 `build/terminal-bench/` 中保存固定版本源码、任务镜像导出的 `*.rootfs.tar` 和验证器 Python。`--direct` 选项使用 Skopeo 直接下载镜像，适用于构建主机采用独立镜像下载通道的配置。

将选定任务源码、根文件系统归档和 `verifier/python/` 复制到实验虚拟机。为 Pi 设置实验专用配置目录，在 `PI_NODROP_AGENT_CONFIG` 中指定其位置；目录包含 `settings.json`、`models.json` 和 `auth.json`，由 UID 1000 用户读写。

在虚拟机项目目录中，以日志任务为例：

```bash
TASK=log-summary-date-ranges
mkdir -p "build/tb-rootfs/$TASK"
sudo tar -xf "build/terminal-bench/$TASK.rootfs.tar" -C "build/tb-rootfs/$TASK"

sudo python3 scripts/run_terminal_bench.py \
  "build/terminal-bench/source/tasks/$TASK" \
  --rootfs "build/tb-rootfs/$TASK" \
  --agent-config "$PI_NODROP_AGENT_CONFIG" \
  --control-mode configured \
  --verifier-python build/terminal-bench/verifier/python \
  --output "results/terminal-bench/$TASK"
```

每轮使用新导出的任务文件系统和新输出目录。`fix-git` 使用 `--workdir /app/personal-site`，其余任务使用默认工作目录 `/app`。

## 结果文件

每轮结果包含：

- `agent-result.json`、`transcript.json`：模型会话结果、token 用量和工具消息。
- `pi/calls.jsonl`：工具调用 ID、调用引用、参数与开始/结束记录。
- `audit/*.buf`、`events.jsonl`：采集原始记录与解码事件。
- `statistics.txt`：内核采集、未处理与溢出计数。
- `verifier.log`、`ctrf.json`、`reward.txt`：任务测试结果。
- `summary.json`、`cleanup.json`：调用关联、事件计数核对、模块清理结果。

任务通过情况由原始验证测试确定。审计完整性单独核对事件计数及 `drop_unsolved`；已保留事件的归属通过捕获的 `call_ref` 校验。

`drop_unsolved` 统计释放审计对象时仍留在缓冲区中的事件，计数位置见 [`nod_proc_release`](../vendor/nodrop/kmodule/procinfo.c#L249)。模型工具请求数和实际执行数分列统计；Pi 因输出截断而跳过的工具请求计入模型请求数。

模型结束原因 `length` 表示单响应输出预算已耗尽。异步取消任务的原始测试含 0.5 秒启动等待及 5/10 秒超时，验证日志保留其具体断言结果与运行时间。
