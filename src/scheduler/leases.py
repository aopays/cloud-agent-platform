"""Worker execution leases with expiry and ownership checks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Lease:
    attempt_id: str
    task_id: str
    owner_id: str
    expires_at: datetime
    generation: int = 1


class InMemoryLeaseManager:
    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._leases: dict[str, Lease] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        *,
        attempt_id: str,
        task_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> Lease | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        async with self._lock:
            now = self._clock()
            current = self._leases.get(attempt_id)
            if current is not None and current.expires_at > now:
                # Acquisition is not a heartbeat. Even the same worker identity
                # must not start a duplicate concurrent execution.
                return None

            generation = 1 if current is None else current.generation + 1
            lease = Lease(
                attempt_id=attempt_id,
                task_id=task_id,
                owner_id=owner_id,
                expires_at=now + timedelta(seconds=ttl_seconds),
                generation=generation,
            )
            self._leases[attempt_id] = lease
            return lease

    async def heartbeat(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        ttl_seconds: float,
    ) -> Lease | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        async with self._lock:
            now = self._clock()
            current = self._leases.get(attempt_id)
            if current is None or current.owner_id != owner_id or current.expires_at <= now:
                return None
            renewed = replace(current, expires_at=now + timedelta(seconds=ttl_seconds))
            self._leases[attempt_id] = renewed
            return renewed

    async def owns(self, attempt_id: str, *, owner_id: str) -> bool:
        async with self._lock:
            current = self._leases.get(attempt_id)
            return bool(
                current is not None
                and current.owner_id == owner_id
                and current.expires_at > self._clock()
            )

    async def release(self, attempt_id: str, *, owner_id: str) -> bool:
        async with self._lock:
            current = self._leases.get(attempt_id)
            if current is None or current.owner_id != owner_id:
                return False
            del self._leases[attempt_id]
            return True
