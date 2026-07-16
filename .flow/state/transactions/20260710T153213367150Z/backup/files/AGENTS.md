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
- `release/public-content.json` 是 Beta 与 Stable 共用的 Public Snapshot 唯一文件边界权威。
- `release/public-exceptions.json` 只允许登记无法物理隔离的最小公共语义；规则见 `docs/internal/PUBLIC-ISOLATION.md`。
- Public Snapshot 必须由白名单构造，不能先复制完整仓库再删除内部文件。
- AI 审阅只做最终语义兜底；路径、引用、依赖闭包和内部内容隔离必须由机械门禁保证。

## 人机边界

- 人：目标、优先级、产品边界、真实验收、不可逆确认。
- Flow：协议、不变量、门禁、证据和恢复。
- AI：候选实现、重构、测试、文档和语义审阅。
- Provider：Git、npm、数据站点和构建工具。

## 验证

```bash
./flow check --profile full
```
