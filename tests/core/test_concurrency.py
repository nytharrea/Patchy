import asyncio
from functools import partial

import pytest

from patchy.core.concurrency import run_limited


class _Tracker:
    def __init__(self):
        self.active = 0
        self.peak = 0
        self.started = []
        self.finished = []

    async def job(self, name, yields=3):
        self.started.append(name)
        self.active += 1
        self.peak = max(self.peak, self.active)
        for _ in range(yields):
            await asyncio.sleep(0)
        self.active -= 1
        self.finished.append(name)


async def test_run_limited_never_runs_more_jobs_than_the_limit():
    tracker = _Tracker()

    await run_limited([partial(tracker.job, n) for n in range(12)], 4)

    assert tracker.peak == 4
    assert sorted(tracker.finished) == list(range(12))


async def test_run_limited_uses_every_slot_it_is_given():
    tracker = _Tracker()

    await run_limited([partial(tracker.job, n, 5) for n in range(3)], 10)

    assert tracker.peak == 3


async def test_run_limited_starts_jobs_in_the_order_they_were_given():
    tracker = _Tracker()
    lengths = [9, 1, 7, 2, 5, 1, 8, 3]

    await run_limited([partial(tracker.job, n, length) for n, length in enumerate(lengths)], 3)

    assert tracker.started == list(range(len(lengths)))


async def test_run_limited_hands_a_freed_slot_to_the_next_job_in_line():
    tracker = _Tracker()
    jobs = [partial(tracker.job, "big", 20), partial(tracker.job, "a", 1), partial(tracker.job, "b", 1)]

    await run_limited(jobs, 2)

    assert tracker.started == ["big", "a", "b"]
    assert tracker.finished == ["a", "b", "big"]


async def test_run_limited_treats_a_non_positive_limit_as_one():
    tracker = _Tracker()

    await run_limited([partial(tracker.job, n) for n in range(4)], 0)

    assert tracker.peak == 1
    assert tracker.finished == [0, 1, 2, 3]


async def test_run_limited_with_no_jobs_returns_immediately():
    await run_limited([], 4)


async def test_run_limited_accepts_a_generator_of_jobs():
    tracker = _Tracker()

    await run_limited((partial(tracker.job, n) for n in range(5)), 2)

    assert sorted(tracker.finished) == list(range(5))


async def test_run_limited_propagates_a_failing_job():
    async def boom():
        raise RuntimeError("upload exploded")

    with pytest.raises(RuntimeError, match="upload exploded"):
        await run_limited([boom], 2)
