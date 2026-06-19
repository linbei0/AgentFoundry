"""
tests/test_orchestrator.py - RunOrchestrator 状态流转测试

验证成功路径、工具失败和模型失败会写入正确 run 状态。
"""

import json
from pathlib import Path

from agentfoundry.models.gateway import ModelCallError
from agentfoundry.models.gateway import ModelResponse, ToolCall
from agentfoundry.runtime.orchestrator import RunOrchestrator
from agentfoundry.runtime.state import RunStatus
from agentfoundry.verification.engine import VerificationResult


class FailingGateway:
    provider_name = "failing"

    def generate(self, task):
        raise ModelCallError("model exploded")


class SequenceGateway:
    provider_name = "sequence"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self.observations_seen = []

    def generate(self, task, observations=None):
        self.observations_seen.append(list(observations or []))
        return self._responses.pop(0)


def write_task(
    path: Path,
    allowed_tools: list[str],
    verification_commands: list[str] | None = None,
) -> None:
    allowed_tools_yaml = "\n".join(f"  - {tool}" for tool in allowed_tools)
    verification_commands = verification_commands or []
    verification_yaml = "\n".join(f"  - {command}" for command in verification_commands)
    verification_block = f"\n{verification_yaml}" if verification_yaml else " []"
    path.write_text(
        f"""
goal: Exercise orchestrator
constraints: []
allowed_tools:
{allowed_tools_yaml}
acceptance_criteria:
  - Run reaches terminal state
verification_commands:{verification_block}
""".strip(),
        encoding="utf-8",
    )


def test_orchestrator_records_successful_state_flow(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"])

    result = RunOrchestrator(runs_root=runs_dir).run(task_path)

    assert result.status is RunStatus.COMPLETED
    assert result.state_history == [
        RunStatus.CREATED,
        RunStatus.PLANNING,
        RunStatus.EXECUTING,
        RunStatus.VERIFYING,
        RunStatus.COMPLETED,
    ]


def test_orchestrator_fails_when_fake_tool_is_not_allowed(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["other_tool"])

    result = RunOrchestrator(runs_root=runs_dir).run(task_path)

    assert result.status is RunStatus.FAILED
    assert result.state_history[-1] is RunStatus.FAILED
    failure_text = (result.episode_path / "failure-attribution.md").read_text(encoding="utf-8")
    assert "Task Spec Failure" in failure_text
    assert "other_tool" in failure_text
    assert (result.episode_path / "tool-calls.jsonl").read_text(encoding="utf-8") == ""


def test_orchestrator_fails_when_model_gateway_fails(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"])

    result = RunOrchestrator(runs_root=runs_dir, model_gateway=FailingGateway()).run(task_path)

    assert result.status is RunStatus.FAILED
    assert result.state_history == [
        RunStatus.CREATED,
        RunStatus.PLANNING,
        RunStatus.FAILED,
    ]
    failure_text = (result.episode_path / "failure-attribution.md").read_text(encoding="utf-8")
    assert "Model Failure" in failure_text
    assert "model exploded" in failure_text
    assert (result.episode_path / "tool-calls.jsonl").read_text(encoding="utf-8") == ""


def test_orchestrator_fails_when_verification_command_fails(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(
        task_path,
        ["fake_tool"],
        verification_commands=["python -c \"import sys; sys.exit(5)\""],
    )

    result = RunOrchestrator(runs_root=runs_dir).run(task_path)

    assert result.status is RunStatus.FAILED
    assert result.state_history == [
        RunStatus.CREATED,
        RunStatus.PLANNING,
        RunStatus.EXECUTING,
        RunStatus.VERIFYING,
        RunStatus.FAILED,
    ]
    failure_text = (result.episode_path / "failure-attribution.md").read_text(encoding="utf-8")
    assert "Verification Failure" in failure_text
    commands_log = result.episode_path / "verification" / "commands.jsonl"
    assert json.loads(commands_log.read_text(encoding="utf-8"))["exit_code"] == 5


def test_orchestrator_fails_unknown_tool_as_task_spec_failure(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["mystery_tool"])

    result = RunOrchestrator(runs_root=runs_dir).run(task_path)

    assert result.status is RunStatus.FAILED
    assert result.state_history == [
        RunStatus.CREATED,
        RunStatus.PLANNING,
        RunStatus.FAILED,
    ]
    failure_text = (result.episode_path / "failure-attribution.md").read_text(encoding="utf-8")
    assert "Task Spec Failure" in failure_text
    assert "mystery_tool" in failure_text


def test_orchestrator_failure_attribution_includes_verification_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"], verification_commands=["slow command"])

    class TimeoutVerificationEngine:
        def __init__(self, episode_writer, workspace_root):
            pass

        def run(self, commands):
            return VerificationResult(
                status="failed",
                failed_command=commands[0],
                exit_code=None,
                failure_reason="timeout",
            )

    monkeypatch.setattr(
        "agentfoundry.runtime.orchestrator.VerificationEngine",
        TimeoutVerificationEngine,
    )

    result = RunOrchestrator(runs_root=runs_dir).run(task_path)

    assert result.status is RunStatus.FAILED
    failure_text = (result.episode_path / "failure-attribution.md").read_text(encoding="utf-8")
    assert "Verification Failure" in failure_text
    assert "slow command" in failure_text
    assert "timeout" in failure_text


def test_orchestrator_completes_after_two_tool_rounds(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"])
    gateway = SequenceGateway(
        [
            ModelResponse("round 1", [ToolCall("fake_tool", {"round": 1})]),
            ModelResponse("round 2", [ToolCall("fake_tool", {"round": 2})]),
            ModelResponse("done", []),
        ],
    )

    result = RunOrchestrator(runs_root=runs_dir, model_gateway=gateway).run(task_path)

    assert result.status is RunStatus.COMPLETED
    assert len(gateway.observations_seen) == 3
    assert gateway.observations_seen[0] == []
    assert gateway.observations_seen[1][0]["tool_name"] == "fake_tool"
    transcript = _read_transcript(result.episode_path)
    assert [record["context_id"] for record in transcript if record.get("event") == "model_call"] == [
        "0001",
        "0002",
        "0003",
    ]
    assert len([record for record in transcript if record.get("event") == "tool_observation"]) == 2
    first_context = (result.episode_path / "contexts" / "0001.txt").read_text(encoding="utf-8")
    second_context = (result.episode_path / "contexts" / "0002.txt").read_text(encoding="utf-8")
    second_manifest = json.loads(
        (result.episode_path / "contexts" / "0002.json").read_text(encoding="utf-8"),
    )
    assert "Observations:" in first_context
    assert "- none" in first_context
    assert "fake_tool" in second_context
    assert '"args": {"round": 1}' in second_context
    assert any(
        source["source_type"] == "observation" and source["name"] == "fake_tool"
        for source in second_manifest["sources"]
    )


def test_orchestrator_verifies_immediately_when_model_returns_no_tools(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"])
    gateway = SequenceGateway([ModelResponse("no tools", [])])

    result = RunOrchestrator(runs_root=runs_dir, model_gateway=gateway).run(task_path)

    assert result.status is RunStatus.COMPLETED
    assert result.state_history == [
        RunStatus.CREATED,
        RunStatus.PLANNING,
        RunStatus.VERIFYING,
        RunStatus.COMPLETED,
    ]
    transcript = _read_transcript(result.episode_path)
    assert [record.get("event") for record in transcript].count("model_call") == 1
    assert [record.get("event") for record in transcript].count("tool_observation") == 0


def test_orchestrator_fails_when_loop_exceeds_max_turns(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"])
    gateway = SequenceGateway(
        [
            ModelResponse("round 1", [ToolCall("fake_tool", {"round": 1})]),
            ModelResponse("round 2", [ToolCall("fake_tool", {"round": 2})]),
            ModelResponse("round 3", [ToolCall("fake_tool", {"round": 3})]),
        ],
    )

    result = RunOrchestrator(runs_root=runs_dir, model_gateway=gateway, max_turns=3).run(task_path)

    assert result.status is RunStatus.FAILED
    assert result.state_history[-1] is RunStatus.FAILED
    failure_text = (result.episode_path / "failure-attribution.md").read_text(encoding="utf-8")
    assert "Loop Limit Failure" in failure_text


def test_orchestrator_model_call_has_context_id_each_turn(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    runs_dir = tmp_path / ".runs"
    write_task(task_path, ["fake_tool"])
    gateway = SequenceGateway(
        [
            ModelResponse("round 1", [ToolCall("fake_tool", {})]),
            ModelResponse("done", []),
        ],
    )

    result = RunOrchestrator(runs_root=runs_dir, model_gateway=gateway).run(task_path)

    transcript = _read_transcript(result.episode_path)
    model_calls = [record for record in transcript if record.get("event") == "model_call"]
    assert result.status is RunStatus.COMPLETED
    assert [record["context_id"] for record in model_calls] == ["0001", "0002"]


def _read_transcript(episode_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (episode_path / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
