"""
haagent/tools/file_tools.py - 文件类本地工具

实现文件发现、读取、写入和补丁类工具，并限制路径在 workspace 内。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from haagent.tools.base import tool_error


PATH_GUIDANCE = "path is relative to workspace_root"
ROOT_GUIDANCE = 'root is relative to workspace_root; use "." or omit root'
CONTEXT_FIND_DEFAULT_MAX_RESULTS = 5
CONTEXT_FIND_DEFAULT_MAX_CHARS = 1600
CONTEXT_FIND_READ_LIMIT = 80
CONTEXT_KEYWORD_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "find",
    "search",
    "file",
    "code",
    "function",
    "implementation",
    "帮我",
    "找到",
    "查找",
    "相关",
    "文件",
    "代码",
    "功能",
    "实现",
    "修改",
    "说明",
}
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
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode not in (0, 1):
            return tool_error("search_failed", completed.stderr.strip() or "ripgrep failed")
        return {"status": "success", "matches": _parse_rg_json(completed.stdout, workspace_root)}

    matches = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if query in line:
                    matches.append(
                        {
                            "path": path.relative_to(workspace_root.resolve()).as_posix(),
                            "line": line_number,
                            "column": line.find(query) + 1,
                            "text": line,
                        },
                    )
        except UnicodeDecodeError:
            continue
    return {"status": "success", "matches": matches}


def context_find(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return tool_error("tool_argument_invalid", "query must be a non-empty string")
    file_glob = args.get("file_glob")
    if file_glob is not None and not isinstance(file_glob, str):
        return tool_error("tool_argument_invalid", "file_glob must be a string")
    max_results = int(args.get("max_results", CONTEXT_FIND_DEFAULT_MAX_RESULTS))
    max_chars = int(args.get("max_chars", CONTEXT_FIND_DEFAULT_MAX_CHARS))
    if max_results <= 0:
        return tool_error("tool_argument_invalid", "max_results must be positive")
    if max_chars <= 0:
        return tool_error("tool_argument_invalid", "max_chars must be positive")

    root = workspace_root.resolve()
    keywords = extract_context_keywords(query)
    scored: dict[str, dict[str, Any]] = {}
    truncated = False
    total_excerpt_chars = 0
    for path in _iter_context_files(root, file_glob):
        relative = path.relative_to(root).as_posix()
        filename_hits = [keyword for keyword in keywords if keyword in relative.lower()]
        if filename_hits:
            _upsert_context_candidate(
                scored,
                relative,
                line=1,
                excerpt=relative,
                keyword=filename_hits[0],
                score=3 * len(filename_hits),
                reason="filename",
            )
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, 1):
            lowered_line = line.lower()
            text_hits = [keyword for keyword in keywords if keyword in lowered_line]
            if not text_hits:
                continue
            _upsert_context_candidate(
                scored,
                relative,
                line=line_number,
                excerpt=line.strip(),
                keyword=text_hits[0],
                score=2 * len(text_hits),
                reason="text",
            )

    candidates: list[dict[str, Any]] = []
    for candidate in sorted(scored.values(), key=lambda item: (-item["score"], item["path"])):
        if len(candidates) >= max_results:
            truncated = True
            break
        excerpt = str(candidate["excerpt"])
        remaining_chars = max_chars - total_excerpt_chars
        if remaining_chars <= 0:
            truncated = True
            break
        if len(excerpt) > remaining_chars:
            excerpt = excerpt[:remaining_chars]
            truncated = True
        total_excerpt_chars += len(excerpt)
        candidates.append({**candidate, "excerpt": excerpt})

    return {
        "status": "success",
        "query": query,
        "keywords": keywords,
        "file_glob": file_glob,
        "candidate_count": len(scored),
        "candidates": candidates,
        "total_excerpt_chars": total_excerpt_chars,
        "truncated": truncated,
    }


def extract_context_keywords(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}", query.lower())
    keywords: list[str] = []
    for token in tokens:
        if token in CONTEXT_KEYWORD_STOPWORDS or len(token) < 3:
            continue
        for keyword in _context_keyword_variants(token):
            if keyword not in keywords:
                keywords.append(keyword)
    return keywords or [query.strip().lower()]


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
        "path": path.relative_to(workspace_root.resolve()).as_posix(),
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


def apply_patch_set(args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """原子校验多个唯一文本替换；全部可应用后才写文件。"""
    replacements = args.get("replacements")
    if not isinstance(replacements, list) or not replacements:
        return tool_error("tool_argument_invalid", "replacements must be a non-empty list")

    staged_texts: dict[Path, str] = {}
    summaries: list[dict[str, object]] = []
    for index, replacement in enumerate(replacements):
        if not isinstance(replacement, dict):
            return _patch_set_error(
                "tool_argument_invalid",
                "each replacement must be an object",
                summaries,
                replacements,
                index,
            )

        path_arg = replacement.get("path")
        old_text = replacement.get("old_text")
        new_text = replacement.get("new_text")
        if not all(isinstance(value, str) for value in (path_arg, old_text, new_text)):
            return _patch_set_error(
                "tool_argument_invalid",
                "path, old_text, and new_text must be strings",
                summaries,
                replacements,
                index,
                path_arg,
            )

        path = resolve_workspace_path(path_arg, workspace_root)
        if path is None:
            return _patch_set_error(
                "tool_argument_invalid",
                f"path must stay inside workspace_root; {PATH_GUIDANCE}",
                summaries,
                replacements,
                index,
                path_arg,
            )
        if not path.exists():
            return _patch_set_error(
                "tool_argument_invalid",
                f"path does not exist: {path_arg}; {PATH_GUIDANCE}",
                summaries,
                replacements,
                index,
                path_arg,
            )
        if not path.is_file():
            return _patch_set_error(
                "tool_argument_invalid",
                f"path must be a file: {path_arg}; {PATH_GUIDANCE}",
                summaries,
                replacements,
                index,
                path_arg,
            )

        text = staged_texts.get(path)
        if text is None:
            text = path.read_text(encoding="utf-8")
        match_count = text.count(old_text)
        if match_count == 0:
            return _patch_set_error(
                "patch_text_not_found",
                "old_text was not found",
                summaries,
                replacements,
                index,
                path_arg,
                match_count,
            )
        if match_count > 1:
            return _patch_set_error(
                "patch_text_not_unique",
                "old_text must match exactly once",
                summaries,
                replacements,
                index,
                path_arg,
                match_count,
            )

        staged_texts[path] = text.replace(old_text, new_text, 1)
        summaries.append(
            {
                "index": index,
                "path": path_arg,
                "status": "ready",
                "match_count": match_count,
                "old_text_chars": len(old_text),
                "new_text_chars": len(new_text),
            },
        )

    for path, text in staged_texts.items():
        path.write_text(text, encoding="utf-8")

    success_summaries = [{**summary, "status": "success"} for summary in summaries]
    changed_paths = sorted({str(summary["path"]) for summary in success_summaries})
    return {
        "status": "success",
        "replacement_count": len(success_summaries),
        "paths": changed_paths,
        "replacements": success_summaries,
    }


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


def _patch_set_error(
    error_type: str,
    message: str,
    summaries: list[dict[str, object]],
    replacements: list[object],
    failed_index: int,
    path: object = "",
    match_count: int | None = None,
) -> dict[str, Any]:
    result = tool_error(error_type, message)
    failed_summary: dict[str, object] = {
        "index": failed_index,
        "path": str(path or ""),
        "status": "error",
        "reason": message,
    }
    if match_count is not None:
        failed_summary["match_count"] = match_count
    replacement_summaries = [*summaries, failed_summary]
    for skipped_index in range(failed_index + 1, len(replacements)):
        skipped = replacements[skipped_index]
        skipped_path = skipped.get("path", "") if isinstance(skipped, dict) else ""
        replacement_summaries.append(
            {
                "index": skipped_index,
                "path": str(skipped_path or ""),
                "status": "skipped",
                "reason": "previous replacement failed",
            },
        )
    result["replacement_count"] = len(replacements)
    result["replacements"] = replacement_summaries
    return result


def _iter_context_files(root: Path, file_glob: str | None):
    pattern = file_glob or "*"
    for path in sorted(root.rglob(pattern), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in NOISE_DIRECTORIES for part in relative_parts):
            continue
        yield path


def _context_keyword_variants(token: str) -> list[str]:
    variants = [token]
    if token.endswith("ing") and len(token) > 5:
        variants.append(token[:-3])
    return variants


def _upsert_context_candidate(
    candidates: dict[str, dict[str, Any]],
    path: str,
    *,
    line: int,
    excerpt: str,
    keyword: str,
    score: int,
    reason: str,
) -> None:
    current = candidates.get(path)
    if current is None:
        candidates[path] = {
            "path": path,
            "line": line,
            "excerpt": excerpt,
            "score": score,
            "reasons": [reason],
            "recommended_file_read": {
                "path": path,
                "keyword": keyword,
                "limit": CONTEXT_FIND_READ_LIMIT,
            },
        }
        return
    current["score"] += score
    if reason not in current["reasons"]:
        current["reasons"].append(reason)
    if score > 0 and line < current["line"]:
        current["line"] = line
        current["excerpt"] = excerpt
        current["recommended_file_read"] = {
            "path": path,
            "keyword": keyword,
            "limit": CONTEXT_FIND_READ_LIMIT,
        }


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


def _parse_rg_json(output: str, workspace_root: Path) -> list[dict[str, Any]]:
    """解析 ripgrep JSON 事件流，只保留 match 事件。"""
    root = workspace_root.resolve()
    matches = []
    for line in output.splitlines():
        event = json.loads(line)
        if event.get("type") != "match":
            continue
        data = event["data"]
        submatches = data.get("submatches") or [{"start": 0}]
        matches.append(
            {
                "path": Path(data["path"]["text"]).resolve().relative_to(root).as_posix(),
                "line": data["line_number"],
                "column": submatches[0]["start"] + 1,
                "text": data["lines"]["text"].rstrip("\n"),
            },
        )
    return matches
