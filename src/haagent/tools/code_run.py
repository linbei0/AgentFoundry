"""
haagent/tools/code_run.py - Python 脚本执行工具

把多行 Python 代码写入工作区临时脚本后执行，避免 shell 转义复杂脚本。
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from haagent.tools.base import tool_error
from haagent.tools.file_tools import resolve_workspace_path


CWD_GUIDANCE = 'cwd is relative to workspace_root; use "." or omit cwd for workspace root'
OUTPUT_EXCERPT_CHAR_LIMIT = 2400


def code_run(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    code = args.get("code")
    if not isinstance(code, str) or not code:
        return tool_error("tool_argument_invalid", "code must be a non-empty string")

    cwd_arg = args.get("cwd")
    if cwd_arg is not None and not isinstance(cwd_arg, str):
        return tool_error("tool_argument_invalid", f"cwd must be a string; {CWD_GUIDANCE}")
    cwd_result = _resolve_cwd(cwd_arg, workspace_root)
    if isinstance(cwd_result, dict):
        return cwd_result

    timeout_seconds = float(args.get("timeout_seconds", 60))
    if timeout_seconds <= 0:
        return tool_error("tool_argument_invalid", "timeout_seconds must be positive")

    root = workspace_root.resolve()
    tmp_dir = root / ".haagent-tmp"
    tmp_dir.mkdir(exist_ok=True)
    script_path = tmp_dir / f"code-run-{uuid.uuid4().hex[:12]}.py"
    script_path.write_text(code, encoding="utf-8")

    try:
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=cwd_result,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stdout_excerpt, stdout_truncated = _excerpt(_decode_timeout_output(error.stdout))
        stderr_excerpt, stderr_truncated = _excerpt(_decode_timeout_output(error.stderr))
        return {
            "status": "error",
            "exit_code": None,
            "stdout_excerpt": stdout_excerpt,
            "stderr_excerpt": stderr_excerpt,
            "truncated": stdout_truncated or stderr_truncated,
            "script_path": script_path.relative_to(root).as_posix(),
            "error": {
                "type": "timeout",
                "message": f"python code timed out after {timeout_seconds} seconds",
            },
        }

    stdout_excerpt, stdout_truncated = _excerpt(completed.stdout)
    stderr_excerpt, stderr_truncated = _excerpt(completed.stderr)
    result = {
        "status": "success" if completed.returncode == 0 else "error",
        "exit_code": completed.returncode,
        "stdout_excerpt": stdout_excerpt,
        "stderr_excerpt": stderr_excerpt,
        "truncated": stdout_truncated or stderr_truncated,
        "script_path": script_path.relative_to(root).as_posix(),
    }
    if completed.returncode != 0:
        result["error"] = {
            "type": "code_run_failed",
            "message": f"python code exited with code {completed.returncode}",
        }
    return result


def _resolve_cwd(cwd_arg: str | None, workspace_root: Path) -> Path | dict[str, Any]:
    if cwd_arg in (None, "."):
        cwd_arg = "."

    cwd = resolve_workspace_path(cwd_arg, workspace_root)
    if cwd is None:
        return tool_error("tool_argument_invalid", f"cwd must stay inside workspace_root; {CWD_GUIDANCE}")
    if not cwd.exists():
        return tool_error("tool_argument_invalid", f"cwd does not exist; {CWD_GUIDANCE}")
    if not cwd.is_dir():
        return tool_error("tool_argument_invalid", f"cwd must be a directory; {CWD_GUIDANCE}")
    return cwd


def _excerpt(value: str) -> tuple[str, bool]:
    truncated = len(value) > OUTPUT_EXCERPT_CHAR_LIMIT
    return value[:OUTPUT_EXCERPT_CHAR_LIMIT], truncated


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
