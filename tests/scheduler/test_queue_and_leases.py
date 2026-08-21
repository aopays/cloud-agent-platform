from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from src.scheduler.leases import InMemoryLeaseManager
from src.scheduler.queue import InMemoryTaskQueue, QueueEmpty, QueueMessage


@dataclass
class ManualClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def test_unacked_message_is_redelivered_after_visibility_timeout() -> None:
    async def scenario() -> None:
        clock = ManualClock(datetime(2026, 8, 19, tzinfo=timezone.utc))
        queue = InMemoryTaskQueue(clock=clock)
        message = QueueMessage("attempt_1", "task_1", "attempt_1")
        assert await queue.enqueue(message)
        assert not await queue.enqueue(message)

        first = await queue.receive(visibility_timeout_seconds=10)
        with pytest.raises(QueueEmpty):
            await queue.receive(visibility_timeout_seconds=10)

        clock.advance(10)
        second = await queue.receive(visibility_timeout_seconds=10)
        assert second.message == first.message
        assert second.receipt != first.receipt
        assert second.delivery_count == 2
        assert not await queue.ack(first.receipt)
        assert await queue.ack(second.receipt)

    asyncio.run(scenario())


def test_lease_prevents_parallel_owner_and_allows_expired_takeover() -> None:
    async def scenario() -> None:
        clock = ManualClock(datetime(2026, 8, 19, tzinfo=timezone.utc))
        leases = InMemoryLeaseManager(clock=clock)
        first = await leases.acquire(
            attempt_id="attempt_1",
            task_id="task_1",
            owner_id="worker-a",
            ttl_seconds=10,
        )
        assert first is not None
        assert (
            await leases.acquire(
                attempt_id="attempt_1",
                task_id="task_1",
                owner_id="worker-b",
                ttl_seconds=10,
            )
            is None
        )
        assert (
            await leases.acquire(
                attempt_id="attempt_1",
                task_id="task_1",
                owner_id="worker-a",
                ttl_seconds=10,
            )
            is None
        )

        clock.advance(10)
        takeover = await leases.acquire(
            attempt_id="attempt_1",
            task_id="task_1",
            owner_id="worker-b",
            ttl_seconds=10,
        )
        assert takeover is not None
        assert takeover.generation == 2
        assert not await leases.owns("attempt_1", owner_id="worker-a")
        assert await leases.owns("attempt_1", owner_id="worker-b")

    asyncio.run(scenario())
