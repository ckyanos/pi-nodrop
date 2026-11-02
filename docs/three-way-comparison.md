# Baseline、固定全量与 Agent 策略选择对照

本报告使用自定义运行器和 chroot 环境。官方 Harbor 执行流程见[原生 Pi 接入检查](harbor-comparison.md)。

2026-10-29，比较 3 个 Terminal-Bench 任务在三种模式下的实际模型运行结果。每个任务每组独立运行一次，共 9 轮，全部通过原始任务测试，模型会话均正常结束。

本表的 Agent 组采用初版策略说明与校验反馈。后续实现的字节计量及原生检查见[上下文优化](agent-policy-optimization.md)。

## 三组定义

| 组别 | 工具执行与审计 | 模型可见的策略参数 |
|---|---|---|
| Baseline | Pi 原工具直接执行，NoDrop 关闭 | 原工具 schema |
| 无控制面：固定 `raw` | 保留 NoDrop 采集和调用身份绑定，策略固定为原样保留 | 原工具 schema |
| 有控制面：Agent 选择 | 保留同一采集与绑定链路，每次调用提交模型选择的策略 | 原工具 schema 及必填的 `audit_policy` |

这里的“无控制面”指关闭逐调用策略选择。固定 `raw` 组仍使用执行器提交调用身份和固定策略，事件继续与原始工具调用关联。

三组均使用 `deepseek-v4.1-flash-al`、`openai-completions`、`medium` thinking，沿用原模型的 2048 输出配置；累计 token、轮数及工具数仅统计，任务超时 900 秒，自动重试与缓存预热关闭。任务、镜像和验证器版本见[固定清单](../experiments/terminal-bench.json)。

环境为 Linux `6.8.0-137-generic`、QEMU TCG、4 vCPU、4 GiB、chroot 和 UID 1000；Pi `1.4.0`、Node.js `22.20.0`。本次补充运行的 baseline 配置见[实验清单](../experiments/api-managed-baseline.json)。

## 累计 Token

| 任务 | Baseline | 无控制面：固定 `raw` | 有控制面：Agent 选择 |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 52339 | 35001 | 62431 |
| `log-summary-date-ranges` | 63312 | 125887 | 60044 |
| `fix-git` | 59721 | 42120 | 108019 |
| 合计 | 175372 | 203008 | 230494 |
| 相对 baseline 的累计差异 | — | +15.76% | +31.43% |

Agent 选择组相对固定 `raw` 组增加 27486 token，即 13.54%。累计 token 按各响应的 `usage.totalTokens` 求和，包含缓存读取：

| 用量字段 | Baseline | 固定 `raw` | Agent 选择 |
|---|---:|---:|---:|
| 非缓存输入 | 24678 | 32848 | 28691 |
| 输出 | 9638 | 9136 | 14667 |
| 缓存读取 | 141056 | 161024 | 187136 |
| 缓存写入 | 0 | 0 | 0 |

每组的执行轨迹独立，工具命令、返回内容和响应轮数存在差异。这些百分比描述本轮累计差异；采集和控制面的因果开销需要固定轨迹或重复试验另行计量。三项任务的变化方向也不同：日志汇总在 Agent 组用量最低，另外两项在该组用量最高。

## 直接进入上下文的增量

逐字段核对三项任务的首轮完整请求：baseline 与固定 `raw` 组均完全相同；从 Agent 组移除新增策略字段及对应必填声明后，请求与 baseline 完全相同。

| 任务 | Baseline 首轮输入 | 固定 `raw` 首轮输入 | Agent 选择首轮输入 |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 1787 | 1787 | 2253 |
| `log-summary-date-ranges` | 1852 | 1852 | 2318 |
| `fix-git` | 1452 | 1452 | 1918 |

新增策略 schema 共增加 2204 字节，当前模型的首轮输入均增加 466 token。NoDrop 事件和调用元数据保存在审计输出中，运行器向模型提供原工具结果。Agent 选择模式的 schema、生成的策略字段和校验反馈进入模型上下文。

| 执行统计 | Baseline | 固定 `raw` | Agent 选择 |
|---|---:|---:|---:|
| API 请求 | 31 | 26 | 35 |
| 模型工具请求 | 34 | 29 | 44 |
| 已绑定的审计调用 | 0 | 29 | 38 |
| 漏填策略被拒绝 | 0 | 0 | 6 |
| 模型及工具会话总秒数 | 187.26 | 210.28 | 229.67 |

会话时间包含模型等待、工具执行和扩展收尾；任务文件系统准备及验证器耗时保存在原始记录中。

Agent 组的 6 次漏填均在原工具执行前被拒绝，模型读取反馈后提交完整调用，增加了对话和修正响应。38 次有效调用选择了 26 次 `raw`、12 次 `counts`，原始 JSON、提交策略和已保存审计记录逐条对应。

## 审计记录

| 指标 | Baseline | 固定 `raw` | Agent 选择 |
|---|---:|---:|---:|
| 原始事件 | 0 | 206823 | 37232 |
| 汇总覆盖事件 | 0 | 0 | 68747 |
| 原始记录字节 | 0 | 17093372 | 2870913 |
| 汇总记录字节 | 0 | 0 | 805731 |
| 审计记录总字节 | 0 | 17093372 | 3676644 |
| 调用元数据字节 | 0 | 24662 | 31484 |

本轮两组审计记录分别为 17.09 MB 和 3.68 MB，使用十进制单位，调用元数据单列。执行路径及事件数量不同，因此该差异也包含负载变化。

`counts` 保留事件类型计数和时间范围，舍弃逐事件参数及顺序；当前策略在来源线程的 monitor 中控制处理和写出，内核采集路径保持原有方式。本轮测量任务结果、token、会话耗时及记录体积；CPU、RSS、吞吐和策略适用性需要单独评价。

固定 `raw` 与 Agent 组的 `drop_unsolved` 分别为 696 和 1506，保留于机器可读结果。已保存记录的身份与策略对应检查通过，完整审计检查按各轮记录分别报告。

## 结果与复现

- [三组机器可读对照](three-way-comparison-results-20261029.json)
- [同配置 baseline 结果](api-managed-baseline-results-20261029.json)
- [固定 raw 实验](api-managed-fixed-raw.md)
- [Agent 选择实验及策略核对](live-agent-policy.md)

按照 [Terminal-Bench 实验说明](terminal-bench.md)准备环境，为每轮任务解包新的文件系统。三组运行器参数分别为 `--audit off`、`--audit on --control-mode fixed-raw` 和 `--audit on --control-mode agent`。baseline 原始结果位于 `results/api-managed-baseline/`；既有两组结果分别位于 `results/api-managed-fixed-raw/` 和 `results/live-agent-policy/`。

```bash
python3 scripts/summarize_terminal_bench.py results/api-managed-baseline \
  --output docs/api-managed-baseline-results-20261029.json
python3 scripts/compare_live_modes.py \
  --baseline results/api-managed-baseline \
  --fixed-raw results/api-managed-fixed-raw \
  --agent results/live-agent-policy \
  --output docs/three-way-comparison-results-20261029.json
```

对照脚本核对任务指令哈希、模型、接口、输出配置、本地限制及首轮完整请求，并从原始会话和审计文件重新计量。每个任务每组运行一次，结果适用于本次小规模对照；旧的 16384 输出配置批次单独保存在[历史开关实验](token-comparison.md)。

临时模型配置、任务进程和挂载均已清理，虚拟机恢复关闭，原有模型配置保持不变。
