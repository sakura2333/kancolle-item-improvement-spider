# Spider GPT 冷启动

本项目采用 Flow Lite。不要恢复旧 `.devops` 控制面，也不要从旧交接包推导当前状态。

## 首读

```text
SPIDER-HARD-RULES.md
SPIDER-AUTHORITY-MAP.md
.flow/project.json
docs/internal/DOCUMENTATION-MAP.md
docs/internal/architecture/README.md
requirements.txt（涉及 Python 构建或验收时）
script/project/init_env.py（涉及 Python 环境时）
```

## 实时事实

```bash
./flow
./flow status
git status --short --branch
cat VERSION
```

## 人类意图接口

```bash
./flow status
./flow check
./flow run
./flow push
./flow beta
./flow stable
./flow package
./flow update
./flow rollback
```

AI 与自动化可以使用 `quality:full`、`stable:preview`、`stable:release`、`update:inspect`、`update:apply`、`recovery:package` 等精确命令。

更新包统一放在：

```text
/Users/sakana/Downloads/GPT-Projects/
```

更新器只依据包内 `update-manifest.json` 的项目、版本和哈希识别，不根据目录或文件名猜测。

## Python 环境事实源

- 依赖版本：`requirements.txt`
- 环境初始化：`python3 script/project/init_env.py`
- `./flow check` 会先检查 `.venv` 与固定依赖版本；环境未就绪时会给出唯一下一步，不再把缺包误报为代码失败。
