# 策略接入的上下文优化

Agent 仍在原工具调用 JSON 中提交 `audit_policy`。执行器在运行原工具前校验并提交策略，NoDrop 继续在采集时携带调用引用与策略 ID。

## 共享说明与简短错误

策略含义由一条共享 guideline 提供。7 个工具 schema 各自保留 `raw/counts` 枚举及必填声明，字段排列在业务参数之前。Pi 的 `before_agent_start` 钩子将说明加入已有 guidelines，并去除重复加入。

参数准备钩子检查缺失或无效策略，返回固定的 66 字节错误文本。业务参数仍经过原有工具准备及 schema 校验，`edit` 的旧参数格式兼容保留。策略缺失时，原工具在执行前返回错误，由模型补齐策略后提交。

## 字节计量

| 指标 | 初版 | 当前实现 |
|---|---:|---:|
| 原工具名称及参数 schema | 3040 | 3040 |
| Agent 工具名称及参数 schema | 5244 | 3557 |
| 工具 schema 增量 | 2204 | 517 |
| 共享说明 | 0 | 144 |
| 6 次策略校验错误文本合计 | 5633 | 396 |

表格使用 UTF-8 字节。schema 计量对象为包含工具名称及参数 schema 的 JSON 数组，共享说明单独计量，未计入 prompt 排版及传输包装。

错误文本测量复用[初版真实模型实验](live-agent-policy.md)保存的 6 次漏填调用，通过当前 Pi 参数准备和校验路径离线回放。业务调用执行数和模型请求数均为 0。其中证书任务的一次 `write`，原错误文本为 4683 字节，当前为 66 字节。

[字节测量结果](agent-policy-optimization-context-20261029.json)包含逐案例数据。复现：

```bash
node scripts/measure_policy_context.mjs results/live-agent-policy \
  docs/agent-policy-optimization-context-20261029.json
```

## 协议与原生检查

Windows 的 6 项测试全部通过，覆盖原工具执行、策略校验、长业务参数不回显、`edit` 参数兼容及并发策略传递。Linux `6.8.0-137-generic` 虚拟机中的 Pi 扩展加载与共享说明去重检查，以及 4 项协议测试全部通过。

原生检查执行 5 次有效调用，保存 505 个原始事件和 1329 个计数事件。相同 `read` 工具的两次调用分别保存 152 个原始事件和 188 个计数事件，归属与策略逐条对应。

结果见[原生检查摘要](agent-policy-optimized-results-20261029.json)。检查使用确定性模型流，外部 API 请求数为 0。模块、执行进程和挂载已清理，虚拟机恢复关闭。

## 测量范围

上述检查验证上下文表示的字节变化、校验行为及原生采集链路。后续真实模型复测的 3 项任务全部通过，首轮输入增量为 158 token，整轮累计为 303816 token，比初版增加 31.81%；5 次漏填的反馈合计为 330 字节。详细的业务输出和策略变化见[优化后实际运行](live-agent-policy-optimized.md)。

[三组实际运行对照](three-way-comparison.md)中的 Agent 数据对应初版实现，各轮代码 SHA-256 随结果保存。
