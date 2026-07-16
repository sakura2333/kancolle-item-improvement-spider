# 数据生命周期

| 路径 | Git 代码 | 可重建 | npm 消费 | 职责 |
|---|---:|---:|---:|---|
| `.flow/local/source-cache/` | 否 | 否 | 否 | 原始响应、本机来源缓存和可复用网页证据 |
| `.flow/local/source-receipts/` | 否 | 可刷新 | 否 | 来源采集 Receipt |
| `dist/data-pipeline/improvement/` | 否 | 是 | 经包投影 | 正式改修数据 |
| `dist/data-pipeline/start2_data/` | 否 | 是 | 经包投影 | 游戏主数据快照 |
| `dist/data-pipeline/assets/` | 否 | 是 | 经包投影 | 稳定图片资产 |
| `dist/data-pipeline/sources/` | 否 | 是 | 否 | 来源归一化、差异与诊断证据 |
| `dist/packages/kancolle-data/` | 否 | 是 | 是 | npm 发布候选 |

根目录 `data/` 与 `log/` 已退役。业务日志写入 `.flow/local/logs/business/`；Flow 事务与检查日志写入 `.flow/state/logs/`。

公开源码不携带原始网页、本机缓存或 generated-state。计算和发布只消费已冻结的来源及候选产物。
