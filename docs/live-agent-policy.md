# Agent 随工具调用选择策略的实际执行实验

2026-10-29，使用真实模型驱动 Pi 执行 3 个 Terminal-Bench 任务。Agent 在原工具调用 JSON 中填写 `audit_policy`，执行器在运行工具前提交调用身份与策略，NoDrop 根据采集记录中的策略生成审计输出。

三个任务各运行一次，全部通过原始验证器。模型自行选择了 `raw` 和 `counts`，38 次有效调用的原始 JSON、提交策略及已保存审计记录全部对应。

## 运行配置

- Pi `1.4.0`、Node.js `22.20.0`，两个常驻执行进程。
- 模型为 `deepseek-v4.1-flash-al`，接口为 `openai-completions`，thinking 为 `medium`，沿用模型原有的 `max_completion_tokens=2048`。
- Linux `6.8.0-137-generic`，QEMU TCG，4 vCPU、4 GiB；chroot、UID 1000，NoDrop 每线程 1 MiB 缓冲，PKEY 关闭。
- 累计 token、响应轮数和工具调用数仅统计，任务超时为 900 秒。SDK 和提供方自动重试关闭，缓存预热关闭。
- 输入为原始任务指令及带策略字段的 7 个工具 schema。策略说明来自字段描述，每次调用的策略由模型填写。
- 每个任务使用全新解包的文件系统。任务源码、镜像及验证器采用[固定版本清单](../experiments/terminal-bench.json)。本批配置见[实验清单](../experiments/live-agent-policy.json)。

## 任务与策略

| 任务 | 原始测试 | 有效调用 | `raw` | `counts` | 漏填策略被拒绝 | API 请求 |
|---|---|---:|---:|---:|---:|---:|
| `openssl-selfsigned-cert` | 6/6 | 10 | 8 | 2 | 1 | 11 |
| `log-summary-date-ranges` | 2/2 | 10 | 0 | 10 | 2 | 9 |
| `fix-git` | 2/2 | 18 | 18 | 0 | 3 | 15 |
| 合计 | 10/10 | 38 | 26 | 12 | 6 | 35 |

模型共提出 44 次工具请求。6 次请求缺少必填字段，在原工具执行前被 schema 校验拒绝；模型根据错误反馈继续提交完整调用，最终完成任务。自动重试事件数为 0，三个模型会话均以 `stop` 正常结束，模型会话和验证器退出码均为 0。

证书任务的环境探测调用选择 `counts`，生成与验证文件的调用选择 `raw`。日志汇总任务的有效调用全部选择 `counts`；Git 恢复任务的有效调用全部选择 `raw`。这些记录反映本轮模型选择，策略对审计需求的适用性另行评估。

## Token 用量

与[上一轮固定 `raw` 实验](api-managed-fixed-raw.md)采用相同模型、输出配置和任务版本：

| 任务 | 固定 `raw` 累计 token | Agent 选择累计 token |
|---|---:|---:|
| `openssl-selfsigned-cert` | 35001 | 62431 |
| `log-summary-date-ranges` | 125887 | 60044 |
| `fix-git` | 42120 | 108019 |
| 合计 | 203008 | 230494 |

本轮累计增加 27486 token，即 13.54%。两组分别独立运行，每任务每组一次，工具执行序列、响应长度和校验错误后的修正均有差异。这个比例描述两批实测总量；控制面的因果开销需要固定调用或重复试验评估。

相同配置的纯 Pi baseline 已补充运行，三组结果见[完整对照](three-way-comparison.md)。

首轮请求可以直接核对：三项任务的消息内容一致，从新请求移除新增策略字段及对应的必填声明后，完整请求与固定 `raw` 组相同。新增 schema 共增加 2204 字节，当前模型报告的首轮输入均增加 466 token：

| 任务 | 固定 `raw` 首轮输入 | Agent 选择首轮输入 | 增量 |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 1787 | 2253 | 466 |
| `log-summary-date-ranges` | 1852 | 2318 | 466 |
| `fix-git` | 1452 | 1918 | 466 |

输入 token 计入普通输入与缓存输入。新增 schema 随后续请求继续发送，模型填写的策略字段及校验反馈也进入调用历史。策略与业务参数共用一次模型响应。

| 用量字段 | 本轮合计 |
|---|---:|
| 非缓存输入 | 28691 |
| 输出 | 14667 |
| 缓存读取 | 187136 |
| 缓存写入 | 0 |

累计 token 按各响应的 `usage.totalTokens` 求和，包含缓存读取。本轮的一个实际成本来源是字段漏填：6 次拒绝产生额外错误反馈及修正响应，证书任务中还包含较长的文件写入参数。

## 审计输出

| 任务 | 原始事件 | 汇总覆盖事件 | 原始记录字节 | 汇总记录字节 |
|---|---:|---:|---:|---:|
| `openssl-selfsigned-cert` | 14629 | 6326 | 1144725 | 36864 |
| `log-summary-date-ranges` | 0 | 62421 | 0 | 768867 |
| `fix-git` | 22603 | 0 | 1726188 | 0 |
| 合计 | 37232 | 68747 | 2870913 | 805731 |

审计输出共 3676644 字节，调用元数据另占 31484 字节。所有已保存原始事件均对应 `raw` 调用，所有汇总行均对应 `counts` 调用。关联检查逐条使用 `call_ref` 与原始工具调用 ID 核对，执行元数据的 `policy_source` 均为 `agent`。

`counts` 在来源线程的 monitor 中生成，保留事件类型计数及时间范围；内核采集仍保留原有路径。它减少逐事件信息的写出和保留，CPU、内存及吞吐收益需要单独测量。

内核统计的 `drop_unsolved` 合计为 1506，按本批配置仅记录。日志汇总和 Git 任务的全量审计完整性检查为未通过；已保存记录的身份与策略对应检查全部通过。

## 复现与结果文件

准备方式见 [Terminal-Bench 实验说明](terminal-bench.md)。每个任务使用新解包的文件系统及原有模型配置：

```bash
sudo python3 scripts/run_terminal_bench.py \
  "build/terminal-bench/source/tasks/$TASK" \
  --rootfs "build/tb-rootfs/live-agent-policy-$TASK" \
  --agent-config "$PI_NODROP_AGENT_CONFIG" \
  --verifier-python build/terminal-bench/verifier/python \
  --audit on --control-mode agent \
  --output "results/live-agent-policy/$TASK"
```

Git 任务额外传入 `--workdir /app/personal-site`。重新汇总与核对：

```bash
python3 scripts/summarize_terminal_bench.py results/live-agent-policy \
  --output docs/live-agent-policy-results-20261029.json
python3 scripts/verify_live_agent_policy.py results/live-agent-policy \
  --baseline results/api-managed-fixed-raw \
  --output docs/live-agent-policy-verification-20261029.json
```

[机器可读结果](live-agent-policy-results-20261029.json)保存用量、测试、审计统计和运行代码 SHA-256；[策略核对结果](live-agent-policy-verification-20261029.json)保存逐调用策略、拒绝原因及首轮请求对照。原始会话、请求和审计记录保存在 `results/live-agent-policy/`。

实验结束后，NoDrop 模块、任务进程和挂载均已清理，临时模型配置已删除，虚拟机已恢复关闭；原有模型输出配置保持为 2048。
