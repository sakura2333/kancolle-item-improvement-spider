## [1.0.24] - 2026-07-06

### Changed

- 公开 `main` 的严格数据构建在 Raw Cache 未发布时，改为校验并复用已经公开的 WikiWiki 装备获取快照；本机存在 Raw Cache 时仍优先离线重建。
- 快照复用只在 `data/raw_data/site_cache/_meta.json` 缺失时启用；原始证据存在但损坏时继续失败，不用旧快照掩盖错误。

### Fixed

- 修复干净公开 checkout 不包含 `data/raw_data/`，却无条件执行 WikiWiki 离线 Raw Cache 解析，导致 GitHub Actions 严格构建在进入数据质量门禁前失败的问题。
- 增加公开快照文件集、Schema、记录唯一性、接受状态及统计数量的一致性门禁；快照缺失或损坏时 strict build 明确失败。

## [1.0.23] - 2026-07-06

### Changed

- Stable 机械 Preview 不再要求整个工作区干净；只要 project-owned 代码已提交并推送，就允许读取当前 generated-state，并忽略 Raw Cache、日志和 Flow 本机状态。
- 机械候选同时纳入已跟踪与未跟踪的 generated-state 文件，避免新生成的公开数据被静默漏出候选。
- Preview 身份新增 generated-state SHA-256，并写入 release ID 与 Candidate Manifest；同一 dev Commit 下数据变化会自动生成新候选。

### Fixed

- 修复 `./flow run` 产生合法 generated-state 后，`main_release.py prepare` 又因工作区不干净而无法继续的闭环冲突。
- 修复旧 Preview 在 generated-state 已变化时仍可能被复用的问题；prepare 现在只对来源漂移重新生成机械候选，Candidate 自身损坏仍会阻断。
- 修复 AI 审核后 Candidate Manifest Schema 被降回旧版本、丢失 generated-state 来源绑定的问题。

## [1.0.22] - 2026-07-06

### Added

- 增加与 AI 最终审核 Commit、公共 Candidate 哈希及审核报告哈希绑定的一次性 main 发布门禁；候选发生变化时自动失效。
- 增加项目专用 `script/project/main_release.py`，负责机械准备临时公共分支、接受 AI 审核凭证和输出状态对账事实。
- 正式 main 与 npm 双制品对账完成后自动关闭门禁，并把发布 Receipt 归档到 generated-state。

### Changed

- `./flow stable` 不再创建分支、调用 AI 或直接推送 main；默认只提示人工步骤，`--confirm` 只消费已审核门禁并做机械对账。
- Stable Preview 从 Flow 公共动作移到低频项目协作脚本：机械候选先推到 `public-candidate/*`，AI 只审净化后的临时分支。
- AI 净化后的最终候选会重新冻结公共文件和 current/improvement2 npm tarball，避免沿用净化前的制品身份。

## [1.0.21] - 2026-07-06

### Changed

- 将 `poi-plugin-item-improvement2` 兼容逻辑绑定到项目自有的 Stable/main 发布编排，而不是要求消费者切换包内兼容路径。
- Stable Preview 现在从同一个 canonical 候选冻结两个唯一 npm 版本：current 制品绑定 `latest`，schema 3 旧 VO 制品绑定 `improvement2`。
- `improvement2` 制品沿用普通 `improvement/*` 与 Schema 路径；旧插件只需安装 dist-tag，不需要代码适配。
- npm 浏览器认证仍由用户手动完成；重新执行 `./flow stable --confirm` 会按 Preview 哈希和 dist-tag 对账，不重新构建制品。

### Fixed

- 修正 1.0.20 将兼容数据作为 `latest` 包内额外路径公开的发布模型；兼容 VO 继续使用字段白名单，但改为发布期临时投影。

## [1.0.20] - 2026-07-06

### Added

- 增加 `poi-plugin-item-improvement2` 的 schema 3 兼容 VO 与自动投影目录；兼容输出只保留旧协议字段，不复制爬虫、清洗或关联逻辑。
- npm 数据包增加兼容 manifest、schema 3 JSON Schema、CommonJS/TypeScript 路径导出和投影一致性测试。

### Changed

- canonical `improvement/detail.nedb` 继续使用 schema 4；兼容列表继续复用 schema 2，旧插件需要显式选择 `data.compat.poiPluginItemImprovement2` 路径。
- 数据质量门禁会校验新旧记录 ID、路由数量、字段白名单和路径契约，并把嵌套兼容 manifest 纳入根 manifest 哈希清单。

## [1.0.19] - 2026-07-06

### Changed

- 同名舰消歧字典拆分为“明确名称别名”和“WikiWiki 链接目标”两层，不再假设两者使用同一字符串。
- `Glorious` 基础页面链接目标严格映射为巡洋战舰形态 1022；`Glorious(正規空母)` 映射为空母形态 1027，同时保留 `Glorious(航空母艦)` 作为明确名称同义写法。

### Fixed

- 修复 WikiWiki 实际页面名与 `1.0.17` 规则不一致，导致 `10.2cm三連装副砲` 和 `Sea Gladiator` 在 `1.0.18` 仍触发 `ship-reference-ambiguous` 的问题。

## [1.0.18] - 2026-07-06

### Changed

- 普通页面与 JSON 的本地缓存有效期统一为 22 小时，适配每日一次的自动 CI，并允许同一天重复运行直接复用缓存。
- 严格模式不再绕过未过期缓存；只有 TTL 过期后才发起条件请求，届时仍禁止网络失败后回退旧缓存。
- 图片继续通过 `download_pic()` 使用 30 天 TTL，严格模式下 30 天内同样不发起网络请求。

### Fixed

- 修复 `DATA_PACKAGE_STRICT` / `FETCH_STRICT` 导致 Akashi List 等来源在数小时内重复发送条件请求的问题。

## [1.0.17] - 2026-07-06

### Added

- 增加同名舰两层消歧字典：`Glorious(巡洋戦艦)` 与 `Glorious(航空母艦)` 可直接映射到唯一 Start2 舰娘 ID。
- WikiWiki 严格门禁会同时输出 `operator-stop.json` 和去重后的 `operator-stops.nedb`。

### Changed

- 裸 `Glorious` 不再按同名候选猜测；只有其绑定链接目标明确指向已登记形态，并与 Start2 候选交叉验证唯一通过时才写入 `shipIds`。
- 人工停止门禁改为红色 `ERROR` 日志，并直接输出 `stopReason`、装备、来源页面、处理方法和可继续断点。

### Fixed

- 修复 `10.2cm三連装副砲` 与 `Sea Gladiator` 因 Start2 中两个 `Glorious` 同名而无法利用 Wiki 链接目标消歧的问题。
- 修复 `flow run` 只统计 operator stop、却不落盘完整停止项且严格拒绝日志仍为 `INFO` 的问题。

## [1.0.16] - 2026-07-06

### Changed

- Akashi List 只下载改修配方实际需要的 useitem/材料图片；装备图片不再进入图片缓存。
- 保留 `download_pic()` 的 30 天默认缓存有效期；普通文件与文本缓存策略不变。

## [1.0.15] - 2026-07-06

### Changed

- 新增统一图片下载入口 `download_pic()`，默认图片缓存有效期为 30 天。
- Akashi List 的图片下载改走 `download_pic()`；普通文件下载与文本缓存策略保持不变。

# Changelog

## [1.0.14] - 2026-07-06

### Changed

- `flow update` 在候选门禁和目标内容身份通过后自动提交全部 project-owned 变化；generated-state、本机配置和恢复状态继续保持未提交。
- `flow rollback` 同样生成反向提交，使回滚结果可以直接再次更新或推送，不再留下暂存中的中间状态。
- 当前 project-owned 工作区只要精确等于更新包 `baseIdentity`，即使上一版尚未提交，也可作为可信基线继续更新；staging 会复制当前工作树内容，而不是只依赖旧 `HEAD`。

### Fixed

- 修复 `1.0.12` 更新成功后留下 39 个 project-owned 修改，导致后续 `1.0.13` 被工作区脏状态拒绝的问题。
- 修复受保护/generated-state 文件已暂存时可能进入更新提交或干扰目标 Git Tree 校验的问题；提交前会自动退回未暂存状态。
- 修复自动提交后事务归档失败时无法恢复 Git `HEAD`，以及更新包提前移动导致重试材料丢失的风险。

## [1.0.13] - 2026-07-05

### Changed

- `questKey` 只接受 `kcQuests` 完整任务名或任务 code 的唯一精确匹配；删除任务名称子串、包含关系和相似度推断。
- WikiWiki 离线解析完成全部页面后，明确输出汇总、结果写入和严格人工停止门禁三个阶段，避免长时间无日志被误判为卡死。

### Fixed

- 修复嵌套日文引号把 `「「Gotland」戦隊、進撃せよ！」` 截断成 `「Gotland`，随后产生虚假任务多匹配的问题。
- 不完整任务名现在只保留为未解析诊断，不写入公开 `source.questKey`。

## [1.0.12] - 2026-07-05

### Added

- 增加统一装备来源投影 `equipment/sources.nedb`，每件装备固定输出 `source.shipIds`、`source.upgradeFromItemIds` 和 `source.questKey`。
- 增加 KcWiki 装备获得关系的输入哈希增量复用，以及统一来源投影的 added/changed/removed 差异记录。
- 增加统一人工停止协议：红色 `ERROR`、非零退出码、机器可读 `stopReason`、人工处理方法和可继续断点。

### Changed

- 舰娘来源只接受 KcWiki API 化数据的 `_api_id`，并以 Start2 ID 与日文名称双重校验；不再通过名称回推游戏 ID。
- 升级来源直接从 canonical `improvement/detail.nedb` 反向投影，不建立第二套名称映射。
- 任务目录切换为 `kcwikizh/kcQuests`，使用顶层数字 key 写入 `source.questKey`；任务 code 与名称只用于匹配和诊断。正式数据构建会先增量刷新完整任务目录，再从本地 Raw Cache 重建 WikiWiki 获取证据。
- WikiWiki 详情抓取默认每天处理 30 个实际未完成页面；断点跳过不占额度，571 件装备约 20 天完成一轮。
- Recovery 将 tracked 与 untracked generated-state 统一收集到 `private/generated-state/`，代码更新包继续排除所有 generated-state。
- 更新候选检查只验证 project-owned 代码契约，不再因受保护的旧 generated-state 版本滞后而阻止 `flow update`；正常 `flow check` 仍严格校验代码与生成数据一致性。

### Fixed

- 修复 Cookie/Cloudflare 失效、持续限流、名称歧义、任务多匹配、权威数据冲突和 canonical NEDB 损坏等场景缺少统一可恢复停止信息的问题。
- 修复 Recovery 未完整保存未跟踪 generated-state，以及遗漏未跟踪 project-owned 新文件的问题。

## [1.0.9] - 2026-07-05

### Added

- 增加 `configs/wikiwiki-page-name-aliases.json`，集中保存 9 个经人工确认的 Start2 名称到 Wiki 页面名称映射，不使用 Wiki 图鉴号作为实体 ID。
- 增加来源站点风险与缓存时效说明，区分逻辑来源、网络主机、标准缓存、start2 版本更新和 WikiWiki 浏览器会话采集。

### Changed

- WikiWiki 名称目录在精确匹配和保守 Unicode 归一化之后，才使用人工接受的名称别名字典；无法唯一匹配的装备继续保持 unresolved，不猜测 URL。
- 获取方式 parser 识别任务链接上下文、活动表格标题与 `武勲褒賞`；经全量审计确认的材料消耗、运用建议和其他装备说明进入精确忽略字典。

### Fixed

- 修复 9 个仅因重音、全半角标点或展示空格差异而无法关联 Wiki 详情页的问题。
- 修复 13 条明确非获取事实被 fallback 误收，以及 Halloween 活动、任务奖励链接、历史活动表和排名奖励未正确分类的问题。

## [1.0.8] - 2026-07-05

### Added

- 增加分类视图黑名单，将 `春イベ`、`夏イベ`、`秋イベ`、`冬イベ`、`欧州イベ` 等季节活动简称统一映射为 `イベント`，原始 HTML 与 `rawText` 保持不变。
- 增加通用回归样本，覆盖装备更新获取、比较表 `入手方法=改修` 与游戏说明中的嵌套高置信获取事实。

### Changed

- 获取方式 parser 识别 `からの更新`、`更新で入手` 等稳定改修更新表达，并在缺少专门获取区段时只遍历自身包含明确获取事实的嵌套列表项。
- 舰娘引用诊断只针对实际提取出的具体名称；“多数空母的初期装备”等泛化描述不再被整句误报为未解析舰娘。
- 少量建议、成本比较与说明文本继续由人工接受的精确忽略字典处理，不扩展装备专用规则。

### Fixed

- 修复季节活动简称无法进入事件分类的问题。
- 修复部分改修更新和比较表获取方式未被识别，以及泛化初期装备描述产生大量虚假 `ship-reference-unresolved` 的问题。

## [1.0.7] - 2026-07-05

### Added

- 增加 `configs/wikiwiki-acquisition-replacements.json`，集中保存经人工接受的特殊标题、上下文标签、字面分类替换、历史标记与非证据忽略项。
- 增加替换字典契约测试，保证特殊项只做精确或显式前缀匹配，并保持原始 HTML 与输出 `rawText` 不变。

### Changed

- WikiWiki 装备获取解析器统一处理嵌套列表、表格和折叠块的上下文继承；任务名中的日文引号与标点不再被错误拆分。
- 无专门获取区段的页面只保留高置信摘要表与顶层获取证据，不再递归吸收游戏说明、性能建议和消耗说明。
- 少数页面特殊措辞不再扩展通用正则，而由可审计替换字典显式处理；模糊陈述继续保留为未分类证据。

### Fixed

- 修复初期装备表、历史作战报酬折叠块和事件奖励表丢失上下文的问题。
- 修复嵌套列表被重复展开，以及更新建议、性能说明被误判为获取方式的问题。

## [1.0.6] - 2026-07-05

### Added

- 增加 WikiWiki 装备卡片页与舰娘卡片页目录采集，原始列表页进入共享 Raw Cache，派生出本机 `name → exact URL` 目录。
- 增加 Start2 装备名称匹配报告，明确列出 resolved、ambiguous 与 unresolved，长时间抓取前即可完成 URL 覆盖诊断。

### Changed

- 装备详情 crawler 只使用 Wiki 列表页提供的名称与精确链接；关联顺序为名称精确匹配、保守 Unicode 归一化匹配，不再把 Wiki 图鉴号当作实体 ID。
- 无法唯一匹配的名称记录为 `url-ambiguous` 或 `url-unresolved`，不会再从 Start2 名称拼接并请求猜测 URL。

### Fixed

- 修复 Start2 半角 `+` 与 Wiki 页面全角 `＋` 等安全表现差异导致详情页 URL 404 的问题。

## [1.0.5] - 2026-07-05

### Changed

- `quick` 与 `full` 只执行开发和完整回归测试；公开发布策略检查改由 Stable Preview 单独执行，不再阻断日常开发检查。
- 项目版本恢复为简洁三段 SemVer；日常迭代直接递增 patch，不再把开发流水号持续编码为 `rc.N`。
- 更新制品推荐使用 `kancolle-spider-update-<目标版本>.zip`，源版本与目标版本继续由 Sidecar 和 Manifest 精确声明。

### Fixed

- 修复公开发布策略测试被默认 `test*.py` 全量发现、导致 `./flow check --profile quick` 错误承担发布阶段职责的问题。
- 清理公开 Release Notes 中的内部运行目录字面路径；发布候选阶段仍会对此进行硬检查。

## [1.0.4-rc.11] - 2026-07-05

### Added

- 增加一次性 `migrate_existing_html.py`，将旧 `.flow/local/wikiwiki-crawler/raw/*.html` 按原 URL 和 SHA-256 安全迁移到共享 raw cache，无需重新抓取。
- 增加纯离线装备获取方式 parser，只消费 `data/raw_data/site_cache/_meta.json` 与对应 HTML，不读取 crawler 私有状态、不访问网络。

### Changed

- 外部 crawler 的 HTML 事实文件改写入 `data/raw_data/site_cache/**`；Cookie、断点、临时下载与日志仍隔离在 `.flow/local/**`。
- 修复真实 WikiWiki 页面中 `No.001` 与后续装备名数字相邻导致页面 ID 被拼接误判，以及 HTML 注释节点触发解析异常的问题。


## [1.0.4-rc.10] - 2026-07-05

### Added

- 增加隔离的 `tools/wikiwiki-crawler/` 手动采集器，可复用本机浏览器 Cloudflare 会话，按装备 ID 断点抓取 WikiWiki 原始 HTML。
- 增加 AI/Flow 外部工具边界：根与目录级 `AGENTS.md`、架构守卫以及机器可读排除 Manifest。
- 增加 429 全站冷却、连续限流熔断、挑战页识别、断点续抓和页面编号审计。

### Changed

- `.flow/local/**` 明确归类为 local-preserved 并加入 Git 忽略，Cookie、原始页面和断点不会进入代码 Update、push 或 Recovery。
- 外部工具允许单向读取导出数据或通过子进程调用公开项目入口；核心 L1-L4 代码不得反向依赖工具。

## [1.0.4-rc.9] - 2026-07-05

### Added

- WikiWiki 装备获取证据增加舰娘与任务稳定引用：舰娘映射到 Start2 `shipId`，任务映射到游戏 `game_id` 与 WikiWiki `wiki_id`。
- 增加 `reference-issues.nedb` 和引用状态统计，明确区分 resolved、partial、ambiguous、unresolved 与任务目录不可用。
- 全量诊断结束时直接输出页面、舰娘引用、任务引用、引用异常和未分类证据数量。

### Changed

- 装备获取诊断记录升级到 schema 3；正式 `equipment/drop-from.nedb` 与 npm 数据仍保持不变。
- 舰娘同名形态使用 KcWiki 后缀辅助消歧；任务目录使用 `kcwiki-quest-data` 的游戏编号、WikiWiki 编号与正式名称。

## [1.0.4-rc.8] - 2026-07-05

### Added

- 增加 WikiWiki 装备详情页全量获取方式诊断工具，遍历 Start2 玩家装备并保存结构化来源、未分类证据和问题清单。
- 增加目录发现、页面装备编号对账、段落/列表/表格解析，以及 current、historical、mixed-summary 可用性分类。
- 增加可被项目现有 `unittest` 入口执行的装备获取方式回归测试。

### Changed

- 全量结果保持诊断性质，不覆盖正式 `equipment/drop-from.nedb`，也不改变 npm 数据包。

## [1.0.4-rc.7] - 2026-07-02

### Changed

- `./flow run` 完成后直接显示各来源当前建议权重与置信度，不再要求人工打开 JSON 文件。
- 严格数据流程日志逐来源记录权重、当前一致性、历史事件数以及历史信号是否已经参与计算。
- 本地验证报告显式携带 `sourceReliability` 摘要，便于后续自动化读取和审计。

本文件只记录公开源码、数据结构和消费接口的变化。

## [1.0.4-rc.6] - 2026-07-02

### Added

- 增加来源事实历史：首次启用建立不可变完整基线，后续只追加新增、删除、修改和恢复事件。
- 增加同行佐证标记，区分已被其他来源支持、明显离群和暂时无法判断的变化。
- 增加相对一致性权重报告，综合当前两两一致率、同行共识和成熟后的历史佐证率。

### Changed

- 来源状态不是 `ok` 时不更新历史，避免抓取或解析失败被误记录成网站全量删除。
- 权重只作为诊断建议输出，范围限制为 0.75～1.25，不参与 Akashi 正式数据投影或跨来源自动选举。
- 当前 RC5 数据作为历史能力引入时的一次性存量基线，之后由严格 Spider 流程自动维护增量。

本文件只记录公开源码、数据结构和消费接口的变化。

## [1.0.4-rc.5] - 2026-07-02

### Added

- 增加经人工确认、按来源和实体类型隔离的语义别名字典，并在每次严格流程中与当前 Start2 ID、名称及限定证据自动对账。
- 增加 WikiWiki 多行完整单元格与 KcWiki 英文装备别名的回归测试。

### Changed

- WikiWiki 二号舰解析先匹配完整单元格，再执行普通分行和改造链语法，避免限定词被拆成独立舰名。
- 验证来源和正式独立数据集只要仍存在 unresolved，就不得在严格模式下报告成功。
- 来源摘要显式输出 unresolved 数量和本轮语义字典命中数。

### Fixed

- 修复 `Fletcher改 Mod.2`、`Fletcher Mk.II`、`宗谷（特務艦）`、`加賀改二護` 共 14 处 WikiWiki 解析问题。
- 修复 KcWiki 两个英文装备名称无法映射 Start2，恢复 ID 142 与 305 的装备获得关系。
- 修复严格流程 `status=ok` 仍可能隐藏少量解析失败的质量语义漏洞。
- 修复更新事务的 Staging 工作树无法复用主工作树 `.venv`、导致完整检查误报环境未初始化的问题。

## [1.0.4-rc.4] - 2026-07-02

### Changed

- `./flow check` 在执行质量检查前验证项目 `.venv` 与固定依赖版本。
- 项目更新器使用包内 macOS ARM64 Wheel 完成离线 staging Full，并在成功后自动推送内网 `dev`。

### Fixed

- 修复依赖已经在 `requirements.txt` 声明，但 AI/验收链路未触达环境初始化事实而误报缺少外部物料的问题。
- 修复缺少 `.venv` 时静默回退系统 Python、将环境缺陷误判成项目代码失败的问题。

## [1.0.4-rc.3] - 2026-07-02

### Added

- 绑定正式 Flow Public Contract 1.0.0，统一人类命令、机器结果和更新/恢复能力边界。
- 增加控制面迁移黑盒验证，覆盖本机数据保留、回滚和同包再次迁移。

### Changed

- 控制面按职责和事实源归并，不再按 `script/`、`scripts/` 等目录名判断项目能力。
- Spider 的质量、数据、Git 和发布逻辑继续由项目自身维护，公共 Flow 只承担统一入口与三项基础能力。

### Fixed

- 修复一次性控制面迁移回滚后可能留下新旧版本混合状态的问题。
- 修复 Recovery `--output` 没有按完整目标文件路径执行的问题。
- 防止文档和测试用目录名称代替真实调用关系判断旧控制逻辑。

## [1.0.4-rc.2] - 2026-07-02

### Added

- 增加分层节点化架构文档和 Mermaid 图，建立文档节点到代码路径的自动对账。
- 增加公开 Stable 内容清单，支持一次性清理历史 main 后按已管理文件增量同步。
- 增加历史技术债务清单、一次性 main 清理说明和发布恢复说明。

### Changed

- Flow Lite 发布只允许一次对授权 legacy tree 做 main 全量内容替换；后续发布不再全量删除。
- 内部发布聚合同时纳入 Changelog、数据包发布记录、Git 变更、质量结果和数据审计摘要；公开仍只输出用户摘要。
- 文档按人类接口、Flow Kernel、Adapter、三个能力、项目命令、产品 Runtime、数据与发布分层。

### Fixed

- 防止公开内容清单缺失时重复触发 main 全量清理。
- 防止架构重构后代码路径与节点文档静默漂移。
- 修复更新候选使用字符串排序导致 `1.0.10` 可能排在 `1.0.9` 之前的问题。
- 保证 Flow `--machine` 输出为单一 JSON，不被 Git 子进程输出污染。
- 增加恢复包在空目录通过 Git bundle 重建项目的真实测试。
- 回滚 Flow Lite 迁移时，将失败版本快照归档到项目外的统一恢复目录，避免删除 `.flow` 后留下失效路径。
- 删除无人消费的旧 Exact Stable 基线凭据，避免内部发布控制面数据继续进入公开 main。

## [1.0.4-rc.1] - 2026-07-02

### Added

- 引入 Flow Lite，统一人类意图命令与三项版本化能力契约。
- 新增完整恢复包、更新事务回滚和项目自有 Stable Preview/Release。

### Changed

- 更新根目录统一为 `/Users/sakana/Downloads/GPT-Projects/`，不再按项目分流。
- 全部可公开技术文档和来源诊断数据进入公开 `main`，Flow 与维护材料只留内网。
- Stable 发布汇总完整变更来源，公开只生成用户摘要。

### Removed

- 删除重型 `.devops` 控制面、Findings/dispute、中央 Release Surface 与平行兼容脚本。

## [1.0.3] - 2026-07-01

### Added

- 公开完整的来源归一化、差异和诊断数据，便于复核正式数据的生成依据。
- 增加公开技术文档集，覆盖架构、数据生命周期、来源仲裁、数据包和生成状态。
- 增加自动生成的 `RELEASE-NOTES.md`，集中展示面向使用者和数据消费方的版本摘要。

### Changed

- 发布候选会汇总项目变更记录、数据包变更记录、机器发布记录和本次提交范围，只输出公开摘要。
- 原始网页缓存、本机运行状态和内部维护资料继续排除在公开发布内容之外。
- 更新包可以安全修改项目自有配置和文档，同时继续保护中央工具与本机配置。

## [1.0.2] - 2026-07-01

### Fixed

- 修复严格数据包构建调用未导入版本读取函数而导致的 `NameError`。
- GitHub Actions 与本地验证统一通过数据包 CLI 执行严格 Spider 主流程。

## [1.0.1] - 2026-07-01

### Added

- 恢复每日定时与手动触发的 GitHub Actions 数据流水线。
- 手动运行默认执行完整严格抓取、质量校验、版本规划和数据包 dry-run，不进行远端写入。
- 发布运行将最新生成数据写入独立 `online` 分支，并支持 npm 发布失败后的同版本恢复。

### Changed

- 自动化不再向公开 `main` 提交生成数据。
- `online` 状态同时保存数据快照、校验报告、数据包版本和公开发布记录。

## [1.0.0] - 2026-07-01

### Added

- 提供完整的 Akashi List 改修路线、材料、星期、二号舰和装备更新目标数据。
- 为具体改修路线增加 ★0～★MAX 的累计效果期望和逐级改修动作。
- 增加 MAX 装备更新槽位，使消费端无需额外查询即可显示更新目标。
- 提供 start2 舰船、装备、装备类型和消耗品映射。
- 提供装备获得关系、特殊装备加成及消耗品图片数据。
- 提供 `@sakura2333/kancolle-data` CommonJS 数据包、类型声明和 JSON Schema。

### Changed

- `improvement-detail.nedb` 升级到 schema 4。
- 明确不同数据集的来源权威；验证来源只生成差异，不自动覆盖正式数据。
- 严格构建要求本次运行取得有效来源响应，不使用旧缓存冒充新鲜结果。
- 网络采集对短暂 TLS、连接重置、超时、429 和 5xx 增加有上限的重试。

### Validation

- 数据包校验覆盖清单一致性、关键文件、Schema、装备引用、图片引用和数据版本。
