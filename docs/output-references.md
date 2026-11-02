# 工具输出引用与分页读取

Pi 扩展默认采用 `reference` 输出模式。文本超过 4096 字节时，适配层保存原始工具结果和完整文本，向模型返回状态、简短预览及索引路径。小结果继续使用原工具结果。

此设置控制 Pi 工具结果进入模型上下文的方式。NoDrop 的采集、`raw/counts` 策略和事件身份传播保持原有路径，审计日志继续独立保存。

## 保存和定位

每份大段输出保存在输出目录的 `outputs/<output_ref>/`。审计模式下，`output_ref` 使用实际调用的 `call_ref`，索引保留两者；关闭审计时，输出层独立生成 `output_ref`，`call_ref` 为 `null`。

| 文件 | 内容 |
|---|---|
| `result.json` | 原始工具结果，包括文本、详情和结构化返回值 |
| `output.txt` | 可分页读取的完整文本 |
| `index.json` | 工具调用 ID、调用引用、状态、文本字节数及分页参数 |

`bash` 已经产生完整输出文件时，适配层以该文件为来源，保存一份持久副本。其他结果保存原工具返回的文本。Pi 的上游截断状态写入索引，原始结果保存在 `result.json`。

索引使用调用 ID 和文件字节位置直接定位。正文保存在一个文件中，分页时按范围读取，默认每页约 2048 字节，并调整 UTF-8 字符边界。长单行、中文及 emoji 均支持分页。

## 通过原 read 工具查询

模型仍使用现有 7 个工具。`read` 新增可选参数 `output_page`，用于读取返回的索引：

```json
{
  "path": "<returned index path>",
  "output_page": 2,
  "audit_policy": "counts"
}
```

页码从 1 开始，返回当前页、总页数、字节范围和正文。`output_page` 与原有的 `offset/limit` 分开使用；普通文件读取继续采用原有参数和实现。每次分页请求也是一次工具调用，由执行器提交新的调用身份及模型选择的审计策略。

需要查找关键词时，可使用原有 `grep` 工具查询同目录的 `output.txt`。

完整结果的错误状态、`bash` 退出码和图片内容保留。程序调用方仍可使用原有 `structuredContent`；模型对话接收的是呈现后的 `content`，完整结构化结果同时写入归档。

## 配置

| 设置 | 用途 | Pi 扩展默认值 |
|---|---|---|
| `PI_NODROP_OUTPUT_MODE` | `reference` 外部保存大结果；`inline` 沿用原返回方式 | `reference` |
| `PI_NODROP_INLINE_BYTES` | 单次结果文本直接展示的字节阈值 | `4096` |
| `PI_NODROP_OUTPUT` | 调用元数据及工具输出目录 | `.pi/nodrop` |

该阈值用于单次输出呈现，累计 token、轮数和工具数继续仅统计。审计策略的 `agent/configured/fixed-raw` 模式与输出呈现模式分别配置。直接使用 `AuditExecutor` 的程序接口默认保留 `inline`，可传入 `outputMode: 'reference'` 启用引用模式。

## 检查与离线计量

Windows 的 10 项测试通过，覆盖原协议、baseline 直接执行及 schema 一致性、长文本归档、UTF-8 分页完整还原、完整 stdout 保存、错误状态与图片保留、索引范围检查，以及 Pi 工具循环中的引用和分页读取。

Linux `6.8.0-137-generic` 中，扩展加载检查和 3 项输出测试通过。实际读取和分页请求分别采用 `raw`、`counts`，输出索引的调用引用与内核事件中的引用对应。详见[原生检查结果](output-reference-results-20261029.json)。

三组真实模型实验统一启用引用模式，共 9 次任务全部通过。Baseline 通过输出扩展直接执行 Pi 工具，两组审计执行通过原 NoDrop 执行器；模型业务 schema 一致。本轮另在 Linux 中以 `none` 后端运行 4 项输出检查，全部通过。详见[三组实际运行](reference-comparison.md)。

固定上一轮的工具结果与 37 个请求，对模型可见正文进行离线替换：

| 指标 | 原记录 | 引用视图 |
|---|---:|---:|
| 工具返回文本字节合计 | 75689 | 21840 |
| 全部请求 JSON 字节合计 | 1134978 | 802016 |
| 日志任务最大输出文本字节 | 51249 | 1302 |

这项计量使用已保存的模型可见正文，替换结果文本，固定其余请求字段；未计入新增参数 schema 和后续分页请求，也未重新调用模型。详情见[回放结果](output-view-replay-20261029.json)，真实模型累计 token 另行测量。

```bash
npm test
sudo python3 scripts/check_output_guest.py --output results/output-reference
node scripts/measure_output_view.mjs results/live-agent-policy-optimized \
  build/output-view-replay docs/output-view-replay-20261029.json
```

原生检查和回放均使用新的输出目录，外部模型 API 请求数为 0。原始检查记录保存于 `results/`，源码 SHA-256 随原生结果保存。
