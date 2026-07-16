# 文档地图

## 0. 项目硬约束

- `SPIDER-HARD-RULES.md`
- `SPIDER-AUTHORITY-MAP.md`

## 1. 当前分层与职责

- `ARCHITECTURE.md`：L1 Flow、L2 Adapter、L3 Project Tool、L4 Business/Data 的单向依赖。
- `FLOW-ADAPTER.md`：公共 Flow 接口到项目工程工具的静态适配边界。
- `PROJECT-TOOLS.md`：质量、运行、Git、Stable、npm 等项目工具职责。
- `FLOW-LOGIC-INVENTORY.md`：哪些逻辑允许属于 Flow，哪些必须留在项目或业务域。
- `tools/AGENTS.md` 与各工具的 `ARCHITECTURE-GUARD.md`：外部手动工具的 AI 阅读、依赖和执行隔离边界。

## 2. Flow 自有事务

- `UPDATE-TRANSACTION.md`：更新包校验、Staging、切换、回滚与身份对账。
- `RECOVERY-PACKAGE.md`：恢复包格式和恢复边界。

## 3. 项目发布

- `RELEASE.md`：项目发布入口、代码状态和数据发布边界。

## 4. 公开技术文档

- `docs/public/**`
- `docs/public/DATA-SCHEMA.md`

代码目录中的 `README.md` 只说明本目录边界。旧九层控制面文档已退出正式文档图，不再作为运行时或治理事实源。
