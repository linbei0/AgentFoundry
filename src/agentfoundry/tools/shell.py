"""
agentfoundry/tools/shell.py - shell 本地工具

执行命令并捕获 timeout、exit_code、stdout 和 stderr。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agentfoundry.tools.base import tool_error
from agentfoundry.tools.file_tools import resolve_workspace_path


def shell(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """运行 shell 命令，捕获 stdout/stderr/exit_code，并把失败结构化返回。"""
    command = args.get("command")
    if not isinstance(command, str) or not command:
        return tool_error("invalid_arguments", "command must be a non-empty string")

    cwd_arg = args.get("cwd", ".")
    if not isinstance(cwd_arg, str):
        return tool_error("invalid_arguments", "cwd must be a string")
    cwd = resolve_workspace_path(cwd_arg, workspace_root)
    if cwd is None:
        return tool_error("path_outside_workspace", "cwd must be inside workspace")

    timeout_seconds = float(args.get("timeout_seconds", 60))
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "status": "error",
            "exit_code": None,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
            "error": {
                "type": "timeout",
                "message": f"command timed out after {timeout_seconds} seconds",
            },
        }

    result = {
        "status": "success" if completed.returncode == 0 else "error",
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        result["error"] = {
            "type": "command_failed",
            "message": f"command exited with code {completed.returncode}",
        }
    return result
