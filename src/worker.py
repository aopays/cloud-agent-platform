"""Worker orchestration joining scheduler, sandbox, runtime, events, and artifacts."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from dataclasses import dataclass

from src.agent_runtime.errors import RuntimeCancelled, RuntimeFailure, RuntimeTimedOut
from src.agent_runtime.loop import AgentRuntime, RuntimeResult
from src.models.tasks import TaskError
from src.repository_preparation import (
    LocalRepositoryPreparer,
    RepositoryPreparationError,
)
from src.sandbox.errors import SandboxError
from src.scheduler.queue import InMemoryTaskQueue, QueueDelivery, QueueEmpty
from src.scheduler.service import LeaseOwnershipError, TaskLifecycleService
from src.shared.contracts import Artifact, TaskStatus, Usage
from src.shared.events import AgentEvent
from src.shared.interfaces import (
    ArtifactStore,
    CancellationSignal,
    EventSink,
    SandboxProvider,
    SandboxSession,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _LeaseAwareCancellation:
    requested: CancellationSignal
    lease_lost: asyncio.Event

    async def is_cancelled(self) -> bool:
        return self.lease_lost.is_set() or await self.requested.is_cancelled()


@dataclass(slots=True)
class TaskWorker:
    worker_id: str
    service: TaskLifecycleService
    queue: InMemoryTaskQueue
    sandbox_provider: SandboxProvider
    repository_preparer: LocalRepositoryPreparer
    runtime: AgentRuntime
    event_sink: EventSink
    artifact_store: ArtifactStore
    lease_ttl_seconds: float = 60

    async def run_once(self) -> bool:
        try:
            delivery = await self.queue.receive(visibility_timeout_seconds=self.lease_ttl_seconds)
        except QueueEmpty:
            return False

        claimed = await self.service.claim_delivery(
            delivery,
            worker_id=self.worker_id,
            lease_ttl_seconds=self.lease_ttl_seconds,
        )
        if not claimed:
            await self.queue.ack(delivery.receipt)
            return True

        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(delivery, heartbeat_stop, lease_lost))
        acknowledge = False
        sandbox: SandboxSession | None = None
        artifact: Artifact | None = None
        result: RuntimeResult | None = None
        target = TaskStatus.SUCCEEDED
        error: TaskError | None = None
        usage: Usage | None = None
        task = await self.service.get_task(delivery.message.task_id)

        try:
            sandbox = await self.sandbox_provider.create(
                task.task_id, delivery.message.attempt_id, task.spec
            )
            await self.repository_preparer.prepare(task.spec.repository, sandbox.workspace)
            await self._check_control(task.task_id, lease_lost)
            await self.service.mark_running(task.task_id)
            cancellation = _LeaseAwareCancellation(
                self.service.cancellation_signal(task.task_id), lease_lost
            )
            result = await self._run_with_lease_guard(
                lease_lost,
                self.runtime.run(
                    task_id=task.task_id,
                    attempt_id=delivery.message.attempt_id,
                    instruction=task.spec.instruction,
                    sandbox=sandbox,
                    event_sink=self.event_sink,
                    cancellation=cancellation,
                    limits=task.spec.limits,
                ),
            )
            usage = result.usage
        except LeaseOwnershipError:
            # The message is deliberately left unacknowledged for takeover after
            # the visibility timeout. Cleanup still runs below.
            pass
        except RuntimeCancelled as exc:
            target, error = TaskStatus.CANCELLED, self._task_error(exc)
        except RuntimeTimedOut as exc:
            target, error = TaskStatus.TIMED_OUT, self._task_error(exc)
        except RuntimeFailure as exc:
            target, error = TaskStatus.FAILED, self._task_error(exc)
        except (SandboxError, RepositoryPreparationError) as exc:
            target, error = TaskStatus.FAILED, self._task_error(exc)
        except Exception:
            logger.exception(
                "worker_execution_failed",
                extra={"task_id": task.task_id, "attempt_id": delivery.message.attempt_id},
            )
            target = TaskStatus.FAILED
            error = TaskError("INTERNAL_ERROR", "task execution failed")

        if sandbox is not None:
            try:
                await sandbox.close()
            except Exception:
                logger.exception(
                    "sandbox_cleanup_failed",
                    extra={
                        "task_id": task.task_id,
                        "attempt_id": delivery.message.attempt_id,
                    },
                )
                target = TaskStatus.FAILED
                error = TaskError("CLEANUP_FAILED", "sandbox cleanup failed", retryable=True)

        try:
            await self._check_lease(lease_lost)
            if (
                error is None or error.code != "CLEANUP_FAILED"
            ) and await self.service.cancellation_signal(task.task_id).is_cancelled():
                target = TaskStatus.CANCELLED
                error = TaskError("CANCELLED", "task cancellation was requested")
            if target == TaskStatus.SUCCEEDED and result is not None:
                artifact = await self.artifact_store.put_text(
                    task.task_id, "report.md", result.final_answer, "text/markdown"
                )
                if await self.service.cancellation_signal(task.task_id).is_cancelled():
                    await self.artifact_store.delete(task.task_id, artifact.artifact_id)
                    artifact = None
                    target = TaskStatus.CANCELLED
                    error = TaskError("CANCELLED", "task cancellation was requested")

            current = await self.service.get_task(task.task_id)
            if current.status == TaskStatus.CANCELLING and (
                error is None or error.code != "CLEANUP_FAILED"
            ):
                target = TaskStatus.CANCELLED
                error = TaskError("CANCELLED", "task cancellation was requested")
                if artifact is not None:
                    await self.artifact_store.delete(task.task_id, artifact.artifact_id)
                    artifact = None
            finished = await self.service.finish_attempt(
                task_id=task.task_id,
                attempt_id=delivery.message.attempt_id,
                worker_id=self.worker_id,
                target=target,
                result=result.final_answer if target == TaskStatus.SUCCEEDED and result else None,
                error=error,
                usage=usage,
            )
            if finished.status != target:
                target = finished.status
                if artifact is not None:
                    await self.artifact_store.delete(task.task_id, artifact.artifact_id)
                    artifact = None
            acknowledge = True
            if artifact is not None:
                await self._emit(
                    delivery,
                    "artifact.created",
                    {
                        "artifactId": artifact.artifact_id,
                        "name": artifact.name,
                        "mediaType": artifact.media_type,
                        "sizeBytes": artifact.size_bytes,
                        "sha256": artifact.sha256,
                    },
                )
        except LeaseOwnershipError:
            logger.warning(
                "worker_lease_lost",
                extra={"task_id": task.task_id, "attempt_id": delivery.message.attempt_id},
            )
        finally:
            heartbeat_stop.set()
            await heartbeat
            if acknowledge:
                await self.queue.ack(delivery.receipt)
        return True

    async def _run_with_lease_guard(
        self,
        lease_lost: asyncio.Event,
        runtime_awaitable: Awaitable[RuntimeResult],
    ) -> RuntimeResult:
        runtime_task = asyncio.ensure_future(runtime_awaitable)
        lease_task = asyncio.create_task(lease_lost.wait())
        try:
            done, _ = await asyncio.wait(
                {runtime_task, lease_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if lease_task in done and lease_lost.is_set():
                runtime_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runtime_task
                raise LeaseOwnershipError("worker lost the execution lease")
            return await runtime_task
        finally:
            lease_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lease_task

    async def _heartbeat(
        self,
        delivery: QueueDelivery,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        interval = max(0.001, self.lease_ttl_seconds / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                lease_ok = await self.service.heartbeat_attempt(
                    delivery.message.attempt_id,
                    worker_id=self.worker_id,
                    lease_ttl_seconds=self.lease_ttl_seconds,
                )
                visibility_ok = await self.queue.extend_visibility(
                    delivery.receipt,
                    timeout_seconds=self.lease_ttl_seconds,
                )
            except Exception:
                lease_lost.set()
                return
            if not lease_ok or not visibility_ok:
                lease_lost.set()
                return

    async def _check_control(self, task_id: str, lease_lost: asyncio.Event) -> None:
        await self._check_lease(lease_lost)
        if await self.service.cancellation_signal(task_id).is_cancelled():
            raise RuntimeCancelled("task cancellation was requested")

    @staticmethod
    async def _check_lease(lease_lost: asyncio.Event) -> None:
        if lease_lost.is_set():
            raise LeaseOwnershipError("worker lost the execution lease")

    @staticmethod
    def _task_error(exc: Exception) -> TaskError:
        return TaskError(
            code=str(getattr(exc, "code", type(exc).__name__.upper())),
            message=str(exc)[:1000],
            retryable=bool(getattr(exc, "retryable", False)),
        )

    async def _emit(
        self,
        delivery: QueueDelivery,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        allocator = getattr(self.event_sink, "append_next", None)
        if allocator is not None:
            await allocator(
                delivery.message.task_id,
                delivery.message.attempt_id,
                event_type,
                payload,
            )
            return
        existing = await self.event_sink.list_after(delivery.message.task_id)
        sequence = max(
            (
                event.sequence
                for event in existing
                if event.attempt_id == delivery.message.attempt_id
            ),
            default=0,
        )
        await self.event_sink.append(
            AgentEvent(
                task_id=delivery.message.task_id,
                attempt_id=delivery.message.attempt_id,
                sequence=sequence + 1,
                event_type=event_type,
                payload=payload,
            )
        )

    async def run_forever(self, stop: asyncio.Event, *, idle_seconds: float = 0.05) -> None:
        while not stop.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("worker_message_failed")
                worked = True
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
                except asyncio.TimeoutError:
                    pass
