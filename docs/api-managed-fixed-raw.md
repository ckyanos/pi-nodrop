# 按 API 配置运行的固定全量实验

2026-10-29，使用真实模型驱动 Pi 执行 3 个 Terminal-Bench 任务。NoDrop 采集及调用身份关联保持开启，工具策略选择采用 `fixed-raw`，固定原样保留。

运行器统计累计 token、模型响应数与工具调用数。模型响应沿用选定 Pi 模型的原有配置，任务保留 900 秒运行超时。

## 结果

| 任务 | 原始任务测试 | 实际 API 请求 | 执行调用数 | 累计 token | API 结束原因 |
|---|---|---:|---:|---:|---|
| `openssl-selfsigned-cert` | 6/6 通过 | 9 | 9 | 35001 | `stop` |
| `log-summary-date-ranges` | 2/2 通过 | 7 | 8 | 125887 | `stop` |
| `fix-git` | 2/2 通过 | 10 | 12 | 42120 | `stop` |
| 合计 | 3 个任务通过 | 26 | 29 | 203008 | 全部正常结束 |

三轮模型会话及原始验证器的退出码均为 0，运行器停止原因和错误字段均为空。模型及工具会话时间分别为 64.94、101.25、44.10 秒，包含模型请求、工具执行及审计收尾。

累计 token 按各次响应的 `usage.totalTokens` 求和：

| 用量字段 | 合计 |
|---|---:|
| 非缓存输入 | 32848 |
| 输出 | 9136 |
| 缓存读取 | 161024 |
| 缓存写入 | 0 |

每个任务运行一次。API 请求、会话记录、调用元数据及原始验证器输出保存在 `results/api-managed-fixed-raw/`。公开数据见[机器可读结果](api-managed-fixed-raw-results-20261029.json)。

## 配置与核对

- 模型为 `deepseek-v4.1-flash-al`，接口为 `openai-completions`，沿用原有 `medium` thinking 配置。请求中的 `max_completion_tokens=2048` 来自原模型配置。
- 本地累计 token、响应轮数和工具调用数限制均为空；对应计数仅用于统计。自动重试关闭。
- Pi `1.4.0`、Node.js `22.20.0`；两个常驻执行进程，每进程一个 libuv I/O 线程。
- Linux `6.8.0-137-generic`，QEMU TCG，4 vCPU、4 GiB；chroot 和 UID 1000。NoDrop 每线程 1 MiB 缓冲，PKEY 关闭。
- 任务使用[固定版本清单](../experiments/terminal-bench.json)中的镜像、源码和验证器，每轮解包全新任务文件系统。

实际保留 206823 个原始系统事件，共 17093372 字节；调用元数据共 24662 字节。每条保留事件均核对到对应的原始工具调用 ID，声明策略及记录策略均为 `raw`。

本批清单见[实验配置](../experiments/api-managed-fixed-raw.json)。固定全量与按工具配置的相同调用序列对照见[工具回放实验](control-comparison.md)，采用累计阈值的历史批次见[历史结果](live-fixed-raw.md)。

## 复现

按 [Terminal-Bench 实验说明](terminal-bench.md)准备任务、编译产物和验证器。为 Pi 提供实验专用的原有模型配置，将 `retry.enabled` 设为 `false`、`retry.provider.maxRetries` 设为 0。每个任务使用新解包的文件系统：

```bash
sudo python3 scripts/run_terminal_bench.py \
  "build/terminal-bench/source/tasks/$TASK" \
  --rootfs "build/tb-rootfs/api-managed-fixed-raw-$TASK" \
  --agent-config "$PI_NODROP_AGENT_CONFIG" \
  --verifier-python build/terminal-bench/verifier/python \
  --audit on --control-mode fixed-raw \
  --output "results/api-managed-fixed-raw/$TASK"
```

Git 任务额外传入 `--workdir /app/personal-site`。重新汇总：

```bash
python3 scripts/summarize_terminal_bench.py results/api-managed-fixed-raw \
  --output docs/api-managed-fixed-raw-results-20261029.json
```

实验结束后，NoDrop、任务进程和挂载均已清理，临时模型配置已删除，虚拟机恢复关闭。原有 Pi 模型配置保持不变。
