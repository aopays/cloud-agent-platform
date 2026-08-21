"""Small replaceable event and artifact adapters for the runnable MVP."""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from src.shared.contracts import Artifact
from src.shared.events import AgentEvent


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: dict[str, list[AgentEvent]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def append(self, event: AgentEvent) -> None:
        async with self._lock:
            events = self._events[event.task_id]
            attempt_events = [
                existing for existing in events if existing.attempt_id == event.attempt_id
            ]
            duplicate = next(
                (existing for existing in attempt_events if existing.sequence == event.sequence),
                None,
            )
            if duplicate is not None:
                if duplicate == event:
                    return
                raise ValueError("event key conflicts with different content")
            expected = 1 if not attempt_events else attempt_events[-1].sequence + 1
            if event.sequence != expected:
                raise ValueError("event sequence must increase by one")
            events.append(event)

    async def append_next(
        self,
        task_id: str,
        attempt_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> AgentEvent:
        """Atomically allocate the next attempt-scoped sequence and append."""

        async with self._lock:
            events = self._events[task_id]
            sequence = max(
                (existing.sequence for existing in events if existing.attempt_id == attempt_id),
                default=0,
            )
            event = AgentEvent(
                task_id=task_id,
                attempt_id=attempt_id,
                sequence=sequence + 1,
                event_type=event_type,
                payload=payload,
            )
            events.append(event)
            return event

    async def list_after(self, task_id: str, after_sequence: int = 0) -> list[AgentEvent]:
        async with self._lock:
            return [
                event for event in self._events.get(task_id, ()) if event.sequence > after_sequence
            ]


class LocalArtifactStore:
    """Content-addressed local files behind the public ArtifactStore port."""

    def __init__(self, root: Path, *, max_artifact_bytes: int = 1_000_000) -> None:
        self._root = root.resolve()
        self._max_artifact_bytes = max_artifact_bytes
        self._items: dict[str, list[Artifact]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def put_text(
        self,
        task_id: str,
        name: str,
        content: str,
        media_type: str = "text/plain",
    ) -> Artifact:
        valid_owner = task_id.startswith("task_") or task_id.startswith("discovery_")
        if not valid_owner or not name or Path(name).name != name:
            raise ValueError("invalid artifact identity")
        encoded = content.encode("utf-8")
        if len(encoded) > self._max_artifact_bytes:
            raise ValueError("artifact exceeds the configured size limit")
        digest = hashlib.sha256(encoded).hexdigest()
        async with self._lock:
            for existing in self._items.get(task_id, ()):
                if existing.name == name:
                    if existing.sha256 == digest:
                        return existing
                    raise ValueError("logical artifact already exists with different content")
            task_root = self._root / task_id
            await asyncio.to_thread(task_root.mkdir, parents=True, exist_ok=True)
            artifact_id = f"artifact_{uuid4().hex}"
            destination = task_root / f"{artifact_id}-{name}"
            await asyncio.to_thread(destination.write_bytes, encoded)
            artifact = Artifact(
                artifact_id=artifact_id,
                name=name,
                media_type=media_type,
                size_bytes=len(encoded),
                sha256=digest,
                storage_path=str(destination),
            )
            self._items[task_id].append(artifact)
            return artifact

    async def list(self, task_id: str) -> list[Artifact]:
        async with self._lock:
            return list(self._items.get(task_id, ()))

    async def get(self, task_id: str, artifact_id: str) -> Artifact | None:
        async with self._lock:
            return next(
                (item for item in self._items.get(task_id, ()) if item.artifact_id == artifact_id),
                None,
            )

    async def delete(self, task_id: str, artifact_id: str) -> bool:
        async with self._lock:
            items = self._items.get(task_id, [])
            artifact = next((item for item in items if item.artifact_id == artifact_id), None)
            if artifact is None:
                return False
            await asyncio.to_thread(
                Path(artifact.storage_path).unlink,
                missing_ok=True,
            )
            items.remove(artifact)
            return True
