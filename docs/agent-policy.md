# 随工具调用提交审计策略

Pi 扩展默认使用 `agent` 模式。Agent 在原工具调用 JSON 中同时提交业务参数与必填字段 `audit_policy`，选择本次调用采用的审计处理：

```json
{
  "name": "read",
  "arguments": {
    "path": "src/main.py",
    "audit_policy": "raw"
  }
}
```

`raw` 保留逐事件系统调用参数及顺序；`counts` 保留按调用和事件类型汇总的计数及时间范围。同一工具在不同调用中可以选择不同策略。

默认工具集为 `read/bash/edit/write`，名称与业务 description 沿用 Pi。策略含义与一个调用示例由共享 guideline 提供。Harbor 的默认有控制面条件采用该字段接口，工具名变体作为历史对照保留。

## 执行链路

1. 模型生成工具调用，策略字段与业务参数位于同一份 JSON。
2. Pi schema 和执行器校验策略取值。缺失或无效策略在原工具执行前报错。
3. 执行器保存原始调用 JSON，为调用分配引用，并从业务参数中移除 `audit_policy`。
4. 执行进程在调用原始 Pi 工具前，经 N-API 和 ioctl 提交调用引用及策略 ID。
5. NoDrop 采集时写入身份与策略，线程及子进程沿用调用配置。来源线程的 monitor 按记录中的策略生成原始事件或计数。

`calls.jsonl` 中的 `input.audit_policy` 保存模型提出的策略，`policy_id` 保存提交策略，`policy_source` 保存采用模式。业务工具的参数和结果继续使用 Pi 原有实现。

## 模式

| 模式 | 模型可见参数 | 实际策略来源 |
|---|---|---|
| `agent` | 原业务参数及必填的 `audit_policy` | 每次工具调用中的选择 |
| `configured` | 原业务参数 | `PI_NODROP_POLICIES` 中的工具名配置 |
| `fixed-raw` | 原业务参数 | 固定 `raw` |

Pi 扩展与任务运行器默认采用 `agent`。其他两种模式用于保留静态配置和固定全量实验。

## 2026-10-30 四工具字段接口检查

本地 14 项测试及 Linux `6.8.0-137-generic` 上的 5 项原生测试通过。Pi 扩展加载器注册 `read/bash/edit/write` 四个工具。原生测试包含 4 次字段模式调用与 1 次固定 raw 对照，保存 500 条原始事件和 376 个计数事件；已保存事件的策略与调用归属核对通过。测试使用脚本模型流，外部模型请求数为 0。

| 工具定义测量 | 业务工具数 | 声明字节 | 共享说明字节 |
|---|---:|---:|---:|
| 原生工具 | 4 | 2,717 | 0 |
| 当前策略字段接口 | 4 | 3,005 | 175 |
| 历史工具名变体 | 8 | 5,853 | 193 |

声明字节为工具名称、description 和参数 schema 序列化后的 UTF-8 JSON 长度，测量使用原生输出配置。真实模型的 token 用量另行测量。数据与原生检查见[字段接口检查记录](field-policy-interface-checks-20261030.json)。

官方 Harbor 的新一轮三个任务、三种条件共 9 个模型运行全部通过原始验证器。字段接口的三项首轮输入均比 baseline 多 91 token，仍有 7 次漏填后的修正。累计 token、原生工具输出及策略分布见[字段接口三组实测](harbor-field-comparison.md)。

```bash
node scripts/measure_policy_interface.mjs build/field-interface-measurement.json
```

## 2026-10-29 初版接口及内核检查

Windows 上的 5 项协议测试全部通过。Linux `6.8.0-137-generic` 虚拟机中，Pi 扩展加载检查和 3 项原生后端测试全部通过。测试使用真实 Pi Agent 工具循环及内置工具，模型流由确定性脚本提供，外部模型 API 请求数为 0。

同一 `read` 工具的两次并发调用采用不同字段值，实际输出如下：

| 工具调用 ID | JSON 策略 | 提交策略 ID | 原始事件 | 计数事件 |
|---|---|---:|---:|---:|
| `agent-read-raw` | `raw` | 1 | 146 | 0 |
| `agent-read-counts` | `counts` | 2 | 0 | 190 |

其他检查覆盖策略缺失及非法值拒绝、无效选择后的再次执行、`edit` 原参数格式兼容、审计字段与业务参数分离，以及固定 `raw` 模式覆盖传入策略。原生测试共执行 5 次有效调用，保留 487 个原始事件和 1266 个计数事件；每条记录均通过调用引用核对策略归属。

详细数据见[检查结果](agent-policy-results-20261029.json)。模块、执行进程及输出挂载已清理，虚拟机恢复关闭。

## 模型用量

当前实现将策略解释作为一条共享 guideline 提供，每个工具 schema 保留 `audit_policy` 枚举及必填声明。模型生成的策略进入工具调用历史，策略选择与业务调用共用一次模型响应。缺失或无效策略在参数准备阶段返回简短错误。

当前工具 description 保持原文，共享说明提供一个包含 `audit_policy` 的 JSON 示例。模型逐调用选择策略；Harness 对缺失或非法值执行前校验。接口能力探测与历史真实模型复测见[策略生成接入](policy-generation.md)。

2026-10-29 版将 7 个工具的名称和参数 schema 序列化为 JSON，原定义为 3040 字节，当时的 `agent` 定义为 3557 字节，增加 517 字节；共享说明为 144 字节。上一轮 6 次漏填调用的离线回放中，错误文本由 5633 字节缩至 396 字节。数据及原生检查见[上下文优化](agent-policy-optimization.md)。

初版定义为 5244 字节，增加 2204 字节。初版真实模型的 3 项任务均通过，38 次有效调用中，模型选择 26 次 `raw` 和 12 次 `counts`。与固定 `raw` 组首轮请求逐字段核对，初版模型的首轮输入均增加 466 token，另有 6 次漏填策略后的修正。

完整用量、策略选择及审计输出见[真实模型实验](live-agent-policy.md)。

共享说明接入后的 3 项真实模型复测均通过，首轮输入增量为 158 token，累计用量及业务输出差异见[优化后实际运行](live-agent-policy-optimized.md)。

已有的静态配置与固定原样保留实验采用原工具 schema，其请求内容核对结果对应原实验模式。

## 运行

加载 NoDrop 后，以 UID 1000 用户运行 Pi：

```bash
PI_NODROP_CONTROL_MODE=agent \
PI_NODROP_OUTPUT=results/pi \
  ./node node_modules/@earendil-works/pi-coding-agent/dist/cli.js -e ./src/extension.mjs
```

任务运行器使用 `--control-mode agent`。累计 token、响应数和工具调用数仍仅统计。

协议测试：

```bash
npm test
```

在已构建的 Linux 6.8 虚拟机中进行原生检查，每次使用新输出目录：

```bash
sudo python3 scripts/check_agent_policy_guest.py --output results/agent-policy
```
