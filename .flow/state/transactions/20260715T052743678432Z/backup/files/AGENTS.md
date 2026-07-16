# Spider AI 入口

这是开发仓库唯一的根级 AI 索引；它属于内部知识面，不进入任何 Beta 或 Stable Public Snapshot。

修改项目之前按顺序读取：

1. `docs/internal/ai/HARD-RULES.md`
2. `docs/internal/ai/AUTHORITY-MAP.md`
3. `docs/internal/ai/START.md`
4. `.flow/project.json`
5. `docs/internal/DOCUMENTATION-MAP.md`
6. 与当前任务对应的内部或公开文档
7. 涉及 Python 构建或验收时读取 `mise.toml`、`pyproject.toml`、`uv.lock`

## 内容边界

- `README.md` 与 `docs/public/**` 只面向公开用户。
- `AGENTS.md`、`docs/internal/**`、`.flow/**`、`script/**`、`tests/**`、`tools/**` 只属于 dev。
- `release/public-content.json` 是项目内容注册表，也是 Beta 与 Stable 共用的 Public Snapshot 唯一内容边界权威。
- `release/public-exceptions.json` 只允许登记无法物理隔离的最小公共语义；规则见 `docs/internal/PUBLIC-ISOLATION.md`。
- Public Snapshot 必须按项目内容归属构造；Git tracked、untracked 或 ignored 状态不得决定公开性。
- 冻结 Candidate 后不得在审核分支清理；AI 只做最终语义兜底，发现问题必须回到 dev 生成新事务。

## 人机边界

- 人：目标、优先级、产品边界、真实验收、不可逆确认。
- Flow：协议、不变量、门禁、证据和恢复。
- AI：候选实现、重构、测试、文档和语义审阅。
- Provider：Git、npm、数据站点和构建工具。

## 验证

```bash
./flow check --profile full
```
