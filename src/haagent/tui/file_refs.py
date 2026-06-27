"""
haagent/tui/file_refs.py - workspace 内文件引用检索

基于当前 workspace 做模糊文件匹配，并生成稳定的 @file 引用 token。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileReferenceMatch:
    path: Path
    display_path: str


def fuzzy_file_matches(workspace_root: Path, query: str, *, limit: int = 20) -> list[FileReferenceMatch]:
    root = workspace_root.resolve()
    needle = query.strip().casefold()
    matches: list[FileReferenceMatch] = []
    if not root.exists():
        return []
    for path in root.rglob("*"):
        if not path.is_file() or _is_hidden_run_artifact(root, path):
            continue
        resolved = path.resolve()
        if not _is_relative_to(resolved, root):
            continue
        display = resolved.relative_to(root).as_posix()
        haystack = display.casefold()
        if needle and not _fuzzy_contains(haystack, needle):
            continue
        matches.append(FileReferenceMatch(path=resolved, display_path=display))
    matches.sort(key=lambda item: (len(item.display_path), item.display_path.casefold()))
    return matches[:limit]


def path_reference_token(workspace_root: Path, path: Path) -> str:
    root = workspace_root.resolve()
    resolved = path.resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError("文件引用必须位于 workspace root 内")
    display = resolved.relative_to(root).as_posix()
    escaped = display.replace("\\", "\\\\").replace('"', '\\"')
    return f'@file("{escaped}")'


def query_after_at(text: str) -> str | None:
    at_index = _reference_at_index(text)
    if at_index < 0:
        return None
    suffix = text[at_index + 1 :]
    if any(char.isspace() for char in suffix):
        return None
    return suffix


def replace_at_query(text: str, token: str) -> str:
    at_index = _reference_at_index(text)
    if at_index < 0:
        return text
    end = at_index + 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return f"{text[:at_index]}{token}{text[end:]}"


def _reference_at_index(text: str) -> int:
    stripped = text[:-1] if text.endswith("@") and text.count("@") > 1 else text
    return stripped.rfind("@")


def _fuzzy_contains(haystack: str, needle: str) -> bool:
    position = 0
    for char in needle:
        found = haystack.find(char, position)
        if found < 0:
            return False
        position = found + 1
    return True


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_hidden_run_artifact(root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in {".git", ".runs", "__pycache__"} for part in parts)
