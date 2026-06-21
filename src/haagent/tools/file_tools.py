"""
haagent/tools/file_tools.py - 文件类本地工具

实现 file_search、file_read 和 apply_patch，并限制路径在 workspace 内。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from haagent.tools.base import tool_error


def file_search(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """优先使用 ripgrep 搜索文本；rg 不可用时退回 Python 遍历。"""
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return tool_error("invalid_arguments", "query must be a non-empty string")

    root_arg = args.get("root", ".")
    if not isinstance(root_arg, str):
        return tool_error("invalid_arguments", "root must be a string")
    root = resolve_workspace_path(root_arg, workspace_root)
    if root is None:
        return tool_error("path_outside_workspace", "root must be inside workspace")

    rg = shutil.which("rg")
    if rg:
        # 使用 JSON 输出避免 Windows 盘符冒号破坏 path:line:column 解析。
        command = [rg, "--json", "--", query, str(root)]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode not in (0, 1):
            return tool_error("search_failed", completed.stderr.strip() or "ripgrep failed")
        return {"status": "success", "matches": _parse_rg_json(completed.stdout)}

    matches = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if query in line:
                    matches.append(
                        {
                            "path": str(path),
                            "line": line_number,
                            "column": line.find(query) + 1,
                            "text": line,
                        },
                    )
        except UnicodeDecodeError:
            continue
    return {"status": "success", "matches": matches}


def file_read(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    path_arg = args.get("path")
    if not isinstance(path_arg, str):
        return tool_error("invalid_arguments", "path must be a string")
    path = resolve_workspace_path(path_arg, workspace_root)
    if path is None:
        return tool_error("path_outside_workspace", "path must be inside workspace")

    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 200))
    if offset < 0 or limit < 0:
        return tool_error("invalid_arguments", "offset and limit must be non-negative")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    selected = lines[offset : offset + limit]
    return {
        "status": "success",
        "path": str(path),
        "offset": offset,
        "limit": limit,
        "content": "".join(selected),
    }


def apply_patch(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """仅允许工作区内文件，并要求 old_text 唯一匹配后再写回。"""
    path_arg = args.get("path")
    old_text = args.get("old_text")
    new_text = args.get("new_text")
    if not all(isinstance(value, str) for value in (path_arg, old_text, new_text)):
        return tool_error("invalid_arguments", "path, old_text, and new_text must be strings")

    path = resolve_workspace_path(path_arg, workspace_root)
    if path is None:
        return tool_error("path_outside_workspace", "path must be inside workspace")

    text = path.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count == 0:
        return tool_error("patch_text_not_found", "old_text was not found")
    if count > 1:
        return tool_error("patch_text_not_unique", "old_text must match exactly once")

    path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    return {"status": "success", "path": str(path), "replacements": 1}


def resolve_workspace_path(path: str, workspace_root: Path) -> Path | None:
    """把相对路径绑定到 workspace，拒绝逃逸到工作区之外的路径。"""
    root = workspace_root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    return None


def _parse_rg_json(output: str) -> list[dict[str, Any]]:
    """解析 ripgrep JSON 事件流，只保留 match 事件。"""
    matches = []
    for line in output.splitlines():
        event = json.loads(line)
        if event.get("type") != "match":
            continue
        data = event["data"]
        submatches = data.get("submatches") or [{"start": 0}]
        matches.append(
            {
                "path": data["path"]["text"],
                "line": data["line_number"],
                "column": submatches[0]["start"] + 1,
                "text": data["lines"]["text"].rstrip("\n"),
            },
        )
    return matches
