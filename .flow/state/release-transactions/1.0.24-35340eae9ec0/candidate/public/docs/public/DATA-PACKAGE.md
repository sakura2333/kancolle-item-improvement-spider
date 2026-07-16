# `@sakura2333/kancolle-data`

数据包提供 CommonJS 入口、TypeScript 声明、JSON Schema、NeDB/JSON 数据和必要图片资产。

主要数据包括：

- 改修列表和路线明细；
- ★0～★MAX 累计效果与逐级动作；
- 装备获得关系；
- 特殊装备加成；
- use-item 图片；
- 数据 manifest、审计摘要和发布记录。

消费方应通过包入口和 manifest 使用稳定路径，不应直接把 `dist/data-pipeline/sources/` 的诊断记录当作应用接口。

严格打包会校验 Schema、关键文件、装备引用、图片引用、数据新鲜度和 tarball 内容。已经发布的相同版本必须与准备发布的 tarball 内容一致，否则发布会被阻断。

## GitHub 与 npm 边界

来源采集输出 Source Bundle；计算工作流从该 Bundle 生成不可变 Candidate。版本规划使用消费者数据的 `contentDigest`，并在分配新 patch 前读取 npm 最高正式版本的 `RELEASES.json`：digest 相同表示该数据已经发布，目标版本固定为 npm 现有版本；现有 canonical 与 `improvement2` 包必须从各自 `RELEASES.json` 证明同一 digest，冲突时作为不可变 Registry 冲突失败。验证通过后，本次 Build 会自动对账缺失的 `improvement2`、dist-tag 和 online-state；digest 不同才分配并发布新版本。发布决策只依赖当前数据与 npm Registry 的权威事实，不依赖上一次 Workflow 是否完成。手动发布工作流仍可对任一冻结 Candidate 做补偿。

`latest` 发布 canonical schema-4 包，`improvement2` 发布同一候选生成的 schema-3 兼容包。两个 tarball 的 release-set 都显式记录并复验相同的消费者 `contentDigest`；发布阶段不得重新生成任何 tarball。
