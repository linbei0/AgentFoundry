"""
haagent/memory/path_policy.py - 长期记忆正式存储路径边界

判断普通文件工具是否正在写入 HaAgent 正式 memory 存储根。
"""

from __future__ import annotations

from pathlib import Path

MEMORY_STORE_PATH_ERROR = "memory_store_path_denied"
MEMORY_STORE_PATH_MESSAGE = "正式 memory 只能通过候选确认流程写入，普通文件工具不能直接修改 memory 存储目录。"


def workspace_memory_root(workspace_root: Path) -> Path:
    """返回当前 workspace 的正式 memory 存储根。"""
    return workspace_root.resolve() / ".haagent" / "memory"


def is_workspace_memory_store_path(path: Path, workspace_root: Path) -> bool:
    """判断规范化后的路径是否位于 workspace 正式 memory 存储根内。"""
    resolved = path.resolve()
    memory_root = workspace_memory_root(workspace_root)
    return resolved == memory_root or memory_root in resolved.parents
