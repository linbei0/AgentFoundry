"""
haagent/tui/modals.py - TUI 弹窗组件

封装帮助和工具审批弹窗，保持 ModalScreen 行为独立于主 App 编排。
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from haagent.runtime.human_interaction import HumanInteractionRequest
from haagent.tui.copy import MODAL_TITLES
from haagent.tui.keys import APPROVAL_BINDINGS, HELP_DISMISS_BINDINGS, help_body
from haagent.tui.renderers import approval_body
from haagent.tui.tool_timeline import ToolTimelineItem


class HelpModal(ModalScreen[None]):
    BINDINGS = HELP_DISMISS_BINDINGS

    def __init__(self, context: str) -> None:
        super().__init__()
        self.context = context

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(MODAL_TITLES["help"], id="help-title")
            yield Static(help_body(self.context), id="help-body")
            yield Static("[Esc]关闭")

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


class ToolApprovalModal(ModalScreen[bool]):
    BINDINGS = APPROVAL_BINDINGS

    def __init__(self, request: HumanInteractionRequest) -> None:
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Static(MODAL_TITLES["approval"], id="approval-title")
            yield Static(Text(approval_body(self.request)), id="approval-body")
            with Horizontal(id="approval-buttons"):
                yield Button("允许 y", id="approval-allow", variant="success", classes="action-success")
                yield Button("拒绝 n", id="approval-deny", variant="error", classes="action-danger")

    def on_mount(self) -> None:
        self.query_one("#approval-deny", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approval-allow")

    def on_key(self, event: events.Key) -> None:
        if event.key in {"?", "question_mark"} or event.character == "?":
            event.stop()
            self.action_help()

    def action_allow(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)

    def action_help(self) -> None:
        self.app.push_screen(HelpModal("approval"))


class ToolDetailsModal(ModalScreen[None]):
    BINDINGS = HELP_DISMISS_BINDINGS

    def __init__(self, item: ToolTimelineItem) -> None:
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        with Vertical(id="tool-details-dialog"):
            yield Static(MODAL_TITLES["tool_details"], id="tool-details-title")
            yield Static(Text(self.item.detail_text()), id="tool-details-body")
            yield Static("[PgUp/PgDn]滚动 [Esc]关闭")

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.title, id="confirm-title")
            yield Static(self.body, id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button("确认 y", id="confirm-yes", variant="error", classes="action-danger")
                yield Button("取消 n", id="confirm-no", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape" or event.character == "n":
            event.stop()
            self.dismiss(False)
            return
        if event.character == "y":
            event.stop()
            self.dismiss(True)
