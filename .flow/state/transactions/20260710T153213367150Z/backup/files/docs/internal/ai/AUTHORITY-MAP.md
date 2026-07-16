# Spider 权威地图

| 问题 | 最终权威 |
|---|---|
| 用户当前意图与不可逆确认 | 用户当前明确输入 |
| 长期硬约束 | `docs/internal/ai/HARD-RULES.md` |
| 当前 Commit、Tree、分支、工作区 | 实时 Git |
| 当前项目版本 | `VERSION` |
| 基础能力与命令契约 | `.flow/project.json` |
| 本机路径和远端覆盖 | `.flow/local.json` |
| 当前正式人类入口 | `./flow list` 的人类命令区 |
| 当前检查结果 | `./flow check` 与 `.flow/state/checks/**` |
| 更新候选是否合法 | `update.transaction` 对 Manifest 与哈希的检查 |
| Stable 候选内容 | `.flow/state/public-candidates/**/candidate-manifest.json` |
| 公开数据字段 | `packages/kancolle-data/schemas/**` 与数据包 Manifest |
| 来源长期相对表现 | `dist/data-pipeline/sources/history/**` 与 `dist/data-pipeline/sources/reliability/**`，仅作诊断，不改变来源权威 |
| 统一装备来源 | `packages/kancolle-data/equipment/sources.nedb`；`shipIds` 只来自经 Start2 校验的 KcWiki `_api_id`，`upgradeFromItemIds` 直接反向投影 canonical `improvement/detail.nedb`，`questKey` 使用 `kcwikizh/kcQuests` 顶层数字 key |
| WikiWiki 装备获取证据 | 原始证据为 `.spider/local/source-cache/**` 中带 `acquisition_source=external-browser-session-crawl` 的记录，离线解析结果为 `dist/data-pipeline/sources/wikiwiki-equipment-detail/**`；任务 code/名称只用于匹配与诊断，接受后的数字 `questKey` 可进入统一装备来源；同名舰明确形态可直接映射，裸名称必须由独立登记的 WikiWiki canonical 链接目标与 Start2 候选交叉验证 |
| 无法自动恢复的停止信息 | 终端红色 `ERROR`、非零退出码、机器可读 `stopReason`、人工处理方法和可继续断点 |
| 某次执行发生了什么 | `.flow/state/executions/**` 的简要证据 |
| 历史原因 | Git 历史、Changelog、恢复包 |

旧对话、旧 ZIP 名称、旧 `.devops` 文档和历史状态不能覆盖实时 Git、`VERSION` 和 `.flow/project.json`。
