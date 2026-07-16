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

公开源码分支只保留可复现的数据产品代码、自动化入口、公开配置和文档。来源缓存、本机状态与维护治理不公开。npm 包只包含稳定消费接口；来源诊断属于构建审计产物，不是 npm 应用接口。
