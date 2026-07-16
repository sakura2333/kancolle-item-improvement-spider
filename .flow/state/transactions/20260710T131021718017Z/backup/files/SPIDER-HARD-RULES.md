# Spider 硬约束

> 第一设计目标：系统复杂度可以增加，但人的认知负担不能随之增加。

## 1. 稳定协议

人只需要记住 `./flow` 与固定意图命令。AI 可以重构内部实现，但完整行为契约必须保持：命令名称、参数兼容、副作用范围、确认位置、失败语义、回滚语义、成功标准、Artifact 和证据等级。

## 2. 三个基础能力

只允许：

- `flow.command`：统一入口、参数转发、退出码、日志和简要执行证据；
- `update.transaction`：验包、staging、保留本机状态、切换、失败回滚；
- `recovery.package`：生成完整恢复包，承担开发恢复、迁移、GPT 交接和技术留档。

能力必须独立、版本化、按需加载。未启用能力不得加载。业务代码不得 import Infra 内部实现。

## 3. 人机职责

- 人：目标、优先级、产品边界、真实验收、不可逆确认；
- Flow：协议、不变量、状态推导、门禁、证据和恢复；
- AI：候选实现、重构、测试、技术文档和变更记录；
- Provider：Git、npm、数据站点和构建工具。

AI 不是自己修改、自己选测试、自己宣布最终通过的裁判。

## 4. 副作用等级

- L0：只读；
- L1：只写临时文件与日志；
- L2：修改本地可恢复状态；
- L3：修改 Git 或远端且可补偿；
- L4：不可逆发布或用户数据变更。

不可逆节点只确认一次。

## 5. Preview / Release

Preview 不修改 Git、Tag 或远端。Release 只消费当前有效 Preview，不得重新构建另一份候选。候选必须绑定 Commit、Tree、配置摘要、Artifact 哈希和创建时间。

## 6. 发布边界

公开 `main` 包含全部可公开消费数据、来源诊断数据、产品源码和技术文档。以下只留内网：`.flow/**`、`script/**`、`tests/**`、`docs/internal/**`、AGENTS、GPT 说明、本机配置、原始网页缓存、日志和执行状态。

发布时聚合项目 Changelog、数据包 Changelog、机器发布记录和 Git 变更；公开只写面向用户的 `RELEASE-NOTES.md`，完整聚合报告只留内网。

## 7. 更新与恢复

默认更新根目录固定为 `/Users/sakana/Downloads/GPT-Projects/`，不按项目分流。Manifest 必须精确声明项目和基线。更新失败自动恢复；用户只需 `./flow rollback`，不得要求分析事务目录。

## 8. 禁止项

不恢复中央注册表强校验、Findings/dispute、中央 Stable main 治理、public projection、release surface、复杂质量凭据、文件全量分类或复杂 Git 发布策略作为 Infra 基础依赖。

## 9. 版本与制品命名

项目日常版本使用简洁三段 SemVer。开发分支和当前状态由 Git、Flow 状态与 Sidecar 表达，不把普通迭代流水号长期编码为 `rc.N`。更新制品文件名只保留短项目名、类型和目标版本；源版本、目标版本、项目身份与内容身份必须以 Sidecar 和 Manifest 为权威。

## 10. main 唯一一次历史内容清理

Flow Lite 迁移允许对明确授权的 legacy main tree 做一次完整内容替换。该动作不重写 Git 历史，不删除 Actions、Tag、Artifact、Cache、Secret 或 Variable。完成后必须通过公开内容清单改为增量同步；清单缺失且 tree 未授权时不得再次全量清理。
## 11. 来源 ID 身份锁定

`Source ID is locator/evidence only, never identity.`

来源 ID 只能作为抓取定位符或来源证据，不能证明跨来源身份相等。禁止用 KCWiki、KC3、WikiWiki、Start2/API、Akashi 或任意外部来源的数字 ID 互相归并到 canonical identity。当前唯一允许的 ID 用途是来源定位或来源证据，例如 Akashi-List detail/png URL 中用于请求页面或图片的 id，以及 WikiWiki 页面内 No. 作为诊断证据。

跨来源装备或舰船匹配只能走名称、别名、类型和上下文事实。无法确认时必须红色 diagnostic、exclude 或 hard stop；不得静默 fallback 到 ID equality。宁愿少数据，也不要错数据进入正式包。

