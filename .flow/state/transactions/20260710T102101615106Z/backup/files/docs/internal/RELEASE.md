# Spider Stable 发布

Stable 是 Spider 项目命令，不属于 Infra 基础能力。公开 main 的候选协作是低频、项目特有、必须人工介入的流程。

## 职责边界

- `./flow stable`：读取门禁并提示下一步；不创建临时分支、不调用 AI、不合并或推送 main。
- `script/project/main_release.py`：机械准备临时公共候选分支、接受 AI 审核凭证、输出对账事实。
- AI：只审核已经机械净化的 `public-candidate/*` 分支，修正文档与公开结构并生成审核报告。
- 人：查看最终 Diff、确认并合并 main、完成 npm 浏览器认证。
- `./flow stable --confirm`：只消费精确绑定的 OPEN 门禁，核对 main 与 npm，成功后关闭门禁并归档 Receipt。

## 人工发布顺序

```bash
./flow check --profile full
git push origin dev
python3 script/project/main_release.py prepare --confirm
```

`prepare` 要求 project-owned 代码已经提交并推送，但允许当前工作区保留 generated-state 与 local-preserved 变化。它复用完整检查，再运行发布专用 `release` Profile，从当前 generated-state 快照按公开白名单生成候选，并从远端 main 创建和推送：

```text
public-candidate/<version>-<dev-short-sha>-<generated-state-short-sha>
```

机械 Preview 会把 `sourceCommit`、Git tree、Stable 配置摘要、generated-state SHA-256 与最终 Candidate SHA-256 同时写入 Manifest。未跟踪但属于 generated-state 的新文件也会进入候选；Raw Cache、日志与 `.flow/state` 只允许存在，不进入公开树。若 project-owned 文件未提交则直接阻断。

它同时输出 `.flow/state/stable/<release-id>/ai-review-template.json`。AI 在临时分支完成语义净化并提交后，把模板中的 `candidateCommit` 对齐远端最终 Commit，形成审核报告，然后执行：

```bash
python3 script/project/main_release.py approve \
  --review-report /path/to/ai-review.json
```

`approve` 会重新校验公共清单、编译公开 Python 源码，并从 AI 最终 Commit 重新冻结 current/latest 与 improvement2 两个 npm tarball。通过后门禁只绑定该精确 Commit、Candidate 哈希、Candidate Manifest 哈希与审核报告哈希。

随后人工审核最终 Diff 并合并 main：

```bash
./flow stable
./flow stable --confirm
```

main 尚未合并时，Flow 只提示合并；main 内容与审核候选一致后，Flow 输出冻结 tarball 的精确 npm 发布命令。完成 npm 认证发布后再次执行 `./flow stable --confirm`，对账通过即归档 Receipt 并关闭门禁。

## 漂移与对账

审核后临时分支、Candidate Manifest 或审核报告发生变化，门禁自动转为 STALE。状态不同步时运行：

```bash
python3 script/project/main_release.py reconcile --mark-stale --json
```

该命令只收集本地 Gate、Preview、临时分支、远端 main 等事实，不猜测成功状态。AI 可以据此修复或重建 generated-state，但不得绕过 Git 内容、npm tarball、dist-tag 与 Receipt 校验。

## main 内容同步

首次发布只对配置中明确授权的 legacy tree 做一次完整内容替换；之后由 `STABLE-CONTENT-MANIFEST.json` 进行增量管理。该过程不重写历史，也不删除 Actions、Tag、Artifact、Cache、Secret 或 Variable。

## npm 双制品

同一个 AI 审核后的 canonical Candidate 冻结：

- current 版本，目标 dist-tag 为 `latest`；
- schema-3 白名单 VO 版本，目标 dist-tag 为 `improvement2`，并继续使用普通 `improvement/*` 路径。

npm 浏览器认证仍由用户手动完成；Flow 只按冻结 tarball 哈希与 dist-tag 对账。
