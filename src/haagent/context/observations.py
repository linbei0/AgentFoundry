"""
haagent/context/observations.py - 工具 observation 摘要与压缩

把工具 observation 转成稳定、紧凑的模型输入摘要。
"""

from __future__ import annotations

from typing import Any


OBSERVATION_EXCERPT_CHAR_LIMIT = 240


def observation_tool_name(observation: dict[str, object]) -> str:
    tool_name = observation.get("tool_name", "unknown_tool")
    return str(tool_name)


def observation_summary(observation: dict[str, object]) -> dict[str, object]:
    tool_name = observation_tool_name(observation)
    args = _dict_or_empty(observation.get("args"))
    result = _dict_or_empty(observation.get("result"))
    if tool_name == "file_read":
        return _file_read_observation_summary(args, result)
    if tool_name == "file_search":
        return _file_search_observation_summary(args, result)
    if tool_name == "shell":
        return _shell_observation_summary(args, result)
    if tool_name == "apply_patch":
        return _apply_patch_observation_summary(args, result)
    return _generic_observation_summary(args, result)


def raw_observation_summary(observation: dict[str, object]) -> dict[str, object]:
    return {
        "args": observation.get("args", {}),
        "result": observation.get("result", {}),
    }


def _file_read_observation_summary(
    args: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, object]:
    content = _string_value(result.get("content"))
    excerpt, truncated = _compact_excerpt(content)
    return {
        "status": _string_value(result.get("status")),
        "path": _first_present_string(args.get("path"), result.get("path")),
        "offset": _first_present(args.get("offset"), result.get("offset")),
        "limit": _first_present(args.get("limit"), result.get("limit")),
        "line_count": len(content.splitlines()),
        "excerpt": excerpt,
        "truncated": truncated,
    }


def _file_search_observation_summary(
    args: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, object]:
    matches = result.get("matches")
    if not isinstance(matches, list):
        matches = []
    excerpt_source = "\n".join(_format_search_match(match) for match in matches)
    excerpt, truncated = _compact_excerpt(excerpt_source)
    return {
        "status": _string_value(result.get("status")),
        "query": _first_present_string(args.get("query"), args.get("pattern")),
        "pattern": _first_present_string(args.get("pattern"), args.get("query")),
        "match_count": len(matches),
        "excerpt": excerpt,
        "truncated": truncated,
    }


def _shell_observation_summary(
    args: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, object]:
    stdout_excerpt, stdout_truncated = _compact_excerpt(_string_value(result.get("stdout")))
    stderr_excerpt, stderr_truncated = _compact_excerpt(_string_value(result.get("stderr")))
    return {
        "status": _string_value(result.get("status")),
        "command": _string_value(args.get("command")),
        "cwd": _string_value(args.get("cwd"), default="."),
        "exit_code": result.get("exit_code"),
        "stdout_excerpt": stdout_excerpt,
        "stderr_excerpt": stderr_excerpt,
        "truncated": stdout_truncated or stderr_truncated,
    }


def _apply_patch_observation_summary(
    args: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, object]:
    old_text = _string_value(args.get("old_text"))
    new_text = _string_value(args.get("new_text"))
    return {
        "status": _string_value(result.get("status")),
        "path": _first_present_string(args.get("path"), result.get("path")),
        "old_text_length": len(old_text),
        "new_text_length": len(new_text),
        "replacements": result.get("replacements"),
        "truncated": False,
    }


def _format_search_match(match: object) -> str:
    if not isinstance(match, dict):
        return str(match)
    path = _string_value(match.get("path"))
    line = _string_value(match.get("line"))
    column = _string_value(match.get("column"))
    text = _string_value(match.get("text"))
    location = path
    if line:
        location = f"{location}:{line}"
    if column:
        location = f"{location}:{column}"
    return f"{location}: {text}"


def _generic_observation_summary(
    args: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, object]:
    return {
        "status": _string_value(result.get("status")),
        "args_keys": sorted(str(key) for key in args),
        "result_keys": sorted(str(key) for key in result),
        "truncated": False,
    }


def _compact_excerpt(value: str) -> tuple[str, bool]:
    truncated = len(value) > OBSERVATION_EXCERPT_CHAR_LIMIT
    return value[:OBSERVATION_EXCERPT_CHAR_LIMIT], truncated


def _dict_or_empty(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _string_value(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _first_present(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    return None


def _first_present_string(*values: object) -> str:
    for value in values:
        if value is not None:
            return str(value)
    return ""
