# 策略字段漏填分析

2026-10-30 三组实测中的 7 次拒绝均由调用参数缺少 `audit_policy` 触发。保存的 Pi `message_end` 与 session 中对应参数一致，进入工具参数准备阶段前已经缺失字段。

| 任务 | 发生位置 | 漏填调用数 |
|---|---|---:|
| 证书 | 首轮两个 bash 调用 | 2 |
| 证书 | 首次 write 调用，第 7 次模型响应 | 1 |
| 日志汇总 | 首轮两个 bash 调用 | 2 |
| Git 修复 | 首轮两个 bash 调用 | 2 |

首轮的两个调用由同一份模型响应生成，随后一起得到校验错误。7 次拒绝对应 4 组模型响应。收到错误反馈后，下一轮调用均补充了字段。

## 约束链路

本轮保存的结构化 system 消息包含四个工具的完整声明，`audit_policy` 均位于 `required` 中，共享策略说明也已存在。工具声明继承 Pi 的 `constrainedSampling: {"type":"json_schema","strict":"prefer"}`。

本轮采用 `openai-completions` 兼容接口。Pi AI 1.4.0 的兼容默认值为 `supportsStrictMode: false`，当前模型配置未覆盖该值。`prefer` 在此条件下回退为普通 function calling，`required` 继续出现在参数 schema 中，生成请求不携带 `strict`。执行前的参数准备函数检查策略，缺失时返回短错误，原业务工具不执行。

利用本轮保存的初始消息及相同 SDK 离线重建三个请求，均确认四个工具的必填声明仍在、策略说明仍在，且没有 `strict` 字段。另用两份模拟 SSE 分块响应核验解析：提供策略字段时解析结果保留该字段，未提供时也不会自动补入。诊断未调用外部模型。

## 轨迹支持的判断

漏填调用均正常以 `toolUse` 结束。所在响应的输出 token 分别为 121、111、139 或 1,169，未出现长度截断信号。6 次发生在任务第一轮，另 1 次发生在首次切换 write 时，未呈现为长上下文末尾遗忘。

轨迹表现为：首轮沿用 `bash({command})`，首次 write 沿用 `write({path, content})`，随后根据校验错误补充审计字段。生成后的校验已经生效，生成阶段的必填保证尚未接通。模型内部为何选择忽略软约束，单凭轨迹不能精确判断。

原始 HTTP 流未在该轮留存；上述定位依据 Pi 已保存的模型调用、声明和离线 SDK 重建。它能定位本地校验与采集的先后关系，不单独证明服务端目前支持严格生成。接通硬约束前需要独立验证兼容接口的真实支持，不能仅依据 schema 中的 `required` 推断。

- [诊断记录](field-policy-omission-analysis-20261030.json)
- [当前 API strict 能力实测](strict-api-support.md)
- [本轮三组实测](harbor-field-comparison.md)
