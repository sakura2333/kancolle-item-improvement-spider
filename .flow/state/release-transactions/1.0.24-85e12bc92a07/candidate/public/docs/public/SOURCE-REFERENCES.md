# 爬虫资源引用与来源选举规则

本文记录 Spider 当前实际访问的远端资源、各来源的权威范围、缓存与降级规则，以及多来源之间如何进行“选举/仲裁”。

> 当前实现不是多数投票系统。每个数据集都有预先确定的权威来源；其他来源只能用于校验，或负责独立的数据集，不得自动覆盖正式结果。

## 1. 远端资源清单

| ID | 资源 | 当前地址 | 代码入口 | 主要用途 | 权威角色 |
|---|---|---|---|---|---|
| `akashi-index` | Akashi List 首页 | `https://akashi-list.me/` | `service/akashi_list/akashi_list_spider.py` | 枚举可改修装备和详情页 ID | 改修数据正式来源 |
| `akashi-detail` | Akashi List 装备详情 | `https://akashi-list.me/detail/{weapon_id}.html` | `service/akashi_list/akashi_list_spider.py`、`akashi_detail_processor.py` | 改修阶段、材料、资材、二号舰、星期和更新目标 | 改修数据正式来源 |
| `wikiwiki-jp` | 日文 WikiWiki 改修表 | `https://wikiwiki.jp/kancolle/%E6%94%B9%E4%BF%AE%E8%A1%A8` | `service/source_validation/wikiwiki_jp.py` | 独立解析改修日程和二号舰条件 | 交叉验证，不覆盖 Akashi |
| `kcwiki-equipment` | KcWiki 装备数据 | `https://raw.githubusercontent.com/kcwiki/kancolle-data/refs/heads/master/wiki/equipment.json` | `service/source_validation/kcwiki_data.py`、`service/data_package/equipment_drop_from.py` | 改修交叉验证；装备获得关系解析 | 验证来源；获得关系数据集的组成来源 |
| `kcwiki-ship` | KcWiki 舰船数据 | `https://raw.githubusercontent.com/kcwiki/kancolle-data/refs/heads/master/wiki/ship.json` | `service/data_package/equipment_drop_from.py` | 舰船初始装备、改造装备和舰船映射 | 获得关系数据集正式来源 |
| `kc3-slotitem-bonus` | KC3 装备加成数据 | `https://raw.githubusercontent.com/KC3Kai/kancolle-replay/refs/heads/master/js/data/mst_slotitem_bonus.json` | `service/data_package/equipment_bonus.py` | 舰种、舰级、舰船和装备类型加成规则 | 特殊加成独立数据集正式来源 |
| `start2-index` | start2 版本索引 | `https://api.kcwiki.moe/start2/archives` | `util/start2/start2_utils.py` | 判断本地主数据是否需要更新 | 主数据版本依据 |
| `start2-current` | 当前完整 start2 | `https://api.kcwiki.moe/start2` | `util/start2/start2_utils.py` | 装备、舰船、消耗品 ID/名称/类型和改造链映射 | ID 与主数据映射基线 |
| `official-slot-card` | 舰 C 官方装备卡 | `https://<game-server>/kcs2/resources/slot/card/{id}_{resource}.png` | `service/data_package/official_assets.py` | 按 Start2 装备 ID、`api_version` 和官方资源码获取 390×390 原图，再编码为 WebP quality 93 | 图片正式来源，不参与改修事实选举 |
| `official-useitem-card` | 舰 C 官方消耗品卡 | `https://<game-server>/kcs2/resources/useitem/card[_]/{id}.png` | `service/data_package/official_assets.py` | 按 Start2 useitem ID 获取官方 PNG；生成 canonical WebP，同时为 improvement2 保留 PNG | 图片正式来源，不参与改修事实选举 |

## 2. 数据集权威划分

### 2.1 改修路线与日程

```text
Akashi List
  -> 正式改修列表和详情投影

WikiWiki / KcWiki
  -> 归一化后与 Akashi 比较
  -> 只写 dist/data-pipeline/sources/**
  -> 不自动改写 dist/data-pipeline/improvement/**
```

正式改修数据包括：

- 装备可改修性；
- 改修阶段与材料；
- 开发资材和改修资材；
- 二号舰及星期；
- 更新目标与目标星级；
- 同一装备的默认路线和二号舰专属材料路线。

### 2.2 装备获得关系

`equipment/drop-from.nedb` 由 KcWiki 的舰船和装备 JSON 共同生成。它是独立数据集，不参与 Akashi 改修路线的竞争。

### 2.3 特殊装备加成

`equipment/special-bonuses.nedb` 由 KC3 的 `mst_slotitem_bonus.json` 生成。它同样是独立数据集，不覆盖 Akashi 或 KcWiki 数据。

### 2.4 ID、名称和类型映射

start2 负责把来源文本映射到稳定的游戏主数据 ID：

- `api_mst_slotitem.json`：装备 ID、名称、类型；
- `api_mst_ship.json`：舰船 ID、名称、改造链；
- `api_mst_useitem.json`：消耗品 ID、名称。

start2 不决定某装备能否改修，也不决定星期和材料；它只提供规范化字典与引用完整性基线。

### 2.5 来源限定语义别名字典

`configs/source-semantic-aliases.json` 只保存已经人工确认的命名差异。字典键同时包含来源和实体类型，不能把 `(特務艦)`、`改二護` 等残片注册为全局别名。WikiWiki 先按完整单元格匹配，再执行普通分行；KcWiki 英文装备别名直接落到 Start2 canonical ID。

每次严格运行都会验证：

- canonical ID 仍存在；
- canonical name 与当前 Start2 一致；
- 对同名形态声明的附加证据仍成立；
- 所有来源的 unresolved 数量为 0。

AI 可以提出候选，但未经人工确认的候选不得进入正式字典，也不得消除 unresolved。

### 2.6 WikiWiki 同名舰引用消歧

WikiWiki 装备详情中的舰娘引用按两层严格规则处理：

1. 带明确形态后缀的已登记名称直接映射，例如 `Glorious(巡洋戦艦)`、`Glorious(正規空母)`；`Glorious(航空母艦)` 作为已登记同义写法处理。
2. 裸同名名称（例如 `Glorious`）不得直接选择候选，必须读取该引用自身绑定的 Wiki 链接目标；WikiWiki canonical 基础页面 `/Glorious` 对应巡洋战舰形态，`/Glorious(正規空母)` 对应空母形态。目标 ID 还必须位于 Start2 同名候选集合中。

链接中的数字、页面内部编号和图片文件名永远不作为游戏主键。链接缺失、目标仍为裸名称、目标与显示文字冲突，或交叉验证后仍不唯一时，严格构建输出 operator stop，不写入公开 `source.shipIds`。

停止信息位于：

```text
dist/data-pipeline/sources/wikiwiki-equipment-detail/operator-stop.json
dist/data-pipeline/sources/wikiwiki-equipment-detail/operator-stops.nedb
```

前者是首要停止摘要，后者是全部去重后的机器可读停止项。终端同时输出红色 `ERROR`、`stopReason`、人工处理方法和可继续使用的 Raw Cache 断点。

## 3. 来源选举/仲裁方式

## 3.1 没有多数投票

当前系统不计算“两个来源赞成就覆盖第三个来源”，也没有按一致率自动切换正式来源。

规则是：

```text
先按数据集确定正式来源
-> 再把其他来源标准化
-> 对相同事实键比较
-> 输出 match / weekday-mismatch / missing / extra
-> 交给审计或人工处理
```

### 3.2 交叉验证比较键

改修日程比较会先按以下维度聚合：

```text
装备 ID
+ 二号舰 ID（或无指定舰）
+ 能力类型 improve / upgrade
+ 更新目标装备 ID
```

同一键下的多条路线会合并星期可用性，但保留路线签名用于差异报告。比较结果分为：

- `match`；
- `weekday-mismatch`；
- `missing-in-candidate`；
- `extra-in-candidate`。

这些结果只形成审计材料，不自动修改正式改修数据。

### 3.3 历史观察与相对权重

成功解析的来源会先建立一次完整基线，之后只追加事实变化。系统根据两两一致、同行共识和积累后的变化佐证输出相对权重，但该权重仅表示“与现有其他来源相比更一致”，不表示官方权威，也不参与正式来源切换。

当前改修投影仍固定来自 Akashi；权重报告位于 `dist/data-pipeline/sources/reliability/`，详细结构见 `SOURCE-HISTORY.md`。

### 3.4 Akashi 内部路线选取

Akashi 同一装备可能存在默认路线和二号舰专属材料路线。当前解析规则是：

1. 材料阶段、目标装备和限定二号舰共同组成路线签名；
2. 同一签名的路线合并；
3. 不同材料或不同目标必须保留为不同路线；
4. 更具体的舰船规则覆盖其改造链祖先规则；
5. 同等具体度的规则按 OR 合并星期；
6. 明确排除的专属舰不会继续进入默认路线。

这属于同一正式来源内部的规则归并，不是跨网站投票。

## 4. 验证来源的启用方式

默认启用：

```text
VALIDATION_SOURCES=wikiwiki-jp,kcwiki-data
```

可按需选择：

```bash
VALIDATION_SOURCES=wikiwiki-jp
VALIDATION_SOURCES=kcwiki-data
VALIDATION_SOURCES=wikiwiki-jp,kcwiki-data
VALIDATION_SOURCES=
```

空值表示关闭外部验证适配器，但不会关闭 Akashi 正式采集。

严格性由以下变量控制：

```text
VALIDATION_STRICT=1
DATA_PACKAGE_STRICT=1
FETCH_STRICT=1
CACHE_ONLY=1
```

- `VALIDATION_STRICT=1`：验证来源失败、存在 unresolved 或质量状态非 `ok` 时失败；
- `DATA_PACKAGE_STRICT=1`：发布级构建；未过期缓存可直接作为本轮有效输入，TTL 过期后必须完成远端验证且禁止旧缓存回退，并拒绝正式独立数据集中的 unresolved；
- `FETCH_STRICT=1`：底层采集在 TTL 过期后强制成功验证，不允许失败后使用旧缓存；
- `CACHE_ONLY=1`：完全禁止网络，仅允许已有缓存。

## 5. HTTP 缓存选取顺序

普通 `fetch()` 的选择顺序为：

1. `CACHE_ONLY=1`：必须读取本地缓存，缺失即失败；
2. 本进程已完成网络校验：直接复用已校验缓存；
3. 本地文本缓存未超过 22 小时：直接读取并记为本轮通过 TTL 校验；严格模式同样遵守此 TTL；
4. 发起带 `ETag` / `Last-Modified` 的条件请求；
5. 返回 `304`：保留缓存，但记为本次网络验证成功；
6. TTL 过期后的网络请求失败：非严格模式可回退旧缓存，严格模式直接失败。

普通文件缓存默认有效期为 7 天；官方 useitem PNG 与装备 `slot/card` 原图通过 `download_pic()` 下载，图片缓存有效期统一为 180 天。两类官方 PNG 都保存在 Source Cache，并确定性编码为 WebP quality 93；useitem PNG 另外作为 improvement2 兼容输入。所有请求元数据写入：

```text
本机 HTTP 缓存元数据
```

注意：start2 当前使用自己的三次重试下载逻辑，不经过 `util/cache.py`。非严格模式下载失败时继续使用仓库内已有 start2；严格模式失败。

## 6. 并发与站点保护

采集按 hostname 分组：

- 不同 hostname 最多各使用一个 worker 并行；
- 同一 hostname 下的所有 URL 串行；
- Akashi 首页和所有详情页始终串行；
- KcWiki 的两个 GitHub Raw URL 因 hostname 相同而串行；
- WikiWiki、Akashi、GitHub Raw 可以彼此并行。

该模型避免因为一个来源 URL 数量多就提高对该站点的并发压力。

## 7. 图片资源现状

### 当前实际行为

- Akashi 只提供改修业务事实，不再参与图片 URL 发现或下载；详情解析完成并转换为 canonical 路线后，独立的 `official-assets` 阶段统一收集装备/useitem ID。
- `api_mst_slotitem` 提供装备 ID 与 `api_version`；Spider 按官方资源码算法生成 `slot/card` 地址。
- 装备官方原图按 Start2 `api_version` 保存在 `.spider/local/source-cache/cache/official/equip/{id}/{api_version}.png`，避免半年 TTL 掩盖资源版本变化；编码缓存位于 `.spider/local/source-cache/cache/official/equip/webp-q93-a100-m6-exact/{id}.webp`，发布投影保存在 `dist/data-pipeline/assets/equip/{id}.webp`，保持 390×390，固定 WebP quality 93、alpha quality 100、method 6。
- `api_mst_useitem` 提供消耗品 ID；Spider 按官方 `useitem/card` 与旧式 `card_` 路径获取 PNG，原图缓存位于 `.spider/local/source-cache/cache/official/useitem/{id}.png`，编码缓存位于 `.spider/local/source-cache/cache/official/useitem/webp-q93-a100-m6-exact/{id}.webp`。`latest` 发布 `assets/useitem/{id}.webp`，`improvement2` 仅发布 `assets/useitem/{id}.png`。
- 旧 `cache/useitem/*.png` 与 `cache/equip/*.png` 属于退役 Akashi 图片缓存；恢复 seed Source Bundle 后会删除文件及对应 `_meta.json` 条目，不进入下一份 Bundle。
- 图片缓存有效期为 180 天；TTL 内直接复用，过期后按统一 HTTP 缓存规则重新验证。
- 改修路线“大图”仍由消费方根据数据绘制，不作为单独抓取资产。

### 网络边界

官方游戏资源服务器可能按出口地区返回 403。严格 Source Acquire 首次缺图或缓存过期时必须成功取得官方资源，否则不生成 ready Source Bundle；已有缓存不得在严格过期场景冒充新鲜输入。CI 可通过 `KANCOLLE_ASSET_BASE_URLS` 指向允许访问的官方游戏服务器候选，并可使用运行环境已有的标准 HTTP(S) 代理配置。

## 8. 站点风险与本地时效

当前 `source-policy.json` 注册 5 个文本/数据来源族；此外图片链路会访问 `KANCOLLE_ASSET_BASE_URLS` 指定或内置候选的官方 game-server。KcWiki JSON 与 KC3 JSON 虽共享 GitHub Raw hostname，但保持不同的数据集权威。

| 来源 | 风险级别 | 当前保护 | 本地时效 |
|---|---|---|---|
| Akashi List | 中 | 同 hostname 串行、通用有界重试、严格模式拒绝旧缓存冒充新鲜 | 文本缓存 48 小时 |
| 舰 C 官方图片资源 | 高 | 可配置 game-server 候选顺序回退（默认使用 w15p）、图片签名校验、严格模式拒绝过期 fallback | 原始 useitem/equip 图片缓存 180 天 |
| WikiWiki 改修表 | 中 | 同 hostname 串行、条件请求、429/5xx 有界重试 | 标准文本缓存 48 小时 |
| WikiWiki 浏览器会话详情采集 | 高 | 单线程、3 秒±1 秒间隔、429 全站 90 秒指数冷却、连续限流熔断、挑战页拒收 | Raw HTML 无自动 TTL；目录和详情仅在显式刷新时更新；Cookie 时效由站点会话控制 |
| KcWiki / KC3 GitHub Raw | 低 | 同 hostname 串行、条件请求、有界重试 | 文本缓存 48 小时 |
| start2 API | 低到中 | 30 秒超时、最多 3 次请求、失败后非严格模式保留本地版本 | 无固定 TTL；每次更新入口先检查远端版本索引，仅版本变化时下载完整数据 |

“Raw HTML 无自动 TTL”表示它是带抓取时间和哈希的历史证据，不会因时间到达而被静默删除；准备 Stable 或需要最新获取方式时应显式刷新。所有风险级别都是当前实现与已观察访问行为下的运维判断，不是来源站点的可用性承诺。

