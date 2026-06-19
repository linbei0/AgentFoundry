"""
tests/test_tool_registry.py - Tool Registry v1 测试

验证工具注册表包含本阶段全部工具定义、风险级别和可导出的 JSON Schema。
"""

import pytest

from agentfoundry.tools.registry import (
    TOOL_REGISTRY,
    ToolDefinition,
    allowed_tool_definitions,
    export_tool_schemas,
    get_tool_definition,
)


def test_tool_registry_contains_mvp_tools() -> None:
    assert set(TOOL_REGISTRY) == {
        "fake_tool",
        "file_search",
        "file_read",
        "apply_patch",
        "shell",
    }
    assert all(isinstance(definition, ToolDefinition) for definition in TOOL_REGISTRY.values())


def test_tool_registry_definitions_have_required_metadata() -> None:
    fake_tool = TOOL_REGISTRY["fake_tool"]

    assert fake_tool.name == "fake_tool"
    assert fake_tool.description == "deterministic test tool"
    assert fake_tool.risk_level == "low"
    assert isinstance(fake_tool.parameters, dict)
    assert fake_tool.parameters["type"] == "object"
    assert fake_tool.parameters["properties"] == {}
    assert fake_tool.parameters["required"] == []
    assert fake_tool.parameters["additionalProperties"] is True


def test_export_fake_tool_schema() -> None:
    schemas = export_tool_schemas(["fake_tool"])

    assert schemas == [
        {
            "name": "fake_tool",
            "description": "deterministic test tool",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": True,
            },
        },
    ]


def test_export_tool_schemas_only_exports_allowed_tools() -> None:
    schemas = export_tool_schemas(["file_read", "shell"])

    assert [schema["name"] for schema in schemas] == ["file_read", "shell"]
    assert [definition.name for definition in allowed_tool_definitions(["file_read"])] == ["file_read"]


def test_tool_registry_rejects_unknown_tool() -> None:
    with pytest.raises(KeyError, match="unknown tool: mystery_tool"):
        get_tool_definition("mystery_tool")

    with pytest.raises(KeyError, match="unknown tool: mystery_tool"):
        export_tool_schemas(["fake_tool", "mystery_tool"])


def test_mutating_tools_are_high_risk() -> None:
    assert TOOL_REGISTRY["apply_patch"].risk_level == "high"
    assert TOOL_REGISTRY["shell"].risk_level == "high"
