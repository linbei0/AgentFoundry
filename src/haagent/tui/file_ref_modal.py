"""
haagent/tui/file_ref_modal.py - @file 引用选择 modal

展示 workspace 内文件匹配结果，并返回选中文件引用 token。
"""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from haagent.tui.file_refs import FileReferenceMatch, fuzzy_file_matches, path_reference_token


class FileReferenceOverlay(ModalScreen[str | None]):
    def __init__(self, workspace_root: Path, query: str) -> None:
        super().__init__()
        self.workspace_root = workspace_root
        self.filter_text = query
        self.selected_index = 0
        self.matches = fuzzy_file_matches(workspace_root, query)

    def compose(self) -> ComposeResult:
        yield Static(self._body(), id="file-ref-dialog")

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "escape":
            event.stop()
            self.dismiss(None)
            return
        if key in {"up", "k"}:
            event.stop()
            self._move(-1)
            return
        if key in {"down", "j"}:
            event.stop()
            self._move(1)
            return
        if key == "backspace":
            event.stop()
            self.filter_text = self.filter_text[:-1]
            self._reload()
            return
        if key == "enter":
            event.stop()
            selected = self._selected()
            if selected is not None:
                self.dismiss(path_reference_token(self.workspace_root, selected.path))
            return
        if event.character and event.character.isprintable():
            event.stop()
            self.filter_text += event.character
            self._reload()

    def _selected(self) -> FileReferenceMatch | None:
        if not self.matches:
            return None
        return self.matches[min(self.selected_index, len(self.matches) - 1)]

    def _move(self, delta: int) -> None:
        if self.matches:
            self.selected_index = min(max(self.selected_index + delta, 0), len(self.matches) - 1)
        self._refresh()

    def _reload(self) -> None:
        self.matches = fuzzy_file_matches(self.workspace_root, self.filter_text)
        self.selected_index = 0
        self._refresh()

    def _refresh(self) -> None:
        self.query_one("#file-ref-dialog", Static).update(self._body())

    def _body(self) -> str:
        lines = ["File References", f"搜索: {self.filter_text or '-'}", ""]
        if not self.matches:
            lines.append("无匹配文件")
        for index, match in enumerate(self.matches):
            marker = ">" if index == self.selected_index else " "
            lines.append(f"{marker} {match.display_path}")
        lines.extend(["", "↑/↓ j/k 移动  Enter 插入引用  Esc 关闭"])
        return "\n".join(lines)
