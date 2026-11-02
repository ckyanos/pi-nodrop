# 工具名承载审计策略

`agent-names` 模式向模型提供原 7 个工具各自的 `_raw/_counts` 入口，共 14 个。harness 通过完整工具名确定业务工具与审计策略，在执行前将策略和调用身份提交给 NoDrop。

```text
read_raw({"path":"a.txt"})     → read，逐事件保留
read_counts({"path":"a.txt"})  → read，事件类型计数
```

业务参数沿用原工具 schema，参数中不使用 `audit_policy`。执行器保存原始参数、`model_tool_name`、原业务 `tool_name`、`call_ref` 和 `policy_id`。仅注册的 14 个入口可执行，未选择后缀的原工具名会作为未知工具名拒绝。参数额外携带 `audit_policy` 时返回冲突反馈。

输出引用继续使用原存储和分页路径。模型收到的读取提示使用 `read_raw/read_counts`，分页调用同样由模型通过工具名选择策略。默认模式仍为 JSON 字段方式的 `agent`。

## 2026-10-29 实测

三个任务各执行一次。三个业务验证器均通过；日志和 Git 会话正常结束，证书会话在业务产物已生成后发生 SIGSEGV，未写出最终会话统计。

| 任务 | 已记录工具调用 | raw / counts | 策略或工具名拒绝 | 已记录 token | 会话状态 |
|---|---:|---:|---:|---:|---|
| `openssl-selfsigned-cert` | 16 | 2 / 14 | 0 | 82,773 | SIGSEGV，部分记录 |
| `log-summary-date-ranges` | 7 | 0 / 7 | 0 | 34,822 | 正常结束 |
| `fix-git` | 19 | 4 / 15 | 0 | 107,623 | 正常结束 |

42 次已记录模型调用均使用有效入口，未发生遗漏策略、未知工具名、冲突策略字段或参数校验拒绝。对应的 42 次执行均保留调用起止元数据，模型工具名后缀、执行策略与已保存事件中的策略逐条一致。实际选择为 6 次 raw、36 次 counts。

证书会话保留原始失败记录，没有重跑。其 13 个已完成响应的 token 从 `agent-events.jsonl` 的 `turn_end` 记录计量，最后一条事件为下一轮 `turn_start`，未产生下一份请求记录。业务验证通过与会话异常分别记录；该部分数据不作为完整会话累计量。

## 上下文开销

首轮请求采用相同模型选项与业务任务，14 个入口各自复用对应业务参数 schema。模型可见说明与工具清单随模式变化。

| 指标 | 固定 raw | JSON 字段加示例 | 工具名后缀 |
|---|---:|---:|---:|
| 工具入口数 | 7 | 7 | 14 |
| 首轮额外输入 token | 0 | 390 | 1,382 |
| 首轮额外完整 JSON / 字节 | 0 | 1,406 | 6,607 |

工具名模式的工具定义 JSON 为 10,942 字节，固定 raw 为 5,104 字节。三项任务中，每项首轮均比固定 raw 增加 1,382 token，比字段加示例方式增加 992 token。累计 token 包含缓存读取。

本轮只运行工具名模式，固定 raw 和字段模式引用既有记录，未在本轮重跑。由于一个会话异常结束，各组独立执行一次，本次分别报告调用正确性、首轮开销和完整会话数据。

## 采集与稳定性记录

实际负载保存 972 条原始事件，以及覆盖 88,462 条事件的计数输出，审计文件合计 1,121,366 字节。采集归属使用原有 `call_ref` 链路，NoDrop 执行机制沿用原实现。未处理事件计数保留在机器可读结果中。

证书任务的 Pi 主进程退出码为 `-11`，16 次工具调用均已有结束记录。内核日志未报告 BUG、Oops 或 panic；Apport 因可执行文件修改时间晚于进程启动时间跳过转储，未获得可用 core。崩溃原因尚未定位。

Linux `6.8.0-137-generic` 上的确定性原生检查通过扩展加载与 3 项工具名测试：3 次调用中，`write_raw/read_raw` 保存 308 条原始事件，`read_counts` 覆盖 162 条计数事件。该检查外部模型请求数为 0。Windows 的 14 项测试通过，包含 SDK 仅启用 14 个入口、原参数和 edit 准备兼容、未知入口拒绝、身份映射及输出分页。

真实模型沿用 `deepseek-v4.1-flash-al`、medium thinking、原有 2048 输出配置和 900 秒任务超时，累计 token、轮数和工具数仅统计，自动重试、自动重跑及缓存预热关闭。输出引用阈值为 4096 字节。环境为 QEMU TCG、4 vCPU、4 GiB、chroot、UID 1000、Node.js 22.20.0、Pi 1.4.0。结束后模块、任务进程、挂载和临时模型配置已清理，虚拟机恢复关闭。

## 使用与复现

完成构建并加载 NoDrop 后运行：

```bash
PI_NODROP_CONTROL_MODE=agent-names PI_NODROP_OUTPUT=results/pi \
  ./node node_modules/@earendil-works/pi-coding-agent/dist/cli.js -e ./src/extension.mjs
```

真实任务运行器使用 `--audit on --control-mode agent-names --output-mode reference`，每项任务采用新的 rootfs 与结果目录。

```bash
npm test
sudo python3 scripts/check_output_guest.py --tool-names --output results/policy-names/native
python3 scripts/verify_policy_names.py results/policy-names/agent-names \
  --baseline results/reference-comparison/fixed-raw \
  --output docs/policy-tool-names-verification-20261029.json
```

- [运行与原生检查结果](policy-tool-names-results-20261029.json)
- [模型调用、策略与采集核对](policy-tool-names-verification-20261029.json)
- [上一轮 JSON 字段与工具级示例](policy-generation.md)
