from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import NotRequired, TypedDict


class FailedPatch(TypedDict):
    name: str
    error: str


class PatchReport(TypedDict):
    applied: list[str]
    failed: list[FailedPatch]
    reason: NotRequired[str]
    output: NotRequired[str]


class Attempt(TypedDict):
    version: str
    stage: str
    reason: str


@dataclass
class BuildNotes:
    attempts: list[Attempt] = field(default_factory=list)
    report: PatchReport | None = None
    warnings: list[str] = field(default_factory=list)
    forced: bool = False
    apk: dict[str, object] | None = None


_active: ContextVar[BuildNotes | None] = ContextVar("patchy_build_notes", default=None)


@contextmanager
def collect() -> Iterator[BuildNotes]:
    sink = BuildNotes()
    token = _active.set(sink)
    try:
        yield sink
    finally:
        _active.reset(token)


def attempt(version: str, stage: str, reason: str) -> None:
    sink = _active.get()
    if sink is not None:
        sink.attempts.append({"version": version, "stage": stage, "reason": reason})


def set_report(report: PatchReport | None) -> None:
    sink = _active.get()
    if sink is not None:
        sink.report = report


def warn(text: str) -> None:
    sink = _active.get()
    if sink is not None and text not in sink.warnings:
        sink.warnings.append(text)


def set_forced(forced: bool) -> None:
    sink = _active.get()
    if sink is not None:
        sink.forced = forced


def set_apk(facts: dict[str, object] | None) -> None:
    sink = _active.get()
    if sink is not None:
        sink.apk = facts


def current() -> BuildNotes | None:
    return _active.get()
