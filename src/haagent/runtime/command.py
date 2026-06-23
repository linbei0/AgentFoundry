"""
haagent/runtime/command.py - 统一命令执行器

封装本地进程执行边界、输出摘要和 subprocess.run 结果。
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CWD_GUIDANCE = 'cwd is relative to workspace_root; use "." or omit cwd for workspace root'
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 120.0
OUTPUT_EXCERPT_CHAR_LIMIT = 2400
REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_TOKEN = "[REDACTED_TOKEN]"
SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
KEY_VALUE_PATTERN = re.compile(
    r"\b(api[_-]?key|secret[_-]?key|access[_-]?token|password|credential)\b\s*[:=]\s*\S{4,}",
    re.IGNORECASE,
)
SECRET_ENV_NAME_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|credential)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommandResult:
    command: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_truncated: bool
    stderr_truncated: bool
    truncated: bool
    timeout: bool
    redacted: bool
    duration_seconds: float
    timeout_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_command(command: str, cwd: Path, timeout_seconds: float) -> CommandResult:
    """运行 shell 命令，并用统一结构表达执行结果。"""
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        output = build_output_summary(
            _decode_timeout_output(error.stdout),
            _decode_timeout_output(error.stderr),
        )
        return CommandResult(
            command=command,
            status="timeout",
            exit_code=None,
            stdout=output["stdout"],
            stderr=output["stderr"],
            stdout_excerpt=output["stdout_excerpt"],
            stderr_excerpt=output["stderr_excerpt"],
            stdout_truncated=output["stdout_truncated"],
            stderr_truncated=output["stderr_truncated"],
            truncated=output["truncated"],
            timeout=True,
            redacted=output["redacted"],
            duration_seconds=time.perf_counter() - started,
            timeout_seconds=timeout_seconds,
        )

    output = build_output_summary(completed.stdout, completed.stderr)
    return CommandResult(
        command=command,
        status="success" if completed.returncode == 0 else "failed",
        exit_code=completed.returncode,
        stdout=output["stdout"],
        stderr=output["stderr"],
        stdout_excerpt=output["stdout_excerpt"],
        stderr_excerpt=output["stderr_excerpt"],
        stdout_truncated=output["stdout_truncated"],
        stderr_truncated=output["stderr_truncated"],
        truncated=output["truncated"],
        timeout=False,
        redacted=output["redacted"],
        duration_seconds=time.perf_counter() - started,
        timeout_seconds=timeout_seconds,
    )


def resolve_execution_cwd(cwd_arg: str | None, workspace_root: Path) -> Path | str:
    """解析执行 cwd，确保结果留在 workspace root 内。"""
    if cwd_arg in (None, "."):
        cwd_arg = "."
    root = workspace_root.resolve()
    candidate = Path(cwd_arg)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        return f"cwd must stay inside workspace_root; {CWD_GUIDANCE}"
    if not resolved.exists():
        return f"cwd does not exist; {CWD_GUIDANCE}"
    if not resolved.is_dir():
        return f"cwd must be a directory; {CWD_GUIDANCE}"
    return resolved


def normalize_timeout(value: Any) -> float | str:
    """校验执行 timeout，省略时使用默认值，超过上限直接拒绝。"""
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "timeout_seconds must be a number"
    timeout_seconds = float(value)
    if timeout_seconds <= 0:
        return "timeout_seconds must be positive"
    if timeout_seconds > MAX_TIMEOUT_SECONDS:
        return f"timeout_seconds must be <= {int(MAX_TIMEOUT_SECONDS)}"
    return timeout_seconds


def build_output_summary(stdout: str, stderr: str) -> dict[str, Any]:
    """生成脱敏后的 stdout/stderr 摘要，避免工具结果暴露完整长输出。"""
    safe_stdout, stdout_redacted = redact_secret_like_text(stdout)
    safe_stderr, stderr_redacted = redact_secret_like_text(stderr)
    stdout_excerpt, stdout_truncated = _excerpt(safe_stdout)
    stderr_excerpt, stderr_truncated = _excerpt(safe_stderr)
    return {
        "stdout": safe_stdout,
        "stderr": safe_stderr,
        "stdout_excerpt": stdout_excerpt,
        "stderr_excerpt": stderr_excerpt,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "truncated": stdout_truncated or stderr_truncated,
        "redacted": stdout_redacted or stderr_redacted,
    }


def redact_secret_like_text(text: str) -> tuple[str, bool]:
    """按 secret-like 模式和当前环境中的敏感变量值脱敏。"""
    redacted = KEY_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED_SECRET}", text)
    redacted = SECRET_TOKEN_PATTERN.sub(REDACTED_TOKEN, redacted)
    for value in _secret_environment_values():
        redacted = redacted.replace(value, REDACTED_SECRET)
    return redacted, redacted != text


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _excerpt(value: str) -> tuple[str, bool]:
    truncated = len(value) > OUTPUT_EXCERPT_CHAR_LIMIT
    return value[:OUTPUT_EXCERPT_CHAR_LIMIT], truncated


def _secret_environment_values() -> list[str]:
    values = [
        value
        for name, value in os.environ.items()
        if SECRET_ENV_NAME_PATTERN.search(name) and len(value) >= 4
    ]
    return sorted(set(values), key=len, reverse=True)
