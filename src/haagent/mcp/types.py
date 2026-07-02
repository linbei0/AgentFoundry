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
