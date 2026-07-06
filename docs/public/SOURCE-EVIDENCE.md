# 来源证据与公开快照

`data/sources/` 不属于 npm 消费 API。公开稳定分支只保留能够支持来源追溯、结构校验或 clean build 的长期数据。

## 公开边界

公开 `main` 保留：

- 来源 URL、抓取或生成时间、内容哈希、记录数量、Schema 版本和健康状态等 metadata；
- KcWiki 装备获得关系与 KC3 特殊加成的正式结构化来源数据；
- 统一装备来源投影及其输入哈希；
- WikiWiki 装备详情的已接受结构化快照；
- advisory-only 的相对一致性机器摘要。

公开 `main` 不保留：

- AI 完整输入、Prompt 和审核工作集；
- 逐条差异、冲突和路线变体；
- 完整 baseline/current 副本、逐轮 changes 与 runs；
- 原始 HTML、HTTP cache、Cookie、Header、代理信息、本机路径和运行日志。

这些运行期产物可以由维护流程重新生成，但不属于长期公开数据契约。

## WikiWiki 装备获取快照

`data/sources/wikiwiki-equipment-detail/` 是公开 clean build 必需的结构化快照。完整快照由以下六个文件组成：

```text
catalog.json
acquisition-records.nedb
dataset-issues.nedb
reference-issues.nedb
unclassified-evidence.nedb
dataset-metadata.json
```

构建器在维护环境存在 Raw Cache 时重新解析原始证据；在干净公开 checkout 中则严格校验并复用上述快照。文件缺失、计数不一致、记录未接受、Schema 不匹配或仍存在 operator stop 时，构建失败。

## 其他正式来源数据

- `kcwiki-data/equipment-drop-from.nedb`：经 Start2 校验的舰娘初始与改造装备关系；
- `kc3-slotitem-bonus/special-bonuses.nedb`：特殊装备加成规则；
- `equipment-sources/equipment-sources.nedb`：舰船、升级与任务来源的统一投影；
- 各目录的 `metadata.json` / `dataset-metadata.json`：来源、时间、哈希、数量、Schema 与错误摘要。

## 相对一致性摘要

`data/sources/reliability/summary.json` 是聚合后的 advisory-only 摘要。它可以描述来源之间的相对一致性，但明确满足：

- `applyToCanonicalElection=false`；
- 不进行多数投票；
- 不自动切换正式来源；
- 不证明某来源具有官方权威。

正式数据仍按各数据集预先声明的权威来源生成。
