# iBrain 厂商参数复测

2026-10-30 使用 `project-ak-api` 完成 7 个紧凑用例，另有 1 个非法 schema 请求在未收到完整响应时停止，未重试。测试仅通过 iBrain，没有调用 Claude 或厂商官方接口。另一次模型目录 GET 用于鉴权检查。

## 本批结果

| 型号 | 用例 | 观察 |
|---|---|---|
| Doubao-Seed-2.1-pro-260628 | 非法 thinking.type | 返回正常工具调用，未拒绝非法选项 |
| qwen3.8-max | 普通工具调用 | 参数完整 |
| qwen3.8-max | enable_thinking=false，指定函数，流式要求漏填 | 返回工具调用，缺少 audit_policy |
| qwen3.8-max | enable_thinking 传入非法字符串 | 返回正常工具调用，未拒绝非法选项 |
| glm-5.3 | 普通工具调用，thinking=enabled | 参数完整 |
| glm-5.3 | 流式要求漏填 | 缺少 audit_policy |
| glm-5.3 | 非法 thinking.type | 返回正常工具调用，未拒绝非法选项 |

豆包请求携带其文档定义的函数级 strict；Qwen 和 GLM 按工具调用文档构造，没有额外添加未确认支持的 strict。Qwen 指定函数用例采用文档中的 enable_thinking=false 和具名 tool_choice；GLM 保留 auto 及 enabled 思考配置。

完成请求共报告 **2,540 token**。停止请求没有完整 usage，用量保留为未知，不计作零。API 请求均直接解析服务响应，没有 Pi/NoDrop 执行或参数补填。

## 能力边界

本批验证了厂商文档格式在 iBrain 入口上的响应，尚未确认原生约束模式在上游启用。非法选项仍产生工具调用，可能涉及过滤、忽略或容错，仅凭响应无法确定是哪一种。

Gemini 本批没有追加模型请求。先前在已知代理前缀下探测 GenerateContent 原生路径，得到 URL 404 或页面 404；尚未取得可用的 VALIDATED/ANY 入口。DeepSeek 的 iBrain Beta 映射同样未确认，本批未追加该模型请求。这些情况不计为厂商原生能力失败。

因此，当前可复现的是指定 iBrain 请求下的漏填现象。各家原生强约束的横向比较仍需要已确认的原生接口或网关映射。本报告不将上述用例汇总为原生约束失败率。

## 复现

在测试环境提供 project-ak-api，然后执行紧凑用例：

```bash
python scripts/probe_vendor_tool_routes.py \
  --agent-config path/to/pi-agent-config \
  --output-dir results/vendor-route-checks
```

本批停止的 invalid-schema 用例没有再次执行；补测使用 --skip-cases invalid-schema。默认不自动重试，--full 为显式扩展用例。

- [完整请求、响应及 usage](vendor-protocol-route-checks-20261030.json)
- [厂商协议核对](tool-schema-constraint-protocols.md)
- [测试凭证配置](test-credentials.md)
