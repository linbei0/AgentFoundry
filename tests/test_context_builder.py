"""
tests/test_context_builder.py - ContextBuilder v1 测试

验证上下文文件、上下文索引和工具用途会被写入 episode package。
"""

import json
from pathlib import Path

import pytest

from agentfoundry.context.builder import ContextBuildError, ContextBuilder
from agentfoundry.runtime.episode import EpisodeWriter
from agentfoundry.runtime.task_contract import TaskSpec


def make_task(allowed_tools: list[str] | None = None) -> TaskSpec:
    return TaskSpec(
        goal="Build context",
        constraints=["No retrieval"],
        allowed_tools=allowed_tools or ["fake_tool", "file_read"],
        acceptance_criteria=["Context is auditable"],
        verification_commands=["uv run pytest"],
    )


def make_writer(tmp_path: Path) -> EpisodeWriter:
    task_path = tmp_path / "task.yaml"
    task_path.write_text(
        """
goal: Build context
constraints:
  - No retrieval
allowed_tools:
  - fake_tool
acceptance_criteria:
  - Context is auditable
verification_commands:
  - uv run pytest
""".strip(),
        encoding="utf-8",
    )
    return EpisodeWriter.create(runs_root=tmp_path / ".runs", task_path=task_path)


def test_context_builder_writes_context_files_and_manifest(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    builder = ContextBuilder(
        task=make_task(),
        workspace_root=tmp_path,
        provider_name="fake",
        episode_writer=writer,
    )

    result = builder.build()

    assert result.context_id == "0001"
    assert (writer.path / "contexts" / "0001.txt").exists()
    assert (writer.path / "contexts" / "0001.json").exists()
    manifest = json.loads((writer.path / "context-manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["provider"] == "fake"
    assert manifest["summary"]["workspace_root"] == str(tmp_path)
    assert manifest["contexts"][0]["context_id"] == "0001"


def test_context_builder_model_input_contains_tool_usage(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    builder = ContextBuilder(
        task=make_task(),
        workspace_root=tmp_path,
        provider_name="fake",
        episode_writer=writer,
    )

    builder.build()

    model_input = (writer.path / "contexts" / "0001.txt").read_text(encoding="utf-8")
    assert "goal: Build context" in model_input
    assert "fake_tool: deterministic test tool" in model_input
    assert "file_read: read a workspace text file with offset and limit" in model_input
    assert "verification_commands:" in model_input


def test_context_builder_rejects_unknown_allowed_tool(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    builder = ContextBuilder(
        task=make_task(["fake_tool", "mystery_tool"]),
        workspace_root=tmp_path,
        provider_name="fake",
        episode_writer=writer,
    )

    with pytest.raises(ContextBuildError, match="mystery_tool"):
        builder.build()
