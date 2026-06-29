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

from haagent.runtime.command import (
    CWD_GUIDANCE,
    build_output_summary,
    normalize_timeout,
    resolve_execution_cwd,
)
from haagent.runtime.path_policy import PathPolicy, default_path_policy, resolve_cwd_for_execution
from haagent.tools.base import tool_error


def code_run(args: dict[str, Any], workspace_root: Path, path_policy: PathPolicy | None = None) -> dict[str, Any]:
    code = args.get("code")
    if not isinstance(code, str) or not code:
        return tool_error("tool_argument_invalid", "code must be a non-empty string")

    cwd_arg = args.get("cwd")
    if cwd_arg is not None and not isinstance(cwd_arg, str):
        return tool_error("tool_argument_invalid", f"cwd must be a string; {CWD_GUIDANCE}")
    if path_policy is None:
        cwd_result = resolve_execution_cwd(cwd_arg, workspace_root)
    else:
        cwd_result = resolve_cwd_for_execution(cwd_arg, path_policy or default_path_policy(workspace_root))
    if isinstance(cwd_result, str):
        error_type = "path_policy_denied" if path_policy is not None else "tool_argument_invalid"
        return tool_error(error_type, cwd_result)

    timeout_result = normalize_timeout(args.get("timeout_seconds"))
    if isinstance(timeout_result, str):
        return tool_error("tool_argument_invalid", timeout_result)

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
            timeout=timeout_result,
        )
    except subprocess.TimeoutExpired as error:
        output = build_output_summary(
            _decode_timeout_output(error.stdout),
            _decode_timeout_output(error.stderr),
        )
        return {
            "status": "error",
            "exit_code": None,
            "stdout_excerpt": output["stdout_excerpt"],
            "stderr_excerpt": output["stderr_excerpt"],
            "stdout_truncated": output["stdout_truncated"],
            "stderr_truncated": output["stderr_truncated"],
            "truncated": output["truncated"],
            "timeout": True,
            "redacted": output["redacted"],
            "timeout_seconds": timeout_result,
            "script_path": script_path.relative_to(root).as_posix(),
            "error": {
                "type": "timeout",
                "message": f"python code timed out after {timeout_result} seconds",
            },
        }

    output = build_output_summary(completed.stdout, completed.stderr)
    result = {
        "status": "success" if completed.returncode == 0 else "error",
        "exit_code": completed.returncode,
        "stdout_excerpt": output["stdout_excerpt"],
        "stderr_excerpt": output["stderr_excerpt"],
        "stdout_truncated": output["stdout_truncated"],
        "stderr_truncated": output["stderr_truncated"],
        "truncated": output["truncated"],
        "timeout": False,
        "redacted": output["redacted"],
        "timeout_seconds": timeout_result,
        "script_path": script_path.relative_to(root).as_posix(),
    }
    if completed.returncode != 0:
        result["error"] = {
            "type": "code_run_failed",
            "message": f"python code exited with code {completed.returncode}",
        }
    return result


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
