# 固定全量与按工具配置对照

2026-10-29，在 Linux 6.8 虚拟机中回放 3 个 Terminal-Bench 任务的已记录工具调用，每个任务运行两种配置，共 6 轮。全部通过原始任务测试，共执行 78 次工具调用。运行过程使用 Pi 内置工具及相同执行器，新增模型请求和 API token 均为 0。

## 对照条件

| 条件 | 调用身份 | NoDrop 采集 | 策略采用 |
|---|---|---|---|
| `fixed-raw` | 保留 | 开启 | 旁路工具策略选择，固定原样保留 |
| `configured` | 保留 | 开启 | 按工具选择 `raw/counts` |

本轮隔离现有调用级策略选择与输出处理。身份提交、两个常驻执行进程、线程及子进程继承、内核事件格式和采集范围在两组中保持一致。`fixed-raw` 每次提交固定策略 ID，`configured` 根据工具配置选择策略 ID。

两组的对应任务使用同一份回放输入，调用分组、工具名、参数及调用 ID 一致。回放保持组内并行、组间顺序，复现原记录中的工具错误并继续执行后续调用。任务验证在执行器退出、NoDrop 卸载后进行。

## 结果

脚本从等待执行器就绪前开始计时，到执行器关闭后结束，包含工具调用与审计收尾。文件系统解包、挂载和任务验证单独计时。

| 任务 | 每组调用数 | 固定全量时间（秒） | 按工具配置时间（秒） | 固定全量审计字节 | 按工具配置审计字节 |
|---|---:|---:|---:|---:|---:|
| `openssl-selfsigned-cert` | 14 | 72.09 | 70.46 | 2236999 | 2204493 |
| `log-summary-date-ranges` | 6 | 46.64 | 51.18 | 5626763 | 5531390 |
| `fix-git` | 19 | 28.42 | 37.76 | 1948118 | 1932859 |

审计字节为 `audit/*.buf` 与 `audit/*.counts.jsonl` 的文件大小之和。调用元数据、工具结果、解码 JSON 和验证器输出分别统计。

每个条件运行一次，时长和日志量均为本批观测值。证书和日志任务只调用配置为 `raw` 的工具，两组处理粒度相同，可用于观察相同处理下的运行波动。各轮实际系统事件数随执行环境变化，详细计数保存在[机器可读结果](control-comparison-results-20261029.json)。

## 策略采用核对

按工具配置使用[策略文件](../experiments/token-audit-policies.json)：`bash/write/edit` 原样保留，`read/grep/find/ls` 计数。

Git 任务的 18 次 `bash` 调用在两组均采用原样保留；1 次 `read` 调用的结果如下：

| 条件 | `read` 关联的原始事件 | 计数事件 | 直方图记录 | 关联审计字节 |
|---|---:|---:|---:|---:|
| 固定全量 | 162 | 0 | 0 | 9926 |
| 按工具配置 | 0 | 159 | 14 | 2313 |

每个保留记录均通过 `call_ref` 核对到原始工具调用 ID 和声明策略。固定全量组的事件策略均为 `raw`；配置组的 `read` 记录策略为 `counts`。两轮 `read` 的实际事件数分别为 162 和 159，上表报告各自的保留粒度及输出大小。

## 环境与评价范围

- Linux `6.8.0-137-generic`，QEMU TCG，4 vCPU、4 GiB。
- Pi `1.4.0` 内置工具，Node.js `22.20.0`，两个常驻执行进程，每个进程一个 libuv I/O 线程。
- NoDrop 每线程 1 MiB 缓冲，PKEY 关闭；采集范围为 UID 1000 的已标记调用。
- 任务来自固定版本 Terminal-Bench 2.1，镜像、源码和验证器沿用[任务清单](../experiments/terminal-bench.json)。每轮从同一任务归档解包全新文件系统，以 chroot 和 UID 1000 运行。
- 回放程序直接执行已记录的工具调用，保持工具调用分组，组间由工具完成状态推进。模型会话等待时间由回放驱动替代。
- 本轮评价调用级策略选择、记录生成和任务结果。完整场景中的 Agent 主运行时线程分类、OpenShell、Lua 脱敏及信息要求 R 的重建属于其他实现与实验范围。
- 0 token 来自回放驱动无需模型推理。真实模型会话的 token 对照见[审计开关实验](token-comparison.md)。

实验结束后，NoDrop 已卸载，任务进程和挂载均已清理，虚拟机恢复关闭。回放环境采用独立工具输入，使用过程中无需模型凭据。

## 复现

按照 [Terminal-Bench 实验说明](terminal-bench.md)准备任务镜像、验证器和编译产物。公开的[回放输入](../experiments/replay/)保留工具调用、分组和预期错误标记，与实测来源会话具有相同的工具调用序列。输入 SHA-256、来源会话 SHA-256 和执行顺序记录在[实验清单](../experiments/control-comparison.json)。

为每个条件分别解包全新的任务文件系统，`MODE` 取 `fixed-raw` 或 `configured`：

```bash
sudo python3 scripts/run_terminal_bench.py \
  "build/terminal-bench/source/tasks/$TASK" \
  --rootfs "build/tb-rootfs/$TASK-$MODE" \
  --replay "experiments/replay/$TASK.json" \
  --verifier-python build/terminal-bench/verifier/python \
  --audit on --control-mode "$MODE" \
  --policies experiments/token-audit-policies.json \
  --output "results/control-comparison/$TASK-$MODE"
```

Git 任务额外传入 `--workdir /app/personal-site`。原始结果保存在 `results/control-comparison/`，包括工具结果、调用元数据、采集文件、原始任务测试结果和运行器摘要。

重新汇总：

```bash
python3 scripts/compare_control_replay.py results/control-comparison \
  --output docs/control-comparison-results-20261029.json
```
