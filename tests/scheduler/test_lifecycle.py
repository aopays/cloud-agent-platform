from __future__ import annotations

import asyncio

import pytest

from src.models.repository import IdempotencyConflict, InMemoryTaskRepository
from src.scheduler import CancellationBroker, InMemoryLeaseManager, InMemoryTaskQueue
from src.scheduler.service import (
    InvalidTaskTransition,
    LeaseOwnershipError,
    TaskLifecycleService,
)
from src.shared.contracts import RepositorySpec, TaskSpec, TaskStatus


def make_service() -> tuple[TaskLifecycleService, InMemoryTaskQueue, CancellationBroker]:
    queue = InMemoryTaskQueue()
    cancellations = CancellationBroker()
    service = TaskLifecycleService(
        repository=InMemoryTaskRepository(),
        queue=queue,
        leases=InMemoryLeaseManager(),
        cancellations=cancellations,
    )
    return service, queue, cancellations


def spec(instruction: str = "find TODO") -> TaskSpec:
    return TaskSpec(
        instruction=instruction,
        repository=RepositorySpec(url="https://example.test/repository.git"),
    )


def test_create_is_idempotent_and_enqueues_once() -> None:
    async def scenario() -> None:
        service, queue, _ = make_service()
        first = await service.create_task(
            spec(), idempotency_key="same-key-001", tenant_id="tenant-a"
        )
        second = await service.create_task(
            spec(), idempotency_key="same-key-001", tenant_id="tenant-a"
        )

        assert first.task_id == second.task_id
        assert first.status == TaskStatus.QUEUED
        delivery = await queue.receive(visibility_timeout_seconds=30)
        assert delivery.message.task_id == first.task_id
        assert await queue.ack(delivery.receipt)

    asyncio.run(scenario())


def test_idempotency_key_rejects_different_request() -> None:
    async def scenario() -> None:
        service, _, _ = make_service()
        await service.create_task(
            spec("first"), idempotency_key="same-key-002", tenant_id="tenant-a"
        )
        with pytest.raises(IdempotencyConflict):
            await service.create_task(
                spec("different"), idempotency_key="same-key-002", tenant_id="tenant-a"
            )

    asyncio.run(scenario())


def test_terminal_state_is_immutable() -> None:
    async def scenario() -> None:
        service, queue, _ = make_service()
        task = await service.create_task(
            spec(), idempotency_key="terminal-001", tenant_id="tenant-a"
        )
        delivery = await queue.receive(visibility_timeout_seconds=30)
        assert await service.claim_delivery(delivery, worker_id="worker-a", lease_ttl_seconds=30)
        await service.mark_running(task.task_id)
        done = await service.finish_attempt(
            task_id=task.task_id,
            attempt_id=delivery.message.attempt_id,
            worker_id="worker-a",
            target=TaskStatus.SUCCEEDED,
            result="report",
        )
        assert done.status == TaskStatus.SUCCEEDED
        with pytest.raises(InvalidTaskTransition):
            await service.transition(task.task_id, TaskStatus.RUNNING)

    asyncio.run(scenario())


def test_running_cancellation_propagates_and_finishes_once() -> None:
    async def scenario() -> None:
        service, queue, cancellations = make_service()
        task = await service.create_task(
            spec(), idempotency_key="cancel-key-001", tenant_id="tenant-a"
        )
        delivery = await queue.receive(visibility_timeout_seconds=30)
        assert await service.claim_delivery(delivery, worker_id="worker-a", lease_ttl_seconds=30)
        await service.mark_running(task.task_id)

        cancelling = await service.cancel_task(task.task_id, tenant_id="tenant-a")
        assert cancelling.status == TaskStatus.CANCELLING
        assert await cancellations.signal_for(task.task_id).is_cancelled()

        cancelled = await service.finish_attempt(
            task_id=task.task_id,
            attempt_id=delivery.message.attempt_id,
            worker_id="worker-a",
            target=TaskStatus.CANCELLED,
        )
        duplicate = await service.finish_attempt(
            task_id=task.task_id,
            attempt_id=delivery.message.attempt_id,
            worker_id="worker-a",
            target=TaskStatus.CANCELLED,
        )
        assert cancelled.status == TaskStatus.CANCELLED
        assert duplicate == cancelled

    asyncio.run(scenario())


def test_duplicate_delivery_cannot_start_a_parallel_execution() -> None:
    async def scenario() -> None:
        service, queue, _ = make_service()
        await service.create_task(spec(), idempotency_key="delivery-key-001", tenant_id="tenant-a")
        first = await queue.receive(visibility_timeout_seconds=30)
        assert await service.claim_delivery(first, worker_id="worker-a", lease_ttl_seconds=30)
        assert await queue.nack(first.receipt)

        duplicate = await queue.receive(visibility_timeout_seconds=30)
        assert not await service.claim_delivery(
            duplicate, worker_id="worker-b", lease_ttl_seconds=30
        )

    asyncio.run(scenario())


def test_tenant_cannot_read_or_cancel_another_tenants_task() -> None:
    async def scenario() -> None:
        from src.models.repository import TaskNotFound

        service, _, _ = make_service()
        task = await service.create_task(
            spec(), idempotency_key="tenant-key-001", tenant_id="tenant-a"
        )
        with pytest.raises(TaskNotFound):
            await service.get_task_for_tenant(task.task_id, tenant_id="tenant-b")
        with pytest.raises(TaskNotFound):
            await service.cancel_task(task.task_id, tenant_id="tenant-b")

    asyncio.run(scenario())


def test_idempotent_retry_repairs_failed_queue_delivery() -> None:
    class FailOnceQueue(InMemoryTaskQueue):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def enqueue(self, message):
            if not self.failed:
                self.failed = True
                raise RuntimeError("queue unavailable")
            return await super().enqueue(message)

    async def scenario() -> None:
        queue = FailOnceQueue()
        service = TaskLifecycleService(
            repository=InMemoryTaskRepository(),
            queue=queue,
            leases=InMemoryLeaseManager(),
            cancellations=CancellationBroker(),
        )
        with pytest.raises(RuntimeError, match="queue unavailable"):
            await service.create_task(
                spec(), idempotency_key="repair-key-001", tenant_id="tenant-a"
            )
        repaired = await service.create_task(
            spec(), idempotency_key="repair-key-001", tenant_id="tenant-a"
        )
        delivery = await queue.receive(visibility_timeout_seconds=30)
        assert delivery.message.task_id == repaired.task_id

    asyncio.run(scenario())


def test_attempt_cannot_commit_another_task() -> None:
    async def scenario() -> None:
        service, queue, _ = make_service()
        first = await service.create_task(
            spec(), idempotency_key="binding-key-001", tenant_id="tenant-a"
        )
        second = await service.create_task(
            spec(), idempotency_key="binding-key-002", tenant_id="tenant-a"
        )
        delivery = await queue.receive(visibility_timeout_seconds=30)
        assert delivery.message.task_id == first.task_id
        assert await service.claim_delivery(delivery, worker_id="worker-a", lease_ttl_seconds=30)
        with pytest.raises(LeaseOwnershipError):
            await service.finish_attempt(
                task_id=second.task_id,
                attempt_id=delivery.message.attempt_id,
                worker_id="worker-a",
                target=TaskStatus.CANCELLED,
            )
        assert (await service.get_task(second.task_id)).status == TaskStatus.QUEUED

    asyncio.run(scenario())
