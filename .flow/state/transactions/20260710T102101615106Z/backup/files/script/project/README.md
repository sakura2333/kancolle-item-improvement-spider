# Spider Project Tools

本目录属于项目工程工具层，负责质量检查、Spider 运行、npm 构建、代码提交和 Stable 投影。

公共 `./flow` 只通过 `script/flow_adapter.py` 调用少数稳定目标；业务解析、数据生产与 npm 细节不进入 Flow 命令空间。CI 和维护脚本可以直接调用本目录中的原生工具。

## 检查分层

默认 `test*.py` 属于开发/完整回归；`release_test*.py` 只属于 Stable Preview 的公开发布策略检查。发布专用检查不得反向阻断 `quick`。
