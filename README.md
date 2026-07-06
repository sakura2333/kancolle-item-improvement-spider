# kancolle-item-improvement-spider

舰队 Collection 装备改修数据工具。项目从 Akashi List、游戏 start2 主数据和独立社区数据源生成结构化、可追溯的改修与装备数据，并维护可复用的 `@sakura2333/kancolle-data` 数据包。

## 环境

- Python 3.11+
- pip
- Node.js 20+ 与 npm（校验或使用数据包时需要）

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Windows PowerShell 使用 `.venv\\Scripts\\python.exe`。

## 运行

```bash
PYTHONPATH=. .venv/bin/python service/akashi_list/akashi_list_spider.py

# 与 GitHub Actions 相同的严格数据包构建入口
PYTHONPATH=. .venv/bin/python -m service.data_package.cli build --strict
```

可选环境变量：

- `DEBUG=1`：输出调试日志；
- `CACHE_ONLY=1`：只读取本地缓存，不访问网络；
- `VALIDATION_SOURCES=wikiwiki-jp,kcwiki-data`：选择独立验证来源；
- `VALIDATION_SOURCES=`：关闭独立来源采集；
- `VALIDATION_STRICT=1`：独立验证来源抓取或解析失败时终止运行。

严格构建要求网络来源在本次运行中取得有效结果。WikiWiki 装备获取原始页面不随公开仓库发布：维护环境存在原始证据时会重新离线解析；干净的公开 checkout 会严格校验并复用仓库中的已接受获取快照，快照缺失或损坏时构建失败。

## 数据

主要数据位置：

```text
data/improvement/improvement-list.json
data/improvement/improvement-detail.nedb
data/start2_data/
data/assets/useitems/
packages/kancolle-data/
data/sources/
```

`improvement-detail.nedb` 使用 schema 4，包含：

- 改修路线的材料、星期、二号舰和更新目标；
- ★0～★MAX 的 11 行累计效果期望；
- ★0→1 至 ★9→MAX 的逐级改修动作；
- 独立的 MAX 装备更新槽位；
- 源站没有效果表时的显式 `effectSource.status=unavailable`。

完整字段定义见 `DATA_SCHEMA.md` 和 `packages/kancolle-data/schemas/`。

`data/sources/` 随稳定分支只提供来源元数据、正式结构化来源快照和聚合摘要，用于追溯与 clean build，不属于 npm 消费接口。运行期 AI 输入、差异工作集、历史副本、原始网页和 HTTP 缓存不进入公开 `main`。相对一致性摘要位于 `data/sources/reliability/summary.json`，明确标记为 advisory-only，不参与正式数据选举。

## 数据来源

- Akashi List：改修路线、材料、星期、二号舰和更新目标；
- start2：舰船、装备、装备类型和消耗品的 ID/名称映射；
- KcWiki ship/equipment：经 Start2 校验的舰娘初始/改造装备关系；
- KC3 `mst_slotitem_bonus`：特殊装备加成；
- WikiWiki 装备详情：任务等补充来源证据；
- `kcwikizh/kcQuests`：以顶层数字 key 提供 canonical `questKey`；
- canonical `improvement/detail.nedb`：直接反向投影升级来源。

项目不进行跨来源多数投票。验证来源只报告差异，不会自动覆盖正式结果。来源名称与 Start2 不一致时，只允许使用经人工确认、按来源隔离的语义别名字典；严格流程会重新核对目标 ID，并拒绝未解析项。

## WikiWiki 装备获取快照

`data/sources/wikiwiki-equipment-detail/` 保存可公开的结构化获取证据、未分类证据和问题清单。舰娘引用必须与 Start2 候选交叉验证；任务只在完整名称或 code 唯一精确匹配时写入 canonical 数字 `questKey`。

少数不适合泛化的页面标题、上下文措辞、分类别名和非证据说明集中维护在：

- `configs/wikiwiki-acquisition-replacements.json`；
- `configs/wikiwiki-page-name-aliases.json`。

这些字典只接受人工确认项，不改写原始证据，也不使用 Wiki 图鉴号、URL 数字或图片文件名作为游戏实体 ID。公开仓库不包含浏览器 Cookie、抓取断点或原始页面缓存。

## 技术文档

公开文档按长期职责收口：

- [`DATA_SCHEMA.md`](DATA_SCHEMA.md)：数据结构、Schema 与 npm 兼容契约；
- [`docs/public/ARCHITECTURE.md`](docs/public/ARCHITECTURE.md)：模块、数据生命周期和发布面；
- [`docs/public/SOURCE-REFERENCES.md`](docs/public/SOURCE-REFERENCES.md)：来源权威、缓存与仲裁规则；
- [`docs/public/SOURCE-EVIDENCE.md`](docs/public/SOURCE-EVIDENCE.md)：来源证据、结构化快照与公开边界。

正式版本变化以 GitHub Releases 与 Git tags 为准。

## 自动数据更新

仓库的 GitHub Actions 每天运行一次严格 Spider 主流程，也支持手动执行。手动运行默认只完成抓取、质量校验、版本规划和数据包 dry-run，不写入远端；明确启用发布后，生成数据会写入独立的 `online` 分支，并将验证通过的数据包发布到 npm。

自动化不会提交或改写公开 `main`。`main` 保存稳定源码和基线数据，`online` 保存最新生成数据状态。发布运行需要配置 npm 发布凭据。

## npm 数据包

数据包位于 `packages/kancolle-data/`：

```js
const data = require('./packages/kancolle-data')

console.log(data.improvement.listPath)
console.log(data.improvement.detailPath)
console.log(data.equipment.dropFromPath)
console.log(data.equipment.sourcesPath)
console.log(data.equipment.specialBonusesPath)
console.log(data.assets.useitemPath(71))
```

校验：

```bash
cd packages/kancolle-data
npm run check
npm pack --dry-run
```

包名为 `@sakura2333/kancolle-data`。当前协议通过默认发行线提供；旧版 `poi-plugin-item-improvement2` 使用 `improvement2` dist-tag：

```bash
npm install @sakura2333/kancolle-data@improvement2
```

已发布版本以 npm registry 的实际结果为准。

## License

MIT License，详见 `LICENSE`。
