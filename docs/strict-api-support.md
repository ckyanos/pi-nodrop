# 当前 API 的 strict 工具参数探测

2026-10-30 对当前配置的 `deepseek-v4.1-flash-al` 接口直接发送 6 个请求，检查工具 JSON Schema 的实际执行情况。探测不经过 Pi 的工具参数修正，不执行任何业务工具，模型响应配置沿用当前值。所有请求关闭并行工具调用，流式与非流式均包含验证用例。

## 结果

| 用例 | strict | 流式 | HTTP | 工具参数结果 |
|---|---|---|---:|---|
| 明确要求漏填的对照 | false | 否 | 200 | 缺少 audit_policy |
| 正常调用 | true | 否 | 200 | 参数符合 schema |
| 明确要求漏填 | true | 否 | 200 | 仍缺少 audit_policy |
| 明确要求漏填 | true | 是 | 200 | 仍缺少 audit_policy |
| 非法枚举与额外字段 | true | 是 | 200 | 返回 audit_policy=drop 和 legacy=yes |
| 含未定义必填项的无效 strict schema | true | 是 | 200 | 仍生成调用，缺少该必填项 |

本次 6 个请求共报告 3,084 token。正常调用的合规结果可以由模型遵循提示产生；另外 4 个 strict 请求返回了违反 schema 的工具参数，直接否定当前路由具备强制约束的保证。

当前接口接受 `function.strict: true`，但没有在这些用例中强制执行必填、枚举和额外属性限制。该结果针对当前配置的 API 路由，不能外推为模型本身或其他服务端点不支持严格生成。项目保留原有执行前校验，尚未启用依赖该能力的严格生成配置。

## 协议边界

[DeepSeek 官方工具调用文档](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/) 将 strict 定义为 Beta 功能，要求使用官方 Beta 基址、所有函数启用 strict，并由服务端校验 schema。探测使用的字段位置、全属性必填及 `additionalProperties: false` 与该格式一致。

当前使用配置中的代理路由；是否暴露或透传官方 Beta 能力，需要该服务的接口说明或服务端证据确认。探测未切换服务地址、未将现有凭证发送到其他服务，也未改动 Pi 的正常工具接口。

## 复现

```bash
python scripts/probe_strict_support.py \
  --agent-config path/to/pi-agent-config \
  --output results/strict-support.json
```

输出保留用例请求、生成的工具参数、schema 违规项及 usage，不保存 API 地址、认证头或密钥。

- [完整探测记录](strict-support-probe-20261030.json)
- [官方 Beta API 对照探测](strict-official-api-support.md)
- [iBrain 19 个型号/路由对照](strict-model-matrix.md)
- [本轮漏填定位](field-policy-omissions.md)
