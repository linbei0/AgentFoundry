# HaAgent TUI 技术设计文档

## 1. 背景与目标

HaAgent 的目标是本地个人 AI 助手：用户配置一次模型后，进入任意目录运行 `haagent`，即可围绕当前目录完成文件阅读、资料整理、文档修改、项目分析、命令执行和多轮任务延续。

当前 CLI 已经具备核心 Agent Runtime，但使用体验仍偏工程化：用户需要理解 profile、workspace、session、失败阶段、工具事件等概念。TUI 的目标不是做 IDE，而是把这些运行状态变成直观、可控、可恢复的个人助手界面。

TUI 设计目标：

- 让普通用户能看懂“当前在哪个目录、用哪个模型、任务是否正在执行、失败在哪里”。
- 降低配置和会话恢复成本。
- 保留 HaAgent 现有 runtime 约束：`ModelGateway`、`ToolRouter`、workspace root、episode trace。
- 不把 harness/eval/dogfood 暴露成普通用户主路径。
- 不做 Web UI，不做桌面 App，不做 Codex clone，不做 IDE。

## 2. 参考依据

TUI 框架推荐使用 Textual。Textual 官方文档提供了 App/compose、screen、modal、worker、测试等能力，适合构建可测试的 Python 终端应用：[Textual App](https://textual.textualize.io/guide/app/)、[Workers](https://textual.textualize.io/guide/workers/)、[Screens/ModalScreen](https://textual.textualize.io/guide/screens/)、[Testing/run\_test](https://textual.textualize.io/guide/testing/)、[TextArea](https://textual.textualize.io/widgets/text_area/)。

Rich 适合承担 Markdown、表格、Panel、日志等终端渲染：[Rich Console](https://rich.readthedocs.io/en/latest/console.html)、[Rich 文档](https://rich.readthedocs.io/en/latest/index.html)。

MCP 规范中关于工具安全、用户确认、workspace/roots、elicitation 的原则可作为 Agent TUI 的安全参考：用户应清楚知道工具调用和数据访问，并能授权或拒绝：[MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18)。

OpenAI Agents 文档强调运行循环、会话状态、审批暂停和恢复，这与 HaAgent 的多轮会话和工具审批设计一致：[Running agents](https://developers.openai.com/api/docs/guides/agents/running-agents)。

本地参考项目：

- OpenHarness 使用 Textual 构建终端 UI，值得参考其 runtime/UI 分离、modal 审批和 `run_test()` 测试方式。
- GenericAgent 的 TUI 功能较丰富，可参考交互经验，但不建议照搬大文件和自动安装依赖模式。

## 3. 当前项目基础

HaAgent 当前已有适合作为 TUI 后端的基础：

- `AgentSession.run_prompt_events()` 已能输出结构化 `ChatEvent`。
- `AgentSession` 已支持 session 创建、恢复、bounded summary。
- `list_sessions()` / `find_latest_session()` 已支持当前 workspace 的会话列表。
- `ProviderProfile` 已支持用户级 profile 配置，真实 API key 解析优先级是环境变量、系统凭据库、显式明文用户文件；默认 setup 写入系统凭据库。
- `ModelGateway` 和 `ToolRouter` 已形成 runtime 边界。
- CLI 当前默认入口仍是个人助手聊天模式，`haagent tui` 是显式的 TUI 垂直切片入口。

当前已经抽出 **应用服务层**。TUI 不直接调用 CLI handler，也不解析 `print_chat_event()` 输出，而是通过结构化服务接口复用同一套会话和事件流能力。

## 4. 总体架构

推荐采用三层架构：

```text
TUI Adapter
  ↓
Assistant Service
  ↓
Runtime Core
```

### 4.1 Runtime Core

Runtime Core 保持现状，不被 TUI 绕过：

- `ModelGateway`：所有模型调用入口。
- `ToolRouter`：所有工具调用入口。
- `AgentSession`：多轮会话、事件流、session package。
- `RunOrchestrator`：任务运行与模型/工具循环。
- workspace root：限制文件和命令工具作用范围。
- episode/transcript/tool-calls：保留审计与复盘能力。

### 4.2 Assistant Service

已有 `AssistantService`，作为 CLI 与 TUI 共享的应用服务层。

职责：

- 读取 active profile。
- 检查 API key 是否可用，并暴露环境变量、keyring、显式明文用户文件等非敏感状态。
- 创建新 session。
- 恢复指定 session。
- 继续当前 workspace 最新 session。
- 列出当前 workspace sessions。
- 运行用户 prompt，并产出 `ChatEvent` 流。
- 暴露当前 workspace、provider、model、session 状态。

要求：

- 不依赖 Textual。
- 不打印 stdout。
- 不解析 CLI 文本输出。
- 不保存真实 API key。
- 不绕过 `AgentSession`、`ModelGateway`、`ToolRouter`。

### 4.3 TUI Adapter

TUI 只负责交互和展示：

- 把用户输入转成 service 调用。
- 把 `ChatEvent` 映射成 UI 消息。
- 把审批、补充问题、配置错误做成 modal。
- 把运行状态展示为用户能理解的文本。
- 长任务通过 Textual worker 执行，避免界面卡死。

## 5. TUI 信息架构

首版 TUI 建议包含四个区域：

### 5.1 顶部状态栏

展示：

- 当前 workspace。
- active profile。
- provider / model。
- API key 是否可用，以及实际使用的凭据来源摘要。
- 当前 session id。
- 当前运行状态：idle / running / waiting\_user / failed。

### 5.2 主对话区

展示：

- 用户消息。
- assistant 回复。
- 工具调用摘要。
- 文件修改摘要。
- 命令执行摘要。
- 错误信息。

原则：

- 默认不展示完整 tool output。
- 默认不展示完整 transcript。
- 需要时提供“查看详情”入口，但不把大量 trace 塞进主视图。

### 5.3 输入区

推荐使用 Textual `TextArea`：

- 支持多行输入。
- `Ctrl+Enter` 提交。
- `Esc` 取消当前编辑或关闭 modal。
- 输入为空时不提交。

### 5.4 侧边栏

展示：

- 当前配置健康度。
- 最近 sessions。
- 本轮工具调用列表。
- 当前任务阶段。
- 简短帮助提示。

侧边栏不是功能堆叠区，只展示会影响用户判断的状态。

## 6. 关键交互设计

### 6.1 首次启动

当用户运行 `haagent tui`：

- 如果 profile 存在且 API key 可通过环境变量、系统凭据库或显式明文用户文件解析，直接进入 TUI。
- 如果 profile 缺失，提示运行 setup 或进入 TUI 内配置向导。
- 如果 API key 不可用，只显示环境变量名和非敏感凭据状态，不要求用户在 TUI 输入真实 key。

### 6.2 配置检查

TUI 应能显示：

- profile name。
- provider。
- base\_url。
- model。
- api\_key\_env。
- api\_key\_env 是否存在。
- credential source 配置值、实际使用来源和 keyring 可用性摘要。

真实 API key 不应显示、不应输入、不应写入文件。

### 6.3 工具审批

当 runtime 需要用户确认时，TUI 使用 ModalScreen 展示：

- 工具名称。
- 影响范围。
- 关键参数摘要。
- 允许 / 拒绝按钮。

这符合 MCP 对工具调用安全和用户授权的建议。

### 6.4 用户补充信息

当 Agent 需要用户回答问题时，TUI 使用 modal 或专门输入状态：

- 展示问题。
- 提供文本输入。
- 回答后继续同一个 turn。
- 不把审批/补充问题误当成新用户任务。

### 6.5 失败展示

失败信息必须清晰，不做静默 fallback。

展示字段：

- failed\_stage。
- failure\_category。
- reason。
- episode\_path。
- 可建议用户下一步检查什么。

例如 DeepSeek 配置选错 provider 导致 HTTP 404，TUI 应提示“当前 provider/base\_url/model 组合可能不匹配”，而不是只显示 404。

## 7. 入口策略

当前入口策略：

- `haagent`：默认进入经典文本聊天。
- `haagent chat`：保留经典文本聊天。
- `haagent setup`：保留命令行配置。
- `haagent tui`：显式进入 TUI 垂直切片，方便测试、试用和后续打磨。

暂不把 `haagent` 默认入口切到 TUI。TUI 已通过 `AssistantService` 避免复用 CLI print 输出；后续是否改默认入口需要单独产品决策和 CLI 回归覆盖。

## 8. 技术选型

当前依赖：

```toml
dependencies = [
  "pyyaml>=6.0.0",
  "rich>=13.x",
  "textual>=0.80.0",
]
```

说明：

- Textual 负责 TUI 框架、布局、事件、modal、worker、测试。
- Rich 负责终端内容渲染。
- 不建议运行时自动安装依赖；依赖应由 `pyproject.toml` 管理。
- Textual 当前已作为主依赖；如果后续希望默认文本 chat 更轻量，再单独评估 optional extra。

## 9. 测试策略

TUI 必须可自动化测试，不只靠人工试用。

测试重点：

- `AssistantService` 单元测试：
  - profile 缺失。
  - API key env 缺失。
  - 创建 session。
  - 恢复 session。
  - 列出 sessions。
  - event stream 正常转发。
- Textual `run_test()`：
  - app 能启动。
  - 状态栏显示 workspace/profile。
  - 输入 prompt 后触发 service。
  - running 状态不阻塞 UI。
  - modal 可批准/拒绝。
  - session 列表可选择。
- CLI 回归：
  - `haagent` 仍进入经典文本聊天。
  - `haagent tui` 进入 TUI。
  - `haagent chat` 仍进入经典文本模式。
  - `haagent setup` 不受影响。
- 安全测试：
  - API key 不出现在 UI snapshot、transcript、session summary、tool-calls。

## 10. 非目标

首版不做：

- Web UI。
- Electron / 桌面 App。
- IDE 代码编辑器。
- 文件管理器。
- 多 Agent 编排。
- 长期记忆。
- 复杂插件系统。
- 复杂主题市场。
- 自动安装 TUI 依赖。
- 把 eval/dogfood 作为普通用户主路径。

## 11. 结论

HaAgent 已进入 TUI 垂直切片阶段，但 TUI 不应该直接长在 CLI 输出层上。当前路线是：

1. 保持 runtime 不动。
2. 通过已抽出的 `AssistantService` 复用 profile、session 和事件流能力。
3. 用 Textual 构建并测试显式 `haagent tui`。
4. 保持 `haagent` 默认进入经典文本聊天。
5. 后续再单独评估是否把默认入口切到 TUI。
