"""
haagent/tui/app.py - HaAgent TUI 应用编排

组合 Textual 组件、协调会话状态和后台 worker，具体渲染与组件细节拆分到同级模块。
"""

from __future__ import annotations

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical

from haagent.app.assistant_service import AssistantService
from haagent.memory import MemoryCandidate
from haagent.runtime.chat_session import ChatEvent
from haagent.runtime.human_interaction import HumanInteractionRequest, HumanInteractionResponse
from haagent.tui.command_suggestions import CommandSuggestionOverlay
from haagent.tui.commands import command_registry, parse_slash_command
from haagent.tui.file_ref_modal import FileReferenceOverlay
from haagent.tui.file_refs import query_after_at, replace_at_query
from haagent.tui.keys import APP_BINDINGS, footer_text
from haagent.tui.modals import HelpModal, ToolApprovalModal
from haagent.tui.renderers import (
    failure_body,
    memory_panel_text,
    payload_text,
    side_bar,
    status_line,
)
from haagent.tui.state import MIN_HEIGHT, MIN_WIDTH, PendingInteraction, layout_for_size
from haagent.tui.search_modal import SearchOverlay
from haagent.tui.sessions import SessionOverlay, SessionOverlayResult
from haagent.tui.utils import safe_summary
from haagent.tui.widgets import ConversationView, FooterBar, PromptInput, ResizeMessage, SideBar, StatusBar, _end_location


class HaAgentTuiApp(App[None]):
    MIN_WIDTH = MIN_WIDTH
    MIN_HEIGHT = MIN_HEIGHT
    CSS_PATH = "haagent.tcss"
    BINDINGS = APP_BINDINGS

    def __init__(self, service: AssistantService) -> None:
        super().__init__()
        self.service = service
        self._state = "idle"
        self._conversation_lines: list[str] = []
        self._conversation_rendered_count = 0
        self._conversation_placeholder_rendered = False
        self._tool_lines: list[str] = []
        self._last_failure: dict[str, str] | None = None
        self._pending_interaction: PendingInteraction | None = None
        self._default_prompt_placeholder = "输入消息；Enter 发送，Shift+Enter 换行"
        self._memory_mode = False
        self._memory_detail_mode = False
        self._memory_candidates: list[MemoryCandidate] = []
        self._memory_selected = 0
        self._memory_error: str | None = None
        self._memory_notice: str | None = None
        self._commands = command_registry()

    def compose(self) -> ComposeResult:
        yield StatusBar("", id="status-bar")
        yield ResizeMessage("终端尺寸过小\n请调整到至少 80x24 后继续使用 HaAgent TUI。", id="resize-message", classes="hidden")
        with Horizontal(id="main"):
            yield ConversationView(id="conversation", wrap=True, auto_scroll=True)
            yield SideBar("", id="side-bar")
        with Vertical(id="input-panel"):
            yield PromptInput(placeholder=self._default_prompt_placeholder, id="prompt-input", show_line_numbers=False)
        yield FooterBar(footer_text("chat"), id="footer-bar")

    def on_mount(self) -> None:
        self.query_one("#side-bar", SideBar).can_focus = True
        self._show_initial_configuration_state()
        self._refresh()
        self._update_responsive_layout()
        self.query_one("#prompt-input", PromptInput).focus()

    def on_resize(self, event: events.Resize) -> None:
        self._update_responsive_layout(width=event.size.width, height=event.size.height)

    def on_key(self, event: events.Key) -> None:
        if self._memory_mode and self._pending_interaction is None:
            if self._handle_memory_key(event.key):
                event.stop()
                return
        if self._pending_interaction is not None:
            return
        prompt_input = self.query_one("#prompt-input", PromptInput)
        if self._prompt_value(prompt_input):
            return
        if event.key == "s":
            event.stop()
            self.action_open_sessions()
            return
        if event.key in {"/", "slash"} or event.character == "/":
            event.stop()
            self.action_open_command_suggestions()
            return
        if event.key == "m":
            event.stop()
            self.action_toggle_memory()
        elif event.key == "enter" and self._memory_mode:
            event.stop()
            self.action_memory_enter()
        elif event.key in {"a", "y"} and self._memory_mode:
            event.stop()
            self.action_confirm_memory()
        elif event.key == "r" and self._memory_mode:
            event.stop()
            self.action_reject_memory()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self._submit_prompt(event.input)

    def action_submit_prompt(self) -> None:
        self._submit_prompt(self.query_one("#prompt-input", PromptInput))

    def _submit_prompt(self, prompt_input: PromptInput) -> None:
        prompt = self._prompt_value(prompt_input).strip()
        if not prompt:
            return
        command = parse_slash_command(prompt, self._commands)
        if command is not None:
            self._set_prompt_value(prompt_input, "")
            self._handle_slash_command(command)
            return
        self._set_prompt_value(prompt_input, "")
        if self._pending_interaction is not None and self._pending_interaction.request.interaction_type == "user_input":
            self._complete_interaction(HumanInteractionResponse(approved=True, answer=prompt))
            return
        self._append_block("You", prompt)
        self._state = "running"
        self._refresh()
        self._run_prompt(prompt)

    def action_help(self) -> None:
        self.push_screen(HelpModal(self._help_context()))

    def action_open_sessions(self) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        if prompt_input.has_focus and self._prompt_value(prompt_input):
            prompt_input.insert("s")
            return
        self.push_screen(SessionOverlay(self.service.list_sessions()), self._handle_session_overlay_result)

    def action_open_search(self) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        if prompt_input.has_focus and self._prompt_value(prompt_input):
            return
        self.push_screen(SearchOverlay(list(self._conversation_lines)), self._defer_prompt_focus)

    def action_open_command_suggestions(self) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        if prompt_input.has_focus and self._prompt_value(prompt_input):
            prompt_input.insert("/")
            return
        self.push_screen(CommandSuggestionOverlay(self._commands.commands()), self._handle_command_suggestion_result)

    def action_open_file_refs(self) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        query = query_after_at(self._prompt_value(prompt_input))
        if query is None:
            return
        status = self.service.get_workspace_status()
        self.push_screen(FileReferenceOverlay(status.workspace_root, query), self._handle_file_reference_result)

    def action_quit(self) -> None:
        self.exit(None)

    def action_conversation_page_up(self) -> None:
        self.query_one("#conversation", ConversationView).scroll_page_up(animate=False, force=True)

    def action_conversation_page_down(self) -> None:
        self.query_one("#conversation", ConversationView).scroll_page_down(animate=False, force=True)

    def action_cancel_interaction(self) -> None:
        if self._memory_mode:
            if self._memory_detail_mode:
                self._memory_detail_mode = False
            else:
                self._memory_mode = False
                self.query_one("#prompt-input", PromptInput).focus()
            self._refresh()
            return
        if self._pending_interaction is None:
            return
        self._complete_interaction(HumanInteractionResponse(approved=False, answer=""))

    def action_toggle_memory(self) -> None:
        self._memory_mode = not self._memory_mode
        self._memory_detail_mode = False
        if self._memory_mode:
            self._load_memory_candidates()
            self._set_prompt_value(self.query_one("#prompt-input", PromptInput), "")
            self.query_one("#side-bar", SideBar).focus()
        else:
            self.query_one("#prompt-input", PromptInput).focus()
        self._refresh()

    def action_memory_enter(self) -> None:
        if not self._memory_mode or not self._memory_candidates:
            return
        self._memory_detail_mode = not self._memory_detail_mode
        self._refresh()

    def action_memory_up(self) -> None:
        self._move_memory_selection(-1)

    def action_memory_down(self) -> None:
        self._move_memory_selection(1)

    def action_memory_first(self) -> None:
        if self._memory_mode and self._memory_candidates and not self._memory_detail_mode:
            self._memory_selected = 0
            self._refresh()

    def action_memory_last(self) -> None:
        if self._memory_mode and self._memory_candidates and not self._memory_detail_mode:
            self._memory_selected = len(self._memory_candidates) - 1
            self._refresh()

    def action_confirm_memory(self) -> None:
        if not self._memory_mode or not self._memory_candidates:
            return
        candidate = self._selected_memory_candidate()
        try:
            self.service.confirm_memory_candidate(candidate.candidate_id)
        except Exception as error:
            self._memory_notice = f"Memory confirm failed: {error}"
            self._append_block("Memory warning", f"Memory confirm failed: {error}")
        else:
            self._memory_notice = f"Memory confirmed: {candidate.candidate_id}"
            self._append_line(f"Memory confirmed: {candidate.candidate_id}")
        self._memory_detail_mode = False
        self._load_memory_candidates()
        self._refresh()

    def action_reject_memory(self) -> None:
        if not self._memory_mode or not self._memory_candidates:
            return
        candidate = self._selected_memory_candidate()
        try:
            self.service.reject_memory_candidate(candidate.candidate_id, "rejected from TUI")
        except Exception as error:
            self._memory_notice = f"Memory reject failed: {error}"
            self._append_block("Memory warning", f"Memory reject failed: {error}")
        else:
            self._memory_notice = f"Memory rejected: {candidate.candidate_id}"
            self._append_line(f"Memory rejected: {candidate.candidate_id}")
        self._memory_detail_mode = False
        self._load_memory_candidates()
        self._refresh()

    def action_focus_tools(self) -> None:
        self.query_one("#side-bar", SideBar).focus()

    def action_new_session(self) -> None:
        try:
            status = self.service.create_session()
        except Exception as error:
            self._append_block("Session warning", f"New session failed: {error}")
        else:
            self._append_line(f"New session: {status.session_id}")
        self._refresh()

    def action_resume_latest(self) -> None:
        try:
            status = self.service.continue_latest_session()
        except Exception as error:
            self._append_block("Session warning", f"Resume latest failed: {error}")
        else:
            self._append_line(f"Resumed session: {status.session_id}")
        self._refresh()

    def _handle_slash_command(self, result) -> None:
        if result.error:
            self._append_block("Command", result.error)
            self._refresh()
            return
        command = result.command
        if command is None:
            return
        if command.action == "help":
            self.action_help()
        elif command.action == "sessions":
            self.action_open_sessions()
        elif command.action == "memory":
            if not self._memory_mode:
                self.action_toggle_memory()
        elif command.action == "tools":
            self.action_focus_tools()
        elif command.action == "new_session":
            self.action_new_session()
        elif command.action == "resume_latest":
            self.action_resume_latest()

    def _handle_session_overlay_result(self, result: SessionOverlayResult | None) -> None:
        if result is None:
            self.set_timer(0.01, self._restore_prompt_focus)
            return
        try:
            if result.action == "resume" and result.session is not None:
                status = self.service.resume_session(result.session.session_path)
            elif result.action == "continue_latest":
                status = self.service.continue_latest_session()
            else:
                status = self.service.create_session()
        except Exception as error:
            self._append_block("Session warning", f"Session operation failed: {error}")
        else:
            self._append_line(f"Session active: {status.session_id}")
        self._refresh()
        self.set_timer(0.01, self._restore_prompt_focus)

    def _handle_command_suggestion_result(self, command) -> None:
        if command is not None:
            self._handle_slash_command(parse_slash_command(command.token, self._commands))
        self.set_timer(0.01, self._restore_prompt_focus)

    def _handle_file_reference_result(self, token: str | None) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        if token is not None:
            self._set_prompt_value(prompt_input, replace_at_query(self._prompt_value(prompt_input), token))
        prompt_input.focus()

    def _restore_prompt_focus(self, _result: object | None = None) -> None:
        self.query_one("#prompt-input", PromptInput).focus()

    def _defer_prompt_focus(self, _result: object | None = None) -> None:
        self.set_timer(0.01, self._restore_prompt_focus)

    @work(thread=True, exclusive=True)
    def _run_prompt(self, prompt: str) -> None:
        try:
            result = self.service.run_prompt_events(
                prompt,
                event_sink=lambda event: self.call_from_thread(self._handle_chat_event, event),
                interaction_handler=self._handle_interaction,
            )
        except Exception as error:
            self.call_from_thread(self._handle_prompt_error, error)
            return
        status = str(getattr(result, "status", "completed"))
        self.call_from_thread(self._finish_prompt, status)

    def _handle_chat_event(self, event: ChatEvent) -> None:
        event_type = event.event_type
        payload = event.payload
        if event_type == "assistant_message":
            self._append_block("Assistant", payload_text(payload, "content", event.message))
        elif event_type == "tool_started":
            self._record_tool_line(f"Tool {payload_text(payload, 'tool_name', 'unknown')} ...")
        elif event_type == "tool_finished":
            self._record_tool_line(f"Tool {payload_text(payload, 'tool_name', 'unknown')} done")
        elif event_type == "tool_failed":
            self._record_tool_line(f"Tool {payload_text(payload, 'tool_name', 'unknown')} failed")
        elif event_type == "approval_requested":
            self._state = "waiting approval"
            tool_name = payload_text(payload, "tool_name", "unknown")
            self._tool_lines.append(f"{tool_name} pending approval")
            self._append_line(f"Tool {tool_name} pending approval")
        elif event_type == "user_input_requested":
            self._state = "waiting input"
            question = payload_text(payload, "question", event.message)
            self._set_answer_required(question)
            self._append_block("Answer required", question)
        elif event_type == "approval_granted":
            tool_name = payload_text(payload, "tool_name", "unknown")
            self._state = "running"
            self._tool_lines.append(f"{tool_name} approved")
            self._append_line(f"Approval granted: {tool_name}")
        elif event_type == "approval_denied":
            tool_name = payload_text(payload, "tool_name", "unknown")
            self._tool_lines.append(f"{tool_name} denied")
            self._append_line(f"Approval denied: {tool_name}")
        elif event_type == "user_input_received":
            self._handle_user_input_received(event)
        elif event_type == "memory_candidates_created":
            self._handle_memory_candidates_created(event)
        elif event_type == "memory_extraction_warning":
            self._append_block("Memory warning", payload_text(payload, "message", event.message))
        elif event_type == "failure":
            self._handle_failure_event(event)
        self._refresh()

    def _record_tool_line(self, line: str) -> None:
        self._tool_lines.append(line)
        self._append_line(line)

    def _handle_user_input_received(self, event: ChatEvent) -> None:
        tool_name = payload_text(event.payload, "tool_name", "request_user_input")
        self._state = "running"
        if event.payload.get("approved") is False:
            self._append_line(f"Answer declined: {tool_name}")
        else:
            self._append_line(f"Answer submitted: {tool_name}")

    def _handle_memory_candidates_created(self, event: ChatEvent) -> None:
        message = payload_text(
            event.payload,
            "message",
            event.message or "发现可记忆候选，已放入候选队列，等待你确认。",
        )
        self._append_block("Memory", message)
        self._memory_notice = message
        self._memory_mode = True
        self._memory_detail_mode = False
        self._load_memory_candidates(silent=True)

    def _handle_failure_event(self, event: ChatEvent) -> None:
        self._state = "failed"
        reason = payload_text(event.payload, "reason", event.message)
        failed_stage = payload_text(event.payload, "failed_stage", "unknown")
        category = payload_text(event.payload, "failure_category", "unknown")
        episode_path = payload_text(event.payload, "episode_path", "unknown")
        self._last_failure = {
            "failed_stage": failed_stage,
            "failure_category": category,
            "reason": reason,
            "episode_path": episode_path,
        }
        self._append_block("Failure", failure_body(failed_stage, category, reason, episode_path))

    def _handle_interaction(self, request: HumanInteractionRequest) -> HumanInteractionResponse:
        pending = PendingInteraction(request)
        self.call_from_thread(self._begin_interaction, pending)
        pending.done.wait()
        return pending.response or HumanInteractionResponse(approved=False, answer="")

    def _begin_interaction(self, pending: PendingInteraction) -> None:
        self._pending_interaction = pending
        request = pending.request
        if request.interaction_type == "approval":
            self._state = "waiting approval"
            self.push_screen(ToolApprovalModal(request), self._complete_approval)
        else:
            self._state = "waiting input"
            self._set_answer_required(request.question)
        self._refresh()

    def _complete_approval(self, approved: bool | None) -> None:
        self._complete_interaction(HumanInteractionResponse(approved=bool(approved), answer=""))

    def _complete_interaction(self, response: HumanInteractionResponse) -> None:
        pending = self._pending_interaction
        if pending is None:
            return
        pending.response = response
        pending.done.set()
        self._pending_interaction = None
        self._restore_prompt_input()
        self._state = "running"
        self._refresh()

    def _set_answer_required(self, question: str) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        prompt_input.placeholder = f"回答 Agent 的问题：{safe_summary(question, 90)}"
        prompt_input.focus()

    def _restore_prompt_input(self) -> None:
        self.query_one("#prompt-input", PromptInput).placeholder = self._default_prompt_placeholder

    def _prompt_value(self, prompt_input: PromptInput) -> str:
        return prompt_input.text

    def _set_prompt_value(self, prompt_input: PromptInput, value: str) -> None:
        prompt_input.load_text(value)
        prompt_input.move_cursor(_end_location(value))

    def _finish_prompt(self, status: str) -> None:
        if status == "completed" and self._state not in {"waiting approval", "waiting input"}:
            self._state = "idle"
        elif status != "completed":
            self._state = "failed"
        self._refresh()

    def _handle_prompt_error(self, error: Exception) -> None:
        self._state = "failed"
        self._append_block("Failure", str(error))
        self._refresh()

    def _show_initial_configuration_state(self) -> None:
        status = self.service.get_workspace_status()
        if status.profile_error is not None:
            self._append_block("Config", "未找到默认模型配置\n请先运行：uv run haagent setup")
        elif status.credential_store_available is False:
            reason = status.credential_store_error or "unknown"
            self._append_block("Config", f"系统凭据库不可用：{reason}\n请运行：uv run haagent setup 重新选择凭据来源。")
        elif status.api_key_env and not status.api_key_available:
            self._append_block("Config", f"API key 缺失：{status.api_key_env}\nHaAgent 不会在 TUI 中输入、保存或显示真实 API key。")

    def _refresh(self) -> None:
        status = self.service.get_workspace_status()
        self.query_one("#status-bar", StatusBar).update_status(status_line(status, ui_state=self._state, width=self.size.width))
        self._refresh_conversation()
        self.query_one("#side-bar", SideBar).update_content(
            side_bar(
                status,
                ui_state=self._state,
                tool_lines=self._tool_lines,
                last_failure=self._last_failure,
                memory_text=self._memory_panel_text() if self._memory_mode else None,
            ),
        )
        self.query_one("#footer-bar", FooterBar).update_footer(footer_text(self._help_context()))

    def _help_context(self) -> str:
        if self.size.width < self.MIN_WIDTH or self.size.height < self.MIN_HEIGHT:
            return "too_small"
        if self._pending_interaction is not None:
            return "pending_input" if self._pending_interaction.request.interaction_type == "user_input" else "approval"
        if self._memory_mode:
            return "memory_detail" if self._memory_detail_mode else "memory_list"
        return "chat"

    def _refresh_conversation(self) -> None:
        conversation = self.query_one("#conversation", ConversationView)
        if self._memory_mode:
            conversation.show_memory(self._memory_panel_text())
            self._conversation_placeholder_rendered = False
            self._conversation_rendered_count = 0
            return
        if not self._conversation_lines:
            if not self._conversation_placeholder_rendered:
                conversation.show_placeholder()
                self._conversation_placeholder_rendered = True
            return
        if self._conversation_placeholder_rendered or self._conversation_rendered_count > len(self._conversation_lines):
            conversation.clear()
            self._conversation_rendered_count = 0
            self._conversation_placeholder_rendered = False
        conversation.append_lines(self._conversation_lines, start=self._conversation_rendered_count)
        self._conversation_rendered_count = len(self._conversation_lines)
        self.call_after_refresh(self._scroll_conversation_to_end)

    def _scroll_conversation_to_end(self) -> None:
        conversation = self.query_one("#conversation", ConversationView)
        conversation.scroll_to(y=conversation.max_scroll_y, animate=False, immediate=True, force=True)

    def _load_memory_candidates(self, *, silent: bool = False) -> None:
        try:
            self._memory_candidates = self.service.list_memory_candidates(status="pending")
            self._memory_error = None
            if self._memory_selected >= len(self._memory_candidates):
                self._memory_selected = max(0, len(self._memory_candidates) - 1)
        except Exception as error:
            self._memory_candidates = []
            self._memory_error = str(error)
            if not silent:
                self._append_block("Memory warning", f"Memory candidates unavailable: {error}")

    def _selected_memory_candidate(self) -> MemoryCandidate:
        return self._memory_candidates[self._memory_selected]

    def _handle_memory_key(self, key: str) -> bool:
        if key in {"up", "k"}:
            self.action_memory_up()
            return True
        if key in {"down", "j"}:
            self.action_memory_down()
            return True
        if key == "g":
            self.action_memory_first()
            return True
        if key in {"G", "shift+g", "upper_g"}:
            self.action_memory_last()
            return True
        return False

    def _move_memory_selection(self, delta: int) -> None:
        if not self._memory_mode or self._memory_detail_mode or not self._memory_candidates:
            return
        next_index = self._memory_selected + delta
        self._memory_selected = min(max(next_index, 0), len(self._memory_candidates) - 1)
        self._refresh()

    def _memory_panel_text(self) -> str:
        return memory_panel_text(
            candidates=self._memory_candidates,
            selected_index=self._memory_selected,
            detail_mode=self._memory_detail_mode,
            notice=self._memory_notice,
            error=self._memory_error,
        )

    def _footer_text(self) -> str:
        return footer_text(self._help_context())

    def _append_block(self, title: str, body: str) -> None:
        self._conversation_lines.append(f"{title}\n  {body}")

    def _append_line(self, line: str) -> None:
        self._conversation_lines.append(line)

    def _update_responsive_layout(self, width: int | None = None, height: int | None = None) -> None:
        terminal_width = width if width is not None else self.size.width
        terminal_height = height if height is not None else self.size.height
        layout = layout_for_size(terminal_width, terminal_height)
        self.query_one("#resize-message", ResizeMessage).set_class(not layout.too_small, "hidden")
        self.query_one("#main", Horizontal).set_class(layout.too_small, "hidden")
        self.query_one("#input-panel", Vertical).set_class(layout.too_small, "hidden")
        self.query_one("#footer-bar", FooterBar).set_class(layout.too_small, "hidden")
        self.query_one("#side-bar", SideBar).set_class(not layout.show_side_bar, "hidden")


def run_tui(service: AssistantService) -> int:
    HaAgentTuiApp(service).run()
    return 0
