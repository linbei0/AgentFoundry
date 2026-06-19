"""
agentfoundry/models/fake.py - 测试用模型网关

提供确定性 fake model，方便测试 orchestrator 和工具链路。
"""

from __future__ import annotations

from typing import Any

from agentfoundry.models.gateway import ModelResponse, ToolCall
from agentfoundry.runtime.task_contract import TaskSpec


class FakeModelGateway:
    provider_name = "fake"

    def __init__(self, response: ModelResponse | None = None) -> None:
        self._response = response or ModelResponse(
            content="Use the fake tool for the MVP execution step.",
            tool_calls=[ToolCall(name="fake_tool", args={})],
        )

    def generate(
        self,
        task: TaskSpec,
        observations: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        if observations and self._response.tool_calls:
            return ModelResponse(content="Fake model observed tool results.", tool_calls=[])
        return self._response
