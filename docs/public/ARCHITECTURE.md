# Spider 架构与数据生命周期

## 产品职责

Spider 从 Akashi List、start2 以及声明的社区来源生成舰队 Collection 改修和装备数据，输出：

- 正式改修列表与路线明细；
- 舰船、装备、装备类型和消耗品主数据；
- 装备获得关系与特殊装备加成；
- 来源元数据、正式结构化快照和聚合摘要；
- `@sakura2333/kancolle-data` npm 数据包；
- 可验证的公开数据快照。

## 业务模块

- `service/akashi_list/`：正式改修数据抓取、解析与逐级期望；
- `service/source_validation/`：外部来源归一化、差异比较和运行期审计材料生成；
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

各数据集预先声明正式来源。系统不使用跨来源多数票自动改写 canonical 数据。

## 数据生命周期

| 路径 | `main` | `online` | npm | 说明 |
|---|---:|---:|---:|---|
| `data/improvement/` | 是 | 是 | 经包投影 | 正式改修数据 |
| `data/start2_data/` | 是 | 是 | 经包投影 | 游戏主数据快照 |
| `data/assets/` | 是 | 是 | 经包投影 | 稳定图片资产 |
| `data/sources/` | 是（公开子集） | 是 | 否 | 来源元数据、正式快照与聚合摘要；运行期工作集不进入 `main` |
| `packages/kancolle-data/` | 是 | 选择性 | 是 | 消费方稳定接口 |
| `data/raw_data/` | 否 | 否 | 否 | 原始响应和本机缓存 |
| `dist/`、日志和运行状态 | 否 | 否 | 否 | 可重建或内部证据 |

公开“全量数据”是指全部可公开、可复现且属于长期契约的数据投影、来源元数据和必要结构化快照；不包含 AI/差异/历史工作集、原始网页缓存、本机路径、凭据、测试日志、运行 Receipt 或临时构建产物。

## 严格数据生产

严格生产会验证声明的远端来源，完成数据投影、Schema、引用、新鲜度、记录数量和文件大小检查。普通本地运行可以使用有效缓存；发布级流程不得用过期缓存冒充新鲜结果。

WikiWiki 装备获取原始页面不随公开仓库发布。维护环境存在原始证据时优先离线重建；干净的公开 checkout 会严格校验并复用已公开的结构化获取快照，快照缺失或损坏时失败。

## 发布面与 Generated state

- `main`：稳定源码、技术文档、完整公开数据和数据包源码；
- `online`：严格数据工作流生成的最新数据状态和验证记录；
- npm：面向应用消费方的稳定数据接口。

Generated state 是由明确源码和数据输入生成的可校验状态。其 manifest 可记录构建标识、基线提交、文件 SHA-256、大小和验证结果。公开归档不得包含绝对路径、路径穿越、符号链接、重复成员、异常膨胀或原始网页缓存。

`STABLE-CONTENT-MANIFEST.json` 记录公开 `main` 由项目管理的文件集合，用于检查稳定内容边界。
