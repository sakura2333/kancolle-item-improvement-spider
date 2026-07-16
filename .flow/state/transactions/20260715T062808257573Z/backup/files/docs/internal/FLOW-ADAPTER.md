# Flow 1.1 适配边界

`script/flow_adapter.py` 只做三件事：

1. 声明公共命令是否支持、Profile/Target 和副作用等级；
2. 将 `status/check/run/push/stable/doctor` 映射到 `script.project.cli`；
3. 向 `update.transaction` 与 `recovery.package` 提供最小项目边界。

适配层不得保存质量步骤、Spider 来源、Git 提交算法、Stable 文件清单或 npm 构建逻辑。非公共诊断与构建命令直接属于项目工具，不进入 `./flow help`。

公共入口固定为 `./flow`；不存在 `quality:*`、`data:*`、`stable:*`、`npm:*`、`update:*` 或 `recovery:*` 第二命令空间。

## Flow package 更新边界

本仓库内嵌的 `script/flow/**` 是 Spider 当前使用的 Flow package 实现副本。更新该 package 时必须同时更新：

1. `.flow/project.json` 的公约绑定；
2. `script/flow/contract.py` 中的 package identity 与支持矩阵；
3. `tests/test_flow_command.py` 和 `script/project/verify.py` 中的契约门禁；
4. 必要时更新 `docs/internal/FLOW-ADAPTER.md`。

Flow package 更新不得顺手改变 Spider 业务命令、数据生成物或 npm 包内容。若没有新的正式公约包，只允许做向后兼容实现修补，并保持 `flow.public 1.1.0` 绑定不变。

