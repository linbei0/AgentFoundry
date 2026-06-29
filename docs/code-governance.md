# 代码治理

HaAgent 当前按“本地个人 AI 助手”治理代码变更。CLI、TUI、runtime、provider、tool 和文档术语都应服务“在目标目录直接运行 `haagent` 并进入 TUI”的体验。

## 边界

- CLI 负责解析启动参数、打开 TUI，并保留非交互开发/CI 命令的短输出。
- TUI 负责普通交互入口：模型配置、会话管理、自然语言任务、联网开关、工具审批、记忆候选和失败展示。
- `AgentSession` 负责多轮会话、bounded summary、working state 和 session package。
- `RunOrchestrator` 负责 task contract、模型调用、工具执行、episode trace 和 verification。
- `ModelGateway` 是所有模型调用边界。
- `ToolRouter` 是所有工具调用边界。

## 变更规则

- 优先做小而明确的改动，避免把个人助手体验改造成 IDE 或多 Agent 系统。
- 普通用户文档优先说明无子命令 `haagent`、TUI 内 `/model`、当前目录 workspace、多轮会话和 `/sessions`/`--continue`/`--resume`。
- `task.yaml`、eval、dogfood、inspect 属于高级/开发/验证能力；改动时保持可用，但不要把它们写成用户价值主线。
- 所有行为变更必须有 pytest 覆盖；TDD 内循环优先运行最小相关测试，完成前至少运行与改动直接相关的测试。
- 只有跨多个核心模块、改动共享 runtime 合同、触及 `ToolRouter`、`ModelGateway`、context、episode、CLI 入口、workspace 边界或 secret 处理，或准备提交、合并、发布、交付时，才要求运行完整 `uv run pytest -q`。
- `uv run haagent check` 是快速质量门禁；改动 harness、eval、smoke、CLI 质量门禁或 runtime 任务执行时，交付前运行它。
