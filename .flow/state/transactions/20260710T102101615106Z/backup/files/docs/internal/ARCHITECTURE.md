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

负责质量检查、默认本机运行、代码 push、Stable 投影和 npm 构建。CI 可以直接调用这些原生工具，不需要把每个内部动作注册成 Flow 命令。

### L4 业务与数据层

负责抓取、解析、语义校验、来源历史、权重计算和数据包生成。业务层不依赖 Flow；生成数据由自己的状态与发布工具治理。

## 状态边界

- `project-owned`：源码、配置、测试、工程工具和正式文档；进入代码 Update 与 `push`。
- `generated-state`：`configs/generated-state.json` 声明的生成数据；不进入代码 Update identity，不由 `push` 暂存。
- `local-preserved`：本机配置、缓存、日志、虚拟环境和 Flow 状态；任何 Update 都不得覆盖。

代码更新身份升级为 `flow-content-sha256`，兼容旧 `project-owned-sha256`。`.flow/baseline.json` 是 Flow authority state，可以随代码提交保存，但不参与 contentHash 计算；Git commit 只作为落地与审计结果，不作为 update 判定依据。来源快照 Hash、generated-state Manifest、npm integrity 和 Artifact SHA 仍由各自数据或发布工具维护，它们不是代码 Update Hash。


## 外部手动工具域（不属于 L1-L4）

`tools/**` 不构成第五层，也不进入 `Flow → Adapter → Project Tool → Business/Data` 依赖链。它只保存可手动运行的离线或外部采集工具。

```text
External Tooling
    ──read exported data──> Business/Data exports
    ──subprocess──────────> documented project entry

Core L1-L4 ──X──> tools/**
```

边界由根 `AGENTS.md`、`tools/AGENTS.md`、工具目录的 `ARCHITECTURE-GUARD.md` 与 `FLOW-EXCLUSION.manifest.json` 共同声明。Flow、CI、npm 和默认质量入口不得执行该目录；更新包仅可把它作为静态源码分发。所有凭据与采集状态写入 `.flow/local/**`。
