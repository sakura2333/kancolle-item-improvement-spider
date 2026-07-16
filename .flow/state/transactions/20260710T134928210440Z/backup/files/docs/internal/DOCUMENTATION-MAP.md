# 文档地图

## 0. 双入口

- `README.md`：公开用户入口，只能引用 Public Snapshot 中真实存在的内容。
- `AGENTS.md`：dev 内部 AI 入口，不进入 Beta 或 Stable。

## 1. AI 内部知识面

- `docs/internal/ai/HARD-RULES.md`：长期不可违反约束。
- `docs/internal/ai/AUTHORITY-MAP.md`：事实与权威来源。
- `docs/internal/ai/START.md`：AI 冷启动和任务路由。
- `docs/internal/ARCHITECTURE.md`：内部层次和依赖方向。
- `docs/internal/FLOW-ADAPTER.md`：Flow 到项目工具的适配边界。
- `docs/internal/PROJECT-TOOLS.md`：质量、运行、Git 和发布工具职责。
- `docs/internal/FLOW-LOGIC-INVENTORY.md`：Flow 与项目逻辑边界。
- `tools/AGENTS.md`：一次性迁移和外部维护工具阅读边界。

## 2. Public Snapshot 权威

- `release/public-content.json`：Beta 与 Stable 共用的唯一白名单内容声明。
- `script/project/stable_command.py`：从白名单构造不可变 Public Snapshot。
- `script/project/public_content_audit.py`：内部入口、引用和正文机械门禁。
- `script/project/main_boundary.py`：Workflow 与 Python import 闭包。

## 3. Flow 自有事务

- `docs/internal/UPDATE-TRANSACTION.md`：更新包校验、Staging、切换和回滚。
- `docs/internal/RECOVERY-PACKAGE.md`：恢复包格式与恢复边界。
- `docs/internal/RELEASE.md`：Beta、Stable、AI 兜底审阅和数据发布边界。

## 4. 公开技术文档

- `docs/public/**`
- `packages/kancolle-data/schemas/**`

公开文件不得反向引用 `AGENTS.md`、`docs/internal/**`、`script/**` 或 Flow 控制面。内部文档可以引用公开契约。
