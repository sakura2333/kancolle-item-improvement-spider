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

正常更新直接执行 `./flow update`。Flow 从 `.flow/local.json` 的 `downloadRoot` 读取更新目录，以当前 `packageVersion` 为起点只定位 canonical `N+1` 文件名，再以包内 project identity 与 `from.contentHash` 做最终验真。每应用一包都会退出当前更新子进程、重新加载磁盘上的新版 Flow、刷新 `packageVersion/contentHash` 后再寻找下一包。`--package <zip>` 仅作为人工指定单包的覆盖入口。

## Python 环境事实源

- 依赖版本：`requirements.txt`
- 环境初始化：`python3 script/project/init_env.py`
- `./flow check` 会先检查 `.venv` 与固定依赖版本；环境未就绪时会给出唯一下一步，不再把缺包误报为代码失败。
