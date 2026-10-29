# 实验输出

实验脚本将原始记录和校验结果写入此目录。Git 跟踪本说明，实验输出由 `.gitignore` 排除。

`scripts/run_guest.py` 为每轮实验创建结果目录。重新运行前，将上一轮结果归档至项目目录之外。

运行 `python3 scripts/verify_results.py results` 可解码并检查调用归属、输出策略、事件计数及模块清理结果。

已发布的验证数据见[结果摘要](../docs/result-summary-20261028.json)和[实验报告](../docs/experiment-report.md)。
