"""
tests/test_loop_guidance.py - Agent loop 推进策略测试

验证工具结果和 no-tool 回复会生成短小、可审计的下一步 guidance。
"""

from __future__ import annotations

from haagent.runtime.loop_guidance import (
    LoopGuidanceState,
    guidance_for_no_tool_response,
    guidance_for_observation,
)


def test_guidance_for_successful_file_search_selects_file_to_read() -> None:
    guidance = guidance_for_observation(
        {
            "tool_name": "file_search",
            "args": {"query": "greet"},
            "result": {
                "status": "success",
                "matches": [{"path": "src/app.py", "line": 1, "text": "def greet"}],
            },
        },
        LoopGuidanceState(),
    )

    assert guidance is not None
    assert guidance.status == "continue"
    assert "file_read" in guidance.message
    assert "src/app.py" in guidance.message


def test_guidance_for_missing_file_prefers_suggestion_path() -> None:
    guidance = guidance_for_observation(
        {
            "tool_name": "file_read",
            "args": {"path": "app.py"},
            "result": {
                "status": "error",
                "error": {
                    "type": "tool_argument_invalid",
                    "message": "path does not exist: app.py",
                },
                "suggestions": ["src/app.py"],
            },
        },
        LoopGuidanceState(),
    )

    assert guidance is not None
    assert guidance.status == "handle_error"
    assert guidance.message == "File path failed; try the suggested path with file_read: src/app.py."


def test_guidance_for_patch_miss_reads_current_file_before_retry() -> None:
    guidance = guidance_for_observation(
        {
            "tool_name": "apply_patch",
            "args": {"path": "README.md", "old_text": "missing", "new_text": "new"},
            "result": {
                "status": "error",
                "error": {"type": "patch_not_applied", "message": "old_text not found"},
            },
        },
        LoopGuidanceState(),
    )

    assert guidance is not None
    assert "file_read README.md" in guidance.message
    assert "narrow old_text" in guidance.message


def test_guidance_for_shell_failure_uses_output_without_mechanical_retry() -> None:
    guidance = guidance_for_observation(
        {
            "tool_name": "shell",
            "args": {"command": "pytest -q"},
            "result": {
                "status": "error",
                "exit_code": 1,
                "stdout": "x" * 1000,
                "stderr": "AssertionError: bad value",
            },
        },
        LoopGuidanceState(),
    )

    assert guidance is not None
    assert "Use stderr/stdout" in guidance.message
    assert "do not rerun the same command unchanged" in guidance.message
    assert "x" * 300 not in guidance.message


def test_consecutive_failures_require_new_strategy_or_user_input() -> None:
    state = LoopGuidanceState()
    first = guidance_for_observation(
        {
            "tool_name": "file_read",
            "args": {"path": "missing.py"},
            "result": {"status": "error", "error": {"type": "tool_argument_invalid", "message": "missing"}},
        },
        state,
    )
    second = guidance_for_observation(
        {
            "tool_name": "file_read",
            "args": {"path": "missing.py"},
            "result": {"status": "error", "error": {"type": "tool_argument_invalid", "message": "missing"}},
        },
        state,
    )

    assert first is not None
    assert second is not None
    assert "Do not repeat the same failing tool call" in second.message
    assert "request_user_input" in second.message


def test_no_tool_review_pushes_file_modification_to_tools() -> None:
    guidance = guidance_for_no_tool_response(
        "Here is the code you should put in README.md:\n```markdown\nupdated\n```",
        "修改 README 文件",
        LoopGuidanceState(),
    )

    assert guidance is not None
    assert guidance.status == "continue"
    assert "file_write/apply_patch" in guidance.message


def test_no_tool_review_pushes_unverified_completion_to_validation() -> None:
    guidance = guidance_for_no_tool_response(
        "Done, tests pass.",
        "修改 Python 文件并运行测试",
        LoopGuidanceState(),
    )

    assert guidance is not None
    assert "verify" in guidance.message
    assert "shell/code_run" in guidance.message


def test_no_tool_review_allows_normal_final_answer() -> None:
    guidance = guidance_for_no_tool_response(
        "Project has src/app.py and tests/test_app.py.",
        "总结项目结构",
        LoopGuidanceState(),
    )

    assert guidance is None
