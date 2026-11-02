# 工具参数约束的接口差异

核对日期：2026-10-30。

多模型统一发送 `tools.function.strict=true` 的探针，检验的是该请求在指定兼容路由上的结果。原生协议、模型版本、推理服务配置及网关映射均影响约束是否启用。此前 14/19 的统计保留为兼容接口观察，不作为各厂商原生能力的测量。

## 厂商接口

| 服务 | 官方文档中的方式 | 与原探针的关系 |
|---|---|---|
| Gemini | GenerateContent 的 `toolConfig.functionCallingConfig.mode=VALIDATED` 允许文本或调用并要求 schema 合规；`ANY` 要求调用。Interactions 使用 `generation_config.tool_choice` 的 `validated/any` 模式。 | 原探针未使用这些原生开关，也未确认 iBrain 将 strict 映射到它们。 |
| DeepSeek | Beta 基址搭配每个函数的 `strict:true`，并要求服务端校验 schema。 | 官方 Beta 实测已采用文档方式；iBrain 普通兼容路由是否映射到 Beta 仍未确认。 |
| 豆包方舟 | Function Calling 文档明确提供函数级 `strict:true`，要求所有属性必填，可选值用 nullable 表示。 | 字段形式与原探针一致，适用型号和 iBrain 透传仍需确认。 |
| Qwen / 百炼 | 工具调用文档描述 tools 和 tool_choice；另有 `response_format.type=json_schema` 结构化回答能力。 | 当前核对材料不足以确认所测型号支持函数参数 strict；正文 schema 输出不能作为 tool_calls 参数约束已启用的证据。 |
| GLM / 智谱 | 工具调用文档使用 tools、parameters、required 和 auto；结构化输出指南采用 `response_format.type=json_object`，字段要求写入提示词。 | 这些指南未建立函数级 strict 的保证；不能从指南缺少开关推断所有部署都没有约束能力。 |

来源：[Gemini GenerateContent](https://ai.google.dev/gemini-api/docs/generate-content/function-calling#function-calling-modes)、[Gemini Interactions](https://ai.google.dev/gemini-api/docs/function-calling#function-calling-modes)、[DeepSeek](https://api-docs.deepseek.com/guides/tool_calls/)、[方舟](https://docs.volcengine.com/docs/ark/function-calling?lang=zh)、[百炼工具调用](https://help.aliyun.com/zh/model-studio/qwen-function-calling)、[百炼参数参考](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[智谱工具调用](https://docs.bigmodel.cn/cn/guide/capabilities/function-calling)、[智谱结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)。

## 开源推理服务

vLLM 把工具调用外层格式与参数 schema 约束分开，`--tool-strict-level parameter` 可在服务端提高约束级别；行为还受 parser、版本及全局开关影响。required/named 的具体约束同样依赖 parser，不能统一理解为只要强制调用就保证参数合规。[vLLM 文档](https://docs.vllm.ai/en/latest/features/tool_calling/)

SGLang 提供 `structural_tag`，可对触发后的函数内容绑定 schema。该能力需要推理服务及请求格式配合，不是模型名称本身的属性。[SGLang 文档](https://docs.sglang.io/docs/advanced_features/structured_outputs)

## 后续测量口径

先确认型号、官方协议和服务端支持范围，再确认中间路由的参数映射；按各家声明的方式构造请求。未暴露约束入口的路由记为能力不可用或尚未核实，不计为原生约束失败。强制调用模式与允许直接回答的模式分别测试，避免改变 Agent 是否使用工具的决策。

输出检查继续区分工具调用、正文 JSON、拒绝、截断和错误。约束启用后，再检查 audit_policy 的必填和枚举，以及真实工具的多轮行为。上一轮直接响应足以说明对应请求的字段未受约束，但不能据此确定是未启用、网关未映射，还是已启用约束发生失效。
