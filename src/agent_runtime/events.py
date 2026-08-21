"""Strictly ordered, redacted runtime event emission."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from src.shared.events import AgentEvent
from src.shared.interfaces import EventSink

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)((?:aws_)?(?:secret_access_key|session_token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://)[^\s/@]+:[^\s/@]+@"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        secret_keys = {
            "authorization",
            "api_key",
            "apikey",
            "password",
            "secret",
            "access_token",
            "refresh_token",
            "aws_secret_access_key",
            "aws_session_token",
            "secret_access_key",
            "session_token",
        }
        return {
            str(key): "[REDACTED]" if str(key).lower() in secret_keys else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact(item) for item in value]
    return value


class EventRecorder:
    def __init__(self, sink: EventSink, task_id: str, attempt_id: str) -> None:
        self._sink = sink
        self._task_id = task_id
        self._attempt_id = attempt_id
        self._sequence = 0

    async def emit(self, event_type: str, payload: dict[str, Any]) -> AgentEvent:
        safe_payload = redact(payload)
        allocator = getattr(self._sink, "append_next", None)
        if allocator is not None:
            event = cast(
                AgentEvent,
                await allocator(
                    self._task_id,
                    self._attempt_id,
                    event_type,
                    safe_payload,
                ),
            )
            self._sequence = event.sequence
            return event
        for _ in range(10):
            existing = await self._sink.list_after(self._task_id)
            observed_sequence = max(
                (stored.sequence for stored in existing if stored.attempt_id == self._attempt_id),
                default=0,
            )
            self._sequence = max(self._sequence, observed_sequence)
            event = AgentEvent(
                task_id=self._task_id,
                attempt_id=self._attempt_id,
                sequence=self._sequence + 1,
                event_type=event_type,
                payload=safe_payload,
            )
            try:
                await self._sink.append(event)
            except ValueError as exc:
                if "sequence" not in str(exc) and "event key conflicts" not in str(exc):
                    raise
                continue
            self._sequence = event.sequence
            return event
        raise ValueError("event sequence remained contended after retries")
