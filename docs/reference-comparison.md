# 输出引用模式下的三组实际运行

本报告使用自定义运行器和 chroot 环境。官方 Harbor 执行流程见[原生 Pi 接入检查](harbor-comparison.md)。

2026-10-29，三组分别运行证书生成、日志汇总和 Git 修复任务，每项任务运行一次，共 9 次真实模型执行。任务使用新解包的文件系统，完成后运行原始验证器。

| 组别 | 执行方式 | 审计策略 |
|---|---|---|
| Baseline | Pi 原工具直接执行，使用统一输出呈现层 | 关闭 NoDrop |
| 无控制面 | 两个常驻工具执行进程，NoDrop 采集 | 固定 `raw` |
| 有控制面 | 两个常驻工具执行进程，NoDrop 采集 | Agent 在原调用 JSON 中选择 `audit_policy` |

三组均采用 `reference` 输出模式：4096 字节以内直接返回，大结果保存正文及索引，先返回预览和引用，通过原 `read` 工具按约 2048 字节分页读取。Baseline 的输出引用独立生成，索引中的 `call_ref` 为 `null`；审计组保留实际调用引用。

模型为 `deepseek-v4.1-flash-al`，接口为 `openai-completions`，thinking 为 `medium`，沿用 2048 输出配置。累计 token、轮数和工具数仅统计，任务超时 900 秒；自动重试、自动重跑和缓存预热关闭。

环境为 Linux `6.8.0-137-generic`、Node.js `22.20.0`、Pi `1.4.0`、QEMU TCG、4 vCPU、4 GiB、chroot 和 UID 1000。任务版本与文件校验值见[任务清单](../experiments/terminal-bench.json)，本轮配置见[实验清单](../experiments/reference-comparison.json)。

累计 token 使用 API 返回的 `input + output + cacheRead + cacheWrite`，包含缓存读取。各组独立执行，结果同时列出响应轮数、工具调用与输出量。


## 累计 token

| 任务 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 105,254 | 52,253 | 81,190 |
| `log-summary-date-ranges` | 50,247 | 15,471 | 30,308 |
| `fix-git` | 56,134 | 46,370 | 131,827 |
| 合计 | 211,635 | 114,094 | 243,325 |

有控制面相对 baseline：+31,690 token（+14.97%）。

有控制面相对无控制面：+129,231 token（+113.27%）。

9 次任务全部通过原始验证器，模型会话均正常结束。每个条件每项任务运行一次，整轮差异同时包含模型轨迹、业务返回和调用轮数的变化。

## 请求与输出

| 指标 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| 模型请求 | 39 | 26 | 37 |
| 模型工具请求 | 41 | 34 | 46 |
| 外部保存的大结果 | 1 | 2 | 2 |
| 显式分页请求 | 3 | 0 | 2 |
| 外部保存正文 / 字节 | 5,494 | 18,106 | 20,282 |
| 呈现前工具文本 / 字符 | 32,224 | 34,779 | 50,465 |
| 实际返回模型的工具文本 / 字符 | 28,002 | 19,218 | 32,728 |
| 模型与工具会话 / 秒 | 220.722 | 234.598 | 319.513 |

“呈现前工具文本”以归档的原始结果还原，其余短结果沿用实际返回。正文存储量采用 `output.txt` 文件字节数，保留 Pi 已保存的完整 stdout；工具文本按模型消息中的文本字符计量。审计记录单独统计。

## 首轮请求核对

| 任务 | Baseline / 无控制面输入 | 有控制面输入 | 策略新增输入 | 策略新增 JSON 字节 |
|---|---:|---:|---:|---:|
| `fix-git` | 1,484 | 1,642 | 158 | 665 |
| `log-summary-date-ranges` | 1,884 | 2,042 | 158 | 665 |
| `openssl-selfsigned-cert` | 1,819 | 1,977 | 158 | 665 |

三个任务的 baseline 与固定 raw 首轮完整请求逐字段一致。有控制面组移除策略 schema 和共享 guideline 后也与其一致；三组均包含同一 `read.output_page` schema。后续策略字段和共享说明随调用历史进入请求。

## Git 任务的上下文变化

有控制面组的 Git 任务比固定 raw 多使用 85,457 token，占三项累计增量的 66.13%。两组均将大段输出保存为外部文件，后续业务输出和模型生成的历史仍有差异：

| Git 任务指标 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| 模型请求 | 12 | 10 | 16 |
| 模型工具请求 | 13 | 13 | 22 |
| 实际返回工具文本 / 字符 | 12,411 | 11,411 | 23,366 |
| 模型思考文本 / 字符 | 3,332 | 2,634 | 16,178 |
| 全部请求中 assistant 消息 JSON / 字节 | 49,269 | 42,255 | 223,524 |
| 全部请求中 tool 消息 JSON / 字节 | 102,656 | 79,809 | 234,316 |

后两行按全部请求累计，包含历史消息的重复发送，使用紧凑 UTF-8 JSON 计量。思考文本按已保存的模型消息计量。有控制面组另有 3 次策略漏填反馈；三项任务合计漏填 7 次，每次反馈 66 字节。

输出引用在实际调用中生效：有控制面组日志任务的一次返回由 14,859 缩为 1,273 字符，Git 的一次返回由 5,423 缩为 1,272 字符。Baseline 实际读取了 3 页，有控制面组读取了 2 页，按需读取继续使用原 `read` 工具。

## 策略与审计记录

| 指标 | 无控制面 | 有控制面 |
|---|---:|---:|
| 有效审计调用 | 34 | 39 |
| 原样保留事件 | 86,403 | 116,463 |
| 计数策略覆盖事件 | 0 | 0 |
| 审计文件 / 字节 | 6,768,765 | 9,509,208 |
| 调用元数据 / 字节 | 28,879 | 35,432 |
| 未处理事件计数 | 576 | 584 |

有控制面组实际执行策略：`raw` 39 次，`counts` 0 次。策略校验拒绝 7 次，错误文本合计 462 字节。已核对模型提交参数、调用元数据与已保存事件中的身份和策略。

未处理事件保留计数。9 次运行均关闭自动重试与累计阈值；结束后临时模型配置已删除，审计模块、任务进程和挂载均已清理，虚拟机恢复关闭。

## 结果与复现

- [三组机器可读结果](reference-comparison-results-20261029.json)
- [策略与采集核对](reference-policy-verification-20261029.json)
- [工具输出存储与分页](output-references.md)

每项任务使用新的 rootfs 和结果目录。运行器参数为 `--output-mode reference --inline-bytes 4096`；baseline 使用 `--audit off`，无控制面使用 `--audit on --control-mode fixed-raw`，有控制面使用 `--audit on --control-mode agent`。模型配置目录通过 `--agent-config` 提供，任务清单固定原始任务与验证器版本。

```bash
python3 scripts/compare_live_modes.py \
  --baseline results/reference-comparison/baseline \
  --fixed-raw results/reference-comparison/fixed-raw \
  --agent results/reference-comparison/agent \
  --output docs/reference-comparison-results-20261029.json
python3 scripts/verify_live_agent_policy.py results/reference-comparison/agent \
  --baseline results/reference-comparison/fixed-raw \
  --output docs/reference-policy-verification-20261029.json
```
