# iBrain 多模型 strict 探测

2026-10-30 选取 iBrain 的 19 个型号/路由组合，覆盖 GPT、DeepSeek、GLM、Qwen、Gemini 和豆包。每项设置 6 个分析用例，共 114 个。Claude 请求数为 0。

本轮统一使用 OpenAI 风格的 strict 字段，尚未逐项确认厂商原生约束入口及 iBrain 映射。以下统计描述这一兼容请求的响应，不能解释为各家模型原生约束能力的测量。[各家协议核对](tool-schema-constraint-protocols.md) 记录 Gemini 原生模式、推理服务端设置及正文结构化输出的区别。

## 结果

| 结论 | 数量 |
|---|---:|
| 携带 strict 字段的请求返回了违反 schema 的工具参数 | 14 |
| 完成全部有效 strict 调用并拒绝非法 schema | 3 |
| 生成未见违规，但有用例未调用工具 | 1 |
| 接口异常，缺少有效输出 | 1 |

| 型号 | API / 路由 | 观察 |
|---|---|---|
| gpt-5.6-luna | Responses / direct | 未见参数违规；拒绝非法 schema；非法值用例未调用工具 |
| gpt-5.6-sol | Responses / direct | 通过本组用例 |
| gpt-5.6-terra | Responses / direct | 通过本组用例 |
| gpt-6-astra | Responses / direct | 通过本组用例 |
| gpt-6.1-sol | Chat Completions / root | strict 非流式、流式均漏填 |
| gpt-6.1-terra | Chat Completions / root | 返回缺少 choices 的对象或 request_error，无法判断生成约束 |
| Deepseek-v4-pro-al | Responses / direct | strict 流式漏填、非法枚举；非流式请求出现 504 |
| deepseek-v4.1-flash-al | Chat Completions / root | strict 非流式、流式均漏填 |
| self-innovate-DeepSeek-V4.1-Flash-public | Chat Completions / root | 漏填、非法枚举、额外字段 |
| self-innovate-GLM-5.3-public | Chat Completions / root | 漏填、非法枚举、额外字段 |
| self-innovate-GLM-5.3-Flash-public | Chat Completions / root | strict 非流式、流式均漏填 |
| glm-5.3 | Chat Completions / root | strict 非流式、流式均漏填 |
| qwen3.8-max | Chat Completions / root | 漏填、非法枚举 |
| qwen3.8-flash | Chat Completions / root | 漏填、非法枚举 |
| self-innovate-Qwen3.8-Flash-Next-public | Chat Completions / root | strict 非流式、流式均漏填 |
| gemini-3.1-pro-preview | Chat Completions / root | strict 非流式漏填；其他用例存在过滤、流错误或结束标记异常 |
| gemini-3.8-flash | Chat Completions / root | 漏填、非法枚举、额外字段 |
| Doubao-Seed-2.1-pro-260628 | Chat Completions / root | 漏填、非法枚举、额外字段 |
| doubao-seed-2.1-lite-260915 | Chat Completions / root | 漏填、非法枚举 |

三个通过型号的有效 strict 请求均返回了工具调用，必填、枚举、额外字段检查全部通过；非法 schema 通过 SSE error 事件拒绝，HTTP 状态为 200，错误码为 `invalid_function_parameters`。因此仅检查 HTTP 状态不能判定请求成功。Luna 的非法值用例没有返回工具调用，单独记录。

14 个组合的反例均来自有效 schema 下、已完成响应中的工具参数。异常响应、截断响应、非法 schema 的生成结果不计入这一数量。DeepSeek Pro 和 Gemini Pro 虽有异常用例，仍分别保留了已完成调用中的直接反例。

## 方法

所有请求直接发到 API，不进入 Pi 的参数准备、工具校验、NoDrop 上下文提交或业务执行，也没有客户端参数补填。四个原有 GPT 型号沿用配置的 Responses 路由，DeepSeek Pro 同样沿用其配置；其余型号使用 Chat Completions。新发现型号通过模型目录对应的 root 路由测试。型号和路径共同构成一项结果，服务提供的型号标识不用于证明底层模型版本。

每组用例为：非 strict 漏填对照、strict 正常调用、strict 漏填非流式、strict 漏填流式、strict 非法枚举与额外字段流式，以及非法 strict schema。对象全部属性必填、`additionalProperties=false`；`audit_policy` 枚举为 `raw/counts`。探针故意提出与 schema 冲突的参数要求，检查接口约束能力；本轮不测量日常任务漏填概率。

原有配置的单响应 token 参数沿用配置值，新型号使用 2048。推理型号发送 medium；其余省略推理参数。没有累计 token 预算或任务轮数限制。实验期间未修改 Pi 的默认模型、认证配置或业务工具接口。

初轮触发每分钟请求限流，之后采用全局 2.6 秒间隔、最多 3 个型号并发。已完成的模型输出直接复用；限流、路由失败、中断及错误事件解析未完成的用例单独补测。Responses 的嵌套 SSE error 解析已修正，并用离线事件验证。已有违规响应没有被后续采样替换。

最终分析记录报告 **57,883 token**；包含初轮额外已保存尝试的已报告用量为 **58,275 token**。未报告 usage 的错误和中断不估算用量，完整尝试数与费用以服务端记录为准。

## 对原型的含义

这些违规参数在进入 Pi/NoDrop 前就已存在，可以将本轮观察定位到 API 返回环节。该观察尚未区分约束未启用、网关未映射与已启用约束失效。接口能接受 `strict:true` 或拒绝非法 schema，均不足以单独证明生成约束有效。通过用例的三个 GPT Responses 路由提供了后续接入候选。

本轮是多路由能力探测，选取的 19 项不是随机样本；14/19 只描述这一组结果。结果未进一步区分服务网关、协议转换、推理服务和模型本身的责任，也不将单轮通过解释为长期零漏填保证。实际 Pi 接入还需显式启用该路由的 strict 能力，并验证真实工具 schema 的请求与返回。

## 复现

```bash
python scripts/probe_strict_matrix.py \
  --agent-config path/to/pi-agent-config \
  --output-dir results/strict-matrix
```

脚本读取 `ibrain` 配置与凭证，排除 Claude，不在报告中保存密钥、认证头或内部服务地址。`--models` 可指定待测型号；`--resume-from` 复用已完成输出，并保留违规结果。原始响应记录保存于实验结果目录。

- [逐项请求、工具参数、错误及 usage](strict-model-matrix-results-20261030.json)
- [原配置接口探测](strict-api-support.md)
- [官方 DeepSeek Beta 对照](strict-official-api-support.md)
