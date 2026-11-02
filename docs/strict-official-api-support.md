# 官方 DeepSeek API 的 strict 探测

2026-10-30 使用官方 API Key，向 `https://api.deepseek.com/beta/chat/completions` 发送一轮 6 个请求。模型为 `deepseek-flash`，`reasoning_effort=medium`，`max_tokens=2048`。用例沿用代理接口探测，直接解析响应及 SSE 参数片段，没有参数补填、自动重试或业务工具执行。

## 结果

| 用例 | strict | 流式 | HTTP | 结果 | 总 token |
|---|---|---|---:|---|---:|
| 明确要求漏填的对照 | false | 否 | 200 | 缺少 audit_policy | 608 |
| 正常调用 | true | 否 | 200 | 参数符合 schema | 444 |
| 明确要求漏填 | true | 否 | 200 | 缺少 audit_policy | 465 |
| 明确要求漏填 | true | 是 | 200 | 返回 audit_policy=raw，参数符合 schema | 793 |
| 非法枚举与额外字段 | true | 是 | 200 | 未返回工具调用，finish_reason=stop | 679 |
| 含未定义必填项的无效 schema | true | 是 | 400 | 拒绝未定义的 required 字段 | — |

6 个请求共报告 **2,989 token**。非法 schema 返回 `Required property 'undefined_required_field' not found in object`，确认该端点执行了 schema 合法性校验。有效 strict schema 的非流式响应仍返回 `{"value":"probe"}`，构成本轮必填字段约束的直接反例。流式漏填用例返回了合法参数；非法枚举用例没有工具调用，该结果不作为参数约束成功的证据。

这轮结果表明：官方 Beta 路由执行了 schema 校验，但所测配置仍出现 strict 生成漏填。单轮用例不估计漏填概率，也未确定非流式与流式结果差异的原因。现有 Pi 配置与执行前策略校验保持原样。

## 复现

[官方工具调用文档](https://api-docs.deepseek.com/guides/tool_calls/) 要求使用 Beta 基址、函数设置 `strict:true`，对象全部属性必填并设置 `additionalProperties:false`。本轮请求采用该格式。

在运行环境中设置官方 `DEEPSEEK_API_KEY`，然后执行：

```bash
python scripts/probe_strict_support.py --official \
  --output results/strict-official.json
```

- [请求、参数与 usage 记录](strict-official-probe-20261030.json)
- [代理接口探测](strict-api-support.md)
