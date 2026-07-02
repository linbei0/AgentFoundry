# MCP Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-version MCP client support so HaAgent can connect to user-configured stdio and Streamable HTTP MCP servers, expose discovered tools/resources through the existing ToolRouter boundary, and show MCP status in the TUI.

**Architecture:** Add a focused `haagent.mcp` package for config, async MCP connections, and a sync runtime wrapper used by HaAgent's synchronous runtime. Add a per-session runtime tool registry view that combines static `TOOL_REGISTRY` entries with connected MCP dynamic tool definitions, then pass that registry through context building, schema export, policy evaluation, and dispatch. Dynamic MCP tools are never written into the global `TOOL_REGISTRY`.

**Tech Stack:** Python 3.11, `mcp>=1,<2`, stdlib dataclasses/json/asyncio/threading, existing pytest suite, existing `ToolRouter`, `ContextBuilder`, `AgentSession`, Textual TUI command flow.

## Global Constraints

- Keep plain `haagent` / Textual TUI as the ordinary user path.
- Model calls must go through `ModelGateway`.
- Tool calls must go through `ToolRouter`.
- Every tool call must append a record to `tool-calls.jsonl`.
- Failures must be explicit and structured; do not add silent fallbacks or simulated success paths.
- Dynamic MCP tools default to `risk_level="high"`.
- `list_mcp_resources` and `read_mcp_resource` are read-only MCP resource tools.
- Do not route behavior by guessing user language, tool names, descriptions, schemas, or model output wording.
- Do not commit changes unless the user explicitly requests a commit.

---

## File Structure

- Create `src/haagent/mcp/__init__.py`: public package exports.
- Create `src/haagent/mcp/types.py`: dataclasses for server config, settings, tool/resource/status metadata.
- Create `src/haagent/mcp/settings.py`: load and validate `~/.haagent/mcp.json`.
- Create `src/haagent/mcp/client.py`: async MCP connection manager using the official Python SDK.
- Create `src/haagent/mcp/runtime.py`: sync wrapper owning a background asyncio loop for HaAgent's sync runtime.
- Create `src/haagent/tools/mcp_tools.py`: `list_mcp_resources` and `read_mcp_resource` handlers.
- Modify `pyproject.toml`: add `mcp>=1,<2`.
- Modify `src/haagent/tools/registry.py`: add runtime registry view and MCP resource tool definitions.
- Modify `src/haagent/tools/router.py`: accept runtime registry and MCP runtime, validate/dispatch dynamic MCP tools.
- Modify `src/haagent/context/builder.py`: accept runtime registry for allowed tool validation and task metadata.
- Modify `src/haagent/context/messages.py`: render allowed tool descriptions from runtime registry.
- Modify `src/haagent/runtime/run_turns.py`: export schemas from runtime registry.
- Modify `src/haagent/runtime/orchestrator.py`: pass runtime registry and MCP runtime into router/context/turn loop.
- Modify `src/haagent/runtime/chat_turn.py`: carry MCP runtime/registry through `ChatTurnRequest`.
- Modify `src/haagent/runtime/chat_session.py`: load MCP config, start/close runtime, expose status.
- Modify `src/haagent/app/assistant_service.py`: expose MCP status to the TUI layer.
- Modify `src/haagent/tui/commands.py` and `src/haagent/tui/app.py`: add `/mcp` status command.
- Create `tests/fixtures/fake_mcp_server.py`: real stdio MCP server for integration tests.
- Create `tests/test_mcp_settings.py`: config parser tests.
- Create `tests/test_mcp_runtime.py`: client/runtime tests.
- Extend `tests/test_tool_registry.py`, `tests/test_tool_router.py`, `tests/test_chat_turn.py`, `tests/test_tui_app.py`.

---

### Task 1: MCP Config Types And Settings Loader

**Files:**
- Create: `src/haagent/mcp/__init__.py`
- Create: `src/haagent/mcp/types.py`
- Create: `src/haagent/mcp/settings.py`
- Modify: `pyproject.toml`
- Test: `tests/test_mcp_settings.py`

**Interfaces:**
- Produces: `McpSettings`, `McpStdioServerConfig`, `McpHttpServerConfig`, `McpSettingsError`
- Produces: `user_mcp_settings_path() -> Path`
- Produces: `load_mcp_settings(config_path: Path | None = None) -> McpSettings`
- Later tasks consume `McpSettings.servers` and `McpSettings.tool_risks`

- [ ] **Step 1: Write failing settings tests**

```python
"""
tests/test_mcp_settings.py - MCP 配置解析测试

验证用户级 MCP 配置的缺省、stdio/http 解析和风险等级校验。
"""

import json

import pytest

from haagent.mcp.settings import McpSettingsError, load_mcp_settings
from haagent.mcp.types import McpHttpServerConfig, McpStdioServerConfig


def test_missing_mcp_settings_returns_empty(tmp_path):
    settings = load_mcp_settings(tmp_path / "missing.json")

    assert settings.servers == {}
    assert settings.tool_risks == {}


def test_loads_stdio_and_http_servers(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "local": {"type": "stdio", "command": "uvx", "args": ["demo"], "env": {"TOKEN": "secret"}},
                    "remote": {"type": "http", "url": "http://127.0.0.1:8765/mcp", "headers": {"Authorization": "Bearer secret"}},
                },
                "tool_risks": {"local.echo": "medium"},
            },
        ),
        encoding="utf-8",
    )

    settings = load_mcp_settings(path)

    assert isinstance(settings.servers["local"], McpStdioServerConfig)
    assert settings.servers["local"].command == "uvx"
    assert settings.servers["local"].args == ["demo"]
    assert isinstance(settings.servers["remote"], McpHttpServerConfig)
    assert settings.servers["remote"].url == "http://127.0.0.1:8765/mcp"
    assert settings.tool_risks == {"local.echo": "medium"}


def test_rejects_unknown_risk_level(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"servers": {}, "tool_risks": {"local.echo": "trusted"}}),
        encoding="utf-8",
    )

    with pytest.raises(McpSettingsError, match="invalid MCP tool risk"):
        load_mcp_settings(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_settings.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'haagent.mcp'`.

- [ ] **Step 3: Add dependency**

Modify `pyproject.toml` dependencies:

```toml
dependencies = [
    "httpx>=0.27.0",
    "keyring>=25.0.0",
    "mcp>=1,<2",
    "pyyaml>=6.0.0",
    "rich>=13.0.0",
    "textual>=0.80.0",
]
```

- [ ] **Step 4: Implement types and loader**

`src/haagent/mcp/types.py`:

```python
"""
src/haagent/mcp/types.py - MCP 配置与运行期元数据类型

定义 HaAgent 作为 MCP client 使用的 server 配置、工具资源元数据和连接状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


McpRiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class McpStdioServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    type: Literal["stdio"] = "stdio"


@dataclass(frozen=True)
class McpHttpServerConfig:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    type: Literal["http"] = "http"


McpServerConfig = McpStdioServerConfig | McpHttpServerConfig


@dataclass(frozen=True)
class McpSettings:
    servers: dict[str, McpServerConfig] = field(default_factory=dict)
    tool_risks: dict[str, McpRiskLevel] = field(default_factory=dict)


@dataclass(frozen=True)
class McpToolInfo:
    server_name: str
    name: str
    description: str
    input_schema: dict[str, object]
    risk_level: McpRiskLevel = "high"


@dataclass(frozen=True)
class McpResourceInfo:
    server_name: str
    uri: str
    name: str | None = None
    description: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class McpConnectionStatus:
    name: str
    state: Literal["configured", "connected", "failed"]
    detail: str = ""
    tools: list[McpToolInfo] = field(default_factory=list)
    resources: list[McpResourceInfo] = field(default_factory=list)
```

`src/haagent/mcp/settings.py`:

```python
"""
src/haagent/mcp/settings.py - 用户级 MCP 配置加载

读取并校验 ~/.haagent/mcp.json，返回不含运行期连接状态的配置对象。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from haagent.models.provider_profile import user_config_dir
from haagent.mcp.types import McpHttpServerConfig, McpSettings, McpStdioServerConfig


class McpSettingsError(Exception):
    """MCP 配置损坏或不可解析时抛出。"""


def user_mcp_settings_path() -> Path:
    return user_config_dir() / "mcp.json"


def load_mcp_settings(config_path: Path | None = None) -> McpSettings:
    path = config_path or user_mcp_settings_path()
    if not path.exists():
        return McpSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise McpSettingsError(f"invalid MCP settings JSON: {error}") from error
    if not isinstance(raw, dict):
        raise McpSettingsError("MCP settings must be a JSON object")
    return McpSettings(
        servers=_parse_servers(raw.get("servers", {})),
        tool_risks=_parse_tool_risks(raw.get("tool_risks", {})),
    )


def _parse_servers(value: object) -> dict[str, McpStdioServerConfig | McpHttpServerConfig]:
    if not isinstance(value, dict):
        raise McpSettingsError("MCP servers must be an object")
    servers: dict[str, McpStdioServerConfig | McpHttpServerConfig] = {}
    for name, raw_config in value.items():
        if not isinstance(name, str) or not name.strip():
            raise McpSettingsError("MCP server name must be a non-empty string")
        if not isinstance(raw_config, dict):
            raise McpSettingsError(f"MCP server {name} must be an object")
        config_type = raw_config.get("type")
        if config_type == "stdio":
            command = _required_string(raw_config, "command", f"MCP server {name}")
            servers[name] = McpStdioServerConfig(
                name=name,
                command=command,
                args=_string_list(raw_config.get("args", []), f"MCP server {name} args"),
                env=_string_map(raw_config.get("env", {}), f"MCP server {name} env"),
                cwd=_optional_string(raw_config.get("cwd"), f"MCP server {name} cwd"),
            )
        elif config_type == "http":
            servers[name] = McpHttpServerConfig(
                name=name,
                url=_required_string(raw_config, "url", f"MCP server {name}"),
                headers=_string_map(raw_config.get("headers", {}), f"MCP server {name} headers"),
            )
        else:
            raise McpSettingsError(f"unsupported MCP server type for {name}: {config_type!r}")
    return servers


def _parse_tool_risks(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise McpSettingsError("MCP tool_risks must be an object")
    risks: dict[str, str] = {}
    for key, risk in value.items():
        if not isinstance(key, str) or "." not in key:
            raise McpSettingsError("MCP tool risk key must use <server>.<tool>")
        if risk not in {"low", "medium", "high"}:
            raise McpSettingsError(f"invalid MCP tool risk for {key}: {risk!r}")
        risks[key] = risk
    return risks


def _required_string(raw: dict[str, Any], field: str, owner: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise McpSettingsError(f"{owner} requires string field {field}")
    return value


def _optional_string(value: object, owner: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise McpSettingsError(f"{owner} must be a string when provided")
    return value


def _string_list(value: object, owner: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise McpSettingsError(f"{owner} must be a list of strings")
    return list(value)


def _string_map(value: object, owner: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise McpSettingsError(f"{owner} must be an object")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise McpSettingsError(f"{owner} must contain only string values")
    return dict(value)
```

`src/haagent/mcp/__init__.py`:

```python
"""
src/haagent/mcp/__init__.py - MCP client 集成入口

导出 HaAgent MCP client 配置、连接管理和运行期适配的公共类型。
"""
```

- [ ] **Step 5: Run settings tests**

Run: `uv run pytest tests/test_mcp_settings.py -q`

Expected: PASS.

---

### Task 2: Async MCP Client Manager And Sync Runtime Wrapper

**Files:**
- Create: `src/haagent/mcp/client.py`
- Create: `src/haagent/mcp/runtime.py`
- Create: `tests/fixtures/fake_mcp_server.py`
- Test: `tests/test_mcp_runtime.py`

**Interfaces:**
- Consumes: `McpSettings`, `McpServerConfig`, `McpToolInfo`, `McpResourceInfo`, `McpConnectionStatus`
- Produces: `McpClientManager.connect_all()`, `close()`, `list_statuses()`, `list_tools()`, `list_resources()`, `call_tool()`, `read_resource()`
- Produces: `SyncMcpRuntime.start()`, `close()`, `call_tool()`, `read_resource()`, `list_statuses()`, `list_tools()`, `list_resources()`
- Later tasks use only `SyncMcpRuntime` from synchronous HaAgent runtime code.

- [ ] **Step 1: Write fake MCP server fixture**

`tests/fixtures/fake_mcp_server.py`:

```python
"""
tests/fixtures/fake_mcp_server.py - 测试用 stdio MCP server

提供 echo 工具和 demo resource，供 HaAgent MCP client 集成测试连接。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("haagent-fixture")


@server.tool()
def echo(text: str) -> str:
    return f"echo:{text}"


@server.resource("fixture://hello")
def hello_resource() -> str:
    return "hello from fixture"


if __name__ == "__main__":
    server.run("stdio")
```

- [ ] **Step 2: Write failing runtime tests**

`tests/test_mcp_runtime.py`:

```python
"""
tests/test_mcp_runtime.py - MCP 运行期连接测试

验证同步 HaAgent runtime 可以通过后台事件循环连接和调用异步 MCP server。
"""

from pathlib import Path

from haagent.mcp.runtime import SyncMcpRuntime
from haagent.mcp.types import McpSettings, McpStdioServerConfig


def test_sync_mcp_runtime_discovers_and_calls_stdio_tool():
    server_path = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
    runtime = SyncMcpRuntime(
        McpSettings(
            servers={
                "fixture": McpStdioServerConfig(
                    name="fixture",
                    command="python",
                    args=[str(server_path)],
                ),
            },
        ),
    )

    try:
        runtime.start()

        tools = runtime.list_tools()
        assert [tool.name for tool in tools] == ["echo"]
        assert tools[0].server_name == "fixture"
        assert runtime.call_tool("fixture", "echo", {"text": "hi"}) == "echo:hi"
        assert runtime.read_resource("fixture", "fixture://hello") == "hello from fixture"
    finally:
        runtime.close()


def test_sync_mcp_runtime_records_failed_server_without_raising():
    runtime = SyncMcpRuntime(
        McpSettings(
            servers={
                "missing": McpStdioServerConfig(
                    name="missing",
                    command="python",
                    args=["does-not-exist.py"],
                ),
            },
        ),
    )

    try:
        runtime.start()

        statuses = runtime.list_statuses()
        assert statuses[0].name == "missing"
        assert statuses[0].state == "failed"
        assert "failed" in statuses[0].detail.lower() or statuses[0].detail
    finally:
        runtime.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_runtime.py -q`

Expected: FAIL because `haagent.mcp.runtime` does not exist.

- [ ] **Step 4: Implement client manager**

`src/haagent/mcp/client.py`:

```python
"""
src/haagent/mcp/client.py - 异步 MCP client manager

连接 stdio 和 Streamable HTTP MCP server，并暴露工具、资源和调用接口。
"""

from __future__ import annotations

import contextlib
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ReadResourceResult

from haagent.mcp.types import (
    McpConnectionStatus,
    McpHttpServerConfig,
    McpResourceInfo,
    McpServerConfig,
    McpSettings,
    McpStdioServerConfig,
    McpToolInfo,
)


class McpServerNotConnectedError(Exception):
    """MCP server 未连接或连接已丢失时抛出。"""


class McpClientManager:
    def __init__(self, settings: McpSettings) -> None:
        self._settings = settings
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: list[AsyncExitStack] = []
        self._tools: list[McpToolInfo] = []
        self._resources: list[McpResourceInfo] = []
        self._statuses: dict[str, McpConnectionStatus] = {
            name: McpConnectionStatus(name=name, state="configured")
            for name in settings.servers
        }

    async def connect_all(self) -> None:
        for name, config in self._settings.servers.items():
            try:
                if isinstance(config, McpStdioServerConfig):
                    await self._connect_stdio(name, config)
                elif isinstance(config, McpHttpServerConfig):
                    await self._connect_http(name, config)
            except Exception as error:
                self._statuses[name] = McpConnectionStatus(
                    name=name,
                    state="failed",
                    detail=_redacted_error(error),
                )

    async def close(self) -> None:
        while self._stacks:
            stack = self._stacks.pop()
            with contextlib.suppress(Exception, BaseException):
                await stack.aclose()
        self._sessions.clear()

    def list_statuses(self) -> list[McpConnectionStatus]:
        return list(self._statuses.values())

    def list_tools(self) -> list[McpToolInfo]:
        return list(self._tools)

    def list_resources(self) -> list[McpResourceInfo]:
        return list(self._resources)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        session = self._session(server_name)
        result = await session.call_tool(tool_name, arguments)
        return _stringify_tool_result(result)

    async def read_resource(self, server_name: str, uri: str) -> str:
        session = self._session(server_name)
        result = await session.read_resource(uri)
        return _stringify_resource_result(result)

    async def _connect_stdio(self, name: str, config: McpStdioServerConfig) -> None:
        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env or None,
            cwd=config.cwd,
        )
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        await self._register_session(name, stack, read_stream, write_stream)

    async def _connect_http(self, name: str, config: McpHttpServerConfig) -> None:
        stack = AsyncExitStack()
        read_stream, write_stream, _ = await stack.enter_async_context(
            streamable_http_client(config.url, headers=config.headers or None),
        )
        await self._register_session(name, stack, read_stream, write_stream)

    async def _register_session(self, name: str, stack: AsyncExitStack, read_stream: Any, write_stream: Any) -> None:
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        self._sessions[name] = session
        self._stacks.append(stack)
        tools_result = await session.list_tools()
        tools = [
            McpToolInfo(
                server_name=name,
                name=tool.name,
                description=tool.description or f"MCP tool {tool.name}",
                input_schema=_object_schema(tool.inputSchema),
                risk_level=self._settings.tool_risks.get(f"{name}.{tool.name}", "high"),
            )
            for tool in tools_result.tools
        ]
        resources: list[McpResourceInfo] = []
        with contextlib.suppress(Exception):
            resources_result = await session.list_resources()
            resources = [
                McpResourceInfo(
                    server_name=name,
                    uri=str(resource.uri),
                    name=resource.name,
                    description=resource.description,
                    mime_type=resource.mimeType,
                )
                for resource in resources_result.resources
            ]
        self._tools.extend(tools)
        self._resources.extend(resources)
        self._statuses[name] = McpConnectionStatus(
            name=name,
            state="connected",
            tools=tools,
            resources=resources,
        )

    def _session(self, server_name: str) -> ClientSession:
        session = self._sessions.get(server_name)
        if session is None:
            raise McpServerNotConnectedError(f"MCP server is not connected: {server_name}")
        return session


def _object_schema(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) and value.get("type", "object") == "object" else {"type": "object", "properties": {}}


def _stringify_tool_result(result: CallToolResult) -> str:
    return "\n".join(str(item.text) for item in result.content if hasattr(item, "text"))


def _stringify_resource_result(result: ReadResourceResult) -> str:
    parts: list[str] = []
    for item in result.contents:
        text = getattr(item, "text", None)
        blob = getattr(item, "blob", None)
        if text is not None:
            parts.append(str(text))
        elif blob is not None:
            parts.append(str(blob))
    return "\n".join(parts)


def _redacted_error(error: Exception) -> str:
    return str(error)
```

- [ ] **Step 5: Implement sync runtime wrapper**

`src/haagent/mcp/runtime.py`:

```python
"""
src/haagent/mcp/runtime.py - 同步运行期 MCP 适配

为 HaAgent 的同步 ToolRouter 提供后台 asyncio loop 上的 MCP 调用能力。
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Coroutine, TypeVar

from haagent.mcp.client import McpClientManager
from haagent.mcp.types import McpConnectionStatus, McpResourceInfo, McpSettings, McpToolInfo


T = TypeVar("T")


class SyncMcpRuntime:
    def __init__(self, settings: McpSettings) -> None:
        self._settings = settings
        self._manager = McpClientManager(settings)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        ready: Future[None] = Future()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            ready.set_result(None)
            loop.run_forever()

        self._thread = threading.Thread(target=run_loop, name="haagent-mcp", daemon=True)
        self._thread.start()
        ready.result(timeout=5)
        self._submit(self._manager.connect_all())

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            self._submit(self._manager.close())
        finally:
            loop = self._loop
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._loop = None
            self._thread = None

    def list_statuses(self) -> list[McpConnectionStatus]:
        return self._manager.list_statuses()

    def list_tools(self) -> list[McpToolInfo]:
        return self._manager.list_tools()

    def list_resources(self) -> list[McpResourceInfo]:
        return self._manager.list_resources()

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        return self._submit(self._manager.call_tool(server_name, tool_name, arguments))

    def read_resource(self, server_name: str, uri: str) -> str:
        return self._submit(self._manager.read_resource(server_name, uri))

    def _submit(self, coroutine: Coroutine[Any, Any, T]) -> T:
        if self._loop is None:
            raise RuntimeError("MCP runtime has not started")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=30)
```

- [ ] **Step 6: Run runtime tests**

Run: `uv run pytest tests/test_mcp_runtime.py -q`

Expected: PASS.

---

### Task 3: Runtime Tool Registry View

**Files:**
- Modify: `src/haagent/tools/registry.py`
- Test: `tests/test_tool_registry.py`

**Interfaces:**
- Produces: `ToolRuntimeRegistry`
- Produces: `default_tool_runtime_registry(dynamic_tools: dict[str, ToolDefinition] | None = None) -> ToolRuntimeRegistry`
- Updates: `export_tool_schemas(names: list[str], registry: ToolRuntimeRegistry | None = None) -> list[dict[str, Any]]`
- Later tasks pass `ToolRuntimeRegistry` into context builder, run loop, router.

- [ ] **Step 1: Write failing registry tests**

Append to `tests/test_tool_registry.py`:

```python
def test_runtime_registry_exports_dynamic_mcp_tool_schema():
    dynamic = ToolDefinition(
        name="mcp__fixture__echo",
        description="Echo text",
        risk_level="high",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    registry = default_tool_runtime_registry({"mcp__fixture__echo": dynamic})

    schemas = export_tool_schemas(["mcp__fixture__echo"], registry=registry)

    assert schemas == [dynamic.to_model_schema()]


def test_runtime_registry_does_not_mutate_global_tool_registry():
    dynamic = ToolDefinition(
        name="mcp__fixture__echo",
        description="Echo text",
        risk_level="high",
        parameters={"type": "object", "properties": {}},
    )
    default_tool_runtime_registry({"mcp__fixture__echo": dynamic})

    assert "mcp__fixture__echo" not in TOOL_REGISTRY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tool_registry.py::test_runtime_registry_exports_dynamic_mcp_tool_schema tests/test_tool_registry.py::test_runtime_registry_does_not_mutate_global_tool_registry -q`

Expected: FAIL because `ToolRuntimeRegistry` helpers do not exist.

- [ ] **Step 3: Implement registry view**

Add to `src/haagent/tools/registry.py` after `ToolDefinition`:

```python
@dataclass(frozen=True)
class ToolRuntimeRegistry:
    static_tools: dict[str, ToolDefinition]
    dynamic_tools: dict[str, ToolDefinition]

    def get(self, name: str) -> ToolDefinition:
        if name in self.dynamic_tools:
            return self.dynamic_tools[name]
        return get_tool_definition(name)

    def has(self, name: str) -> bool:
        return name in self.dynamic_tools or name in self.static_tools

    def allowed_definitions(self, names: list[str]) -> list[ToolDefinition]:
        return [self.get(name) for name in names]


def default_tool_runtime_registry(
    dynamic_tools: dict[str, ToolDefinition] | None = None,
) -> ToolRuntimeRegistry:
    return ToolRuntimeRegistry(
        static_tools=TOOL_REGISTRY,
        dynamic_tools=dict(dynamic_tools or {}),
    )
```

Update existing helpers:

```python
def allowed_tool_definitions(
    names: list[str],
    registry: ToolRuntimeRegistry | None = None,
) -> list[ToolDefinition]:
    runtime_registry = registry or default_tool_runtime_registry()
    return runtime_registry.allowed_definitions(names)


def export_tool_schemas(
    names: list[str],
    registry: ToolRuntimeRegistry | None = None,
) -> list[dict[str, Any]]:
    return [
        definition.to_model_schema()
        for definition in allowed_tool_definitions(names, registry=registry)
    ]
```

- [ ] **Step 4: Add MCP resource tool definitions**

Add `list_mcp_resources` to `TOOL_REGISTRY` with `risk_level="low"` and `read_mcp_resource` with `risk_level="medium"`:

```python
"list_mcp_resources": ToolDefinition(
    name="list_mcp_resources",
    description="List resources exposed by connected MCP servers.",
    risk_level="low",
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
),
"read_mcp_resource": ToolDefinition(
    name="read_mcp_resource",
    description="Read one resource from a connected MCP server by server name and URI.",
    risk_level="medium",
    parameters={
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "uri": {"type": "string"},
        },
        "required": ["server", "uri"],
        "additionalProperties": False,
    },
),
```

- [ ] **Step 5: Run registry tests**

Run: `uv run pytest tests/test_tool_registry.py -q`

Expected: PASS.

---

### Task 4: MCP Tool Handlers And ToolRouter Dispatch

**Files:**
- Create: `src/haagent/tools/mcp_tools.py`
- Modify: `src/haagent/tools/router.py`
- Test: `tests/test_tool_router.py`

**Interfaces:**
- Consumes: `SyncMcpRuntime`
- Produces: `mcp_tool_handler(tool_name: str, args: dict[str, Any], runtime: SyncMcpRuntime) -> dict[str, Any]`
- Produces: `list_mcp_resources(args, runtime) -> dict[str, Any]`
- Produces: `read_mcp_resource(args, runtime) -> dict[str, Any]`
- Updates: `ToolRouter.__init__(..., tool_registry: ToolRuntimeRegistry | None = None, mcp_runtime: SyncMcpRuntime | None = None)`

- [ ] **Step 1: Write failing ToolRouter tests**

Append focused tests to `tests/test_tool_router.py`:

```python
class FakeMcpRuntime:
    def __init__(self):
        self.calls = []

    def call_tool(self, server_name, tool_name, arguments):
        self.calls.append((server_name, tool_name, arguments))
        return "echo:hi"

    def list_resources(self):
        return []

    def read_resource(self, server_name, uri):
        return "resource text"


def test_tool_router_dispatches_dynamic_mcp_tool_through_trace(tmp_path):
    writer = EpisodeWriter.create(tmp_path / "runs", tmp_path / "task.yaml")
    dynamic = ToolDefinition(
        name="mcp__fixture__echo",
        description="Echo text",
        risk_level="high",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    runtime = FakeMcpRuntime()
    router = ToolRouter(
        ["mcp__fixture__echo"],
        writer,
        workspace_root=tmp_path,
        approved_tools=["mcp__fixture__echo"],
        tool_registry=default_tool_runtime_registry({"mcp__fixture__echo": dynamic}),
        mcp_runtime=runtime,
    )

    result = router.dispatch("mcp__fixture__echo", {"text": "hi"})

    assert result == {"ok": True, "output": "echo:hi"}
    assert runtime.calls == [("fixture", "echo", {"text": "hi"})]


def test_dynamic_mcp_tool_defaults_to_high_risk_approval(tmp_path):
    writer = EpisodeWriter.create(tmp_path / "runs", tmp_path / "task.yaml")
    dynamic = ToolDefinition(
        name="mcp__fixture__echo",
        description="Echo text",
        risk_level="high",
        parameters={"type": "object", "properties": {}},
    )
    router = ToolRouter(
        ["mcp__fixture__echo"],
        writer,
        workspace_root=tmp_path,
        approval_allowed_tools=["mcp__fixture__echo"],
        tool_registry=default_tool_runtime_registry({"mcp__fixture__echo": dynamic}),
        mcp_runtime=FakeMcpRuntime(),
    )

    result = router.dispatch("mcp__fixture__echo", {})

    assert result["ok"] is False
    assert result["error"]["type"] == "approval_required"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tool_router.py::test_tool_router_dispatches_dynamic_mcp_tool_through_trace tests/test_tool_router.py::test_dynamic_mcp_tool_defaults_to_high_risk_approval -q`

Expected: FAIL because router has no dynamic registry or MCP runtime.

- [ ] **Step 3: Implement MCP tool handlers**

`src/haagent/tools/mcp_tools.py`:

```python
"""
src/haagent/tools/mcp_tools.py - MCP 工具适配器

把 MCP resources 和动态 MCP tools 适配成 ToolRouter 可调用的同步 handler。
"""

from __future__ import annotations

import re
from typing import Any

from haagent.mcp.runtime import SyncMcpRuntime
from haagent.tools.base import tool_error


_MCP_TOOL_RE = re.compile(r"^mcp__(?P<server>[^_][A-Za-z0-9_]*?)__(?P<tool>.+)$")


def list_mcp_resources(args: dict[str, Any], runtime: SyncMcpRuntime | None) -> dict[str, Any]:
    del args
    if runtime is None:
        return tool_error("mcp_unavailable", "MCP runtime is not available")
    resources = [
        {
            "server": resource.server_name,
            "uri": resource.uri,
            "name": resource.name,
            "description": resource.description,
            "mime_type": resource.mime_type,
        }
        for resource in runtime.list_resources()
    ]
    return {"ok": True, "resources": resources}


def read_mcp_resource(args: dict[str, Any], runtime: SyncMcpRuntime | None) -> dict[str, Any]:
    if runtime is None:
        return tool_error("mcp_unavailable", "MCP runtime is not available")
    return {"ok": True, "output": runtime.read_resource(args["server"], args["uri"])}


def run_mcp_tool(tool_name: str, args: dict[str, Any], runtime: SyncMcpRuntime | None) -> dict[str, Any]:
    if runtime is None:
        return tool_error("mcp_unavailable", "MCP runtime is not available")
    match = _MCP_TOOL_RE.match(tool_name)
    if match is None:
        return tool_error("invalid_mcp_tool_name", f"invalid MCP tool name: {tool_name}")
    return {
        "ok": True,
        "output": runtime.call_tool(match.group("server"), match.group("tool"), args),
    }
```

- [ ] **Step 4: Update ToolRouter to use runtime registry**

Modify `ToolRouter.__init__`:

```python
        tool_registry: ToolRuntimeRegistry | None = None,
        mcp_runtime: SyncMcpRuntime | None = None,
```

Set fields:

```python
        self._tool_registry = tool_registry or default_tool_runtime_registry()
        self._mcp_runtime = mcp_runtime
```

Add handlers:

```python
            "list_mcp_resources": lambda args: list_mcp_resources(args, self._mcp_runtime),
            "read_mcp_resource": lambda args: read_mcp_resource(args, self._mcp_runtime),
```

Change policy and validation references from `TOOL_REGISTRY[tool_name]` to:

```python
tool_definition = self._tool_registry.get(tool_name)
policy_decision = evaluate_tool_call(
    tool_definition,
    approval_allowed_tools=self._approval_allowed_tools,
    approved_tools=self._approved_tools,
)
```

Route dynamic MCP tools before normal handler lookup:

```python
elif tool_name.startswith("mcp__"):
    result = run_mcp_tool(tool_name, args, self._mcp_runtime)
else:
    result = self._run_handler(tool_name, args, interaction_handler)
```

Update `_validate_args(tool_name, args)` to accept a registry parameter and read `registry.get(tool_name).parameters`.

Update `_assert_registry_alignment()` to require handlers only for static tools in `TOOL_REGISTRY`, not dynamic MCP tools.

- [ ] **Step 5: Run ToolRouter tests**

Run: `uv run pytest tests/test_tool_router.py -q`

Expected: PASS.

---

### Task 5: Pass Runtime Registry Through Context And Turn Loop

**Files:**
- Modify: `src/haagent/context/builder.py`
- Modify: `src/haagent/context/messages.py`
- Modify: `src/haagent/runtime/run_turns.py`
- Modify: `src/haagent/runtime/orchestrator.py`
- Modify: `src/haagent/runtime/chat_turn.py`
- Test: `tests/test_chat_turn.py`

**Interfaces:**
- Consumes: `ToolRuntimeRegistry`
- Updates: `ContextBuilder(..., tool_registry: ToolRuntimeRegistry | None = None)`
- Updates: `build_task_message(..., tool_registry: ToolRuntimeRegistry | None = None)`
- Updates: `TurnLoopDependencies.tool_registry`
- Updates: `RunOrchestrator(..., tool_registry: ToolRuntimeRegistry | None = None, mcp_runtime: SyncMcpRuntime | None = None)`
- Updates: `ChatTurnRequest.tool_registry`, `ChatTurnRequest.mcp_runtime`, `ChatTurnRequest.mcp_tool_names`

- [ ] **Step 1: Write failing chat turn test**

Append to `tests/test_chat_turn.py`:

```python
def test_chat_turn_allows_dynamic_mcp_tool_in_task_contract(tmp_path):
    dynamic = ToolDefinition(
        name="mcp__fixture__echo",
        description="Echo text",
        risk_level="high",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    registry = default_tool_runtime_registry({"mcp__fixture__echo": dynamic})
    seen_allowed_tools = []

    class CapturingOrchestrator:
        def __init__(self, **kwargs):
            assert kwargs["tool_registry"] is registry

        def run(self, task_path):
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            seen_allowed_tools.extend(task["allowed_tools"])
            return _completed_run_result(tmp_path)

    ChatTurnRunner().run(
        ChatTurnRequest(
            prompt="use echo",
            workspace_root=tmp_path,
            runs_root=tmp_path / "runs",
            model_gateway=FakeModelGateway([]),
            max_turns=1,
            tool_registry=registry,
            mcp_tool_names=["mcp__fixture__echo"],
            orchestrator_factory=CapturingOrchestrator,
        ),
    )

    assert "mcp__fixture__echo" in seen_allowed_tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_turn.py::test_chat_turn_allows_dynamic_mcp_tool_in_task_contract -q`

Expected: FAIL because `ChatTurnRequest` has no MCP fields.

- [ ] **Step 3: Modify context and message builders**

Update `ContextBuilder.__init__` to store:

```python
self._tool_registry = tool_registry or default_tool_runtime_registry()
```

Update `_validate_tools`:

```python
unknown_tools = [tool for tool in self._task.allowed_tools if not self._tool_registry.has(tool)]
```

Update call to `build_task_message`:

```python
tool_registry=self._tool_registry,
```

Update `build_task_message` signature:

```python
tool_registry: ToolRuntimeRegistry | None = None,
```

Inside `build_task_message`:

```python
runtime_registry = tool_registry or default_tool_runtime_registry()
...
lines.append(f"- {tool}: {runtime_registry.get(tool).description}")
```

- [ ] **Step 4: Modify run loop and orchestrator**

Add `tool_registry: ToolRuntimeRegistry` to `TurnLoopDependencies`.

Update schema export:

```python
tool_schemas = [] if state.final_response_requested else export_tool_schemas(
    deps.allowed_tools,
    registry=deps.tool_registry,
)
```

Update `RunOrchestrator.__init__` to accept and store `tool_registry` and `mcp_runtime`.

Pass them into `ToolRouter`, `prepare_initial_messages`, and `TurnLoopDependencies`.

- [ ] **Step 5: Modify chat turn request and task YAML writer**

Add fields to `ChatTurnRequest`:

```python
tool_registry: ToolRuntimeRegistry | None = None
mcp_runtime: SyncMcpRuntime | None = None
mcp_tool_names: list[str] = field(default_factory=list)
```

Update `write_chat_task_yaml` signature:

```python
mcp_tool_names: list[str] | None = None,
```

Append:

```python
allowed_tools.extend(mcp_tool_names or [])
if mcp_tool_names:
    allowed_tools.extend(["list_mcp_resources", "read_mcp_resource"])
```

Pass `tool_registry` and `mcp_runtime` to the orchestrator factory.

- [ ] **Step 6: Run chat/context tests**

Run: `uv run pytest tests/test_chat_turn.py tests/test_tool_registry.py tests/test_tool_router.py -q`

Expected: PASS.

---

### Task 6: AgentSession And TUI MCP Status

**Files:**
- Modify: `src/haagent/runtime/chat_session.py`
- Modify: `src/haagent/app/assistant_service.py`
- Modify: `src/haagent/tui/commands.py`
- Modify: `src/haagent/tui/app.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `load_mcp_settings()`, `SyncMcpRuntime`
- Produces: `AgentSession.mcp_status() -> dict[str, object]`
- Produces: `AssistantService.get_mcp_status() -> dict[str, object]`
- Produces: `/mcp` slash command status output

- [ ] **Step 1: Write failing service/TUI tests**

Append to relevant tests:

```python
def test_tui_slash_command_registry_includes_mcp():
    registry = command_registry()

    assert registry.get("mcp") is not None


def test_assistant_service_mcp_status_without_session(tmp_path):
    service = AssistantService(workspace_root=tmp_path, runs_root=tmp_path / ".runs")

    status = service.get_mcp_status()

    assert status["configured_count"] == 0
    assert status["servers"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tui_app.py::test_tui_slash_command_registry_includes_mcp tests/test_assistant_service.py::test_assistant_service_mcp_status_without_session -q`

Expected: FAIL because `/mcp` and service status do not exist.

- [ ] **Step 3: Start MCP runtime in AgentSession**

In `AgentSession.__init__`:

```python
self._mcp_settings = load_mcp_settings()
self._mcp_runtime = SyncMcpRuntime(self._mcp_settings)
self._mcp_runtime.start()
self._mcp_tool_names = [
    f"mcp__{_sanitize_tool_segment(tool.server_name)}__{_sanitize_tool_segment(tool.name)}"
    for tool in self._mcp_runtime.list_tools()
]
self._tool_registry = default_tool_runtime_registry(
    mcp_tool_definitions(self._mcp_runtime.list_tools()),
)
```

Create helper `mcp_tool_definitions(tools: list[McpToolInfo]) -> dict[str, ToolDefinition]` in `src/haagent/mcp/tool_adapter.py`.

Ensure `AgentSession.run_prompt_events` passes `tool_registry`, `mcp_runtime`, and `mcp_tool_names` into `ChatTurnRequest`.

Add `AgentSession.close()` that calls `self._mcp_runtime.close()`. TUI should call it where the app/session is already torn down; tests can call it directly.

- [ ] **Step 4: Add MCP status formatting**

In `AgentSession`:

```python
def mcp_status(self) -> dict[str, object]:
    statuses = self._mcp_runtime.list_statuses()
    return {
        "configured_count": len(statuses),
        "connected_count": sum(1 for item in statuses if item.state == "connected"),
        "failed_count": sum(1 for item in statuses if item.state == "failed"),
        "servers": [
            {
                "name": item.name,
                "state": item.state,
                "detail": item.detail,
                "tool_count": len(item.tools),
                "resource_count": len(item.resources),
            }
            for item in statuses
        ],
    }
```

In `AssistantService.get_mcp_status()`, return empty status before session creation and delegate to current session after creation.

- [ ] **Step 5: Add `/mcp` command**

Add command in `command_registry()`:

```python
SlashCommand("mcp", "Show configured MCP server status.")
```

In TUI command handler, route `/mcp` to service status and render:

```text
No MCP servers configured.
```

or:

```text
MCP servers:
- fixture: connected (tools: 1, resources: 1)
- broken: failed - <detail>
```

- [ ] **Step 6: Run TUI/service tests**

Run: `uv run pytest tests/test_tui_app.py tests/test_assistant_service.py -q`

Expected: PASS.

---

### Task 7: Integration Verification And Redaction

**Files:**
- Modify: `src/haagent/mcp/client.py`
- Modify: `src/haagent/mcp/settings.py`
- Modify: `src/haagent/runtime/episode.py` only if an explicit MCP connection summary writer is needed.
- Test: `tests/test_mcp_runtime.py`

**Interfaces:**
- Produces: `redact_mcp_secret_text(text: str, settings: McpSettings) -> str`
- Applies redaction to status details, connection errors, and any MCP setup event payloads.

- [ ] **Step 1: Write failing redaction test**

Append to `tests/test_mcp_runtime.py`:

```python
def test_mcp_status_redacts_configured_header_and_env_values():
    settings = McpSettings(
        servers={
            "local": McpStdioServerConfig(name="local", command="bad-secret-token", env={"TOKEN": "secret-token"}),
            "remote": McpHttpServerConfig(name="remote", url="http://example.invalid", headers={"Authorization": "Bearer secret-header"}),
        },
    )

    assert "secret-token" not in redact_mcp_secret_text("failed: secret-token", settings)
    assert "secret-header" not in redact_mcp_secret_text("failed: Bearer secret-header", settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_runtime.py::test_mcp_status_redacts_configured_header_and_env_values -q`

Expected: FAIL because redaction helper does not exist.

- [ ] **Step 3: Implement redaction helper**

Add to `src/haagent/mcp/settings.py`:

```python
def redact_mcp_secret_text(text: str, settings: McpSettings) -> str:
    redacted = text
    secrets: set[str] = set()
    for config in settings.servers.values():
        if isinstance(config, McpStdioServerConfig):
            secrets.update(value for value in config.env.values() if value)
        elif isinstance(config, McpHttpServerConfig):
            secrets.update(value for value in config.headers.values() if value)
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= 4:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted
```

Use this helper in `McpClientManager.connect_all()` when writing failed status details.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_mcp_settings.py tests/test_mcp_runtime.py tests/test_tool_router.py tests/test_tool_registry.py tests/test_chat_turn.py -q`

Expected: PASS.

- [ ] **Step 5: Run broad non-slow suite**

Run: `uv run pytest -m "not slow" -q`

Expected: PASS.

---

## Self-Review

- Spec coverage: client-only MCP, stdio/http, user config, dynamic registry, ToolRouter boundary, resource list/read, TUI `/mcp`, default high-risk policy, explicit `tool_risks`, structured errors, and redaction are each assigned to tasks.
- Type consistency: `McpSettings`, `SyncMcpRuntime`, `ToolRuntimeRegistry`, and `mcp__server__tool` naming are introduced before tasks that consume them.
- Known deliberate exclusions: project-level MCP config, MCP prompts/templates, CLI `mcp add/remove`, and `/mcp auth` are not implemented in this plan.
