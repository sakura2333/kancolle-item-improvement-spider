## 1.0.19 (2026-07-06)

- 同名舰消歧改为分别维护明确文本别名与 WikiWiki 页面目标。
- 裸 `Glorious` 只有链接到 canonical 基础页面 `/Glorious` 时才交叉验证为巡洋战舰形态 1022。
- `Glorious(正規空母)` 页面与明确文本映射为空母形态 1027；`Glorious(航空母艦)` 继续作为可接受同义名称。
- 未登记页面目标仍保持红色 `ERROR` 和 exit 75，不进行装备反推或默认选择。
- 对外数据路径与 Schema 均未改变。

## 1.0.18 (2026-07-06)

- 普通页面和 JSON 缓存改为 22 小时，适配每日 CI；同一天重复运行不会再次请求站点。
- `strict` 只控制 TTL 过期后的失败处理：过期后必须成功验证，失败不得回退；未过期缓存可以直接作为本轮有效输入。
- 图片维持 30 天 TTL，严格构建不会提前绕过图片缓存。
- 对外数据路径与 Schema 均未改变。

## 1.0.17 (2026-07-06)

- 同名舰采用两层严格消歧：明确形态名称直接映射；裸名称必须由其绑定的 Wiki 链接目标交叉验证。
- `Glorious(巡洋戦艦)` 映射到 1022，`Glorious(航空母艦)` 映射到 1027；裸 `Glorious` 无法验证时继续拒绝构建。
- 人工停止现在以红色 `ERROR` 输出，并保存首项摘要 `operator-stop.json` 与全部去重停止项 `operator-stops.nedb`。
- 对外数据路径和 Schema 均未改变，只提高 `source.shipIds` 的准确性与失败可诊断性。

## 1.0.16 (2026-07-06)

- Akashi List 不再下载装备图片，只保留配方所需的 useitem/材料图片。
- 图片仍统一通过 `download_pic()` 下载，默认缓存 30 天。
- 对外数据结构和普通文件缓存策略均未改变。

## 1.0.15 (2026-07-06)

- Akashi List 图片统一通过 `download_pic()` 下载。
- 图片缓存默认 30 天；无特殊需求时调用方无需重复传入过期时间。
- HTML、JSON 与普通文件缓存规则未改变。

# Release Notes

## 1.0.14 (2026-07-06)

本版本补齐代码更新事务的 Git 闭环，不改变 Spider 数据、公开 NEDB 或 npm 消费接口。

### 更新自动提交

- `flow update` 成功返回前会自动提交 project-owned 代码，提交信息记录源版本与目标版本。
- generated-state、本机配置、Raw Cache 和恢复状态不会进入该提交；即使此前被暂存，也会自动退回未暂存状态。
- 更新仍不自动 push、不打 Tag、不发布 npm。

### 连续更新与回滚

- 旧版 Flow 留下的未提交更新，只要当前 project-owned 内容身份精确等于下一更新包基线，就可直接继续更新，无需人工逐文件提交。
- staging 使用当前可信工作树作为基线，因此不会因 `HEAD` 仍停留在更早版本而误判候选。
- `flow rollback` 会生成反向提交，回滚后工作区代码保持干净，同一更新包可再次应用。

### 兼容性

- 对外数据结构没有变化。
- 本版本只修改项目更新、回滚、Git 提交和事务恢复行为。

## 1.0.13 (2026-07-05)

本版本收紧任务来源写入规则，并修复 WikiWiki 嵌套任务引号导致的虚假歧义。

### 严格任务收录

- 只有完整 canonical 任务名或完整任务 code 能唯一精确映射到 `kcQuests` 时，才写入公开 `source.questKey`。
- 不再使用子串、包含关系或模糊相似度推断任务；不完整证据仅保留在内部诊断中。
- 完整任务名直接在原始方法文本中匹配，因此外层引用与任务名自身引号嵌套时不会被截断。

### 运行可见性

- 571 页逐页解析结束后会继续输出“解析汇总”“写入数据集”“严格门禁”阶段日志。
- 公开数据 Schema 和既有字段均不改变；本版本只提高 `questKey` 内容准确性。

## 1.0.12 (2026-07-05)

本版本把舰娘、升级链和任务来源统一为可直接消费的装备来源记录，并完成 KcWiki 增量、WikiWiki 每日轮询和人工停止协议。

### 统一装备来源

- `equipment/sources.nedb` 为每件装备固定提供 `shipIds`、`upgradeFromItemIds` 和 `questKey` 三组数组。
- 舰娘 ID 只信任 KcWiki `_api_id`，同时与 Start2 的 ID 和名称校验。
- 升级来源直接从 canonical 改修详情反向投影；任务使用 `kcQuests` 顶层数字 key。正式数据构建会先刷新完整任务目录，再离线重建已有 WikiWiki Raw Cache。

### 增量与抓取

- KcWiki ship/equipment 输入未变化时复用既有解析结果；统一来源输出记录 added、changed、removed 与 unchanged。
- WikiWiki 默认每天抓取 30 个实际未完成页面，断点跳过不占额度；571 件装备约 20 天完成一轮。
- 每轮记录新增、变化、未变化、失败、剩余数量和下一装备 ID。

### 可恢复停止与制品边界

- 无法自动恢复时统一输出红色 `ERROR`、非零退出码、`stopReason`、人工处理方法和断点。
- Recovery 私有保存 generated-state，并完整纳入未跟踪的 project-owned 新文件；代码更新包和代码 Hash 继续完全排除 generated-state。
- 更新 staging 将生成态一致性检查与代码候选检查分离，旧生成数据不会阻止代码更新；完成更新并重新生成后，完整门禁仍要求两者一致。

### 兼容性

- 新增 npm 数据包 `equipment.sourcesPath` 与 `schemas.equipmentSourcesPath`。
- 原有 `drop-from` 和 special-bonus 数据仍保留，统一来源表作为新的聚合消费入口。

## 1.0.9 (2026-07-05)

本版本收口 WikiWiki 全量装备页审计中发现的名称关联和 fallback 过收问题；正式装备来源数据和 npm 消费接口不变。

### 名称关联

- 9 个经人工确认的重音、全半角标点和展示空格差异进入独立页面名称字典。
- 名称目录仍按精确匹配、保守归一化、人工别名的顺序关联；无法唯一匹配时不会猜测 URL。

### 离线解析

- 任务页面链接、历史活动表格、Halloween 活动名和武勋褒赏可以进入对应来源分类。
- 材料消耗、装备使用建议、性能比较和其他装备的获取说明由精确忽略字典排除，不扩大通用正则。
- 全量快照中的未分类证据只保留两条“无常设来源”事实，等待独立 availability 模型。

### 兼容性

- Raw HTML、诊断数据 Schema、正式 `drop-from` 和 npm 消费接口均不变。

## 1.0.8 (2026-07-05)

本版本继续提高 WikiWiki 装备获取方式离线解析的准确性，并把季节活动简称和少量特殊文本收口到可审计字典；正式装备来源数据和 npm 消费接口不变。

### 分类与结构

- 季节活动简称通过分类黑名单统一映射为事件语义，原始证据文本保持不变。
- 支持稳定的改修更新表达、比较表中的改修获取，以及游戏说明内自身带有明确获取信号的嵌套列表。
- 缺少专门获取区段的页面仍采用保守 fallback，不递归吸收一般性能、运用或历史说明。

### 引用诊断

- 只有实际提取出的具体舰娘名称才进入引用解析；泛化初期装备描述不再生成虚假未解析引用。
- 同名形态的真实歧义继续保留，无法安全分类的“无常设来源”等陈述继续进入未分类证据。

### 兼容性

- 已采集 Raw HTML 可直接全量重建解析结果，无需重新抓取。
- 诊断数据 Schema、正式 `drop-from` 和 npm 消费接口均不变。

## 1.0.7 (2026-07-05)

本版本提高 WikiWiki 装备获取方式离线解析的结构覆盖率，并把少数特殊页面措辞收口到可审计字典；正式装备来源数据和 npm 消费接口不变。

### 离线解析

- 统一继承嵌套列表、表格和折叠内容的获取上下文，保留任务与活动名称中的完整标点。
- 缺少专门获取区段时只接受高置信证据，避免把性能说明、使用建议和材料消耗误当成获取方式。
- 特殊标题、同义措辞和明确非证据文本由人工接受的替换字典处理，不通过扩大通用规则强行覆盖。

### 可审计性

- 原始 HTML 和输出证据文本保持不变；字典只参与标题识别、上下文继承和来源分类。
- 无法安全分类的模糊陈述继续进入未分类清单，不为了提高覆盖率静默猜测。

### 兼容性

- 诊断数据 Schema、正式 `drop-from` 和 npm 消费接口均不变。
- 已采集 Raw HTML 可直接重新解析，无需重新请求 WikiWiki。

## 1.0.6 (2026-07-05)

本版本修正外部 WikiWiki 采集器的详情页寻址方式，不改变正式装备来源数据或 npm 消费接口。

### 名称目录

- 采集 Wiki 装备卡片页与舰娘卡片页，建立由 Wiki 页面名称指向详情页精确链接的本机目录。
- 与 Start2 的关联只使用名称精确匹配和保守 Unicode 归一化，不使用 Wiki 图鉴号作为业务 ID。
- 半角与全角符号等安全表现差异可以自动匹配，同时保留改造阶段、括号和名称后缀的区分。

### 抓取安全

- 无法唯一关联的名称会进入问题报告，不再通过拼接名称猜测详情页地址。
- 列表页与详情页原始 HTML 继续进入统一 Raw Cache，离线解析器与正式数据保持隔离。

### 兼容性

- 已有详情页断点与 Raw HTML 可继续复用。
- 正式 `drop-from`、npm Schema 和插件消费接口均不变。

## 1.0.5 (2026-07-05)

本版本调整项目维护检查的执行阶段，不改变 Spider 数据、解析结果或 npm 消费接口。

### 检查分层

- 日常快速检查只运行开发回归，不再执行仅对公开发布内容有意义的检查。
- 公开发布候选仍会单独执行发布内容检查，并在不符合要求时停止发布。
- 版本号恢复为简洁三段格式，后续日常修复按 patch 版本递增。

### 兼容性

- WikiWiki Raw Cache、离线解析器、正式装备来源数据和 npm Schema 均保持不变。
- 更新包的源版本和目标版本仍由配套清单精确校验，文件名缩短不降低更新安全性。

## 1.0.4-rc.11 (2026-07-05)

本版本把外部 WikiWiki 采集器与项目离线解析器统一到同一个 Raw HTML 事实入口，不改变正式 `drop-from` 或 npm 数据。

### Raw 证据统一

- 外部 crawler 将有效 HTML 直接写入 `data/raw_data/site_cache/**`；Cookie、断点、临时文件和事件日志继续留在 crawler 的本机私有运行目录。
- 增加一次性迁移脚本，可把旧 crawler 输出目录中的 HTML 安全迁移到共享 Raw Cache，无需重新抓取。
- 迁移默认保留旧文件，支持 dry-run、SHA-256 校验、冲突保护和显式 `--remove-source`。

### 离线解析

- 默认装备获取诊断入口改为纯离线 parser，只读取 Raw Cache 元数据及 HTML，不读取 crawler 私有状态，也不访问网络。
- 修复 WikiWiki 页面编号与装备名数字相邻时的 ID 拼接误判。
- 修复 HTML 注释节点参与文本提取时可能触发的解析异常。

### 兼容性

- `data/raw_data/**` 仍属于本机保留范围，不进入代码更新包。
- 正式装备来源数据、npm Schema 和 Stable 发布面保持不变。

## 1.0.4-rc.10 (2026-07-05)

本版本增加一个与核心架构隔离的 WikiWiki 浏览器会话采集器，用于先完成原始证据抓取，不改变正式 `drop-from`、npm 数据或默认 Spider。

### 外部采集工具

- 单线程、断点续抓 571 件玩家装备页面，按装备 ID 保存原始 HTML 与 SHA-256。
- 复用本机临时 Cloudflare Cookie，但凭据只存放在本机私有配置目录，不会进入 Git、更新包或日志。
- HTTP 429 触发全站冷却；连续限流或挑战页会停止本轮并保留断点。
- 页面 `No.xxx` 缺失或不一致只记审计状态，不丢弃原始证据。

### 架构边界

- `tools/**` 明确位于 L1-L4 之外，核心代码不得依赖；Flow、CI、npm 和默认质量流程不得执行。
- 更新包可以分发工具源码，但只能作为静态文件。

## 1.0.4-rc.9 (2026-07-05)

本版本在 RC8 全量装备获取诊断之上增加舰娘与任务 ID 关联，并把所有无法唯一关联的证据显式计入异常。正式插件数据不变。

### 引用关联

- 舰娘名称、链接和表格文本映射到 Start2 `shipId`；同名形态使用 KcWiki 日文后缀辅助消歧。
- 任务名称与 WikiWiki 任务编号映射到 `kcwiki-quest-data` 的游戏 `game_id`、WikiWiki `wiki_id` 和正式名称。
- 输出 `reference-issues.nedb`，区分 unresolved、ambiguous 与任务目录不可用。
- `dataset-metadata.json` 和终端摘要直接显示 ship/quest 成功数与异常数。

### 兼容性

- WikiWiki 装备获取诊断记录升级到 schema 3。
- 正式 `equipment/drop-from.nedb`、npm Schema 与发布流程不变。

## 1.0.4-rc.8 (2026-07-05)

本版本新增 WikiWiki 装备详情页的全量获取方式诊断能力，不改变正式插件数据或 npm Schema。

### 装备获取方式诊断

- 遍历 Start2 玩家装备，并优先通过 WikiWiki 装备卡片目录定位详情页。
- 提取开发、舰娘携带、任务、改修更新、活动、排名、建造、购买和交换等来源证据。
- 页面编号与 Start2 装备 ID 不一致时拒绝记录；失败、低置信度和未分类文本独立保存。
- 当前结果仅用于覆盖率与结构分析，不覆盖正式 `drop-from`。

## 1.0.4-rc.7 (2026-07-02)

本版本不改变权重算法和 npm 数据 Schema，只补齐来源权重的运行可观察性。

### 运行日志

- `./flow run` 的最终结果直接列出各来源 `relativeWeight/confidence`。
- `data-validate` 日志逐来源写入权重、当前一致性分、累计历史事件数和历史信号启用状态。
- `dist/data-pipeline/local-validation.json` 新增 `sourceReliability` 摘要；权重仍为 advisory-only，不参与正式数据选举。

### 兼容性

- 权重算法、已有历史文件和 `@sakura2333/kancolle-data` 消费字段保持不变。

## 1.0.4-rc.6 (2026-07-02)

本版本不改变 npm 数据 Schema，新增来源长期观察与仅供分析的相对权重。

### 来源历史

- 以 RC5 成功解析结果建立一次完整存量基线：Akashi 2634 条、WikiWiki 1692 条、KcWiki 705 条可比较事实。
- 后续成功运行只追加 `added`、`removed`、`modified`、`reappeared` 事件，并保留最近完整状态。
- 失败或 partial 来源不会更新历史，避免把解析故障误判成网站数据删除。

### 相对权重

- 初始横向一致性建议权重：Akashi `1.0248`、WikiWiki `1.0345`、KcWiki `0.9406`。
- 当前尚无历史增量，因此置信度为 `medium`；积累至少 5 条可判断变化后，历史同行佐证才开始参与计算。
- 权重仅用于观察哪个来源长期更一致，不参与正式来源选举，也不会自动覆盖 Akashi 数据。

### 兼容性

- `@sakura2333/kancolle-data` 消费字段保持不变。
- 新增内容只位于公开诊断目录 `data/sources/history/` 与 `data/sources/reliability/`。

## 1.0.4-rc.5 (2026-07-02)

本版本不改变数据 Schema，但修正来源名称映射、严格门禁和装备获得关系快照。

### 语义映射

- 新增经人工确认的来源限定字典；每条目标 ID 都会在运行时与当前 Start2 自动核对。
- WikiWiki 多行舰名会在拆行前按完整语义解析，不再把 `(特務艦)`、`改二護` 等后缀当成独立舰名。
- KcWiki 的两个 `Kai Ni` 英文装备别名分别稳定映射到 Start2 ID 142 和 305。

### 质量与数据

- 当前 WikiWiki unresolved 从 14 条降为 0，KcWiki 装备获得关系 unresolved 从 2 条降为 0。
- 装备获得关系记录由 247 项增至 249 项，关系数由 1645 增至 1647。
- 严格流程发现任何新的 unresolved 时直接失败，并在日志摘要中显示来源、问题数和字典命中数。
- 隔离 Staging 工作树会复用主工作树的项目 Python 环境，更新事务不再因 `.venv` 未进入 Git 工作树而误失败。

### 兼容性

- npm 数据结构和字段保持不变；仅补回此前因名称差异遗漏的两条正式关系。

## 1.0.4-rc.4 (2026-07-02)

本版本不改变数据 Schema、正式数据内容或 npm 消费接口。

### 环境与验收

- Python 依赖版本继续以 `requirements.txt` 为唯一事实源。
- `./flow check` 会先验证项目虚拟环境和固定依赖，不再把环境未初始化误报为代码错误。
- 1.0.3 更新包可使用内置离线 Wheel 自动完成真实 Full、切换和内网 `dev` 推送。

### 兼容性

- `@sakura2333/kancolle-data` 内容与 1.0.4-rc.3 相同。
- 公开数据和技术文档边界保持不变。

## 1.0.4-rc.3 (2026-07-02)

本版本不改变数据 Schema、正式数据内容或 npm 消费接口。

### 使用与恢复

- 项目维护入口统一为 `./flow`，更新和恢复失败时会给出明确下一步。
- 控制面迁移会保留本机原始缓存和配置，并支持回滚后使用同一迁移包再次安装。
- Recovery Package 支持由用户指定完整输出文件路径。

### 兼容性

- `@sakura2333/kancolle-data` 内容与 1.0.4-rc.2 相同。
- 公开数据和技术文档边界保持不变。

## 1.0.4-rc.2 (2026-07-02)

本页由发布候选生成器汇总项目 Changelog、数据包 Changelog、机器发布记录和本次 Git 变更后生成。只保留面向使用者和数据消费方的摘要。

### 新增

- 增加分层节点化架构文档和 Mermaid 图，建立文档节点到代码路径的自动对账。
- 增加公开 Stable 内容清单，支持一次性清理历史 main 后按已管理文件增量同步。
- 增加历史技术债务清单、一次性 main 清理说明和发布恢复说明。
- Added improvement detail schema 4 with source-faithful ★0..★MAX `levelExpectations`。
- Added fixed 11-row route `stepList` data for every normal improvement level and optional MAX conversion。
- Preserved conditional effect text separately from simple numeric values so consumers do not apply context-specific bonuses globally。
- Added the MAX conversion target name so consumers can render the upgrade result without a separate equipment-master lookup。
- Added `schemas/improvement-detail.schema.json` for the schema 4 record contract。

### 修复

- 防止公开内容清单缺失时重复触发 main 全量清理。
- 防止架构重构后代码路径与节点文档静默漂移。
- 修复更新候选使用字符串排序导致 `1.0.10` 可能排在 `1.0.9` 之前的问题。
- 增加恢复包在空目录通过 Git bundle 重建项目的真实测试。

### 兼容性

- Improvement list schema: 2 (unchanged)。
- Improvement detail schema: 4。
- Consumers that only read existing detail fields remain compatible; schema-aware validators must accept version 4。

### 数据快照

数据包版本：`@sakura2333/kancolle-data@0.3.0`

- 改修路线明细：372
- 装备获得记录：247
- 特殊装备加成记录：348
- 消耗品图片：16

### 数据边界

- `data/sources/` 提供可公开的来源诊断数据，但不属于 npm 消费接口。
- 原始网页缓存和本机运行状态不属于公开数据集。
