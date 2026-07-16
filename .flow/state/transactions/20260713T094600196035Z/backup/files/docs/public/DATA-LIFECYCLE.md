# 数据生命周期

| 路径 | Git 代码 | 可重建 | npm 消费 | 职责 |
|---|---:|---:|---:|---|
| `.spider/local/source-cache/` | 否 | 否 | 否 | 原始响应、本机来源缓存和可复用网页证据 |
| `.spider/local/source-receipts/` | 否 | 可刷新 | 否 | 来源采集 Receipt |
| `dist/data-pipeline/improvement/` | 否 | 是 | 经包投影 | 正式改修数据 |
| `dist/data-pipeline/start2_data/` | 否 | 是 | 经包投影 | 游戏主数据快照 |
| `dist/data-pipeline/assets/` | 否 | 是 | 经包投影 | 稳定图片资产 |
| `dist/data-pipeline/sources/` | 否 | 是 | 否 | 来源归一化、差异与诊断证据 |
| `packages/kancolle-data/` | 是 | 否 | 否 | npm 源码模板、入口与公开 Schema |
| `dist/packages/kancolle-data/` | 否 | 是 | 是 | 完整生成数据包候选 |
| `dist/npm/kancolle-data/<version>/` | 否 | 是 | 是 | 隔离的 npm 打包、审计与发布制品 |

根目录 `data/` 与 `log/` 已退役。业务日志写入 `.spider/local/logs/business/`；内部事务与检查日志不属于公开数据生命周期。

公开源码不携带原始网页、本机缓存或 generated-state。计算和发布只消费已冻结的来源及候选产物。


## 定时采集与冻结锁

GitHub Actions 每天启动一次 Source Acquire，并优先恢复最近一次成功的冻结 Source Bundle。各来源按独立过期时间决定是否实际访问网络：Start2 为 24 小时，Akashi List、KcWiki、KC3 等普通网络来源为 48 小时，WikiWiki 目录与详情页为 15 天。

Acquire 只有在全部必需来源完成后才写入 `source-bundle.lock.json`。写锁前会验证严格 Build 的固定外部输入闭包，包括 Akashi 首页、WikiWiki 索引、KC3 bonus 与完整 `kcQuests/quests-scn.json`；缺失或仅有 fallback 缓存时不会生成 ready Bundle。该 ready lock 只绑定 Source Bundle Manifest、Git Commit 与内容哈希，不携带可变的来源授权；Data Build 只接受带有效 ready lock 的冻结输入，并由代码内固定契约恢复严格构建所需的完成状态。

Data Build 每天在 Acquire 之后 12 小时运行。GitHub 上仍存在 Acquire 运行时，Build 最多等待 5 分钟；锁仍未释放则本次正常延后，由下一次日常调度重试，不使用未完成快照。

Source Bundle 与 Build Candidate 的 GitHub Artifact 上传显式包含隐藏文件。`.spider/**` 和 `.generated-state/**` 都属于冻结制品契约的一部分，上传后必须保持与 Bundle Manifest 的文件清单和内容哈希一致。

Data Build 先用 Source Bundle 绑定的代码完成离线计算，再切回当前 `main` 的发布控制器执行质量检测和版本规划。消费者身份直接从实际文件重算：canonical digest 覆盖 schema-4 正式路径，`improvement2` digest 覆盖 schema-3 兼容投影路径；JSON/NeDB 采用规范化序列化，图片按原始字节计算。生成时间、包版本、CHANGELOG、RELEASES、manifest 和审计文件不参与身份。canonical digest 不同才分配新 patch；相同则把 npm 已有版本视为唯一目标。已有 `improvement2` 必须匹配当前投影 digest，冲突时停止且不得推进 dist-tag 或 generated-state。已有 npm tarball 会直接冻结进本次 Candidate，缺失变体才从当前数据生成；`online` 缺失或落后只触发同版本对账。全部状态一致时成功 no-op。
