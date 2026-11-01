import asyncio

import pytest

from patchy.engine import notes


def test_nothing_is_recorded_outside_a_collection():
    notes.attempt("1.0", "patch", "boom")
    notes.set_report({"applied": ["A"], "failed": []})
    notes.warn("careful")
    notes.set_forced(True)
    notes.set_apk({"package": "com.example.app"})

    assert notes.current() is None


def test_a_new_collection_starts_empty():
    with notes.collect() as sink:
        assert sink.attempts == []
        assert sink.report is None
        assert sink.warnings == []
        assert sink.forced is False
        assert sink.apk is None


def test_the_collection_is_the_current_one_while_it_is_open_and_gone_afterwards():
    with notes.collect() as sink:
        assert notes.current() is sink

    assert notes.current() is None


def test_attempts_are_kept_in_the_order_they_were_made():
    with notes.collect() as sink:
        notes.attempt("9.9.9", "download", "no page")
        notes.attempt("8.8.8", "patch", "Hide ads: boom")

    assert sink.attempts == [
        {"version": "9.9.9", "stage": "download", "reason": "no page"},
        {"version": "8.8.8", "stage": "patch", "reason": "Hide ads: boom"},
    ]


def test_a_report_can_be_replaced_and_cleared():
    first = {"applied": ["A"], "failed": []}
    second = {"applied": ["B"], "failed": [{"name": "C", "error": "boom"}]}

    with notes.collect() as sink:
        notes.set_report(first)
        assert sink.report == first
        notes.set_report(second)
        assert sink.report == second
        notes.set_report(None)
        assert sink.report is None


def test_the_same_warning_is_kept_once():
    with notes.collect() as sink:
        notes.warn("first")
        notes.warn("second")
        notes.warn("first")

    assert sink.warnings == ["first", "second"]


def test_forced_and_the_apk_facts_can_be_set_and_reset():
    with notes.collect() as sink:
        notes.set_forced(True)
        notes.set_apk({"package": "com.example.app", "abis": ["arm64-v8a"]})
        assert sink.forced is True
        assert sink.apk == {"package": "com.example.app", "abis": ["arm64-v8a"]}
        notes.set_forced(False)
        notes.set_apk(None)
        assert sink.forced is False
        assert sink.apk is None


def test_a_nested_collection_keeps_its_notes_apart_and_restores_the_outer_one():
    with notes.collect() as outer:
        notes.warn("outer before")
        with notes.collect() as inner:
            notes.warn("inner")
            notes.attempt("1.0", "patch", "inner failure")
            assert notes.current() is inner
        assert notes.current() is outer
        notes.warn("outer after")

    assert outer.warnings == ["outer before", "outer after"]
    assert outer.attempts == []
    assert inner.warnings == ["inner"]
    assert len(inner.attempts) == 1


def test_the_previous_collection_is_restored_when_the_block_raises():
    with pytest.raises(RuntimeError, match="boom"), notes.collect():
        raise RuntimeError("boom")

    assert notes.current() is None


def test_a_sink_keeps_its_content_after_the_collection_ends():
    with notes.collect() as sink:
        notes.attempt("1.0", "patch", "boom")

    notes.attempt("2.0", "patch", "ignored")

    assert sink.attempts == [{"version": "1.0", "stage": "patch", "reason": "boom"}]


async def test_concurrent_tasks_each_keep_their_own_notes():
    async def work(name: str) -> notes.BuildNotes:
        with notes.collect() as sink:
            notes.attempt(name, "patch", f"{name} failed")
            await asyncio.sleep(0)
            notes.warn(f"warning of {name}")
            await asyncio.sleep(0)
            notes.set_forced(name == "a")
            return sink

    first, second = await asyncio.gather(work("a"), work("b"))

    assert first.attempts == [{"version": "a", "stage": "patch", "reason": "a failed"}]
    assert second.attempts == [{"version": "b", "stage": "patch", "reason": "b failed"}]
    assert first.warnings == ["warning of a"]
    assert second.warnings == ["warning of b"]
    assert first.forced is True
    assert second.forced is False
    assert notes.current() is None
