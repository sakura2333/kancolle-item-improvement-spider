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

严格构建要求正式来源在本次运行中完成网络校验，不会把旧缓存视为新鲜结果。

## 数据

主要数据位置：

```text
data/improvement/improvement-list.json
data/improvement/improvement-detail.nedb
data/start2_data/
data/assets/useitems/
packages/kancolle-data/
```

`improvement-detail.nedb` 使用 schema 4，包含：

- 改修路线的材料、星期、二号舰和更新目标；
- ★0～★MAX 的 11 行累计效果期望；
- ★0→1 至 ★9→MAX 的 10 个改修动作；
- 独立的 MAX 装备更新槽位；
- 源站没有效果表时的显式 `effectSource.status=unavailable`。

完整字段定义见 `DATA_SCHEMA.md` 和 `packages/kancolle-data/schemas/`。

## 数据来源

- Akashi List：改修路线、材料、星期、二号舰和更新目标；
- start2：舰船、装备、装备类型和消耗品的 ID/名称映射；
- KcWiki ship/equipment：装备获得关系；
- KC3 `mst_slotitem_bonus`：特殊装备加成；
- WikiWiki 与 KcWiki 改修信息：差异验证。

项目不进行跨来源多数投票。验证来源只报告差异，不会自动覆盖正式结果。

## 自动数据更新

仓库的 GitHub Actions 每天运行一次严格 Spider 主流程，也支持手动执行。手动运行默认只完成抓取、质量校验、版本规划和数据包 dry-run，不写入远端；明确启用发布后，生成数据会写入独立的 `online` 分支，并将验证通过的数据包发布到 npm。

自动化不会提交或改写公开 `main`。`main` 继续作为稳定代码和基线数据，`online` 只保存最新生成数据状态。发布运行需要在仓库中配置 `NPM_TOKEN`。

## npm 数据包

数据包位于 `packages/kancolle-data/`：

```js
const data = require('./packages/kancolle-data')

console.log(data.improvement.listPath)
console.log(data.improvement.detailPath)
console.log(data.equipment.dropFromPath)
console.log(data.equipment.specialBonusesPath)
console.log(data.assets.useitemPath(71))
```

校验：

```bash
cd packages/kancolle-data
npm run check
npm pack --dry-run
```

包名为 `@sakura2333/kancolle-data`。已发布版本以 npm registry 的实际结果为准。

## License

MIT License，详见 `LICENSE`。
