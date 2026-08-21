"""At-least-once task queue port and process-local adapter."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QueueEmpty(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class QueueMessage:
    message_id: str
    task_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class QueueDelivery:
    receipt: str
    message: QueueMessage
    delivery_count: int
    visible_after: datetime


class TaskQueue(Protocol):
    async def enqueue(self, message: QueueMessage) -> bool: ...

    async def receive(self, *, visibility_timeout_seconds: float) -> QueueDelivery: ...

    async def ack(self, receipt: str) -> bool: ...

    async def nack(self, receipt: str) -> bool: ...


class InMemoryTaskQueue:
    """At-least-once queue used by the local MVP and deterministic tests."""

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._ready: deque[QueueMessage] = deque()
        self._inflight: dict[str, QueueDelivery] = {}
        self._known: dict[str, QueueMessage] = {}
        self._acked: set[str] = set()
        self._delivery_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, message: QueueMessage) -> bool:
        async with self._lock:
            if message.message_id in self._known or message.message_id in self._acked:
                return False
            self._known[message.message_id] = message
            self._ready.append(message)
            return True

    async def receive(self, *, visibility_timeout_seconds: float = 30) -> QueueDelivery:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        async with self._lock:
            self._requeue_expired_locked()
            if not self._ready:
                raise QueueEmpty("no task message is currently visible")

            message = self._ready.popleft()
            count = self._delivery_counts.get(message.message_id, 0) + 1
            self._delivery_counts[message.message_id] = count
            delivery = QueueDelivery(
                receipt=f"receipt_{uuid4().hex}",
                message=message,
                delivery_count=count,
                visible_after=self._clock() + timedelta(seconds=visibility_timeout_seconds),
            )
            self._inflight[delivery.receipt] = delivery
            return delivery

    async def ack(self, receipt: str) -> bool:
        async with self._lock:
            delivery = self._inflight.pop(receipt, None)
            if delivery is None:
                return False
            message_id = delivery.message.message_id
            self._known.pop(message_id, None)
            self._acked.add(message_id)
            return True

    async def nack(self, receipt: str) -> bool:
        async with self._lock:
            delivery = self._inflight.pop(receipt, None)
            if delivery is None:
                return False
            self._ready.appendleft(delivery.message)
            return True

    async def extend_visibility(self, receipt: str, *, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        async with self._lock:
            delivery = self._inflight.get(receipt)
            if delivery is None:
                return False
            self._inflight[receipt] = replace(
                delivery,
                visible_after=self._clock() + timedelta(seconds=timeout_seconds),
            )
            return True

    def _requeue_expired_locked(self) -> None:
        now = self._clock()
        expired = [
            receipt for receipt, delivery in self._inflight.items() if delivery.visible_after <= now
        ]
        for receipt in expired:
            delivery = self._inflight.pop(receipt)
            self._ready.appendleft(delivery.message)
