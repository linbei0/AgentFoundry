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
        if self._response.tool_calls and not _tool_schema_available(tool_schemas, "fake_tool"):
            return ModelResponse(
                content="Fake model has no fake_tool available; relying on verification.",
                tool_calls=[],
            )
        if observations and self._response.tool_calls:
            return ModelResponse(content="Fake model observed tool results.", tool_calls=[])
        return self._response


def _tool_schema_available(tool_schemas: list[dict[str, Any]], tool_name: str) -> bool:
    if not tool_schemas:
        return True
    return any(schema.get("name") == tool_name for schema in tool_schemas)
