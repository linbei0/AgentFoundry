# HaAgent 产品与 Harness 要求

HaAgent 的产品目标是本地个人 AI 助手：用户配置一次模型后，在任意目录运行 `haagent` 即可围绕当前目录完成个人助手任务。HaAgent 不是 Codex clone，不是 IDE，也不是纯代码 Agent。

## 普通用户路径

```powershell
uv run haagent setup
cd E:\some-folder
uv run haagent
```

Profile 是模型连接配置，支持 OpenAI Responses-compatible endpoint（`openai`）和 OpenAI Chat Completions-compatible endpoint（`openai-chat`）。默认 profile 配置存放在用户级 `~/.haagent/providers.json`；active profile 存放在 `~/.haagent/settings.json`。Workspace 和 session 是目录相关运行状态，默认写在当前目录的 `.runs/sessions`。

真实 API key 解析优先级是：当前环境变量覆盖、系统凭据库、显式 opt-in 的明文用户文件。默认 setup 使用系统凭据库以支持跨终端使用；环境变量适合 CI 或临时覆盖；明文文件必须显式选择并标记为 insecure。真实 API key 不写入项目配置、episode、transcript、日志或 session summary。

## 产品边界

- 代码开发是 HaAgent 支持的一类任务，不是唯一主线。
- `task.yaml`、eval、dogfood、episode inspect 是高级/开发/验证能力。
- 不把 GUI/TUI 作为普通默认路径；如果后续继续推进，只保留显式入口和最小垂直切片，除非另有明确要求。
- 不为了旧实验 artifact 增加复杂兼容逻辑。

## Runtime 约束

- 模型调用必须经过 `ModelGateway`。
- 工具调用必须经过 `ToolRouter`。
- 文件和命令工具必须受 workspace root 限制。
- 运行过程必须继续写入 episode、transcript 和 tool trace，供 inspect/eval 使用。
- 不增加普通用户心智负担，不把 harness/eval 作为用户价值主线。
