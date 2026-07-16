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
- `automation/release/generated_state/`：数据状态导出、校验和恢复；
- `util/http_cache/`：HTTP 重试、缓存、条件请求和采集审计；
- `util/start2/`：游戏主数据读取与索引；
- `packages/kancolle-data/`：受 Git 管理的消费入口、公开 Schema 与构建模板；
- `dist/packages/kancolle-data/`：完整生成数据包候选；
- `dist/npm/kancolle-data/<version>/`：隔离的 npm 打包、审计与发布制品。

## 来源权威

- Akashi List：改修路线、材料、星期、二号舰和更新目标；
- start2：ID、名称、类型和改造链映射；
- KcWiki ship/equipment：装备获得关系；
- KC3 `mst_slotitem_bonus`：特殊装备加成；
- WikiWiki 与 KcWiki 改修信息：交叉验证，不自动覆盖 Akashi 正式结果。

## 公共自动化边界

公开自动化分为三层：

- `automation/acquire/`：访问远端来源，输出带 Manifest 和内容哈希的不可变 Source Bundle；
- `automation/compute/`：只消费冻结 Source Bundle，以 cache-only 模式完成计算、质量验证和 Candidate Bundle；
- `automation/release/`：只验证和发布冻结 Candidate，不重新下载、不重新计算。

对应 GitHub Actions 为 `source-acquire.yml`、`data-build.yml` 和 `release.yml`。Data Build 在分配版本前读取 npm 最高正式版本中的消费者 `contentDigest`。digest 不同才分配新 patch；digest 相同则直接复用 npm 版本，并从当前冻结结果自动补齐缺失的 `improvement2`、dist-tag 与 `online`。该判断不依赖上一次 Workflow、审计文件或 `online` 是否及时推进；`online` 仅是 npm 正式状态的投影。原始网页缓存、浏览器会话和运行日志不进入公开分支。


## 公开内容一致性

公开源码候选由机械文件清单、依赖闭包和禁入路径规则校验；内部维护脚本、测试、缓存和发布治理状态不进入可测试的 Beta 快照。
