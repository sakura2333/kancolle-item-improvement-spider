# Spider Agent 入口

修改项目之前必须依次读取：

1. `SPIDER-HARD-RULES.md`
2. `SPIDER-AUTHORITY-MAP.md`
3. `.flow/project.json`
4. `docs/internal/DOCUMENTATION-MAP.md`
5. `docs/internal/ARCHITECTURE.md`
6. 对应模块目录下的 `README.md`
7. 涉及 Python 构建或验收时，读取 `mise.toml`、`pyproject.toml` 与 `uv.lock`

## 不可违反

- 人类日常入口只有 `./flow` 与固定意图命令。
- 业务代码不得 import `script.flow` 的控制实现；产品域只通过项目命令或 Provider 边界接入。
- 公共能力只允许 `flow.command`、`update.transaction`、`recovery.package`，版本由 `.flow/project.json` 绑定的正式公约解释。
- 三个能力彼此独立、按需加载，契约绑定版本，不绑定目录或类名。
- AI 可以修改候选实现，但不得暗中改变命令副作用、确认点、失败/回滚语义、成功标准、Artifact 或证据等级。
- `.flow/**`、`script/**`、`tests/**`、`docs/internal/**` 只进入内网 `dev`，不得进入公开 `main`。
- 公开 `main` 只发布用户和数据消费方需要的源码、全量可公开数据、技术文档与摘要。
- 不提供全量清理 GitHub Actions、Artifacts、Caches、Secrets 或 Variables 的能力。


## 外部工具隔离

- `tools/**` 是默认不进入核心阅读链的外部手动工具域，不是 L1-L4 架构层。除非任务明确涉及外部工具或数据采集，AI 不应把它纳入核心依赖图、重构范围或运行链分析。
- 核心目录（`flow`、`script`、`service`、`configs`、`packages`）不得 import 或调用 `tools/**`。工具只允许单向读取导出数据，或通过子进程调用公开项目入口。
- Flow、CI、npm 和默认质量入口不得执行 `tools/**`。更新包可以分发工具源码，但更新事务不得执行它。
- 工具的 Cookie、浏览器会话、断点和日志必须写入 `.flow/local/**`；经用户确认可供业务解析复用的原始页面写入 local-preserved 的 `data/raw_data/site_cache/**`，不得提交、发布或输出凭据。

## 验证

Python/uv 工具版本的唯一事实源是 `mise.toml`；依赖版本的唯一事实源是 `pyproject.toml` 与 `uv.lock`；环境初始化统一执行 `mise install && mise exec -- uv sync --locked`。

代码、测试和技术文档必须同步修改，并通过：

```bash
./flow check --profile full
```
