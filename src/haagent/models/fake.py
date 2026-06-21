"""
haagent/models/fake.py - 测试用模型网关

提供确定性 fake model，方便测试 orchestrator 和工具链路。
"""

from __future__ import annotations

from typing import Any

from haagent.models.gateway import ModelResponse, ToolCall
from haagent.runtime.task_contract import TaskSpec


class FakeModelGateway:
    provider_name = "fake"

    def __init__(self, response: ModelResponse | None = None) -> None:
        self._response = response or ModelResponse(
            content="Use the fake tool for the MVP execution step.",
            tool_calls=[ToolCall(name="fake_tool", args={})],
        )
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        task: TaskSpec,
        model_input: str,
        tool_schemas: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ) -> ModelResponse:
        self.calls.append(
            {
                "task": task,
                "model_input": model_input,
                "tool_schemas": list(tool_schemas),
                "observations": list(observations),
            },
        )
        if observations and self._response.tool_calls:
            return ModelResponse(content="Fake model observed tool results.", tool_calls=[])
        return self._response
