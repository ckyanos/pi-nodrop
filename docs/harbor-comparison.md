# Harbor 原生 Pi 三组接入检查

三个 Terminal-Bench 2.1 任务分别使用 baseline、固定 raw 和 Agent 选择策略运行，主表包含每项每种条件的一个有效轮次，共 9 个。任务容器、Agent 调用、验证器、轨迹和结果由官方 Harbor 管理。

下表记录使用工具名策略变体的历史运行。当前默认三组为 `baseline/fixed-raw/agent`，有控制面通过原工具 JSON 的 `audit_policy` 字段选择策略，保持四个业务工具；字段接口见[策略接入](agent-policy.md)。新接口的模型用量与历史结果分别记录。

四工具字段接口的新一轮完整对照见[字段接口三组实测](harbor-field-comparison.md)。

## 运行结果（2026-10-30）

主表按每个任务、每种条件的首个有效轮次汇总，共 9 个轮次。9/9 通过原始验证器，9/9 原生 Pi 会话正常结束；Harbor 与 Pi session 的 token 统计全部一致。

表中 token 包含 Pi usage 的 `input`、`output`、`cacheRead` 和 `cacheWrite`。

| 任务 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| 证书 | 39,615 | 40,075 | 59,395 |
| 日志汇总 | 63,701 | 30,070 | 44,377 |
| Git 修复 | 36,673 | 59,249 | 79,625 |
| **合计** | **139,989** | **129,394** | **183,397** |

本次无控制面总 token 比 baseline 低 7.57%；有控制面比 baseline 高 31.01%，比无控制面高 41.74%。每格一次运行，这些差异同时包含模型执行轨迹的变化。

### 上下文与调用

| 指标 | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| 模型响应数 | 28 | 28 | 33 |
| 模型工具调用数 | 31 | 32 | 51 |
| 业务工具返回字符数 | 30,788 | 27,007 | 30,400 |

| 首轮输入 token | Baseline | 无控制面 | 有控制面 |
|---|---:|---:|---:|
| 证书 | 1,212 | 1,212 | 1,962 |
| 日志汇总 | 1,270 | 1,270 | 2,020 |
| Git 修复 | 925 | 925 | 1,675 |

无控制面三个任务的首轮输入与 baseline 相同。有控制面每项首轮增加 750 token，来自策略入口及说明。审计文件独立保存，业务工具返回沿用原生 Pi；没有将事件正文追加到模型上下文。

### 策略与审计文件

| 条件 | raw 事件 | counts 所计事件 | 审计文件字节 | 调用元数据字节 |
|---|---:|---:|---:|---:|
| Baseline | 0 | 0 | 0 | 0 |
| 无控制面 | 71,148 | 0 | 5,802,985 | 26,992 |
| 有控制面 | 92,779 | 44,142 | 8,405,162 | 37,832 |

审计文件字节为 `.buf` 与 `.counts.jsonl` 的总大小，调用元数据另计。已保存事件的调用标识、策略均与调用元数据一致。不同轮次执行的工具和命令数量不同，文件量按实际执行结果列出。

| 有控制面任务 | raw 调用 | counts 调用 |
|---|---:|---:|
| 证书 | 10 | 12 |
| 日志汇总 | 10 | 0 |
| Git 修复 | 1 | 18 |

日志汇总轮次的调用全部选择 raw；配置选择能力已接通，实际保留量取决于 Agent 的策略选择和执行路径。

### 补充轮次与运行记录

挂载诊断期间额外执行了一次无控制面证书任务，107,125 token、18 次响应，通过原始验证器；首个有效轮次为 40,075 token、10 次响应。两次首轮输入均为 1,212 token，补充轮次单独保存，不并入主表。

调试中修正了配置目录可写锁、审计输出目录绑定和 bind mount 的检测与清理。审计挂载使用 private 传播，结束后通过 `mountpoint` 及挂载表确认清理。安装预检和安装阶段中止的轮次未发生模型请求。

四份已安装 Harbor 核心 Python 源码与固定上游提交的内容一致，差异仅为 CRLF/LF 换行；保留两种形式的 SHA-256，并核对 Python AST 相同。结果收集后已清理临时模型配置、工作进程、任务容器、模块和挂载，并关闭实验虚拟机。

[结构化结果与核对记录](harbor-comparison-results-20261030.json)

## 历史运行的执行方式

| 条件 | Agent 入口 | 工具与输出 |
|---|---|---|
| Baseline | Harbor 内置 `Pi` | Pi 默认四个工具，原生输出 |
| 无控制面 | `NoDropPi`，固定 raw | 同一四个业务工具，原生输出 |
| 有控制面 | `NoDropPi`，工具名选择策略 | 四个工具各有 raw/counts 入口，原生输出 |

四个业务工具为 `read`、`bash`、`edit`、`write`。`NoDropPi` 继承官方 `Pi.run`，安装完成后部署审计扩展，并追加扩展加载参数。模型循环和官方轨迹转换沿用上游实现。审计日志写入每次运行独立的宿主机目录；业务工具返回沿用 Pi 的文本与截断规则。

任务使用原始镜像、WORKDIR、用户、HOME、任务指令和 `tests/test.sh`。验证器由 Harbor 执行，任务时限与资源配置取自原始 `task.toml`。容器保持默认安全配置。每次使用新容器和独立会话。

## 版本与配置

- Harbor `0.25.0`，提交 `509b119db0d97b141dcd9c80f4f7ab861c47c2d6`。
- Pi `1.4.0`，由官方适配器安装并启动 CLI。
- Terminal-Bench 2.1，提交 `7131e4375048a0e408a8fb404b5f499d726b695b`；任务文件通过 Git archive 提取，保留 Git 原始内容和 LF 换行。
- 模型 `deepseek-v4.1-flash-al`，medium thinking，沿用原有 2048 响应输出配置。
- 使用 Pi 原生模型、认证和设置文件；API 请求重试及 Harbor 整轮重跑关闭，累计 token、轮数和工具数仅统计。
- 每轮将配置源复制到独立、可写的私有目录，支持 Pi 原生配置和认证锁；运行结束后清理该副本。
- Linux `6.8.0-137-generic` 虚拟机内运行 Docker/Compose；各任务保留镜像和配置中声明的资源设置。

安装阶段统一使用 USTC Debian 软件源镜像，保留原 Debian archive keyring 的签名校验；共同安装时限为 900 秒。Task 指令、验证器及 Agent 执行时限保留原值。Node 仍从官方默认下载地址安装。

## 审计接口

NoDrop 的 `nod_audit_uid` 模块参数选择目标宿主 UID，默认值为 1000。本次使用 0，匹配原始任务容器的 root 用户；采集仍通过显式调用上下文限定。

容器通过绑定在 `/dev/pi-nodrop` 的 ioctl 接口提交上下文，`PI_NODROP_IOCTL_PATH` 同时配置执行器与 monitor。每次审计运行将独立保存目录绑定至宿主机和任务容器中构建时的审计输出位置。调用标识、策略和原始参数保存在调用元数据中。

容器功能检查使用默认 Docker 安全配置和原始任务镜像，以 root 完成 raw/counts 采集及子进程操作，外部模型请求数为 0。

## 运行当前字段接口

完成 NoDrop 与 N-API 构建，在对应 Python 环境中安装上述 Harbor 版本，并将项目根目录加入 `PYTHONPATH`。准备原始任务目录和仅含所选模型的 Pi 配置目录。

默认三组为 `baseline/fixed-raw/agent`。复现历史工具名条件时，显式传入 `--modes baseline fixed-raw agent-names`。汇总脚本按结果目录识别字段模式和历史模式，并核对对应的策略来源。

```bash
mkdir -p build results/audit
tar -czf build/harbor-audit-payload.tar.gz \
  src/client.mjs src/extension.mjs src/tools.mjs src/worker.mjs \
  src/output-store.mjs src/policy-tools.mjs \
  build/context.node build/nodrop/monitor/monitor

sudo env "PYTHONPATH=$PWD" .venv/bin/python scripts/run_harbor_comparison.py \
  --tasks path/to/original/tasks \
  --agent-config path/to/pi-config \
  --output results/harbor-comparison
```

`--apt-sources` 可提供包含三个 `<task>.sources` 文件的共同安装镜像配置目录。`--install-only` 执行安装预检，模型请求数为 0。结果汇总读取 Harbor 的 trial 记录和 Pi 原生 session，并核对 token 统计、调用元数据及已保存事件。

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/summarize_harbor_comparison.py \
  results/harbor-comparison --output docs/harbor-comparison-results.json
```

- [当前字段接口配置](../experiments/harbor-comparison.json)
- [历史工具名接口配置](../experiments/harbor-names-comparison.json)
- [镜像来源与层核对](../experiments/harbor-image-provenance.json)
- [官方 Pi 适配器](https://github.com/harbor-framework/harbor/blob/509b119db0d97b141dcd9c80f4f7ab861c47c2d6/src/harbor/agents/installed/pi.py)
- [Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1)
- [Debian 软件源镜像说明](https://mirrors.ustc.edu.cn/help/debian.html)
