# 优化后的策略选择实际运行

2026-10-29，使用共享策略说明、紧凑 schema 和简短校验错误，重新运行 3 个 Terminal-Bench 任务。三项任务全部通过原始验证器，模型会话均以 `stop` 正常结束。

首轮新增输入由初版的 466 降至 158 token；本轮整轮累计为 303816 token，比初版增加 31.81%。模型执行轨迹和策略选择均发生变化。

## 配置

本轮采用 `agent` 模式，模型为 `deepseek-v4.1-flash-al`，接口为 `openai-completions`，thinking 为 `medium`，沿用原模型的 2048 输出配置。累计 token、轮数和工具数仅统计；任务超时 900 秒，自动重试及缓存预热关闭。每个任务运行一次，使用新解包的任务文件系统。

环境为 Linux `6.8.0-137-generic`、QEMU TCG、4 vCPU、4 GiB、chroot 和 UID 1000；Pi `1.4.0`、Node.js `22.20.0`，两个常驻工具执行进程。任务与验证器采用[固定版本清单](../experiments/terminal-bench.json)，本轮配置见[实验清单](../experiments/live-agent-policy-optimized.json)。

## 四组累计用量

本轮重跑优化后的 Agent 组，其他三组采用已有的相同模型及输出配置结果：

| 任务 | Baseline | 固定 `raw` | 初版 Agent | 优化后 Agent |
|---|---:|---:|---:|---:|
| `openssl-selfsigned-cert` | 52339 | 35001 | 62431 | 104914 |
| `log-summary-date-ranges` | 63312 | 125887 | 60044 | 136137 |
| `fix-git` | 59721 | 42120 | 108019 | 62765 |
| 合计 | 175372 | 203008 | 230494 | 303816 |

优化后比初版增加 73322 token，即 31.81%；比固定 `raw` 组增加 49.66%，比 baseline 增加 73.24%。这些是每组每任务一次、独立执行的累计差异。

| 执行统计 | 初版 Agent | 优化后 Agent |
|---|---:|---:|
| API 请求 | 35 | 37 |
| 模型工具请求 | 44 | 39 |
| 有效审计调用 | 38 | 34 |
| 漏填策略被拒绝 | 6 | 5 |
| 漏填占工具请求比例 | 13.64% | 12.82% |
| 校验错误文本字节 | 5633 | 330 |
| 工具返回文本字符 | 37298 | 75689 |
| 模型及工具会话总秒数 | 229.67 | 272.84 |

本轮 5 次拒绝均由策略漏填触发，每次错误为 66 字节。模型根据反馈补齐后继续执行，自动重试事件数为 0。漏填概率与累计用量的稳定变化需要重复试验评价。

累计 token 包含缓存读取，字段分解为：

| 用量字段 | 初版 Agent | 优化后 Agent |
|---|---:|---:|
| 非缓存输入 | 28691 | 42145 |
| 输出 | 14667 | 12583 |
| 缓存读取 | 187136 | 249088 |
| 缓存写入 | 0 | 0 |

## 首轮上下文核对

逐字段核对首轮完整请求，从优化版移除策略 schema 和共享 guideline 后，请求与 baseline、固定 `raw` 组完全一致。模型、业务任务及其他请求配置相同。

| 任务 | Baseline / 固定 `raw` | 初版 Agent | 优化后 Agent |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 1787 | 2253 | 1945 |
| `log-summary-date-ranges` | 1852 | 2318 | 2010 |
| `fix-git` | 1452 | 1918 | 1610 |
| 每任务首轮输入增量 | — | 466 | 158 |

输入包含普通输入与缓存输入。新增完整请求体由 2204 缩至 665 字节，新增首轮输入减少 66.09%。共享 guideline 在提供方请求的 `developer` 消息中出现，37 次请求均核对为一次。

## 业务输出与策略变化

日志汇总任务中，初版工具结果文本合计为 9995 字符，优化版为 52628 字符；最大单次返回由 3027 增至 51249 字符。初版的日志预览带有整体行数截断，本轮模型逐个预览全部日志文件。工具返回进入后续对话，形成持续的上下文输入。

证书任务由 11 增至 17 次 API 请求，Git 任务则由 15 降至 12 次。三项任务的累计用量变化方向不同；本轮证据显示固定上下文表示已缩小，整轮用量仍受业务输出、响应轮数和修正过程影响。

| 有效调用策略 | 初版 `raw / counts` | 优化后 `raw / counts` |
|---|---:|---:|
| `openssl-selfsigned-cert` | 8 / 2 | 14 / 0 |
| `log-summary-date-ranges` | 0 / 10 | 6 / 0 |
| `fix-git` | 18 / 0 | 14 / 0 |
| 合计 | 26 / 12 | 34 / 0 |

本轮模型选择全部原样保留，共保存 151824 个原始事件、11832049 字节审计记录，调用元数据另占 29240 字节。初版的审计记录为 3676644 字节，其中包含计数输出。两轮的策略和事件数量不同，策略适用性及选择稳定性需单独评价。

34 次调用的原始 JSON、提交策略及全部已保存记录的身份和策略逐条对应。Git 任务的 `drop_unsolved` 为 304，按实验约定仅记录；该轮全量审计完整性检查未通过，其他两项通过。

## 结果与复现

- [本轮机器可读结果](live-agent-policy-optimized-results-20261029.json)
- [逐调用策略与首轮请求核对](live-agent-policy-optimized-verification-20261029.json)
- [四组对照及工具输出计量](optimized-comparison-results-20261029.json)
- [字节回放与原生接口检查](agent-policy-optimization.md)

按照 [Terminal-Bench 说明](terminal-bench.md)准备环境，每项任务使用新的文件系统，以 `--audit on --control-mode agent` 运行。原始结果保存在 `results/live-agent-policy-optimized/`。重新汇总和核对：

```bash
python3 scripts/summarize_terminal_bench.py results/live-agent-policy-optimized \
  --output docs/live-agent-policy-optimized-results-20261029.json
python3 scripts/verify_live_agent_policy.py results/live-agent-policy-optimized \
  --baseline results/api-managed-fixed-raw \
  --output docs/live-agent-policy-optimized-verification-20261029.json
python3 scripts/compare_live_modes.py \
  --baseline results/api-managed-baseline \
  --fixed-raw results/api-managed-fixed-raw \
  --previous-agent results/live-agent-policy \
  --agent results/live-agent-policy-optimized \
  --output docs/optimized-comparison-results-20261029.json
```

NoDrop 模块、任务进程与挂载已清理，临时模型配置已删除，虚拟机恢复关闭。原有模型配置保持不变，运行源码 SHA-256 随结果保存。
