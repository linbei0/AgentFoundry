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
