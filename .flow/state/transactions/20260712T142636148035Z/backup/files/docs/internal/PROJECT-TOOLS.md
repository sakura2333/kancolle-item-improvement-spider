- Python 与 uv 版本由根目录 `mise.toml` 统一管理；uv 不得自行下载 Python。
# 项目工程工具

项目工程工具位于 `script/project/`，负责实际编排：

- `python script/project/cli.py check --profile quick|full`
- `python script/project/cli.py verify-candidate --json`
- `python script/project/cli.py identity --json`
- `cd packages/kancolle-data && npm run check`
- `cd packages/kancolle-data && npm pack --dry-run`
- `mise exec -- uv run --locked script/project/equipment_acquisition.py`（只读取 `.spider/local/source-cache` 的离线装备获取方式诊断；关联 Start2 shipId 与 `kcQuests` 数字 `questKey`，并打印异常摘要）
- `configs/wikiwiki-acquisition-replacements.json`（人工接受的 WikiWiki 特殊解析字典；困难样本优先加精确字典项，季节活动简称黑名单只作用于分类视图，不扩张通用正则、不改写原始证据；舰娘引用只处理具体名称）

`./flow check/run/push/stable` 只是项目能力的公共包装。Flow 不暴露项目内部阶段命令。

npm 双制品由公开 `automation/release/**` 管理：Data Build 在冻结 Candidate 验证通过且发布计划为真时自动把 canonical 版本发布到 `latest`、schema-3 兼容版本发布到 `improvement2`，并更新 `online`；`release.yml` 只对既有 Candidate 做补偿或对账。Stable main 发布不构建、发布或对账 npm。

公开 main 的临时分支与 AI 审核是低频人工协作，不属于 Flow 协议。正式发布前如需先测试公开代码，执行 `uv run --locked python script/project/main_release.py prepare-beta --confirm`：它会推送唯一且不可覆盖的 `public-beta/<releaseId>` 完整公开快照，不修改 VERSION、main、npm 或 online，也不读取 Stable Migration ID。`uv run --locked python script/project/main_release.py prepare --confirm` 要求 project-owned 代码已提交并 push；generated-state 与 local-preserved 可以变化，但不会进入候选或参与候选身份。AI 完成净化后使用 `approve --review-report ...` 打开一次性门禁。`./flow stable --confirm` 只对账 main 公共代码并关闭门禁。

公开 `main` 不发布 Raw Cache 或 generated-state。Source Acquire Action 把已验证来源冻结为 Source Bundle；Data Build Action 从该 Bundle 恢复 `.spider/local/source-cache` 并严格重建 WikiWiki 装备获取快照。Raw Cache 存在但解析失败时不得回退旧快照。

`push` 只暂存 `project-owned` 路径。运行 Spider 后产生的 generated-state 留在本地或进入独立数据发布流程，不和代码提交混合。

`flow update` 与 `flow rollback` 在内容身份和候选门禁通过后自动提交 project-owned 变化；不会提交 generated-state，也不会自动 push。上一版更新若已经完整应用但尚未提交，只要当前 project-owned 内容身份与下一包基线完全一致，可以直接继续更新并由新提交统一收口。


## 外部手动工具

`tools/**` 只保留一次性迁移和维护脚本，不进入公开 main。正式 WikiWiki 浏览器采集器已经归入 `automation/acquire/wikiwiki/**`，由公开 Source Acquire Action 和本地 `./flow wikiwiki` 包装入口共同调用。Cookie、断点、浏览器状态和日志固定写入 `.spider/local/**`，通过校验的 HTML 写入 `.spider/local/source-cache/**`。

## 质量 Profile 边界

- `quick`：静态检查与开发回归测试，不执行公开发布策略测试。
- `full`：完整离线回归与制品验证，不执行公开发布策略测试。
- `release`：内部发布专用 Profile，仅匹配 `release_test*.py`，不通过公共 `flow check` 暴露。
- Stable Preview 在完整检查通过后强制执行 `release`；发布内容检查失败时不得生成有效候选。
