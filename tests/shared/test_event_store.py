from __future__ import annotations

import asyncio

from src.storage import InMemoryEventStore


def test_event_store_allocates_attempt_sequences_atomically() -> None:
    async def scenario() -> None:
        store = InMemoryEventStore()
        created = await asyncio.gather(
            *(
                store.append_next(
                    "task_1",
                    "attempt_1",
                    "test.event",
                    {"producer": index},
                )
                for index in range(50)
            )
        )

        assert sorted(event.sequence for event in created) == list(range(1, 51))
        stored = await store.list_after("task_1")
        assert [event.sequence for event in stored] == list(range(1, 51))

    asyncio.run(scenario())
