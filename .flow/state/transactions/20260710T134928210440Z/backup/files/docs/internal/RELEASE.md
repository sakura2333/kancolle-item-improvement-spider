# Spider 公开 main 发布

公开 main 发布是低频、项目特有的代码发布流程。它与数据下载、数据计算、npm 发布和 `online` generated-state 发布完全独立。

## 职责边界

- `./flow stable`：读取 main 发布门禁并提示下一步；不创建分支、不调用 AI、不合并或推送 main。
- `script/project/main_release.py`：机械生成公共代码候选、接收 AI 审核报告并打开一次性门禁。
- AI：只对机械 Public Snapshot 做最终语义兜底；文件选择、引用闭包和内部隔离由门禁负责。
- 人：查看最终 Diff 并将审核后的 `public-candidate/*` 合并到 main。
- `./flow stable --confirm`：核对 main 与审核候选的管理文件，写 Receipt 并关闭门禁。
- `.github/workflows/source-acquire.yml`：独立采集并冻结 Source Bundle。
- `.github/workflows/data-build.yml`：独立消费 Source Bundle，计算、验证并冻结 Candidate Bundle。
- `.github/workflows/release.yml`：独立消费 Candidate Bundle，发布或对账 npm `latest` / `improvement2`，随后更新 `online`。

## Beta 公开快照

正式版本管理之外的测试通道：

```bash
mise exec -- uv run --locked python script/project/main_release.py prepare-beta --confirm
```

该命令直接消费与 Stable 完全相同的机械 Public Snapshot，推送唯一 `public-beta/<releaseId>` 分支并写 `beta-receipt.json`。它不会修改 `VERSION`、`main`、npm dist-tag 或 `online`，也不会修改 main、版本或发布状态。测试必须绑定输出的 branch、commit、tree 与 candidateSha256。

## main 发布顺序

```bash
./flow check --profile full
git push origin dev
uv run --locked python script/project/main_release.py prepare --confirm
```

`prepare` 要求 project-owned 代码已经提交并推送。generated-state 与 local-preserved 可以存在或变化，但不会进入 main Candidate，也不会绑定 Candidate 身份。候选名称只绑定版本和 dev Commit：

```text
public-candidate/<version>-<dev-short-sha>
```

机械 Preview 会记录 `sourceCommit`、Git tree、public-content 配置摘要和 Candidate SHA-256，并生成 AI 审核模板。AI 在临时分支完成公开结构与文档净化后提交，再执行：

```bash
uv run --locked python script/project/main_release.py approve \
  --review-report /path/to/ai-review.json
```

`approve` 重新校验公共清单、Action 依赖闭包和公开 Python import 闭包，并将门禁绑定到精确候选 Commit、tree、Candidate hash、Manifest hash 与审核报告 hash。它不构建 npm，不读取 generated-state。

人工合并后执行：

```bash
./flow stable --confirm
```

Flow 逐文件确认 main 与审核候选一致后归档代码发布 Receipt，并关闭门禁。数据是否需要发布由独立 Action 决定，不阻塞 main 代码发布。

## 漂移与对账

候选分支、Candidate Manifest 或审核报告变化时，门禁自动失效。状态不同步时执行：

```bash
uv run --locked python script/project/main_release.py reconcile --mark-stale --json
```

该命令只收集 Gate、Preview、候选分支和远端 main 事实，不猜测成功状态，也不读取 npm 或 online 发布状态。

## main 内容同步

`release/public-content.json` 是 Beta 与 Stable 共用的唯一 Public Snapshot 声明。构建器只从白名单复制文件；`PUBLIC-CONTENT-MANIFEST.json` 只记录公开文件集合，不携带内部 Migration ID。首次迁移和 legacy 清单兼容策略只留在 dev 控制面。`dist/**`、`.flow/**`、`script/**`、`tests/**`、`tools/**` 和本机状态不会进入 main。

## 数据发布

数据发布不经过 Stable 门禁：

```text
source-acquire.yml
  → immutable Source Bundle

data-build.yml
  → deterministic calculation + validation
  → immutable Candidate Bundle

release.yml
  → verify exact Candidate
  → publish/reconcile latest + improvement2
  → publish online generated-state
```

发布失败可对同一 Candidate Bundle 重试；npm 对账是幂等的，计算阶段不会重新运行。
