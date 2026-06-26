"""
haagent/memory/candidates.py - 长期记忆候选队列

维护 session 级 append-only 候选队列，所有长期记忆候选确认前必须先落在这里。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from haagent.memory.governance import (
    validate_candidate_source,
    validate_candidate_status,
    validate_scope_category,
)
from haagent.memory.schema import CandidateEvidence, MemoryCandidate


class CandidateQueueError(RuntimeError):
    """候选队列缺失或状态不合法时抛出。"""


class CandidateQueue:
    def __init__(self, session_path: Path) -> None:
        self.session_path = session_path
        self.path = session_path / "memory_candidates.jsonl"

    def create(
        self,
        *,
        scope: str,
        category: str,
        title: str,
        body: str,
        evidence: CandidateEvidence,
        source: str,
        tags: list[str] | None = None,
        risk_flags: list[str] | None = None,
    ) -> MemoryCandidate:
        validate_scope_category(scope, category)
        validate_candidate_source(source)
        created_at = _now_iso()
        candidate = MemoryCandidate(
            candidate_id="cand_" + uuid.uuid4().hex[:12],
            scope=scope,
            category=category,
            title=title,
            body=body,
            evidence=evidence,
            source=source,
            status="pending",
            created_at=created_at,
            updated_at=created_at,
            tags=list(tags or []),
            risk_flags=list(risk_flags or []),
        )
        self._append(candidate)
        return candidate

    def list(self, status: str | None = None) -> list[MemoryCandidate]:
        if status is not None:
            validate_candidate_status(status)
        candidates = list(self._latest().values())
        if status is None:
            return candidates
        return [candidate for candidate in candidates if candidate.status == status]

    def get(self, candidate_id: str) -> MemoryCandidate:
        candidate = self._latest().get(candidate_id)
        if candidate is None:
            raise CandidateQueueError(f"memory candidate not found: {candidate_id}")
        return candidate

    def reject(self, candidate_id: str) -> MemoryCandidate:
        candidate = self.get(candidate_id)
        if candidate.status != "pending":
            raise CandidateQueueError(f"candidate is not pending: {candidate_id}")
        rejected = replace(candidate, status="rejected", updated_at=_now_iso())
        self._append(rejected)
        return rejected

    def mark_confirmed(self, candidate_id: str, memory_id: str) -> MemoryCandidate:
        candidate = self.get(candidate_id)
        if candidate.status != "pending":
            raise CandidateQueueError(f"candidate is not pending: {candidate_id}")
        confirmed = replace(
            candidate,
            status="confirmed",
            updated_at=_now_iso(),
            committed_memory_id=memory_id,
        )
        self._append(confirmed)
        return confirmed

    def _latest(self) -> dict[str, MemoryCandidate]:
        latest: dict[str, MemoryCandidate] = {}
        if not self.path.exists():
            return latest
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                candidate = MemoryCandidate.from_dict(json.loads(line))
            except (json.JSONDecodeError, ValueError) as error:
                raise CandidateQueueError(f"invalid memory_candidates.jsonl line {line_number}") from error
            latest[candidate.candidate_id] = candidate
        return latest

    def _append(self, candidate: MemoryCandidate) -> None:
        self.session_path.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(candidate.to_dict(), ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
