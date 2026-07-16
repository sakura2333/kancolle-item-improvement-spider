# 数据生命周期

| 路径 | Git 代码 | 可重建 | npm 消费 | 职责 |
|---|---:|---:|---:|---|
| `.spider/local/source-cache/` | 否 | 否 | 否 | 原始响应、本机来源缓存和可复用网页证据 |
| `.spider/local/source-receipts/` | 否 | 可刷新 | 否 | 来源采集 Receipt |
| `dist/data-pipeline/improvement/` | 否 | 是 | 经包投影 | 正式改修数据 |
| `dist/data-pipeline/start2_data/` | 否 | 是 | 经包投影 | 游戏主数据快照 |
| `dist/data-pipeline/assets/` | 否 | 是 | 经包投影 | useitem PNG+WebP 与装备 WebP quality 93 稳定图片资产 |
| `dist/data-pipeline/sources/` | 否 | 是 | 否 | 来源归一化、差异与诊断证据 |
| `packages/kancolle-data/` | 是 | 否 | 否 | npm 源码模板、入口与公开 Schema |
| `dist/packages/kancolle-data/` | 否 | 是 | 是 | 完整生成数据包候选 |
| `dist/npm/kancolle-data/<version>/` | 否 | 是 | 是 | 隔离的 npm 打包、审计与发布制品 |

根目录 `data/` 与 `log/` 已退役。业务日志写入 `.spider/local/logs/business/`；内部事务与检查日志不属于公开数据生命周期。

公开源码不携带原始网页、本机缓存或 generated-state。计算和发布只消费已冻结的来源及候选产物。官方 PNG 原图只存在于 Source Cache/Source Bundle；`latest` 发布 useitem 270×270 与装备 390×390 的 WebP quality 93，`improvement2` 只投影 useitem PNG。


## 定时采集与冻结锁

GitHub Actions 每天启动一次 Source Acquire，并优先恢复最近一次成功的冻结 Source Bundle。各来源按独立过期时间决定是否实际访问网络：Start2 为 24 小时，Akashi List、KcWiki、KC3 等普通网络来源为 48 小时，WikiWiki 目录与详情页为 15 天，官方 useitem/equip 图片为 180 天。

Acquire 只有在全部必需来源完成后才写入 `source-bundle.lock.json`。写锁前会验证严格 Build 的固定外部输入闭包，包括 Akashi 首页、WikiWiki 索引、KC3 bonus 与完整 `kcQuests/quests-scn.json`；缺失或仅有 fallback 缓存时不会生成 ready Bundle。该 ready lock 绑定 Source Bundle Manifest、采集时 Git Commit 与内容哈希，不携带可变的来源授权。采集 Commit 只作为来源追溯信息，不要求与后续 Build Commit 相同；Data Build 使用当前 main 的构建代码消费任意完整且通过 ready-lock 校验的冻结输入，若旧 Bundle 缺少当前契约所需数据，则由严格构建校验明确拒绝并要求重新 Acquire。

Data Build 每天在 Acquire 之后 12 小时运行。GitHub 上仍存在 Acquire 运行时，Build 最多等待 5 分钟；锁仍未释放则本次正常延后，由下一次日常调度重试，不使用未完成快照。

Source Bundle 与 Build Candidate 的 GitHub Artifact 上传显式包含隐藏文件。`.spider/**` 和 `.generated-state/**` 都属于冻结制品契约的一部分，上传后必须保持与 Bundle Manifest 的文件清单和内容哈希一致。

Data Build 始终使用当前 `main` 的代码：先校验 Source Bundle Manifest、ready lock 与内容哈希，再恢复冻结输入并完成离线计算、质量检测和版本规划。Source Bundle 的采集 Commit 只用于来源追溯，不参与代码切换或强一致校验；旧 Bundle 缺少当前代码所需输入时，由 CACHE_ONLY/STRICT 构建明确拒绝并要求重新 Acquire。数据 digest 仍用于质量比较与 `online` 状态；npm 是否升版则由一个包业务身份方法判断。工作流把 canonical 与 `improvement2` 都真实打成 tgz，并对当前包和 Registry tarball 使用同一算法：JSON/NeDB 规范化，二进制按原始字节计算，`package.json` 排除版本号；数据、入口、类型、Schema 与校验脚本参与，manifest、README、CHANGELOG、RELEASES、许可证摘要和审计文件不参与。两个变体均相同则复用已有版本；缺失变体和状态只触发同版本对账；任一变体业务内容变化则分配下一 patch。已有 npm tarball 会直接冻结进本次 Candidate，全部状态一致时成功 no-op。`npm publish` 或 dist-tag 命令返回非零时不会立即把事务判死：发布器使用 `--prefer-online` 持续查询 Registry，最长等待 120 秒；只要远端版本、tarball 与 tag 最终和冻结 Candidate 一致，就按幂等成功继续后续变体。超过确认窗口仍无法对账时才失败，并在审计中同时保留 npm 输出的开头和错误尾部。
