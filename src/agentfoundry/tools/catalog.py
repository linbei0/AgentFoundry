"""
agentfoundry/tools/catalog.py - 工具目录

集中维护可暴露给 ContextBuilder 的工具名和一句话用途。
"""

from __future__ import annotations


TOOL_CATALOG = {
    "fake_tool": "deterministic test tool",
    "file_search": "search workspace text using ripgrep when available",
    "file_read": "read a workspace text file with offset and limit",
    "apply_patch": "replace unique text inside a workspace file",
    "shell": "run a shell command with timeout and captured output",
}
