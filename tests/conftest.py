"""
tests/conftest.py - pytest 测试分层标记

按测试文件职责自动添加 unit、contract、workflow、slow 和 smoke 标记。
"""

from __future__ import annotations

from pathlib import Path

import pytest


CONTRACT_FILES = {
    "test_cli_export_eval.py",
    "test_cli_inspect.py",
    "test_context_builder.py",
    "test_episode_validator.py",
    "test_eval_export.py",
    "test_model_gateway.py",
    "test_task_loading.py",
    "test_tool_registry.py",
    "test_tool_router.py",
}

WORKFLOW_FILES = {
    "test_cli_run.py",
    "test_orchestrator.py",
    "test_verification_engine.py",
}

UNIT_FILES = {
    "test_command.py",
    "test_episode_writer.py",
    "test_failure_taxonomy.py",
    "test_policy.py",
}

SMOKE_FILES = {"test_cli_smoke.py"}

SLOW_NODE_KEYWORDS = {
    "test_run_command_records_timeout",
    "test_verification_engine_records_timeout",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help="run manual real-model dogfood tests; skipped by default",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """为测试选择命令提供稳定 marker，不把分层噪音写进每个用例。"""
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename in CONTRACT_FILES:
            item.add_marker(pytest.mark.contract)
        elif filename in WORKFLOW_FILES:
            item.add_marker(pytest.mark.workflow)
        elif filename in UNIT_FILES:
            item.add_marker(pytest.mark.unit)
        elif filename in SMOKE_FILES:
            item.add_marker(pytest.mark.smoke)

        if any(keyword in item.nodeid for keyword in SLOW_NODE_KEYWORDS):
            item.add_marker(pytest.mark.slow)
