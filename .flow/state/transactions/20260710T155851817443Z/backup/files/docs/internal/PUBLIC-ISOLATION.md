# Public Snapshot 隔离与例外治理

公开性由项目内容注册表定义，不由 Git tracked 状态、发布后的删除或 AI 猜测决定。

## 静态内容注册表

`release/public-content.json` 同时登记：

- 公开内容类别；
- 内部控制面与内部文档；
- 本机 Runtime 状态；
- Release Transaction 状态；
- generated output 与 machine workspace；
- 顶级位置清单和稳定覆盖顺序。

例如 `configs/**` 可以整体属于公开 Runtime，而 `configs/*.local.*` 由 `localRuntimeState` 稳定覆盖。新增顶级位置、未分类文件或非授权归属冲突会阻断候选。

Git 仍用于绑定 `sourceCommit`、`sourceTree` 和分支身份，但不参与内容分类。

## 物理隔离

- `AGENTS.md`、`docs/internal/**`、`script/**`、`tests/**`、`tools/**`、`release/**` 属于内部源内容。
- `.flow/state/release-transactions/**` 保存动态发布事务。
- `.spider/local/**` 保存公开 Runtime 的本机状态。
- `dist/**`、`data/**`、`log/**` 是 generated output。
- Public Snapshot 只从注册为公开的内容构造，再生成公共 `.gitignore`、`RELEASE-NOTES.md` 和 `PUBLIC-CONTENT-MANIFEST.json`。

## 稳定例外

`release/public-exceptions.json` 只登记无法物理隔离且属于公共功能契约的最小语义。每项例外绑定精确路径、字面量、次数、owner、reason、review 方式和禁止邻接内容。

例外是长期内容规则，不是某次发布临时加入的豁免。当前例外仅包括 GitHub Workflow 的 `NPM_TOKEN` Secret 名称，以及来源验证能力自身的 AI 数据审计语义。

## 不可变 Candidate

Release Transaction 先在 `workspace/` 构造候选，经机械检查后一次性冻结到：

```text
candidate/public/
candidate/candidate.zip
candidate/manifest.json
```

Candidate Manifest 同时绑定内容哈希、确定性 Archive 哈希、Public Manifest、例外清单身份和 Public Isolation 结果。冻结后 Beta、Stable 审核、AI Review 和最终发布只能读取它。

## AI Review Projection

`review/beta/beta-ai-review.zip` 通过固定 Schema 从 Candidate 和渠道事实投影生成，不复制内部 Receipt，也不扫描内部禁词规则本身。它包含：

- `review-identity.json`；
- `candidate-inventory.json`；
- `public-isolation-summary.json`；
- `public-exceptions.json`；
- `candidate-files.txt`；
- `PUBLIC-CONTENT-MANIFEST.json`；
- `candidate.zip`；
- `review-manifest.json`。

内部路径、完整审计策略、Flow 配置和渠道 Receipt 在结构上没有进入投影的入口。

## 机械门禁

候选必须满足：

1. 所有受管内容都有唯一项目归属；
2. 内部路径和内部引用为零；
3. 公开 Python 入口与 Markdown 路径引用闭合；
4. 稳定例外精确匹配；
5. 公共 checkout 产生本机状态后 Git 工作树仍干净；
6. Candidate 文件集、Public Manifest、内容哈希与 Archive 哈希一致；
7. Beta 和 Stable 审核分支均为 Candidate 的精确 tree；
8. main tree 与审核通过的 Candidate tree 完全一致。

AI 只负责机械规则难以判断的公开语义，不承担文件选择、脱敏或候选修改。
