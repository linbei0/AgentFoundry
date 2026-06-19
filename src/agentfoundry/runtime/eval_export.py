"""
agentfoundry/runtime/eval_export.py - Eval Case 导出器

把已校验的 episode package 转换为可审计、可序列化的最小 eval case 字典。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentfoundry.runtime.episode_validator import load_validated_episode_package
from agentfoundry.runtime.task_contract import load_task


EVAL_CASE_VERSION = "1.0"


def export_eval_case(episode_path: Path) -> dict[str, Any]:
    """导出单个 episode 的 eval case；入口先执行完整 package 校验。"""
    package_view = load_validated_episode_package(episode_path)

    episode_metadata = package_view.episode_metadata
    failure_record = package_view.failure_record
    task = load_task(episode_path / "task.yaml")

    return {
        "eval_case_version": EVAL_CASE_VERSION,
        "episode_version": episode_metadata["episode_version"],
        "task": {
            "goal": task.goal,
            "acceptance_criteria": task.acceptance_criteria,
            "verification_commands": task.verification_commands,
        },
        "workspace_root": episode_metadata["workspace_root"],
        "final_status": episode_metadata["status"],
        "failure": _failure_summary(failure_record),
        "verification": _verification_summary(package_view.verification_commands),
        "tool_names_used": _tool_names_used(package_view.tool_calls),
    }


def _failure_summary(record: dict[str, Any]) -> dict[str, Any] | None:
    if record["status"] == "success":
        return None
    failure = record["failure"]
    return {
        "category": failure["category"],
        "stage": failure["stage"],
        "evidence": failure["evidence"],
    }


def _verification_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "command": record["command"],
            "status": record["status"],
            "exit_code": record.get("exit_code"),
            "timeout": bool(record.get("timeout", False)),
        }
        for record in records
    ]


def _tool_names_used(records: list[dict[str, Any]]) -> list[str]:
    names = {str(record["tool_name"]) for record in records}
    return sorted(names)
