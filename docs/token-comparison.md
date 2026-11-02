# 审计开关与 token 用量

2026-10-29，在 Linux 6.8 实验虚拟机中运行 3 个 Terminal-Bench 任务，每个任务分别关闭、开启审计，共 6 轮。每轮采用新任务文件系统和独立模型会话，6 轮均通过原始任务测试。

本实验的关闭组使用纯 Pi 并卸载 NoDrop。保留采集、比较固定全量与按工具配置的结果见[工具回放对照](control-comparison.md)。

## 实测结果

累计 token 来自各次模型响应的 `usage.totalTokens`，包含输入、输出及缓存 token。变化率以关闭组为基准。

| 任务 | 关闭 | 开启 | 差值 | 变化率 |
|---|---:|---:|---:|---:|
| `openssl-selfsigned-cert` | 57826 | 56850 | -976 | -1.7% |
| `log-summary-date-ranges` | 42330 | 73473 | +31143 | +73.6% |
| `fix-git` | 36810 | 73990 | +37180 | +101.0% |
| 合计 | 136966 | 204313 | +67347 | +49.2% |

每个条件运行一次。上述差值是本批独立模型会话的端到端观测值，包含模型解题路径、工具输出长度和调用轮数的变化。

## 请求与上下文核对

运行器在两组中使用相同的只读观察扩展，保存每次发送给 API 的请求体、字节数与 SHA-256。审计配置和调用身份保存在执行链路中。

| 任务 | 首个请求体 | 首轮输入 token：关闭 / 开启 | 全会话工具定义 | 全会话系统提示词 |
|---|---|---:|---|---|
| `openssl-selfsigned-cert` | 完全一致 | 1787 / 1787 | 一致 | 一致 |
| `log-summary-date-ranges` | 完全一致 | 1852 / 1852 | 一致 | 一致 |
| `fix-git` | 完全一致 | 1452 / 1452 | 一致 | 一致 |

首轮输入量按 `totalTokens - output` 计算，合并缓存与非缓存部分。3 个任务测得的首轮输入增量均为 0；审计扩展复用原始工具定义，调用身份和策略通过 IPC、N-API 与 ioctl 提交。

后续请求中的工具输出与执行轮数存在差异：

| 任务 | 模型响应轮数：关闭 / 开启 | 工具请求数：关闭 / 开启 | 工具返回文本字符合计：关闭 / 开启 |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 14 / 13 | 13 / 14 | 3392 / 4297 |
| `log-summary-date-ranges` | 9 / 7 | 9 / 6 | 5180 / 20796 |
| `fix-git` | 8 / 14 | 10 / 19 | 12074 / 12199 |

日志任务的开启组首先用 `bash` 列目录并读取日志，单次工具返回 15993 个文本字符；关闭组先使用 `ls`，单次返回 3115 个文本字符。较长的工具输出随后被带入后续请求。Git 任务两组工具返回文本总量接近，开启组的模型响应从 8 轮增加到 14 轮。字符数用于解释内容长度，token 统计仍采用 API 报告值。

## 控制配置与实际采用

关闭组使用 Pi 原始工具，NoDrop 模块保持卸载。开启组加载审计扩展与 NoDrop，通过[配置文件](../experiments/token-audit-policies.json)选择调用对应的保留策略：

| 工具 | 策略 |
|---|---|
| `bash`、`write`、`edit` | `raw` |
| `read`、`grep`、`find`、`ls` | `counts` |

策略在工具执行前与调用身份一起提交。子进程、线程继承配置，事件头保存调用引用与策略，来源线程的 monitor 按策略生成记录。

证书任务实际执行 13 次 `bash`、1 次 `write`；日志任务执行 6 次 `bash`；Git 任务执行 18 次 `bash`、1 次 `read`。Git 的 `read` 调用产生 175 个计数事件、14 条直方图记录。保存的原始事件与计数记录均核对了调用引用、原始工具调用 ID 与配置策略。

本轮覆盖调用级配置选择、上下文提交及 `raw/counts` 写出。Agent 主运行时线程的分类、OpenShell、Lua 参数脱敏和关注路径策略属于场景设计的其他实现范围。

## 环境与预算

- Terminal-Bench 2.1，任务版本、文件哈希及镜像 digest 沿用[任务清单](../experiments/terminal-bench.json)。
- Linux `6.8.0-137-generic`，QEMU TCG，4 vCPU、4 GiB；官方任务镜像导出的 chroot，UID 1000。
- Pi `1.4.0`，`deepseek-v4.1-flash-al`，`openai-completions`，`medium` thinking level。
- 两组单响应输出上限均为 16384 token；单任务累计上限为 200000 token、40 个模型响应、100 次工具请求、900 秒。
- 开启组使用两个常驻执行进程，NoDrop 每线程 1 MiB 缓冲，PKEY 关闭。
- 执行顺序为证书关闭/开启、日志开启/关闭、Git 关闭/开启，见[本批实验配置](../experiments/token-comparison.json)。
- 原始验证器在 Agent 退出后运行。本批采用 chroot 工作负载驱动，验证结果与模型用量按上述环境报告。

## 复现与结果文件

按照 [Terminal-Bench 实验说明](terminal-bench.md)准备任务镜像、验证器和实验专用模型配置。为两个条件分别解包全新的任务文件系统。运行器支持：

```bash
sudo python3 scripts/run_terminal_bench.py \
  "build/terminal-bench/source/tasks/$TASK" \
  --rootfs "build/tb-rootfs/$TASK-$MODE" \
  --agent-config "$PI_NODROP_AGENT_CONFIG" \
  --verifier-python build/terminal-bench/verifier/python \
  --audit "$MODE" --control-mode configured \
  --policies experiments/token-audit-policies.json \
  --output "results/token-comparison/$TASK-$MODE"
```

`MODE` 为 `off` 或 `on`。Git 任务额外传入 `--workdir /app/personal-site`。实验专用模型配置将单响应上限设为 16384。

原始结果保存在 `results/token-comparison/`，包括 `request-*.json`、`requests.jsonl`、`transcript.json`、`agent-result.json`、工具调用记录、审计文件和原始测试结果。公开汇总见[机器可读结果](token-comparison-results-20261029.json)，可重新生成：

```bash
python3 scripts/compare_token_usage.py results/token-comparison \
  --output docs/token-comparison-results-20261029.json
```

实验结束后，NoDrop 已卸载，任务进程及挂载已清理，临时模型配置已删除，虚拟机恢复关闭。原有模型配置的输出上限仍为 2048。
