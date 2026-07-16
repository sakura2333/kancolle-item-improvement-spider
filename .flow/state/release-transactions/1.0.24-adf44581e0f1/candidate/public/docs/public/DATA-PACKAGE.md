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

来源采集输出 Source Bundle；计算工作流从该 Bundle 生成不可变 Candidate。版本规划使用实际消费者文件的规范化身份，而不是 `RELEASES.json` 中自报的旧 digest。canonical schema-4 digest 决定是否分配新 patch；`improvement2` schema-3 投影 digest 单独验证兼容包。版本号、生成时间和发布历史元数据被排除，因此同一数据重复构建不会升版。canonical digest 相同表示该数据已经发布，目标版本固定为 npm 现有版本；若同版本兼容包存在但实际投影 digest 不一致，则作为不可变 Registry 冲突失败。验证通过后自动对账缺失变体、dist-tag 和 online-state。发布决策只依赖当前数据与 npm Registry 的实际 tarball，不依赖上一次 Workflow。

`latest` 发布 canonical schema-4 包，`improvement2` 发布同一候选生成的 schema-3 兼容包。release-set 分别记录 `current` 与 `improvement2` 两个实际文件 digest，并在冻结后重新打开两个 tarball 复验；发布阶段不得重新生成任何 tarball。
