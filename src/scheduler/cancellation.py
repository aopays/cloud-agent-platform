"""Cancellation propagation independent of a concrete Redis implementation."""

from __future__ import annotations

import asyncio


class CancellationBroker:
    def __init__(self) -> None:
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    async def cancel(self, task_id: str) -> None:
        async with self._lock:
            self._cancelled.add(task_id)

    async def is_cancelled(self, task_id: str) -> bool:
        async with self._lock:
            return task_id in self._cancelled

    def signal_for(self, task_id: str) -> TaskCancellationSignal:
        return TaskCancellationSignal(self, task_id)


class TaskCancellationSignal:
    def __init__(self, broker: CancellationBroker, task_id: str) -> None:
        self._broker = broker
        self._task_id = task_id

    async def is_cancelled(self) -> bool:
        return await self._broker.is_cancelled(self._task_id)
