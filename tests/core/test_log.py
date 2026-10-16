import asyncio
from types import SimpleNamespace

import pytest

from patchy.core import log


class _TickingClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 1.0
        return self.now


class _Clock:
    def __init__(self, *readings):
        self.readings = iter(readings)

    def monotonic(self):
        return next(self.readings)


def _record_logs(monkeypatch):
    records = []

    def record(level, message):
        records.append((level, message))

    monkeypatch.setattr(log, "logger", SimpleNamespace(log=record))
    return records


def test_step_summary_appends_to_the_file_named_by_github(monkeypatch, tmp_path):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))

    assert log.step_summary("## First\n") is True
    assert log.step_summary("second") is True

    assert target.read_text(encoding="utf-8") == "## First\nsecond\n"


def test_step_summary_does_nothing_outside_github_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert log.step_summary("ignored") is False


def test_step_summary_reports_an_unwritable_target_instead_of_failing(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    warnings = []
    monkeypatch.setattr(log, "warn", warnings.append)

    assert log.step_summary("text") is False
    assert any("job summary" in warning for warning in warnings)


def test_timed_adds_the_stage_to_the_active_collector(monkeypatch):
    monkeypatch.setattr(log, "time", _Clock(10.0, 12.5))
    _record_logs(monkeypatch)

    with log.collect_timings() as timings, log.timed("download"):
        pass

    assert timings == {"download": 2.5}


def test_timed_logs_how_long_the_stage_took(monkeypatch):
    monkeypatch.setattr(log, "time", _Clock(10.0, 12.5))
    records = _record_logs(monkeypatch)

    with log.timed("patch"):
        pass

    assert records == [("TIMING", "patch took 2.5 s")]


def test_timed_still_records_a_stage_that_raised(monkeypatch):
    monkeypatch.setattr(log, "time", _Clock(1.0, 4.0))
    _record_logs(monkeypatch)

    with log.collect_timings() as timings, pytest.raises(RuntimeError, match="HTTP 503"), log.timed("download"):
        raise RuntimeError("HTTP 503")

    assert timings == {"download": 3.0}


def test_timed_adds_up_a_stage_that_runs_more_than_once(monkeypatch):
    monkeypatch.setattr(log, "time", _TickingClock())
    _record_logs(monkeypatch)

    with log.collect_timings() as timings:
        with log.timed("download"):
            pass
        with log.timed("download"):
            pass

    assert timings == {"download": 2.0}


def test_timed_without_a_collector_only_logs(monkeypatch):
    monkeypatch.setattr(log, "time", _Clock(0.0, 1.0))
    records = _record_logs(monkeypatch)

    with log.timed("verify"):
        pass

    assert records == [("TIMING", "verify took 1.0 s")]


def test_every_collector_starts_empty_and_is_dropped_afterwards(monkeypatch):
    monkeypatch.setattr(log, "time", _TickingClock())
    _record_logs(monkeypatch)

    with log.collect_timings() as first, log.timed("download"):
        pass
    with log.collect_timings() as second:
        pass

    assert first == {"download": 1.0}
    assert second == {}
    assert log._timings.get() is None


async def test_timed_records_across_awaits_in_the_same_task(monkeypatch):
    _record_logs(monkeypatch)

    async def work():
        with log.timed("download"):
            await asyncio.sleep(0)

    with log.collect_timings() as timings:
        await work()

    assert list(timings) == ["download"]
    assert timings["download"] >= 0.0
