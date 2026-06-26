"""
haagent/memory/audit.py - 长期记忆审计日志

以 JSONL 记录候选和长期记忆状态变化，不保存 secret 或完整运行 trace。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from haagent.memory.governance import redact_sensitive
from haagent.memory.schema import AUDIT_EVENT_TYPES, MemoryAuditEvent


class MemoryAuditError(RuntimeError):
    """审计事件结构不合法时抛出。"""


class MemoryAuditLog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "audit.jsonl"

    def append(
        self,
        *,
        event_type: str,
        scope: str,
        actor: str,
        category: str | None = None,
        candidate_id: str | None = None,
        memory_id: str | None = None,
        status_from: str | None = None,
        status_to: str | None = None,
        reason: str | None = None,
        summary: str | None = None,
    ) -> MemoryAuditEvent:
        if event_type not in AUDIT_EVENT_TYPES:
            raise MemoryAuditError(f"unknown memory audit event type: {event_type}")
        event = MemoryAuditEvent(
            event_id="audit_" + uuid.uuid4().hex[:12],
            event_type=event_type,
            created_at=datetime.now(UTC).isoformat(),
            actor=actor,
            scope=scope,
            category=category,
            candidate_id=candidate_id,
            memory_id=memory_id,
            status_from=status_from,
            status_to=status_to,
            reason=redact_sensitive(reason) if reason is not None else None,
            summary=_audit_summary(summary),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event


def _audit_summary(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(redact_sensitive(value).split())
    return normalized[:240]
