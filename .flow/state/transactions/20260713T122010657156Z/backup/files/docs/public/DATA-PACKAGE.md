# `@sakura2333/kancolle-data`

数据包提供 CommonJS 入口、TypeScript 声明、JSON Schema、NeDB/JSON 数据和必要图片资产。

主要数据包括：

- 改修列表和路线明细；
- ★0～★MAX 累计效果与逐级动作；
- 装备获得关系；
- 特殊装备加成；
- 官方 use-item PNG；
- 舰 C 官方 `slot/card` 原图生成的 390×390 WebP quality 93 装备图片；
- 数据 manifest、审计摘要和发布记录。

消费方应通过包入口和 manifest 使用稳定路径，不应直接把 `dist/data-pipeline/sources/` 的诊断记录当作应用接口。

严格打包会校验 Schema、关键文件、装备引用、图片引用、数据新鲜度和 tarball 内容。已经发布的相同版本必须与准备发布的 tarball 内容一致，否则发布会被阻断。

## GitHub 与 npm 边界

来源采集输出 Source Bundle；计算工作流从该 Bundle 生成不可变 Candidate。版本规划不读取 `RELEASES.json` 的旧自报 digest，而是把 canonical 与 `improvement2` 实际打包后，通过同一个 npm 业务身份方法比较当前 tgz 和 Registry tarball。身份覆盖数据、入口代码、类型声明、Schema、校验脚本和规范化后的稳定 `package.json` 契约；版本号、生成 manifest、README、CHANGELOG、RELEASES、许可证摘要与审计文件被排除。两个变体均相同表示 npm 业务内容已发布，可复用现有版本并自动对账缺失变体、dist-tag 和 online-state；任一变体业务内容变化都分配下一 patch。发布决策不依赖上一次 Workflow。

`latest` 发布 canonical schema-4 包，`improvement2` 发布同一候选生成的 schema-3 兼容包。release-set 分别记录 `current` 与 `improvement2` 两个实际文件 digest，并在冻结后重新打开两个 tarball 复验；发布阶段不得重新生成任何 tarball。

## 图片资产契约

- `assets/useitem/{id}.png`：官方 `useitem/card`（或历史 `card_`）PNG，ID 来自 `api_mst_useitem`。
- `assets/equip/{id}.webp`：官方 `slot/card` 390×390 原图的确定性 WebP 投影，quality 93、alpha quality 100、method 6。
- `manifest.datasets.equipmentImages` 使用 schema 2，并声明 `format=webp`、`quality=93`、`source=official-slot-card` 与实际 `availableIds`。
- Akashi 页面图片 URL 不属于数据包或图片获取契约。
- 原始 PNG 与 HTTP 元数据只存在于 Source Cache；图片缓存 TTL 为 180 天。
