# Spider 公开 main 发布

公开 main 发布是低频、项目特有的代码发布流程。它与数据下载、数据计算、npm 发布和 `online` generated-state 发布完全独立。

## 职责边界

- `release/public-content.json`：项目内容注册表，决定静态内容归属；不依赖 Git tracked/untracked 状态。
- `script/project/stable_command.py`：从注册表构造并冻结唯一 Candidate。
- `script/project/main_release.py`：从冻结 Candidate 生成 Beta、Stable 审核分支和 AI Review Projection。
- AI：只审阅固定投影；发现问题时拒绝候选，不在候选分支上清理。
- 人：审核最终 Diff，并把精确 Stable 审核分支合并到 main。
- `./flow stable --confirm`：要求 main tree 与审核 Candidate tree 完全一致，写 Stable Receipt 并关闭门禁。

## 发布事务

每次发布位于：

```text
.flow/state/release-transactions/<releaseId>/
├── workspace/
├── internal/
├── candidate/{public,candidate.zip,manifest.json}
├── review/
│   ├── beta/          # Beta 审阅投影
│   └── stable/        # Stable 审阅投影
├── result/
└── status.json
```

`workspace` 是可变内部工作区；`internal` 保存完整策略和诊断；`candidate` 在冻结后不可修改；`review` 是固定 Schema 的外部审阅投影；`result` 保存渠道 Receipt。详细模型见 `docs/internal/CONTENT-MODEL.md`。

## Beta

```bash
mise exec -- uv run --locked python script/project/main_release.py prepare-beta --confirm
```

命令推送 `public-beta/<releaseId>` 的精确 Candidate tree，写 `result/beta-receipt.json`，并生成 `review/beta/beta-ai-review.zip`。审阅包不是内部 Receipt 的脱敏副本，只包含白名单投影字段、公开例外、公开文件身份与精确 Candidate Archive。

Beta 不修改 Candidate Manifest、`VERSION`、main、npm 或 `online`。AI 发现问题时应修复 dev 并生成新事务。

## Stable 审核与发布

```bash
./flow check --profile full
git push origin dev
mise exec -- uv run --locked python script/project/main_release.py prepare --confirm
```

`prepare` 推送 `public-candidate/<releaseId>` 的精确 Candidate tree。该分支在冻结后不能增加清理 Commit。审核通过后：

```bash
mise exec -- uv run --locked python script/project/main_release.py approve \
  --review-report /path/to/ai-review.json
```

`approve` 要求远端 Commit、tree、Public Manifest、内容哈希与冻结 Candidate 完全一致，然后打开一次性门禁。人工合并后执行：

```bash
./flow stable --confirm
```

Flow 要求 main tree 与审核 Candidate tree 完全一致；成功后只写 `result/stable-receipt.json` 和事务状态，不修改冻结 Candidate Manifest。

## 漂移与对账

```bash
mise exec -- uv run --locked python script/project/main_release.py reconcile --mark-stale --json
```

该命令只读取事务、门禁和远端分支事实。候选分支或审核报告漂移会让门禁失效，不会自动覆盖或修补候选。

## 数据发布

公开数据由冻结制品驱动：

```text
source-acquire.yml → immutable Source Bundle
data-build.yml     → immutable Candidate Bundle → automatic npm/online publish
release.yml        → manual reconcile of an existing Candidate
```

代码 Candidate 和数据 Candidate 不互相替代，也不共享发布状态。
