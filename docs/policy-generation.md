# 策略生成接入

Agent 在原工具调用中同时提交业务参数与 `audit_policy`。每个工具的 description 前置完整调用示例，共享 guideline 说明 `raw/counts` 的保留方式及逐调用选择要求。

例如 `write` 的工具说明前置：

```text
Include audit_policy on every call. Example: {"audit_policy":"raw","path":"file.txt","content":"text"}
```

7 个工具均使用各自可通过参数校验的示例。`configured`、`fixed-raw` 模式沿用原工具说明。参数准备阶段继续检查必填策略，执行器保存模型实际提交的字段，再将策略与调用身份传入 NoDrop。

## 接口能力探测

2026-10-29，使用实验所选模型的同一接口进行两项探测：

| 请求 | HTTP 状态 | 模型返回参数 |
|---|---:|---|
| `strict: true`，schema 要求 `audit_policy`，提示要求省略该字段 | 200 | `{"value":"probe"}` |
| `strict: true`，schema 额外要求一个未定义字段且禁止额外属性 | 200 | `{"value":"probe"}` |

该接口在本次探测中未执行严格参数约束。[DeepSeek 官方严格模式](https://api-docs.deepseek.com/guides/tool_calls/)规定服务端校验 schema，并通过专用入口启用；实验接口的实际行为通过探测单独记录。

本实现使用工具说明和本地校验协作处理参数，属于模型提示约束；生成阶段的硬约束需要接口提供相应能力。

## 真实模型复测

本轮只重跑 Agent 选择策略组的三个完整任务，每项运行一次。基准组和固定 raw 组沿用[上一轮](reference-comparison.md)记录，未在本轮重新执行。

| 任务 | 上轮策略漏填 | 本轮策略漏填 | 本轮响应截断 | 本轮 token | 原始验证器 |
|---|---:|---:|---:|---:|---|
| `openssl-selfsigned-cert` | 3 | 0 | 1 | 92,708 | 通过 |
| `log-summary-date-ranges` | 1 | 0 | 0 | 54,355 | 通过 |
| `fix-git` | 3 | 1 | 0 | 89,663 | 通过 |
| 合计 | 7 | 1 | 1 | 236,726 | 3/3 通过 |

普通漏填按完整响应中缺少策略、且收到策略校验反馈计数。本轮剩余一次发生在 Git 任务后段的 `bash` 调用。响应截断单独计数：证书任务的一次 `write` 以 `length` 结束，Pi 在执行前阻止该不完整调用。两类反馈由验证脚本分别标记为 `missing_policy` 和 `truncated_response`。

本轮共有 50 个模型工具请求，其中 49 个来自完整响应，48 次有效调用执行并保存审计归属；策略均由模型提交为 `raw`。普通漏填的观察比例由 7/46 降至 1/49，工具级示例在本次执行中减少了漏填，提示约束仍允许模型遗漏字段。

首轮请求新增输入由 158 增至 390 token，新增完整 JSON 由 665 增至 1406 字节。三项任务移除策略 schema、共享 guideline 和工具级示例后，首轮请求均与原固定 raw 请求逐字段一致。累计 token 包含缓存读取；上一轮 Agent 组为 243,325，本轮为 236,726。两轮均为独立执行一次，包含业务轨迹变化。

模型沿用 `deepseek-v4.1-flash-al`、`openai-completions`、medium thinking 和原有 2048 输出配置；累计 token、工具数和轮数仅统计。输出采用 4096 字节引用阈值，自动重试、自动重跑和缓存预热关闭。环境为 Linux `6.8.0-137-generic`、Node.js `22.20.0`、Pi `1.4.0`、QEMU TCG、4 vCPU、4 GiB。

## 验证与复现

Windows 的 11 项测试通过，覆盖 7 份示例的参数有效性、原工具参数兼容、固定 raw 说明保持原样、错误反馈、调用身份和输出引用。三个独立的首次工具生成请求分别使用 bash、read、write，均返回模型主动填写的策略；该小测仅生成参数，完整任务另行实际执行。

原生复测的 48 次有效调用保存 159,579 条原始事件，已核对模型参数、执行元数据和已保存事件的策略归属。未处理事件计数为 238，保留在结果中。结束后临时模型配置、任务进程、审计模块及挂载已清理，虚拟机恢复关闭。

- [运行、接口探测与首次调用小测](policy-generation-results-20261029.json)
- [逐调用策略与拒绝原因核对](policy-generation-verification-20261029.json)

```bash
npm test
python3 scripts/probe_strict_tools.py --agent-config <private-agent-config> \
  --output results/strict-tools-probe.json
python3 scripts/verify_live_agent_policy.py results/policy-examples/agent \
  --baseline results/reference-comparison/fixed-raw \
  --output docs/policy-generation-verification-20261029.json
```

接口探测使用两个新的 HTTP 请求，不执行业务工具。严格模式探测和首次工具小测不作为完整任务通过次数。
