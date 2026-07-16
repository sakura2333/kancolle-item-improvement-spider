# Public Snapshot 隔离与例外治理

公开性是源代码与发布声明的固有属性，不由发布后的人工删除或 AI 猜测获得。

## 双平面

- `AGENTS.md` 是 dev 根目录唯一 AI 入口。
- `docs/internal/**`、`script/**`、`tests/**`、`tools/**`、`release/**` 与 `.flow/**` 属于内部控制面。
- `README.md`、`docs/public/**` 与公开 Runtime 只描述 Public Snapshot 中真实存在的能力。
- 内部可以引用公开契约；公开内容不得反向引用内部路径或命令。

## 状态命名空间

- `.flow/**`：更新、检查、候选、门禁和回滚等内部 Flow 状态。
- `.spider/local/**`：公开 Spider 的本机来源缓存、Receipt、浏览器状态与业务日志。
- `dist/**`：可重建输出。

旧 `.flow/local/**` 在首次项目命令执行前迁移到 `.spider/local/**`。`.flow/local.json` 是 Flow 本机配置，不参与迁移。迁移先完成冲突预检；任何目标内容冲突都会停止，旧数据不会被删除或覆盖。

## Public Snapshot 唯一权威

`release/public-content.json` 是 Beta 与 Stable 共用的唯一白名单。候选构建器只复制白名单命中的文件，再生成公共 `.gitignore`、`RELEASE-NOTES.md` 与 `PUBLIC-CONTENT-MANIFEST.json`。禁止先复制完整仓库再删除内部文件。

Beta 与 Stable 共享同一 Candidate 目录和内容哈希。渠道差异只存在于分支、门禁和发布状态，不存在于文件边界。

## 例外清单

`release/public-exceptions.json` 只登记客观无法隔离、且属于公共功能契约的最小语义。每项例外必须绑定：

- 唯一 ID、owner、reason、review 方式和可选失效时间；
- 精确文件路径、精确字面量和精确出现次数；
- 禁止同时出现的相邻内部内容；
- 需要 AI 语义复核的精确文件。

例外清单不是 grep 忽略表。未登记位置、次数漂移、文件缺失、禁止邻接内容或过期例外都会阻断候选。

当前允许的例外只有：公开 GitHub Workflow 需要声明的 `NPM_TOKEN` Secret 名称，以及公开来源验证能力自身的 AI 数据审计 Prompt。Secret 值、内部发布门禁、Migration ID、Flow 路径和本机路径永远不属于例外。

## 机械门禁

Public Snapshot 生成时必须机械验证：

1. 内部路径为零；
2. `.flow/`、内部命令、本机绝对路径和控制面词条引用为零；
3. 所有公开 `python -m` 入口真实存在；
4. Markdown 引用的公开路径真实存在；
5. 所有例外与清单精确一致；
6. 公共 checkout 生成 `.venv`、`.spider/local`、`dist`、本机配置和缓存后，Git 工作树仍干净；
7. Candidate 文件集、Manifest、内容哈希和归档哈希一致。

AI 只复核机械规则难以判断的语义：公开说明是否误导、例外是否合理、公开功能是否借机携带内部治理意图。

## 哈希和 Receipt

- `candidateContentSha256`：按公开文件路径与逐文件 SHA-256 计算的内容身份。
- `candidateArchiveSha256`：确定性 `candidate.zip` 的归档身份。
- `publicIsolation.exceptionManifestSha256`：例外清单身份。

Beta Receipt、Stable Candidate Manifest 与最终 Stable Receipt 都必须保留上述身份和 `publicIsolation` 结果。AI Review Bundle 只使用相对文件名，不得包含工作区、下载目录、用户名或本机绝对路径。
