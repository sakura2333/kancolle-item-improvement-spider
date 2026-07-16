# kancolle-item-improvement-spider

舰队 Collection 装备改修数据工具。项目从 Akashi List、游戏 start2 主数据和独立社区数据源生成结构化、可追溯的改修与装备数据，并维护可复用的 `@sakura2333/kancolle-data` 数据包。

## 环境

- Python 3.14
- mise 2026.7+
- uv 0.11.28
- Node.js 20+ 与 npm（校验或使用数据包时需要）

```bash
mise trust mise.toml
mise install
mise exec -- uv sync --locked
```

环境与依赖事实源：

- `pyproject.toml` 与 `uv.lock` 固定项目依赖版本；
- `mise trust mise.toml` 先信任当前 checkout 的项目工具声明；
- `mise install` 安装项目固定的 Python 与 uv；
- `mise exec -- uv sync --locked` 是唯一依赖同步实现；
- `mise exec -- uv sync --locked` 会严格按 `uv.lock` 同步环境；任何锁定依赖不一致都会直接失败。

Windows PowerShell 使用 `.venv\\Scripts\\python.exe`。

## 运行

```bash
mise exec -- uv run --locked service/akashi_list/akashi_list_spider.py

# 与 GitHub Actions 相同的严格数据包构建入口
mise exec -- uv run --locked python -m service.data_package.cli build --strict
```

可选环境变量：

- `DEBUG=1`：输出调试日志；
- `CACHE_ONLY=1`：只读取本地缓存，不访问网络；
- `VALIDATION_SOURCES=wikiwiki-jp,kcwiki-data`：选择独立验证来源；
- `VALIDATION_SOURCES=`：关闭独立来源采集；
- `VALIDATION_STRICT=1`：独立验证来源抓取或解析失败时终止运行。

严格构建要求正式来源在本次运行中完成网络校验，不会把旧缓存视为新鲜结果。

## 数据

主要数据位置：

```text
dist/data-pipeline/improvement/improvement-list.json
dist/data-pipeline/improvement/improvement-detail.nedb
dist/data-pipeline/start2_data/
dist/data-pipeline/assets/useitem/
dist/data-pipeline/sources/
dist/packages/kancolle-data/
dist/npm/kancolle-data/<version>/
```

`improvement-detail.nedb` 使用 schema 4，包含：

- 改修路线的材料、星期、二号舰和更新目标；
- ★0～★MAX 的 11 行累计效果期望；
- ★0→1 至 ★9→MAX 的 10 个改修动作；
- 独立的 MAX 装备更新槽位；
- 源站没有效果表时的显式 `effectSource.status=unavailable`。

完整字段定义见 `docs/public/DATA-SCHEMA.md` 和 `packages/kancolle-data/schemas/`。

`dist/data-pipeline/sources/` 随稳定分支提供来源归一化结果、差异、冲突和诊断证据。首次启用来源历史时会建立一次完整存量，后续只追加事实增量，并输出不参与正式选举的相对一致性权重。它用于审计，不属于 npm 消费接口。原始网页与 HTTP 缓存不公开。
执行严格数据构建后，终端结果和完整运行日志都会显示当前来源权重与置信度；机器摘要位于 `dist/data-pipeline/local-validation.json`。

## 数据来源

- Akashi List：改修路线、材料、星期、二号舰和更新目标；
- start2：舰船、装备、装备类型和消耗品的 ID/名称映射；
- KcWiki ship/equipment：经 Start2 校验的舰娘初始/改造装备关系，并按输入哈希增量复用；
- KC3 `mst_slotitem_bonus`：特殊装备加成；
- WikiWiki 装备详情：任务等补充来源证据；
- `kcwikizh/kcQuests`：以顶层数字 key 提供 canonical `questKey`；
- canonical `improvement/detail.nedb`：直接反向投影升级来源。

项目不进行跨来源多数投票。验证来源只报告差异，不会自动覆盖正式结果。来源名称与 Start2 不一致时，只允许使用经人工确认、按来源隔离的语义别名字典；严格流程会重新核对目标 ID，并拒绝任何未解析项。

## 技术文档

公开技术文档位于 [`docs/public/`](docs/public/README.md)，包括：

- 产品架构与模块职责；
- 数据生命周期与发布面；
- 数据包结构与兼容边界；
- 来源权威和差异仲裁；
- generated state 与来源诊断数据。

当前版本的用户可见摘要见 [`RELEASE-NOTES.md`](RELEASE-NOTES.md)。内部维护、更新和发布治理文档不会进入公开稳定分支。

## 自动数据更新

公开自动化拆分为三个职责：`source-acquire.yml` 只采集并冻结 Source Bundle；`data-build.yml` 消费冻结来源，完成离线计算、验证和不可变 Candidate，并在消费数据变化时自动发布 `latest`、`improvement2` 和 `online`；`release.yml` 只用于从既有冻结 Candidate 补偿或对账发布。版本规划前会读取 npm 最高正式版本的 `RELEASES.json`，用消费者 `contentDigest` 判定该数据是否已发布；相同 digest 不得再次分配 patch，若 npm 已发布而 `online` 未对齐，只能使用原 Candidate 补偿。下载与计算仍不共享执行阶段，发布只消费已经验证并上传的 Candidate。

自动化不会提交或改写公开 `main`。`main` 只保存稳定代码、公共自动化和数据契约，`online` 只保存最新 generated-state。Data Build 仅在冻结 Candidate 的发布计划要求发布时使用写权限和 `NPM_TOKEN`；手动 Release 保留同等权限用于补偿。

## 全量装备获取来源诊断

该能力使用公开的离线解析入口：

```bash
mise exec -- uv run --locked python -m service.data_package.equipment_acquisition_raw_parse
```

它只读取 `.spider/local/source-cache/` 中已采集的 WikiWiki 原始页面，不进行网络请求，并输出结构化获取方式、未分类证据和问题清单。舰娘证据关联 Start2；任务目录来自 `kcwikizh/kcQuests`，顶层数字 key 是 canonical `questKey`，code 与名称仅用于匹配和诊断。接受后的 `questKey` 会进入统一装备来源投影；严格数据构建会增量获取完整 `quests-scn.json`，随后仅使用本地 Raw Cache 重建 WikiWiki 获取证据。原始证据和问题清单仍保留在 `dist/data-pipeline/sources/wikiwiki-equipment-detail/`。

少数不适合泛化的 Wiki 页面标题、上下文措辞、分类别名、季节活动简称黑名单和非证据说明集中维护在 `configs/wikiwiki-acquisition-replacements.json`。字典只接受人工确认项，并且只作用于分类视图，不改写原始 HTML 或输出 `rawText`；未能安全归类的证据继续进入未分类清单。舰娘引用只解析实际提取出的具体名称，泛化的“初期装备”说明不会被整句登记为未解析舰娘。

Start2 与 Wiki 页面仅存在重音、全半角标点或展示空格差异时，使用 `configs/wikiwiki-page-name-aliases.json` 中经人工确认的定向名称映射。该字典只参与 Start2 名称到 Wiki 作者名称的页面关联，不把 Wiki 图鉴号当作实体 ID，也不做全局模糊匹配。


## WikiWiki 浏览器会话采集

WikiWiki 正式采集器属于公开来源自动化：

```bash
mise exec -- uv run --locked python -m automation.acquire.wikiwiki.crawler catalog --kind all
mise exec -- uv run --locked python -m automation.acquire.wikiwiki.crawler inspect
mise exec -- uv run --locked python -m automation.acquire.wikiwiki.crawler crawl
```

CI 由 `automation.acquire.cli` 调度它并冻结 Source Bundle。配置位于 `configs/wikiwiki-crawler.local.json`，Cookie、浏览器 profile、断点和 receipt 只写 `.spider/local/**`，通过校验的 HTML 写入 `.spider/local/source-cache/**`。

## npm 数据包

`packages/kancolle-data/` 是受 Git 管理的 npm 源码模板与公开 Schema，不包含构建后才生成的 `manifest.json`、数据集和图片，因此不能直接执行 npm 包完整性检查或发布。

严格数据构建生成完整候选到 `dist/packages/kancolle-data/`。本地读取生成候选：

```js
const data = require('./dist/packages/kancolle-data')

console.log(data.improvement.listPath)
console.log(data.improvement.detailPath)
console.log(data.equipment.dropFromPath)
console.log(data.equipment.sourcesPath)
console.log(data.equipment.specialBonusesPath)
console.log(data.assets.useitemPath(71))
```

校验生成候选：

```bash
cd dist/packages/kancolle-data
npm run check
npm pack --dry-run
```

正式 npm 打包与发布使用隔离目录 `dist/npm/kancolle-data/<version>/`，不会修改源码模板或生成候选。包名为 `@sakura2333/kancolle-data`；已发布版本和 dist-tag 以 npm registry 的实际结果为准。

## License

MIT License，详见 `LICENSE`。


## GitHub 数据调度

- Source Acquire 每天在日本时间 03:17 启动；Start2 的刷新周期为 24 小时，普通网络来源为 48 小时，WikiWiki 为 15 天。
- Acquire 会复用最近一次成功 Source Bundle，并在完整采集后写入只绑定 Manifest 的 ready lock；该 lock 不携带可变的来源授权。
- 写入 ready lock 前会验证严格 Build 的固定外部输入闭包，包括 Akashi 首页、WikiWiki 索引、KC3 bonus 与完整 `kcQuests/quests-scn.json`；缺失或只剩 fallback 缓存时 Acquire 直接失败，不生成可消费 Bundle。
- Data Build 每天在日本时间 15:17 启动；若 Acquire 仍在运行，最多等待 5 分钟，随后将本次构建延后到下一天。
- Build 只消费带有效 ready lock 的冻结 Source Bundle，不重新联网采集。
- GitHub Artifact 上传显式保留隐藏运行态目录，Source Bundle 的 `.spider/**` 与 Build Candidate 的 `.generated-state/**` 不会在传输阶段被过滤。
