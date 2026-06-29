# HaAgent TUI Model Center Design

更新时间：2026-06-28
状态：已实施并验证 v1

更新说明：本文保留模型中心 v1 设计的历史上下文。当前产品决策已更新为 TUI-first：无子命令 `haagent` 默认进入 TUI，模型配置在 TUI 内 `/model` 完成，旧 `haagent setup/chat/sessions/memory/tui` 交互入口只提示迁移。

## 目标

HaAgent 需要在 TUI 中提供“快速配置模型”和“快速切换模型”的能力，使用户不用离开 TUI 就能完成 provider/model 发现、API key 配置、profile 保存、当前会话切换、默认 profile 设置和连接测试。

当前普通路径是在任意目录运行 `haagent` 并进入 TUI；TUI 模型中心复用用户级 profile 和 runtime 模型边界，不创建一套独立配置系统。

核心成功标准：

- 用户可以通过 `/model` 打开模型中心，通过 `/models` 进入同一能力或模型搜索态。
- 用户可以从 Models.dev 或等价公开模型目录中搜索主流 provider 和模型。
- 用户可以在 TUI 中输入 API key；输入必须 masked，默认保存到系统 keyring。
- 用户可以显式选择 env 模式；env 模式不收集真实 key，只提示应设置的环境变量。
- `Enter` 切换当前 TUI 会话后续消息使用的 profile/model，不写默认配置。
- `p` 把 profile 设置为默认配置，不改变正在运行的请求。
- 连接测试必须由用户显式触发，并通过 `ModelGateway` 执行。
- 真实 API key 不写入 profile、settings、episode、transcript、tool trace、session summary 或 TUI 可检查文本。

## 参考项目取舍

OpenCode 的 TUI 提供 `/connect` 配置 provider/API key、`/models` 选择模型，并使用 Models.dev 支持大量 provider。HaAgent 采用“模型目录 + TUI 模型选择器”的思路，但不采用 OpenCode 的 provider runtime；HaAgent 的实际调用仍必须经过 Python 侧 `ModelGateway`。

Aider 提供 `/model` 切主模型、`/models` 搜索模型。HaAgent 采用 slash command 的可发现入口，但需要额外区分“当前会话切换”和“默认 profile 设置”，避免一次选择产生意外持久化。

Gemini CLI 的 `/model set <model-name> [--persist]` 证明了 session-only 和 persistent model selection 应明确分离。HaAgent 在 TUI 中使用 `Enter` 和 `p` 分别表达这两种行为。

Textual 的 worker 和 `run_test()` 是 TUI 实现边界：Models.dev 刷新、连接测试和 keyring 写入都不能阻塞 UI；TUI 行为必须通过 headless Pilot 测试覆盖。

## 非目标

- 不重新引入普通交互 CLI 入口；TUI 是唯一普通交互入口。
- 不让 TUI 绕过 `AssistantService`、`AgentSession` 或 `ModelGateway` 直接改 runtime 状态。
- 不把 Models.dev 中所有 provider 都假设成 OpenAI-compatible。
- 不用模型名称、provider 名称或用户语言片段做安全边界。
- 不自动测试连接；连接测试可能消耗额度，必须由用户显式触发。
- 不在模型中心中展示、复制、记录或回显真实 API key。
- 不为了兼容旧 provider profile artifact 增加复杂迁移逻辑。

## 总体结构

```text
TUI Model Center
  ├─ Catalog Layer
  │    ├─ Models.dev fetch
  │    ├─ parsed provider/model catalog
  │    └─ explicit cache and failure state
  ├─ Profile Layer
  │    ├─ user provider profiles
  │    ├─ active default profile
  │    └─ credential status without secrets
  ├─ Gateway Registry
  │    ├─ openai Responses gateway
  │    ├─ openai-chat compatible gateway
  │    └─ future native provider adapters
  ├─ AssistantService API
  │    ├─ list/configure/test profiles
  │    ├─ switch current session profile
  │    └─ set default profile
  └─ Textual Screens
       ├─ ModelCenterOverlay
       ├─ ModelSetupWizard
       └─ ConnectionTestResult view
```

模型目录、profile 管理和 runtime gateway 是三个不同层次。Catalog 只说明“有什么 provider/model 和默认元数据”；Profile 说明“用户配置了什么连接”；Gateway Registry 说明“当前 HaAgent 能怎样真实调用它”。

## Catalog Layer

新增 `haagent.models.catalog`，负责从 Models.dev 拉取、解析和缓存公开模型目录。

建议数据结构：

- `ModelCatalogProvider`
  - `id`
  - `name`
  - `env_names`
  - `api_base_url`
  - `provider_package`
  - `documentation_url`
  - `models`
- `ModelCatalogModel`
  - `id`
  - `name`
  - `family`
  - `supports_tool_call`
  - `supports_reasoning`
  - `modalities`
  - `limits`
  - `cost`
  - `release_date`
  - `last_updated`
- `CatalogFetchResult`
  - `providers`
  - `source`
  - `fetched_at`
  - `used_cache`

缓存位置建议为 `~/.haagent/models_catalog_cache.json`。网络刷新失败时：

- 如果存在缓存，返回缓存并明确标记 `used_cache=True` 和错误摘要。
- 如果不存在缓存，返回结构化错误，不伪造目录。

测试中必须注入 transport，不能依赖真实网络。

## Gateway Registry

HaAgent 当前 `ModelGateway` 只支持：

- `openai`：OpenAI Responses-compatible endpoint。
- `openai-chat`：OpenAI Chat Completions-compatible endpoint。

因此不能因为 Models.dev 能列出 Anthropic、Google、Mistral、Groq、Azure 等 provider，就把所有 provider 都当作可运行。

新增 registry 的职责：

- 将 profile 的 `provider` 字段映射到具体 `ModelGateway` 构造器。
- 将 catalog provider 转成推荐 gateway 类型。
- 给 TUI 暴露 capability 状态：
  - `runnable`：当前 HaAgent 已有 gateway，可以保存并测试。
  - `configurable`：可以保存 profile，但需要用户确认 endpoint/gateway 类型。
  - `adapter_required`：目录中存在，但当前 HaAgent 缺原生 adapter，不能假装可运行。

第一批可运行 provider 应覆盖：

- OpenAI Responses / OpenAI Chat Completions。
- OpenAI-compatible provider/router/local endpoint，例如 OpenRouter、Requesty、DeepSeek、LM Studio、Ollama/OpenAI-compatible endpoint，以及用户自定义 compatible endpoint。
- Anthropic Messages API。
- Google Gemini generateContent API。

对于尚未实现 native adapter 的 direct provider，应通过 registry 标记为 `adapter_required`，不能让连接测试产生误导。TUI 新建配置向导只展示 registry 判定为 `runnable` 的 catalog provider；已实现 native adapter 的 Anthropic 和 Google Gemini 可以直接从目录配置、保存 profile 并连接测试。

## Profile Layer

现有 `ProviderProfileRecord` 继续作为非敏感 profile 配置。需要补充服务 API，但不改变 secret 原则。

新增能力：

- 列出全部 provider profile。
- 按 profile 查询 credential status。
- 保存或更新 provider profile。
- 保存 keyring API key。
- 设置 active default profile。

profile 仍写入 `~/.haagent/providers.json`，active profile 仍写入 `~/.haagent/settings.json`。真实 API key 的优先级保持：

```text
environment variable > configured credential source
```

默认 credential source 是 `keyring`。`env` 模式只保存 `api_key_env`，不收集真实 key。`insecure_file` 仍然只能作为显式 opt-in 高级模式，不作为 TUI 默认推荐。

## AssistantService API

TUI 不能直接读写散落文件或替换 session 内部对象。新增服务层方法：

- `list_model_profiles()`
  - 返回 profile、active marker、credential status、gateway capability。
- `list_catalog_models(query: str | None)`
  - 返回 catalog provider/model 结果。
- `configure_model_profile(request)`
  - 保存 profile；如果请求包含 API key 且 source 是 keyring，则写 keyring。
- `switch_current_session_model(profile_name)`
  - 仅影响当前 TUI 会话后续消息。
  - 如果当前没有 `AgentSession`，记录为当前 TUI service 的 pending session profile，下一次创建 session 时使用。
  - 如果 session 正在运行，返回结构化错误。
- `set_default_model_profile(profile_name)`
  - 只写 active profile，不改正在运行的请求。
- `test_model_profile(profile_name)`
  - 解析 credential，构造 `ModelGateway`，执行显式小请求，返回结构化结果。

连接测试的测试请求应小而明确，例如要求模型返回短文本。失败必须保留 provider 错误摘要、HTTP 状态或 gateway 错误类型，但不得包含 API key 或 Authorization header。

## AgentSession 切换语义

`AgentSession` 需要一个明确方法来切换当前会话的 gateway，例如 `switch_model_gateway(profile_name, profile, gateway)`。

切换规则：

- 仅允许在没有当前 run 时切换。
- 切换后只影响后续 turn。
- session metadata 记录非敏感信息：profile name、provider、model、base_url、切换时间。
- 不把真实 key、credential source 细节或 keyring username 写入 session summary。
- 若当前 turn 正在执行，返回明确错误，由 TUI 展示“当前任务运行中，完成或取消后再切换”。

## TUI 交互设计

新增 slash commands：

- `/model`：打开模型中心。
- `/models`：同一入口，初始焦点放到搜索框或模型列表。

模型中心主界面：

```text
┌─ Models ───────────────────────────────────────────────────────────┐
│ Search: gpt-5                                                       │
├─ Profiles ──────────────┬─ Catalog / Models ───────────────────────┤
│ * default openai/gpt... │ > OpenAI        gpt-5.2-pro      runnable │
│   work    router/...    │   OpenRouter    anthropic/...   runnable │
│   local   lmstudio/...  │   Google        gemini-...      adapter   │
├─────────────────────────┴──────────────────────────────────────────┤
│ Enter switch session  p set default  n new  r refresh  t test  Esc │
└────────────────────────────────────────────────────────────────────┘
```

键盘行为：

- `j/k` 或方向键移动。
- `/` 聚焦搜索。
- `Enter` 切当前会话 profile。
- `p` 设默认 profile。
- `n` 打开配置向导。
- `r` 刷新 catalog。
- `t` 测试当前选中 profile。
- `?` 打开当前 overlay 帮助。
- `Esc` 关闭。

配置向导步骤：

1. Provider：从 Models.dev provider 中搜索选择，也支持 custom OpenAI-compatible。
2. Model：从 provider models 中搜索选择。
3. Gateway：根据 registry 推荐 `openai`、`openai-chat` 或提示需要 adapter。
4. Endpoint：使用 catalog `api` 默认值，可编辑；custom provider 必填。
5. Credential：选择 keyring/env/insecure_file，默认 keyring。
6. API key：仅 keyring/insecure_file 模式出现 masked input；env 模式只显示环境变量提示。
7. Save：保存 profile，可选择立即 `t` 测试。

## Error Handling

错误必须结构化展示，不吞掉：

- Catalog fetch failed：显示网络错误；有缓存时说明正在使用缓存。
- Provider unsupported：显示 `adapter_required`，不能保存为可运行 profile，除非用户选择 custom compatible gateway。
- Missing credential：显示缺少哪个 env 或 keyring key。
- Keyring unavailable：显示系统凭据库不可用；可让用户改用 env 或显式 insecure_file。
- Connection test failed：展示 provider/gateway 错误摘要，不展示 secret。
- Switch denied while running：提示完成或取消当前任务后重试。

## Security and Audit Boundaries

真实 API key 只能存在于：

- 当前 masked input 的内存值。
- keyring。
- 显式 opt-in 的 insecure user credential file。
- 运行时构造 `ModelGateway` 的内存参数。

真实 API key 不能进入：

- `providers.json`
- `settings.json`
- session metadata
- `turns.jsonl`
- `transcript.jsonl`
- `tool-calls.jsonl`
- `working_state.json`
- TUI conversation blocks
- TUI help/status/footer text
- pytest snapshot 或失败消息

所有 secret redaction 不能靠模型提示实现，必须由服务层和数据结构边界保证。

## Testing Plan

按 TDD 顺序实施：

1. Catalog tests
   - 解析 Models.dev provider/model schema。
   - 成功刷新写缓存。
   - 网络失败且有缓存时返回 explicit cached result。
   - 网络失败且无缓存时返回 explicit error。
2. Profile tests
   - 列出 provider profiles。
   - 保存 profile 不写真实 key。
   - keyring 保存成功和失败路径。
   - credential status 不暴露 key。
3. Gateway registry tests
   - `openai` 映射 Responses gateway。
   - `openai-chat` 映射 Chat Completions gateway。
   - OpenAI-compatible catalog provider 推荐 `openai-chat`。
   - unsupported native provider 标记 `adapter_required`。
4. AssistantService tests
   - `Enter` 语义只切当前会话。
   - `p` 语义只设置 default profile。
   - 运行中切换被拒绝。
   - 连接测试经 gateway factory。
   - 错误结果不包含 secret。
5. AgentSession tests
   - 空闲会话可以切换 gateway。
   - 切换后后续 turn 使用新 gateway。
   - metadata 只记录非敏感字段。
6. TUI tests
   - `/model` 和 `/models` 打开 overlay。
   - `Enter`、`p`、`n`、`r`、`t`、`Esc` 行为正确。
   - masked key 不出现在 conversation/status/footer。
   - catalog refresh 和 connection test 使用 worker，不阻塞输入。

相关测试命令：

```powershell
uv run pytest tests/test_model_gateway.py tests/test_credentials.py tests/test_assistant_service.py tests/test_tui_app.py -q
```

若新增 native provider adapter 或改变共享 runtime 合同，应运行：

```powershell
uv run pytest -q
```

## Scope Decisions

本设计已固定以下用户确认：

- 快速切换采用双层语义：当前会话切换和默认配置分开。
- TUI 可以输入 API key，但必须 masked，默认 keyring。
- 需要接 Models.dev 或等价公开模型目录，支持主流厂商快速配置并自动拉取模型列表。
- 连接测试作为显式触发能力，通过 `ModelGateway` 执行。

为避免把目标偷换成最小 profile picker，实施计划必须包含一个独立的 native provider adapter 切片，优先评估并实现 Anthropic 和 Google Gemini 的 `ModelGateway` adapter。TUI 模型中心不依赖这些 adapter 才能完成 catalog/profile/切换基础能力，但最终交付时必须清楚区分：

- 已实现 adapter 的 provider 可以保存、切换和连接测试。
- 尚未实现 adapter 的 provider 只能显示为 `adapter_required`，不能被伪装成可运行。
- 如果 Anthropic 或 Google adapter 在实施中遇到明确协议或测试阻塞，必须把阻塞写入交付说明，并保留结构化能力标记，而不是降级成静默失败或错误路由。
