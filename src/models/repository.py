"""Repository ports and an atomic in-memory MVP adapter."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Protocol

from src.models.tasks import AttemptRecord, TaskRecord


class TaskNotFound(LookupError):
    pass


class VersionConflict(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


class TaskRepository(Protocol):
    async def create_idempotent(
        self,
        record: TaskRecord,
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[TaskRecord, bool]: ...

    async def get(self, task_id: str) -> TaskRecord: ...

    async def save(self, record: TaskRecord, *, expected_version: int) -> TaskRecord: ...

    async def create_attempt(self, record: AttemptRecord) -> tuple[AttemptRecord, bool]: ...

    async def get_attempt(self, attempt_id: str) -> AttemptRecord: ...

    async def get_attempt_for_task(self, task_id: str) -> AttemptRecord: ...

    async def save_attempt(self, record: AttemptRecord) -> AttemptRecord: ...


class InMemoryTaskRepository:
    """Process-local adapter with the same atomic boundaries expected from SQL.

    The lock represents transactions/conditional writes. A production adapter can
    implement these operations using a unique tenant/idempotency constraint and an
    ``UPDATE ... WHERE version = expected_version`` condition.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._attempts: dict[str, AttemptRecord] = {}
        self._lock = asyncio.Lock()

    async def create_idempotent(
        self,
        record: TaskRecord,
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[TaskRecord, bool]:
        async with self._lock:
            lookup_key = (record.tenant_id, idempotency_key)
            existing = self._idempotency.get(lookup_key)
            if existing is not None:
                task_id, fingerprint = existing
                if fingerprint != request_fingerprint:
                    raise IdempotencyConflict(
                        "idempotency key was already used with a different request"
                    )
                return self._tasks[task_id], False

            if record.task_id in self._tasks:
                raise VersionConflict(f"task already exists: {record.task_id}")
            self._tasks[record.task_id] = record
            self._idempotency[lookup_key] = (record.task_id, request_fingerprint)
            return record, True

    async def get(self, task_id: str) -> TaskRecord:
        async with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise TaskNotFound(task_id) from exc

    async def save(self, record: TaskRecord, *, expected_version: int) -> TaskRecord:
        async with self._lock:
            current = self._tasks.get(record.task_id)
            if current is None:
                raise TaskNotFound(record.task_id)
            if current.version != expected_version:
                raise VersionConflict(
                    f"task {record.task_id} expected version {expected_version}, "
                    f"found {current.version}"
                )
            if record.version != expected_version + 1:
                raise VersionConflict("saved record must advance version exactly once")
            self._tasks[record.task_id] = record
            return record

    async def create_attempt(self, record: AttemptRecord) -> tuple[AttemptRecord, bool]:
        async with self._lock:
            existing = self._attempts.get(record.attempt_id)
            if existing is not None:
                if existing.task_id != record.task_id:
                    raise IdempotencyConflict("attempt id belongs to another task")
                return existing, False
            self._attempts[record.attempt_id] = record
            return record, True

    async def get_attempt(self, attempt_id: str) -> AttemptRecord:
        async with self._lock:
            try:
                return self._attempts[attempt_id]
            except KeyError as exc:
                raise TaskNotFound(attempt_id) from exc

    async def get_attempt_for_task(self, task_id: str) -> AttemptRecord:
        async with self._lock:
            matches = [attempt for attempt in self._attempts.values() if attempt.task_id == task_id]
            if not matches:
                raise TaskNotFound(task_id)
            return max(matches, key=lambda attempt: attempt.ordinal)

    async def save_attempt(self, record: AttemptRecord) -> AttemptRecord:
        async with self._lock:
            if record.attempt_id not in self._attempts:
                raise TaskNotFound(record.attempt_id)
            self._attempts[record.attempt_id] = replace(record)
            return record
