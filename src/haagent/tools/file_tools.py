"""
haagent/tools/file_tools.py - 文件类本地工具

实现 file_list、file_search、file_read、file_write 和 apply_patch，并限制路径在 workspace 内。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from haagent.tools.base import tool_error


PATH_GUIDANCE = "path is relative to workspace_root"
ROOT_GUIDANCE = 'root is relative to workspace_root; use "." or omit root'
NOISE_DIRECTORIES = {
    ".git",
    ".runs",
    ".smoke-runs",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


def file_list(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    path_arg = args.get("path", ".")
    if not isinstance(path_arg, str):
        return tool_error("tool_argument_invalid", "path must be a string")
    root = resolve_workspace_path(path_arg, workspace_root)
    if root is None:
        return tool_error("tool_argument_invalid", f"path must stay inside workspace_root; {PATH_GUIDANCE}")
    if not root.exists():
        return tool_error("tool_argument_invalid", f"path does not exist: {path_arg}; {PATH_GUIDANCE}")
    if not root.is_dir():
        return tool_error("tool_argument_invalid", f"path must be a directory: {path_arg}; {PATH_GUIDANCE}")

    max_depth = args.get("max_depth", 2)
    max_entries = args.get("max_entries", 100)
    if max_depth < 0:
        return tool_error("tool_argument_invalid", "max_depth must be non-negative")
    if max_entries <= 0:
        return tool_error("tool_argument_invalid", "max_entries must be positive")

    entries: list[str] = []
    skipped_dirs: set[str] = set()
    truncated = _collect_file_tree(
        root=root,
        current=root,
        current_depth=0,
        max_depth=max_depth,
        max_entries=max_entries,
        entries=entries,
        skipped_dirs=skipped_dirs,
    )
    return {
        "status": "success",
        "path": path_arg,
        "max_depth": max_depth,
        "max_entries": max_entries,
        "entry_count": len(entries),
        "truncated": truncated,
        "tree": "\n".join(entries),
        "skipped_dirs": sorted(skipped_dirs),
    }


def file_search(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """优先使用 ripgrep 搜索文本；rg 不可用时退回 Python 遍历。"""
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return tool_error("tool_argument_invalid", "query must be a non-empty string")

    root_arg = args.get("root", ".")
    if not isinstance(root_arg, str):
        return tool_error("tool_argument_invalid", "root must be a string")
    root = resolve_workspace_path(root_arg, workspace_root)
    if root is None:
        return tool_error("tool_argument_invalid", f"root must stay inside workspace_root; {ROOT_GUIDANCE}")
    if not root.exists():
        return tool_error("tool_argument_invalid", f"root does not exist: {root_arg}; {ROOT_GUIDANCE}")
    if not root.is_dir():
        return tool_error("tool_argument_invalid", f"root must be a directory: {root_arg}; {ROOT_GUIDANCE}")

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
        return tool_error("tool_argument_invalid", "path must be a string")
    path = resolve_workspace_path(path_arg, workspace_root)
    if path is None:
        return tool_error("tool_argument_invalid", f"path must stay inside workspace_root; {PATH_GUIDANCE}")
    if not path.exists():
        result = tool_error("tool_argument_invalid", f"path does not exist: {path_arg}; {PATH_GUIDANCE}")
        result["suggestions"] = _similar_workspace_paths(path_arg, workspace_root)
        return result
    if not path.is_file():
        return tool_error("tool_argument_invalid", f"path must be a file: {path_arg}; {PATH_GUIDANCE}")

    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 200))
    if offset < 0 or limit < 0:
        return tool_error("tool_argument_invalid", "offset and limit must be non-negative")

    keyword = args.get("keyword")
    if keyword is not None and (not isinstance(keyword, str) or not keyword):
        return tool_error("tool_argument_invalid", "keyword must be a non-empty string")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    total_lines = len(lines)
    if keyword is None:
        start_index = offset
    else:
        match_index = _first_keyword_line(lines, keyword)
        if match_index is None:
            return tool_error("keyword_not_found", f"keyword not found in {path_arg}: {keyword}")
        start_index = max(0, match_index - (limit // 2))
        if start_index + limit > total_lines:
            start_index = max(0, total_lines - limit)

    end_index = min(start_index + limit, total_lines)
    selected = lines[start_index:end_index]
    return {
        "status": "success",
        "path": str(path),
        "offset": offset,
        "limit": limit,
        "keyword": keyword,
        "start_line": start_index + 1 if selected else start_index,
        "end_line": end_index,
        "line_count": total_lines,
        "content": "".join(selected),
        "truncated": start_index > 0 or end_index < total_lines,
    }


def file_write(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    path_arg = args.get("path")
    content = args.get("content")
    mode = args.get("mode")
    if not all(isinstance(value, str) for value in (path_arg, content, mode)):
        return tool_error("tool_argument_invalid", "path, content, and mode must be strings")
    if mode not in {"create", "overwrite", "append"}:
        return tool_error("tool_argument_invalid", "mode must be create, overwrite, or append")

    path = resolve_workspace_path(path_arg, workspace_root)
    if path is None:
        return tool_error("tool_argument_invalid", f"path must stay inside workspace_root; {PATH_GUIDANCE}")
    if not path.parent.exists():
        return tool_error("tool_argument_invalid", f"parent directory does not exist: {path_arg}; {PATH_GUIDANCE}")
    if not path.parent.is_dir():
        return tool_error("tool_argument_invalid", f"parent path must be a directory: {path_arg}; {PATH_GUIDANCE}")
    if path.exists() and not path.is_file():
        return tool_error("tool_argument_invalid", f"path must be a file: {path_arg}; {PATH_GUIDANCE}")

    existed = path.exists()
    if mode == "create" and existed:
        return tool_error("file_exists", f"path already exists: {path_arg}")
    if mode == "append" and not existed:
        return tool_error("file_not_found", f"path does not exist for append: {path_arg}")

    if mode == "append":
        with path.open("a", encoding="utf-8") as file:
            file.write(content)
    else:
        path.write_text(content, encoding="utf-8")

    return {
        "status": "success",
        "path": str(path),
        "mode": mode,
        "bytes_written": len(content.encode("utf-8")),
        "created": not existed,
    }


def apply_patch(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """仅允许工作区内文件，并要求 old_text 唯一匹配后再写回。"""
    path_arg = args.get("path")
    old_text = args.get("old_text")
    new_text = args.get("new_text")
    if not all(isinstance(value, str) for value in (path_arg, old_text, new_text)):
        return tool_error("tool_argument_invalid", "path, old_text, and new_text must be strings")

    path = resolve_workspace_path(path_arg, workspace_root)
    if path is None:
        return tool_error("tool_argument_invalid", f"path must stay inside workspace_root; {PATH_GUIDANCE}")
    if not path.exists():
        return tool_error("tool_argument_invalid", f"path does not exist: {path_arg}; {PATH_GUIDANCE}")
    if not path.is_file():
        return tool_error("tool_argument_invalid", f"path must be a file: {path_arg}; {PATH_GUIDANCE}")

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


def _collect_file_tree(
    *,
    root: Path,
    current: Path,
    current_depth: int,
    max_depth: int,
    max_entries: int,
    entries: list[str],
    skipped_dirs: set[str],
) -> bool:
    for child in sorted(current.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
        if child.is_dir() and child.name in NOISE_DIRECTORIES:
            skipped_dirs.add(_relative_tree_path(child, root).rstrip("/"))
            continue
        if len(entries) >= max_entries:
            return True
        entries.append(_relative_tree_path(child, root))
        if child.is_dir() and current_depth < max_depth - 1:
            if _collect_file_tree(
                root=root,
                current=child,
                current_depth=current_depth + 1,
                max_depth=max_depth,
                max_entries=max_entries,
                entries=entries,
                skipped_dirs=skipped_dirs,
            ):
                return True
    return False


def _relative_tree_path(path: Path, root: Path) -> str:
    suffix = "/" if path.is_dir() else ""
    return path.relative_to(root).as_posix() + suffix


def _first_keyword_line(lines: list[str], keyword: str) -> int | None:
    for index, line in enumerate(lines):
        if keyword in line:
            return index
    return None


def _similar_workspace_paths(path_arg: str, workspace_root: Path) -> list[str]:
    root = workspace_root.resolve()
    candidates: list[tuple[float, str]] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if any(part in NOISE_DIRECTORIES for part in relative_parts):
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        score = max(
            SequenceMatcher(None, path_arg, relative).ratio(),
            SequenceMatcher(None, Path(path_arg).name, path.name).ratio(),
        )
        if score >= 0.45:
            candidates.append((score, relative))
    return [relative for _, relative in sorted(candidates, key=lambda item: (-item[0], item[1]))[:5]]


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
