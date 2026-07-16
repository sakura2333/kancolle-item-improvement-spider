- Python 与 uv 版本由根目录 `mise.toml` 统一管理；uv 不得自行下载 Python。
# 项目工程工具

项目工程工具位于 `script/project/`，负责实际编排：

- `python script/project/cli.py check --profile quick|full`
- `python script/project/cli.py verify-candidate --json`
- `python script/project/cli.py identity --json`
- `python script/project/package.py --output-dir dist/npm`
- `cd packages/kancolle-data && npm run check`
- `cd packages/kancolle-data && npm pack --dry-run`
- `mise exec -- uv run --locked script/project/equipment_acquisition.py`（只读取 `.flow/local/source-cache` 的离线装备获取方式诊断；关联 Start2 shipId 与 `kcQuests` 数字 `questKey`，并打印异常摘要）
- `configs/wikiwiki-acquisition-replacements.json`（人工接受的 WikiWiki 特殊解析字典；困难样本优先加精确字典项，季节活动简称黑名单只作用于分类视图，不扩张通用正则、不改写原始证据；舰娘引用只处理具体名称）

`./flow check/run/push/stable` 只是项目能力的公共包装。Flow 不暴露项目内部阶段命令。

`stable` 的 Spider 自定义发布逻辑还会冻结 current/latest 与 `poi-plugin-item-improvement2`/`improvement2` 两个 npm 版本。旧版 VO 只映射原 schema-3 字段，兼容制品使用普通路径；该逻辑留在 `script/project/`，不得上移到 Flow 公约。

公开 main 的临时分支与 AI 审核是低频人工协作，不属于 Flow 协议。`python3 script/project/main_release.py prepare --confirm` 要求 project-owned 代码已提交并 push，但允许 generated-state 与 local-preserved 保持脏状态；它会冻结当前 generated-state 哈希，并把已跟踪和未跟踪的公开生成文件一起推送到机械候选分支。AI 完成净化后使用 `approve --review-report ...` 打开一次性门禁。`./flow stable` 只读取门禁并提示步骤，`./flow stable --confirm` 只做 main/npm 对账和发布收口。

公开 `main` 不发布 Raw Cache。严格构建只有在 `.flow/local/source-cache/_meta.json` 存在时才重建 WikiWiki 装备获取快照；干净公开 checkout 会先校验 `dist/data-pipeline/sources/wikiwiki-equipment-detail/` 的完整性再复用。Raw Cache 存在但解析失败时不得回退旧快照。

`push` 只暂存 `project-owned` 路径。运行 Spider 后产生的 generated-state 留在本地或进入独立数据发布流程，不和代码提交混合。

`flow update` 与 `flow rollback` 在内容身份和候选门禁通过后自动提交 project-owned 变化；不会提交 generated-state，也不会自动 push。上一版更新若已经完整应用但尚未提交，只要当前 project-owned 内容身份与下一包基线完全一致，可以直接继续更新并由新提交统一收口。


## 外部手动工具

`tools/**` 不属于项目工程工具层。它可以读取导出数据或通过子进程调用本页列出的稳定入口，但项目工程工具和业务代码不得反向依赖它。WikiWiki 浏览器会话采集器见 `tools/wikiwiki-crawler/README.md`。它先从 Wiki 卡片列表构建名称到精确 URL 的本机目录，再按 Start2 名称做精确或保守归一化关联；不得把 Wiki 图鉴号当作实体 ID，也不得从 Start2 名称直接猜 URL。Cookie、断点、派生目录和日志固定写入 `.flow/local/**`，通过校验的 HTML 写入 local-preserved 的 `.flow/local/source-cache/**`。

## 质量 Profile 边界

- `quick`：静态检查与开发回归测试，不执行公开发布策略测试。
- `full`：完整离线回归与制品验证，不执行公开发布策略测试。
- `release`：内部发布专用 Profile，仅匹配 `release_test*.py`，不通过公共 `flow check` 暴露。
- Stable Preview 在完整检查通过后强制执行 `release`；发布内容检查失败时不得生成有效候选。
