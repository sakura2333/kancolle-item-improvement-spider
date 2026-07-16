# Spider 分层架构

```text
L1 Flow 公共接口层
    `flow` / `flow.cmd`
    `script/flow/`

        ↓ 只传递公共命令、参数和机器结果

L2 项目适配层
    `script/flow_adapter.py`

        ↓ 只映射到一个项目工程工具入口

L3 项目工程工具层
    `script/project/`
    `packages/kancolle-data/package.json`

        ↓ 调用领域能力

L4 业务与数据层
    `service/`
    `util/`
    `configs/`
    `packages/kancolle-data/`
```

## 单向依赖

```text
Flow → Adapter → Project Tool → Business/Data
```

业务代码不得 import `script.flow` 或 `script.project`。项目工程工具不解释 Flow 公共协议；Flow 不解释 Spider 来源、测试步骤、npm 内容或数据权重。

## 各层职责

### L1 Flow 公共接口层

只实现 `flow.public 1.1.0` 的固定命令、公共参数、机器结果、Update Transaction 与 Recovery Package。它不知道项目内部的测试组合、Spider 来源或 npm 包结构。

### L2 项目适配层

`script/flow_adapter.py` 只声明能力并把公共命令映射到 `script/project/cli.py`。它不保存质量步骤、Git 发布逻辑或业务规则。

### L3 项目工程工具层

负责质量检查、默认本机运行、代码 push 和 Stable main 候选治理。公开 CI 不依赖这一层；来源采集、数据计算和 npm/online 发布统一由 `automation/**` 提供稳定入口。

### L4 业务与数据层

负责抓取、解析、语义校验、来源历史、权重计算和数据包生成。业务层不依赖 Flow；生成数据由自己的状态与发布工具治理。

## 状态边界

- `project-owned`：源码、配置、测试、工程工具和正式文档；进入代码 Update 与 `push`。
- `generated-state`：`configs/generated-state.json` 声明的生成数据；不进入代码 Update identity，不由 `push` 暂存。
- `local-preserved`：本机配置、缓存、日志、虚拟环境和 Flow 状态；任何 Update 都不得覆盖。

代码更新身份升级为 `flow-content-sha256`，兼容旧 `project-owned-sha256`。`.flow/baseline.json` 是 Flow authority state，可以随代码提交保存，但不参与 contentHash 计算；Git commit 只作为落地与审计结果，不作为 update 判定依据。来源快照 Hash、generated-state Manifest、npm integrity 和 Artifact SHA 仍由各自数据或发布工具维护，它们不是代码 Update Hash。


## 外部手动工具域（不属于 L1-L4）

`automation/**` 是公开 main 的自动化能力层，分为来源采集、冻结计算和发布；它可以依赖业务层，但不得依赖 `script/**`、`tests/**` 或 `tools/**`。`tools/**` 不构成运行层，只保存一次性迁移和维护脚本。

```text
External Tooling
    ──read exported data──> Business/Data exports
    ──subprocess──────────> documented project entry

Core L1-L4 ──X──> tools/**
```

公开 main 边界由 `release/main-content.json` 唯一声明，Stable、候选校验和发布门禁共同读取。GitHub Actions 只调用 `automation/**`；Flow 与 `script/**` 只存在于 dev。所有凭据与采集状态写入 `.flow/local/**`。
