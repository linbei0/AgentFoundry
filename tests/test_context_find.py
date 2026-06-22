"""
tests/test_context_find.py - context_find 工具测试

验证轻量上下文检索能从自然语言请求找到工作区内的相关文件和片段。
"""

from __future__ import annotations

import json
from pathlib import Path

from haagent.runtime.episode import EpisodeWriter
from haagent.tools.file_tools import context_find, extract_context_keywords
from haagent.tools.router import ToolRouter


def test_extract_context_keywords_from_natural_language_query() -> None:
    keywords = extract_context_keywords("帮我找到 greeting 逻辑和 README 用法说明")

    assert "greeting" in keywords
    assert "readme" in keywords
    assert "逻辑" not in keywords


def test_context_find_finds_python_and_markdown_matches(tmp_path: Path) -> None:
    _write_workspace(tmp_path)

    result = context_find({"query": "greeting usage"}, tmp_path)

    assert result["status"] == "success"
    paths = [candidate["path"] for candidate in result["candidates"]]
    assert "src/app.py" in paths
    assert "README.md" in paths
    assert result["candidates"][0]["recommended_file_read"]["path"] in paths


def test_context_find_file_glob_limits_candidates(tmp_path: Path) -> None:
    _write_workspace(tmp_path)

    result = context_find({"query": "greeting usage", "file_glob": "*.md"}, tmp_path)

    assert result["status"] == "success"
    assert [candidate["path"] for candidate in result["candidates"]] == ["README.md"]


def test_context_find_skips_noise_directories(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".runs").mkdir()
    (tmp_path / ".runs" / "trace.txt").write_text("greeting hidden", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("greeting hidden", encoding="utf-8")

    result = context_find({"query": "greeting"}, tmp_path)

    paths = [candidate["path"] for candidate in result["candidates"]]
    assert ".runs/trace.txt" not in paths
    assert "node_modules/pkg.js" not in paths


def test_context_find_result_count_and_char_budget(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    for index in range(5):
        (tmp_path / f"note{index}.md").write_text(f"greeting {'x' * 200}\n", encoding="utf-8")

    result = context_find({"query": "greeting", "max_results": 2, "max_chars": 90}, tmp_path)

    assert result["status"] == "success"
    assert len(result["candidates"]) <= 2
    assert result["total_excerpt_chars"] <= 90
    assert result["truncated"] is True


def test_context_find_tool_router_records_tool_call(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    writer = _make_writer(tmp_path)
    router = ToolRouter(["context_find"], writer, workspace_root=tmp_path)

    result = router.dispatch("context_find", {"query": "greeting"})

    assert result["status"] == "success"
    trace = json.loads((writer.path / "tool-calls.jsonl").read_text(encoding="utf-8"))
    assert trace["tool_name"] == "context_find"
    assert trace["status"] == "success"


def _write_workspace(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "def greet(name):\n    return f'Hello, {name}!'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n\nUsage: call greeting from src/app.py.\n", encoding="utf-8")


def _make_writer(tmp_path: Path) -> EpisodeWriter:
    task_path = tmp_path / "task.yaml"
    task_path.write_text(
        """
goal: Find context
allowed_tools:
  - context_find
acceptance_criteria:
  - Context found
verification_commands: []
""".strip(),
        encoding="utf-8",
    )
    return EpisodeWriter.create(runs_root=tmp_path / ".runs", task_path=task_path)
