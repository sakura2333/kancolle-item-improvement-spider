# 项目内容与发布生命周期模型

Git 只保存和标识项目状态，不决定文件是什么，也不决定文件是否公开。项目通过 `release/public-content.json` 管理内容归属，通过 Release Transaction 管理发布过程产生的动态内容。

## 静态内容归属

每个受管内容都必须归入一个项目域：

- `categories.*`：公开代码、公开自动化、公开包模板和公开文档；Beta 与 Stable 可以选择。
- `privateCategories.internalControlPlane`：Flow、项目工程工具、测试、维护工具与发布策略。
- `privateCategories.internalDocumentation`：`AGENTS.md` 与 `docs/internal/**`。
- `privateCategories.localRuntimeState`：本机配置、缓存和 Runtime 状态。
- `privateCategories.releaseTransactionState`：发布事务、审核门禁和结果状态。
- `privateCategories.generatedOutput`：可重建的数据与制品输出。
- `privateCategories.machineWorkspace`：虚拟环境、IDE、缓存和字节码。

顶级入口由 `topLevelManaged` 与 `topLevelExternal` 显式登记。新增顶级位置或受管文件没有归属时，候选构建直接失败。

广义公开目录允许稳定例外。例如 `configs/**` 默认属于公开 Runtime，但 `configs/*.local.*` 由 `localRuntimeState` 覆盖。覆盖顺序由 `privateOverrides` 显式声明，不依赖 Git tracked、untracked 或 ignored 状态。

## Release Transaction

每个 `releaseId` 只对应一个事务：

```text
.flow/state/release-transactions/<releaseId>/
├── workspace/   # 内部可变构建区；冻结后删除
├── internal/    # 完整策略、诊断、Diff 和审计证据
├── candidate/
│   ├── public/  # 不可变 Public Snapshot
│   ├── candidate.zip
│   └── manifest.json
├── review/      # 固定 Schema、按渠道隔离的审阅投影
├── result/      # Beta、审批和 Stable Receipt
└── status.json  # 显式生命周期状态
```

生命周期为：

```text
building
  → candidate-frozen
  → beta-prepared / stable-review-prepared
  → stable-approved
  → stable-published
```

`candidate-frozen` 之后，任何渠道都不得修改 `candidate/public`、`candidate.zip` 或 `candidate/manifest.json`。AI 或人工发现问题时，只能修改 dev 源内容并生成新的 `releaseId`。

## 审阅投影

AI Review Bundle 不是内部 Receipt 的清洗副本。它从冻结候选和事务事实按固定字段重新生成，只包含：

- 候选与渠道身份；
- Public 文件清单；
- Public Isolation 摘要；
- 稳定例外清单；
- `PUBLIC-CONTENT-MANIFEST.json`；
- 精确 `candidate.zip`；
- 审阅文件自身的哈希清单。

内部审计策略、本机路径、完整 Flow 状态和内部 Receipt 不进入审阅投影。规则文本可以存在于内部审计或公开例外清单中，不再通过“用禁词扫描禁词规则本身”的方式判断泄漏。

## Beta 与 Stable

Beta 和 Stable 消费同一个冻结 Candidate：

- Beta 分支是 Candidate 的精确公开树；
- Stable 审核分支也是同一 Candidate 的精确公开树；
- 审核分支不得接受后续清理 Commit；
- main 发布时要求 main tree 与审核通过的 Candidate tree 完全一致；
- 渠道差异只写入 `result/**` 和门禁状态，不写回 Candidate Manifest。
