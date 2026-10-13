import asyncio
from collections.abc import Awaitable, Callable, Iterable

Job = Callable[[], Awaitable[object]]


async def run_limited(jobs: Iterable[Job], limit: int) -> None:
    pending = iter(jobs)

    async def _drain() -> None:
        for job in pending:
            await job()

    await asyncio.gather(*(_drain() for _ in range(max(1, limit))))
