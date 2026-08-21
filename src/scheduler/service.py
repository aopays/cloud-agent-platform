"""Application service for task creation and lifecycle coordination."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from src.models.repository import TaskNotFound, TaskRepository, VersionConflict
from src.models.tasks import AttemptRecord, TaskError, TaskRecord
from src.scheduler.cancellation import CancellationBroker, TaskCancellationSignal
from src.scheduler.leases import InMemoryLeaseManager
from src.scheduler.queue import QueueDelivery, QueueMessage, TaskQueue
from src.shared.contracts import (
    TERMINAL_TASK_STATUSES,
    TaskSpec,
    TaskStatus,
    Usage,
    can_transition,
)
from src.shared.events import AgentEvent
from src.shared.interfaces import EventSink


class InvalidTaskTransition(RuntimeError):
    pass


class LeaseOwnershipError(RuntimeError):
    pass


def _request_fingerprint(spec: TaskSpec) -> str:
    canonical = {
        "instruction": spec.instruction,
        "repository": {"url": spec.repository.url, "ref": spec.repository.ref},
        "limits": {
            "wallTimeSeconds": spec.limits.wall_time_seconds,
            "maxAgentTurns": spec.limits.max_agent_turns,
            "maxInputTokens": spec.limits.max_input_tokens,
            "maxToolOutputBytes": spec.limits.max_tool_output_bytes,
            "maxToolSeconds": spec.limits.max_tool_seconds,
        },
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class TaskLifecycleService:
    """Coordinates persistence, queuing, leases, and cancellation signals."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        queue: TaskQueue,
        leases: InMemoryLeaseManager,
        cancellations: CancellationBroker,
        event_sink: EventSink | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._leases = leases
        self._cancellations = cancellations
        self._event_sink = event_sink
        self._create_lock = asyncio.Lock()

    async def create_task(
        self,
        spec: TaskSpec,
        *,
        idempotency_key: str,
        tenant_id: str,
    ) -> TaskRecord:
        if not 8 <= len(idempotency_key) <= 128:
            raise ValueError("idempotency_key must contain 8 to 128 characters")

        # The in-process lock mirrors the transactional outbox boundary required
        # by a PostgreSQL/Redis adapter and prevents a duplicate caller observing
        # the short-lived CREATED state in the local adapter.
        async with self._create_lock:
            record = TaskRecord(
                task_id=f"task_{uuid4().hex}",
                tenant_id=tenant_id,
                spec=spec,
            )
            stored, created = await self._repository.create_idempotent(
                record,
                idempotency_key=idempotency_key,
                request_fingerprint=_request_fingerprint(spec),
            )
            if not created:
                if stored.status in {TaskStatus.CREATED, TaskStatus.QUEUED}:
                    try:
                        attempt = await self._repository.get_attempt_for_task(stored.task_id)
                    except TaskNotFound:
                        attempt = AttemptRecord(
                            attempt_id=f"attempt_{uuid4().hex}",
                            task_id=stored.task_id,
                            ordinal=1,
                        )
                        await self._repository.create_attempt(attempt)
                    if stored.status == TaskStatus.CREATED:
                        stored = await self.transition(stored.task_id, TaskStatus.QUEUED)
                    await self._queue.enqueue(
                        QueueMessage(
                            message_id=attempt.attempt_id,
                            task_id=stored.task_id,
                            attempt_id=attempt.attempt_id,
                        )
                    )
                return stored

            attempt = AttemptRecord(
                attempt_id=f"attempt_{uuid4().hex}",
                task_id=stored.task_id,
                ordinal=1,
            )
            await self._repository.create_attempt(attempt)
            queued = await self.transition(stored.task_id, TaskStatus.QUEUED)
            await self._queue.enqueue(
                QueueMessage(
                    message_id=attempt.attempt_id,
                    task_id=queued.task_id,
                    attempt_id=attempt.attempt_id,
                )
            )
            return queued

    async def get_task(self, task_id: str) -> TaskRecord:
        return await self._repository.get(task_id)

    def cancellation_signal(self, task_id: str) -> TaskCancellationSignal:
        """Return the shared cancellation signal consumed by Runtime and Worker."""

        return self._cancellations.signal_for(task_id)

    async def get_task_for_tenant(self, task_id: str, *, tenant_id: str) -> TaskRecord:
        record = await self._repository.get(task_id)
        if record.tenant_id != tenant_id:
            # Avoid exposing whether another tenant's task exists.
            raise TaskNotFound(task_id)
        return record

    async def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        result: str | None = None,
        error: TaskError | None = None,
        usage: Usage | None = None,
    ) -> TaskRecord:
        for _ in range(3):
            current = await self._repository.get(task_id)
            if current.status == target:
                return current
            if not can_transition(current.status, target):
                raise InvalidTaskTransition(f"cannot transition {current.status} to {target}")

            now = datetime.now(timezone.utc)
            changes: dict[str, object] = {"status": target}
            if target == TaskStatus.RUNNING and current.started_at is None:
                changes["started_at"] = now
            if target in TERMINAL_TASK_STATUSES:
                changes["finished_at"] = now
            if result is not None:
                changes["result"] = result
            if error is not None:
                changes["error"] = error
            if usage is not None:
                changes["usage"] = usage
            updated = current.with_changes(**changes)
            try:
                saved = await self._repository.save(updated, expected_version=current.version)
                try:
                    attempt = await self._repository.get_attempt_for_task(task_id)
                except TaskNotFound:
                    return saved
                await self._emit_status(
                    attempt.attempt_id,
                    task_id,
                    current.status,
                    target,
                    "state_transition",
                )
                return saved
            except VersionConflict:
                continue
        raise VersionConflict(f"task {task_id} changed repeatedly during transition")

    async def cancel_task(self, task_id: str, *, tenant_id: str | None = None) -> TaskRecord:
        for _ in range(3):
            current = await self._repository.get(task_id)
            if tenant_id is not None and current.tenant_id != tenant_id:
                raise TaskNotFound(task_id)
            if current.status in TERMINAL_TASK_STATUSES or current.status == TaskStatus.CANCELLING:
                return current
            await self._cancellations.cancel(task_id)
            target = (
                TaskStatus.CANCELLED
                if current.status in {TaskStatus.CREATED, TaskStatus.QUEUED}
                else TaskStatus.CANCELLING
            )
            updated = current.with_changes(
                status=target,
                cancellation_requested=True,
                finished_at=(
                    datetime.now(timezone.utc) if target == TaskStatus.CANCELLED else None
                ),
            )
            try:
                saved = await self._repository.save(updated, expected_version=current.version)
                try:
                    attempt = await self._repository.get_attempt_for_task(task_id)
                except TaskNotFound:
                    return saved
                await self._emit_status(
                    attempt.attempt_id,
                    task_id,
                    current.status,
                    target,
                    "cancellation_requested",
                )
                return saved
            except VersionConflict:
                continue
        raise VersionConflict(f"task {task_id} changed repeatedly during cancellation")

    async def claim_delivery(
        self,
        delivery: QueueDelivery,
        *,
        worker_id: str,
        lease_ttl_seconds: float,
    ) -> bool:
        task = await self._repository.get(delivery.message.task_id)
        if task.status in TERMINAL_TASK_STATUSES or task.status == TaskStatus.CANCELLING:
            return False
        lease = await self._leases.acquire(
            attempt_id=delivery.message.attempt_id,
            task_id=delivery.message.task_id,
            owner_id=worker_id,
            ttl_seconds=lease_ttl_seconds,
        )
        if lease is None:
            return False
        if task.status == TaskStatus.QUEUED:
            try:
                await self.transition(task.task_id, TaskStatus.PREPARING)
            except InvalidTaskTransition:
                latest = await self._repository.get(task.task_id)
                if (
                    latest.status in TERMINAL_TASK_STATUSES
                    or latest.status == TaskStatus.CANCELLING
                ):
                    await self._leases.release(
                        delivery.message.attempt_id,
                        owner_id=worker_id,
                    )
                    return False
                raise
        return True

    async def mark_running(self, task_id: str) -> TaskRecord:
        return await self.transition(task_id, TaskStatus.RUNNING)

    async def heartbeat_attempt(
        self,
        attempt_id: str,
        *,
        worker_id: str,
        lease_ttl_seconds: float,
    ) -> bool:
        renewed = await self._leases.heartbeat(
            attempt_id,
            owner_id=worker_id,
            ttl_seconds=lease_ttl_seconds,
        )
        return renewed is not None

    async def finish_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        worker_id: str,
        target: TaskStatus,
        result: str | None = None,
        error: TaskError | None = None,
        usage: Usage | None = None,
    ) -> TaskRecord:
        if target not in TERMINAL_TASK_STATUSES:
            raise ValueError("finish target must be terminal")
        current = await self._repository.get(task_id)
        if current.status in TERMINAL_TASK_STATUSES:
            return current
        attempt = await self._repository.get_attempt(attempt_id)
        if attempt.task_id != task_id:
            raise LeaseOwnershipError("attempt does not belong to the task")
        if not await self._leases.owns(attempt_id, owner_id=worker_id):
            raise LeaseOwnershipError("worker does not own an active attempt lease")
        if current.status == TaskStatus.CANCELLING:
            cleanup_failed = (
                target == TaskStatus.FAILED and error is not None and error.code == "CLEANUP_FAILED"
            )
            if not cleanup_failed:
                target = TaskStatus.CANCELLED
                result = None
                error = error or TaskError("CANCELLED", "task cancellation was requested")
        try:
            finished = await self.transition(
                task_id,
                target,
                result=result,
                error=error,
                usage=usage,
            )
        except InvalidTaskTransition:
            latest = await self._repository.get(task_id)
            if latest.status != TaskStatus.CANCELLING:
                raise
            cleanup_failed = (
                target == TaskStatus.FAILED and error is not None and error.code == "CLEANUP_FAILED"
            )
            if cleanup_failed:
                finished = await self.transition(
                    task_id,
                    TaskStatus.FAILED,
                    error=error,
                    usage=usage,
                )
            else:
                finished = await self.transition(
                    task_id,
                    TaskStatus.CANCELLED,
                    error=TaskError("CANCELLED", "task cancellation was requested"),
                    usage=usage,
                )
        await self._leases.release(attempt_id, owner_id=worker_id)
        return finished

    async def _emit_status(
        self,
        attempt_id: str,
        task_id: str,
        previous: TaskStatus,
        target: TaskStatus,
        reason: str,
    ) -> None:
        if self._event_sink is None:
            return
        payload = {
            "from": previous.value,
            "to": target.value,
            "reason": reason,
        }
        allocator = getattr(self._event_sink, "append_next", None)
        if allocator is not None:
            await allocator(task_id, attempt_id, "task.status_changed", payload)
            return
        for _ in range(10):
            existing = await self._event_sink.list_after(task_id)
            sequence = max(
                (event.sequence for event in existing if event.attempt_id == attempt_id),
                default=0,
            )
            try:
                await self._event_sink.append(
                    AgentEvent(
                        task_id=task_id,
                        attempt_id=attempt_id,
                        sequence=sequence + 1,
                        event_type="task.status_changed",
                        payload=payload,
                    )
                )
            except ValueError as exc:
                if "sequence" not in str(exc) and "event key conflicts" not in str(exc):
                    raise
                continue
            return
        raise ValueError("status event sequence remained contended after retries")
