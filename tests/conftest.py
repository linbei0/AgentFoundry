"""
tests/conftest.py - pytest 测试分层标记

基于实测耗时为慢测试自动打 slow 标，让日常本地开发可用
`pytest -m "not slow"` 在数十秒内拿到反馈，完整套件仍跑全部用例。

SLOW_FILES 的依据是实测：这几个文件要启动 Textual app 或跑真实
agent 流程，单独占去完整套件大部分时间。排除它们后约 545 个用例
~35s 跑完，而完整套件约 134s。修改时请用实测耗时增删，而非凭直觉。
"""

from __future__ import annotations

from pathlib import Path

import pytest


# 实测耗时显著、应在快速本地运行中可被 -m "not slow" 排除的文件。
# 当前实测(完整套件 134s)：
#   test_tui_app.py          ~79s  每个用例启动 Textual app
#   test_real_task_smoke.py  ~13s  跑真实 agent 工作流
#   test_dogfood.py          ~6s   含一个 ~5.8s 的运行时用例
SLOW_FILES = {
    "test_tui_app.py",
    "test_real_task_smoke.py",
    "test_dogfood.py",
}

# 单个慢用例(其所在文件整体不慢，只标到具体用例)。
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
    """为慢测试打 slow 标，供 `-m "not slow"` 快速本地运行排除。"""
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename in SLOW_FILES or any(
            keyword in item.nodeid for keyword in SLOW_NODE_KEYWORDS
        ):
            item.add_marker(pytest.mark.slow)
