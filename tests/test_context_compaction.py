from __future__ import annotations

import json
from pathlib import Path

from haagent.context.builder import ContextBuilder
from haagent.context.compaction import (
    ContextBudget,
    ContextCompactionResult,
    ContextSection,
    ContextSelectionRecord,
    assess_compact_readiness,
    compact_context_sections,
)
from haagent.runtime.episode import EpisodeWriter
from haagent.runtime.task_contract import TaskSpec


def test_collapse_oversized_section_keeps_head_and_tail() -> None:
    section = ContextSection(
        key="large",
        title="Large",
        content="H" * 12 + "M" * 20 + "T" * 8,
        source="test",
        priority=10,
        kind="project_instructions",
    )

    result = compact_context_sections(
        [section],
        ContextBudget(max_total_chars=100, max_section_chars=20, collapse_head_chars=10, collapse_tail_chars=5),
    )

    assert result.sections[0].content.startswith("H" * 10)
    assert result.sections[0].content.endswith("T" * 5)
    assert "...[collapsed 25 chars]..." in result.sections[0].content
    assert result.diagnostics[0].decision == "collapsed"
    assert result.diagnostics[0].original_chars == 40
    assert result.diagnostics[0].final_chars == len(result.sections[0].content)


def test_keeps_recent_observations_before_old_ones() -> None:
    sections = [
        ContextSection(
            key="old",
            title="Old Observation",
            content="old observation " * 20,
            source="tool-calls",
            priority=5,
            kind="observation",
            recent_rank=2,
        ),
        ContextSection(
            key="middle",
            title="Middle Observation",
            content="middle observation " * 20,
            source="tool-calls",
            priority=5,
            kind="observation",
            recent_rank=1,
        ),
        ContextSection(
            key="recent",
            title="Recent Observation",
            content="recent observation",
            source="tool-calls",
            priority=5,
            kind="observation",
            recent_rank=0,
        ),
    ]

    result = compact_context_sections(
        sections,
        ContextBudget(
            max_total_chars=80,
            max_section_chars=500,
            max_tool_observation_chars=40,
            keep_recent_observations=1,
            collapse_head_chars=20,
            collapse_tail_chars=10,
        ),
    )

    selected_keys = {section.key for section in result.sections}
    assert "recent" in selected_keys
    assert "old" not in selected_keys
    assert {record.key for record in result.diagnostics if record.decision == "skipped"}
    assert result.diagnostics[-1].decision == "selected"


def test_skipped_sections_are_recorded() -> None:
    sections = [
        ContextSection("high", "High", "important", "test", 10, "task"),
        ContextSection("low", "Low", "low priority content", "test", 1, "memory"),
    ]

    result = compact_context_sections(sections, ContextBudget(max_total_chars=12, max_section_chars=100))

    assert [section.key for section in result.sections] == ["high"]
    skipped = [record for record in result.diagnostics if record.decision == "skipped"]
    assert [record.key for record in skipped] == ["low"]
    assert skipped[0].reason == "over_total_budget"
    assert skipped[0].final_chars == 0


def test_no_compaction_when_under_budget() -> None:
    sections = [
        ContextSection("a", "A", "alpha", "test", 2, "task"),
        ContextSection("b", "B", "beta", "test", 1, "memory"),
    ]

    result = compact_context_sections(sections, ContextBudget(max_total_chars=100, max_section_chars=50))

    assert [section.content for section in result.sections] == ["alpha", "beta"]
    assert all(record.decision == "selected" for record in result.diagnostics)
    assert result.original_chars == len("alphabeta")
    assert result.final_chars == len("alphabeta")


def test_compact_readiness_is_sufficient_under_budget() -> None:
    result = ContextCompactionResult(
        sections=[],
        diagnostics=[
            ContextSelectionRecord("a", "test", "task", "selected", "within_budget", 40, 40, 10),
        ],
        original_chars=50,
        final_chars=40,
    )

    readiness = assess_compact_readiness(result, ContextBudget(max_total_chars=100))

    assert readiness["status"] == "deterministic_sufficient"
    assert readiness["budget_pressure"] == 0.4
    assert readiness["saved_ratio"] == 0.2
    assert readiness["recommendation"] == "keep_deterministic"
    assert readiness["reasons"] == ["within_budget_after_compaction"]


def test_compact_readiness_watches_near_budget_limit() -> None:
    result = ContextCompactionResult(
        sections=[],
        diagnostics=[
            ContextSelectionRecord("a", "test", "task", "selected", "within_budget", 84, 84, 10),
        ],
        original_chars=100,
        final_chars=84,
    )

    readiness = assess_compact_readiness(result, ContextBudget(max_total_chars=100))

    assert readiness["status"] == "watch"
    assert readiness["recommendation"] == "keep_deterministic"
    assert "near_budget_limit" in readiness["reasons"]


def test_compact_readiness_marks_full_compact_candidate_for_severe_pressure() -> None:
    result = ContextCompactionResult(
        sections=[],
        diagnostics=[
            ContextSelectionRecord("kept", "test", "task", "selected", "within_budget", 60, 60, 10),
            ContextSelectionRecord("collapsed", "test", "memory", "collapsed", "section_over_budget", 100, 35, 9),
            ContextSelectionRecord("skipped", "test", "memory", "skipped", "over_total_budget", 80, 0, 1),
        ],
        original_chars=240,
        final_chars=95,
    )

    readiness = assess_compact_readiness(result, ContextBudget(max_total_chars=100))

    assert readiness["status"] == "full_compact_candidate"
    assert readiness["recommendation"] == "evaluate_full_compact"
    assert readiness["skipped_count"] == 1
    assert readiness["collapsed_count"] == 1
    assert "near_budget_limit" in readiness["reasons"]
    assert "skipped_context_present" in readiness["reasons"]
    assert "collapsed_context_present" in readiness["reasons"]


def test_context_builder_returns_compaction_diagnostics_and_manifest(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    context = ContextBuilder(
        task=_task("summarize project"),
        workspace_root=tmp_path,
        provider_name="test-provider",
        episode_writer=writer,
        session_summary="summary from previous turns",
    ).build()

    manifest_path = writer.path / "contexts" / f"{context.context_id}-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert context.diagnostics
    assert "compaction" in manifest
    compaction = manifest["compaction"]
    assert compaction["selected_count"] == 1
    assert compaction["collapsed_count"] == 0
    assert compaction["skipped_count"] == 0
    assert compaction["selected_chars"] == len("summary from previous turns")
    assert compaction["collapsed_saved_chars"] == 0
    assert compaction["skipped_chars"] == 0
    assert compaction["skipped_reasons"] == {}
    assert compaction["diagnostics"][0]["decision"] == "selected"
    assert {record["key"] for record in compaction["diagnostics"]} == {"session_summary"}
    assert manifest["compact_readiness"]["status"] == "deterministic_sufficient"
    assert manifest["compact_readiness"]["recommendation"] == "keep_deterministic"
    assert manifest["source_diagnostics"]["session_summary"] == {
        "present": True,
        "included": True,
        "original_chars": len("summary from previous turns"),
        "model_input_chars": len("summary from previous turns"),
        "limit": 1000,
    }
    assert manifest["source_diagnostics"]["observations"] == {
        "included_in_model_input": False,
        "observation_section_count": 0,
        "compacted_count": 0,
        "truncated_count": 0,
        "skipped_count": 0,
        "original_chars": 0,
        "final_chars": 0,
        "saved_chars": 0,
        "reason": "context_builder_does_not_include_observation_sections",
    }
    assert "diagnostics" not in context.model_input
    assert "compaction" not in context.model_input
    assert "source_diagnostics" not in context.model_input
    assert "compact_readiness" not in context.model_input


def test_context_builder_records_observation_compaction_source_diagnostics(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    raw_output = "OBS-HEAD-" + ("body-" * 500) + "OBS-TAIL"

    context = ContextBuilder(
        task=_task("summarize project"),
        workspace_root=tmp_path,
        provider_name="test-provider",
        episode_writer=writer,
        observations=[
            {
                "tool_name": "shell",
                "args": {"command": "pytest"},
                "result": {"status": "success", "stdout": raw_output, "stderr": ""},
            },
        ],
    ).build()

    manifest_path = writer.path / "contexts" / f"{context.context_id}-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observations = manifest["source_diagnostics"]["observations"]

    assert observations["included_in_model_input"] is False
    assert observations["observation_section_count"] == 0
    assert observations["compacted_count"] == 1
    assert observations["truncated_count"] == 0
    assert observations["skipped_count"] == 0
    assert observations["original_chars"] > observations["final_chars"]
    assert observations["saved_chars"] == observations["original_chars"] - observations["final_chars"]
    assert "source_diagnostics" not in context.model_input
    assert "OBS-HEAD-" not in context.model_input


def test_context_builder_diagnostics_match_real_model_input(tmp_path: Path) -> None:
    project_instructions = "HEAD-" + ("middle-" * 700) + "TAIL"
    skipped_memory = "SKIPPED-MEMORY-" * 400
    writer = _make_writer(tmp_path)
    (tmp_path / "AGENTS.md").write_text(project_instructions, encoding="utf-8")

    compact_budget = ContextBudget(
        max_total_chars=90,
        max_section_chars=200,
        max_tool_observation_chars=1200,
        keep_recent_observations=4,
        collapse_head_chars=20,
        collapse_tail_chars=20,
    )
    context = ContextBuilder(
        task=_task("summarize project"),
        workspace_root=tmp_path,
        provider_name="test-provider",
        episode_writer=writer,
        session_summary="SESSION-KEPT",
        interaction_state=[
            {
                "type": "question",
                "tool": "request_user_input",
                "status": "answered",
                "question": "Continue?",
                "answer_excerpt": skipped_memory,
            },
        ],
        compaction_budget=compact_budget,
    ).build()

    assert "SKIPPED-MEMORY-" not in context.model_input
    assert project_instructions not in context.model_input
    bounded_project_instructions = project_instructions[:4000]
    assert bounded_project_instructions[:20] in context.model_input
    assert bounded_project_instructions[-20:] in context.model_input
    assert "...[collapsed " in context.model_input
    assert "SESSION-KEPT" in context.model_input
    assert "task_envelope" not in {record.key for record in context.diagnostics}


def test_context_builder_records_memory_source_diagnostics_when_memory_is_skipped(tmp_path: Path, monkeypatch) -> None:
    writer = _make_writer(tmp_path)
    memory_block = "\n".join(["Relevant Memory:", "- memory-id: skipped by context budget"])
    fake_result = _FakeMemoryResult(memory_block)
    monkeypatch.setattr(ContextBuilder, "_memory_result", lambda self: fake_result)

    compact_budget = ContextBudget(
        max_total_chars=10,
        max_section_chars=200,
        max_tool_observation_chars=1200,
        keep_recent_observations=4,
        collapse_head_chars=20,
        collapse_tail_chars=20,
    )
    context = ContextBuilder(
        task=_task("summarize project"),
        workspace_root=tmp_path,
        provider_name="test-provider",
        episode_writer=writer,
        compaction_budget=compact_budget,
    ).build()

    manifest_path = writer.path / "contexts" / f"{context.context_id}-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "Relevant Memory:" not in context.model_input
    assert any(record.key == "memory" and record.decision == "skipped" for record in context.diagnostics)
    assert "memory" in manifest
    assert manifest["source_diagnostics"]["memory"]["included_in_model_input"] is False


class _FakeMemoryResult:
    def __init__(self, model_block: str) -> None:
        self.memories = [object()]
        self._model_block = model_block

    def to_model_block(self) -> str:
        return self._model_block

    def to_manifest_dict(self) -> dict:
        return {
            "used_memories": [{"id": "memory-id"}],
            "budget": {"max_workspace_items": 6},
            "diagnostics": {
                "workspace_index_missing": 0,
                "user_index_missing": 0,
                "skipped_inactive": 0,
                "skipped_deleted": 0,
                "skipped_missing": 0,
                "skipped_invalid": 0,
                "skipped_over_budget": 2,
            },
        }


def _make_writer(tmp_path: Path) -> EpisodeWriter:
    task_path = tmp_path / "task.yaml"
    task_path.write_text("goal: test\n", encoding="utf-8")
    writer = EpisodeWriter.create(tmp_path / ".runs", task_path)
    writer.write_plan(
        {
            "goal": "test",
            "constraints": [],
            "acceptance_criteria": [],
            "verification_commands": [],
            "planned_steps": ["Use allowed tools."],
        },
    )
    return writer


def _task(goal: str) -> TaskSpec:
    return TaskSpec(
        goal=goal,
        workspace_root=".",
        allowed_tools=["file_read"],
        acceptance_criteria=[],
        verification_commands=[],
        constraints=[],
        policy={"approval_allowed_tools": [], "approved_tools": []},
    )
