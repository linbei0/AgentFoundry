# HaAgent MCP Client 设计

日期：2026-07-02

## 背景

HaAgent 的普通入口是无子命令 `haagent` 打开的 Textual TUI。MCP 功能第一版只做 HaAgent 作为 MCP client 接入外部 MCP server，不把 HaAgent 暴露为 MCP server。

参考输入：

- `E:\python-project\OpenHarness`：已实现 `McpClientManager`、stdio/Streamable HTTP 连接、动态 MCP tool 适配、resource list/read、TUI 状态摘要。
- `E:\python-project\GenericAgent`：没有 MCP 直接实现，但其工具调用经验说明“模型直接看到工具 schema”比固定代理工具更可靠。
- 官方 MCP 文档和 Python SDK：MCP 核心能力包括 tools/resources/prompts；stdio 和 Streamable HTTP 是当前标准 transport。Python SDK v1 稳定线优先用于第一版，v2 在当前日期仍不作为第一版依赖目标。

## 目标

- 支持从用户级配置加载外部 MCP server。
- 支持 stdio 和 Streamable HTTP MCP server。
- 将外部 MCP tools 暴露为普通 HaAgent 工具 schema。
- 所有 MCP tool 调用继续经过 `ToolRouter`、审批、guardrail、`tool-calls.jsonl` 和 episode trace。
- 支持列出与读取 MCP resources。
- TUI 通过 `/mcp` 展示连接状态、发现的 tools/resources 和错误摘要。

## 非目标

- 第一版不把 HaAgent 自身暴露为 MCP server。
- 第一版不支持 MCP prompts/templates 注入模型上下文。
- 第一版不实现项目级 MCP 配置、插件 MCP 配置合并、CLI `mcp add/remove` 或 `/mcp auth` 完整凭据管理。
- 第一版不根据工具名、描述或 schema 自动猜测风险等级。

## 配置

新增用户级配置文件：

```json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-server-filesystem"],
      "env": {},
      "cwd": null
    },
    "docs": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": {}
    }
  },
  "tool_risks": {
    "filesystem.list": "medium"
  }
}
```

规则：

- 配置文件路径为用户级 `~/.haagent/mcp.json`。
- `servers.<name>.type` 支持 `stdio` 和 `http`。
- `tool_risks` 使用 `<server>.<tool>` 键，值只能是 `low`、`medium`、`high`。
- 配置中的 `env` 和 `headers` 允许存在，但 status、trace、错误信息必须脱敏。
- 配置解析失败必须显式报错；连接单个 server 失败不阻塞普通会话。

## 架构

新增 `haagent.mcp` 子包：

- `types.py`：定义 `McpStdioServerConfig`、`McpHttpServerConfig`、`McpToolInfo`、`McpResourceInfo`、`McpConnectionStatus`。
- `settings.py`：读取和校验 `~/.haagent/mcp.json`。
- `client.py`：实现 `McpClientManager`，负责连接、关闭、列出 tools/resources、调用 tool、读取 resource。
- `tool_adapter.py`：将 `McpToolInfo` 转为 HaAgent `ToolDefinition` 和 `ToolHandler`。

新增运行期 registry 视图：

- 静态内置工具仍来自 `TOOL_REGISTRY`。
- MCP 连接成功后生成动态 `ToolDefinition`，工具名格式为 `mcp__<server>__<tool>`。
- `ContextBuilder`、`export_tool_schemas`、`ToolRouter` 使用同一个 registry 视图，避免模型 schema、allowed_tools 校验和实际 dispatch 脱节。
- 动态 registry 不写入全局 `TOOL_REGISTRY`，避免跨会话污染和连接失败后的过期 schema。

## 数据流

1. TUI/`AgentSession` 创建或恢复时加载 MCP 配置。
2. `McpClientManager.connect_all()` 连接所有配置 server。
3. 成功连接的 server 产生动态 tools/resources/status。
4. `ChatTurnRunner` 创建本轮 task contract 时，将当前已连接的动态 MCP 工具加入 `allowed_tools`。
5. `RunOrchestrator` 创建 `ToolRouter` 和 `ContextBuilder` 时传入同一个 registry 视图。
6. 模型看到每个动态 MCP tool 的真实 JSON schema。
7. 模型调用 `mcp__server__tool` 时，`ToolRouter` 先走 policy/guardrail/参数校验，再调用 `McpClientManager.call_tool()`。
8. 结果写入 `tool-calls.jsonl`，并以普通 tool observation 回到模型。

## 安全策略

- 动态 MCP tool 默认 `risk_level="high"`，复用现有高风险审批流。
- `list_mcp_resources` 和 `read_mcp_resource` 为只读工具，默认低/中风险。
- 用户可通过 `tool_risks` 显式降低某个 MCP tool 风险等级。
- 不通过工具名、描述、schema 或模型输出内容猜测风险。
- MCP 连接和调用错误必须结构化返回，不做静默 fallback。
- MCP tool 不获得 HaAgent workspace boundary 的自动保护；外部 server 的真实能力由用户配置与审批控制，所以默认高风险。

## TUI 行为

新增或扩展 `/mcp`：

- 无参数：展示 configured/connected/failed server 列表、工具数量、resource 数量、失败原因摘要。
- 第一版不要求在 TUI 内新增/删除 server；用户可手写 `~/.haagent/mcp.json`。
- 连接失败不阻断普通聊天，但状态中必须可见。

## 测试

新增测试覆盖：

- 解析 stdio/http MCP 配置。
- 连接 fake stdio MCP server 并发现 tools/resources。
- 动态 MCP tool schema 能随本轮 registry 导出给模型。
- `ToolRouter` 能 dispatch 动态 MCP tool，并写入 tool trace。
- 动态 MCP tool 默认 high-risk，需要审批。
- `tool_risks` 能显式降低指定工具风险。
- `list_mcp_resources` 和 `read_mcp_resource` 返回结构化结果。
- 单个 server 连接失败不阻塞普通会话，且状态可见。
- env/header/error/status 脱敏，不泄露 secret。

建议验证命令：

```powershell
uv run pytest tests/test_mcp_client.py tests/test_tool_router.py tests/test_tool_registry.py tests/test_chat_turn.py -q
uv run pytest -m "not slow" -q
```

## 开放问题

- 后续是否支持项目级 `.haagent/mcp.json`，需要单独设计信任边界。
- 后续是否实现 `/mcp add/remove/auth`，需要和用户级 secret 存储策略一起设计。
- 后续是否支持 MCP prompts/templates，必须先评估上下文预算和 prompt 注入边界。
