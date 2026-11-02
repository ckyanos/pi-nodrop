# Harness 策略选择的三组对照

本报告使用自定义运行器和 chroot 环境。官方 Harbor 执行流程见[原生 Pi 接入检查](harbor-comparison.md)。

2026-10-29，baseline、固定 raw、Agent 通过工具名选择策略三组分别运行证书生成、日志汇总和 Git 修复任务。每组每项任务执行一次，共 9 次新的真实模型运行。

| 组别 | 业务执行 | 审计方式 |
|---|---|---|
| Baseline | Pi 原工具直接执行 | 关闭 NoDrop |
| 无控制面 | 两个常驻工具执行进程 | NoDrop 固定 raw |
| 有控制面 | 两个常驻工具执行进程 | Agent 选择 `_raw/_counts`，harness 在执行前提交策略 |

三组采用相同模型、任务、输出引用与分页设置。每次使用新文件系统和结果目录，Agent 退出后运行原始任务验证器。模型为 `deepseek-v4.1-flash-al`，medium thinking，沿用 2048 输出配置，任务超时 900 秒。累计 token、轮数和工具数仅统计；自动重试、自动重跑和缓存预热关闭。

环境为 Linux `6.8.0-137-generic`、Node.js `22.20.0`、Pi `1.4.0`、QEMU TCG、4 vCPU、4 GiB、chroot 和 UID 1000。工具结果超过 4096 字节时保存正文与索引，先返回预览及引用，按约 2048 字节分页读取。审计日志保存在独立文件中。

累计 token 为 API 报告的 `input + output + cacheRead + cacheWrite`，包含缓存读取。

## 累计 token

| 任务 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| `openssl-selfsigned-cert` | 47,102 | 82,722 | 52,154 |
| `log-summary-date-ranges` | 26,540 | 45,407 | 51,637 |
| `fix-git` | 130,028 | 67,953 | 61,797 |
| 合计 | 203,670 | 196,082 | 165,588 |

有控制面相对 baseline：-38,082 token（-18.70%）。

有控制面相对无控制面：-30,494 token（-15.55%）。

## 运行记录

| 指标 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| 业务验证通过 | 3 | 3 | 3 |
| 会话正常结束 | 3 | 3 | 3 |
| 模型请求 | 36 | 37 | 26 |
| 模型工具请求 | 38 | 45 | 32 |
| 有效审计调用 | 0 | 45 | 32 |
| 外部保存的大结果 | 2 | 3 | 1 |
| 外部正文 / 字节 | 15,593 | 72,813 | 5,186 |
| 分页调用 | 0 | 3 | 0 |
| 工具结果文本 / 字符 | 28,400 | 27,564 | 23,949 |
| 保存的原始事件 | 0 | 200,145 | 101,246 |
| 计数覆盖事件 | 0 | 0 | 25,580 |
| 审计文件 / 字节 | 0 | 15,682,373 | 8,519,317 |
| 调用元数据 / 字节 | 0 | 41,477 | 27,867 |

有控制面实际执行 raw 17 次、counts 15 次；执行前拒绝 0 次。模型工具名、原始参数、执行元数据和已保存事件中的身份与策略已逐条核对。

## 首轮输入

| 任务 | Baseline / 无控制面 | 有控制面 | 策略新增 token | 新增请求 JSON / 字节 |
|---|---:|---:|---:|---:|
| `fix-git` | 1,484 | 2,866 | 1,382 | 6,607 |
| `log-summary-date-ranges` | 1,884 | 3,266 | 1,382 | 6,607 |
| `openssl-selfsigned-cert` | 1,819 | 3,201 | 1,382 | 6,607 |

baseline 与固定 raw 的首轮完整请求逐字段一致。有控制面提供 14 个工具入口，分别复用原 7 个业务参数 schema；模型选项与用户任务相同。各组独立执行一次，累计量同时包含工具清单、模型轨迹、调用轮数和业务返回变化。

## 复现与数据

- [本轮实验配置](../experiments/harness-comparison.json)
- [任务版本与文件校验值](../experiments/terminal-bench.json)
- [三组结果及逐调用策略核对](harness-comparison-results-20261029.json)
- [工具名策略机制](policy-tool-names.md)

运行器统一使用 `--output-mode reference --inline-bytes 4096`。三组分别使用 `--audit off --control-mode fixed-raw`、`--audit on --control-mode fixed-raw`、`--audit on --control-mode agent-names`。每次为 `--rootfs` 和 `--output` 提供新的目录，模型配置通过 `--agent-config` 提供。

```bash
python3 scripts/compare_harness_modes.py results/harness-comparison-20261029 \
  --output docs/harness-comparison-results-20261029.json
```

结束后审计模块、任务进程、挂载及临时模型配置已清理，虚拟机恢复关闭。未处理事件计数保存在机器可读结果中。
