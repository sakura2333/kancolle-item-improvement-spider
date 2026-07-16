# Spider 架构

## 产品职责

Spider 从 Akashi List、start2 以及声明的社区来源生成舰队 Collection 改修和装备数据，输出：

- 正式改修列表与路线明细；
- 舰船、装备、装备类型和消耗品主数据；
- 装备获得关系与特殊装备加成；
- 来源归一化结果、差异和诊断证据；
- `@sakura2333/kancolle-data` npm 数据包；
- 可验证的公开数据快照。

## 业务模块

- `service/akashi_list/`：正式改修数据抓取、解析与逐级期望；
- `service/source_validation/`：外部来源归一化、差异比较和审计材料；
- `service/data_package/`：公开投影、manifest 构建和质量校验；
- `service/generated_state/`：数据状态导出、校验和恢复；
- `util/http_cache/`：HTTP 重试、缓存、条件请求和采集审计；
- `util/start2/`：游戏主数据读取与索引；
- `packages/kancolle-data/`：消费方稳定接口。

## 来源权威

- Akashi List：改修路线、材料、星期、二号舰和更新目标；
- start2：ID、名称、类型和改造链映射；
- KcWiki ship/equipment：装备获得关系；
- KC3 `mst_slotitem_bonus`：特殊装备加成；
- WikiWiki 与 KcWiki 改修信息：交叉验证，不自动覆盖 Akashi 正式结果。

## 严格数据生产

严格生产必须重新验证声明的远端来源，完成数据投影、Schema、引用、新鲜度、记录数量和文件大小检查。旧缓存只能用于普通本地运行，不能冒充发布级新鲜数据。

公开 GitHub 数据工作流只负责严格数据生产、独立 `online` 数据状态和 npm 数据包，不会把运行日志、内部维护流程或原始网页缓存写入稳定分支。


## Stable 内容一致性

公开 `main` 包含 `STABLE-CONTENT-MANIFEST.json`，用于记录项目管理的公开文件集合。Flow Lite 迁移完成后，后续发布只同步该集合，不依赖全量删除仓库内容。
