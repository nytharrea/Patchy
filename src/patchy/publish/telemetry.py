import re

from .. import catalog
from ..core import log, paths
from ..fetch.bundles import ManifestError, read_manifest
from .assets import find_build_statuses

EMPTY = "–"
REASON_LIMIT = 120
NO_STATUS_REASON = "no status file was uploaded, the build job may have been cancelled or crashed"
MARKDOWN_SPECIALS = re.compile(r"([\\`*_\[\]|<>&~])")


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return EMPTY
    tenths = round(seconds, 1)
    if tenths < 60:
        return f"{tenths:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _escape(text: str) -> str:
    return MARKDOWN_SPECIALS.sub(r"\\\1", text)


def _first_line(text: str, limit: int = REASON_LIMIT) -> str:
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _seconds(status: dict | None, stage: str) -> float | None:
    timings = (status or {}).get("timings")
    value = timings.get(stage) if isinstance(timings, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _is_ok(status: dict | None) -> bool:
    return status is not None and status.get("ok") is True


def _state(status: dict | None) -> str:
    if status is None:
        return "⚠️ no status"
    return "✅ ok" if _is_ok(status) else "❌ failed"


def _row(key: str, status: dict | None) -> str:
    version = status.get("version") if status else None
    cells = [
        f"`{key}`",
        _escape(str(version)) if version else EMPTY,
        _state(status),
        format_duration(_seconds(status, "download")),
        format_duration(_seconds(status, "patch")),
        format_duration(_seconds(status, "total")),
    ]
    return "| " + " | ".join(cells) + " |"


def _slowest(stage: str, planned: list[str], statuses: dict[str, dict]) -> str | None:
    timed: list[tuple[float, str]] = []
    for key in planned:
        seconds = _seconds(statuses.get(key), stage)
        if seconds is not None:
            timed.append((seconds, key))
    if not timed:
        return None
    seconds, key = max(timed)
    return f"Slowest {stage}: `{key}` ({format_duration(seconds)})"


def _failures(planned: list[str], statuses: dict[str, dict]) -> list[str]:
    lines: list[str] = []
    for key in planned:
        status = statuses.get(key)
        if status is None:
            lines.append(f"- `{key}` — {NO_STATUS_REASON}")
        elif not _is_ok(status):
            reason = _first_line(str(status.get("error") or "unknown error"))
            lines.append(f"- `{key}` — {_escape(reason)}")
    return lines


def render_table(planned: list[str], statuses: dict[str, dict]) -> str:
    succeeded = sum(1 for key in planned if _is_ok(statuses.get(key)))
    lines = [
        "## ⏱️ Build telemetry",
        "",
        f"{succeeded} of {len(planned)} build(s) succeeded.",
        "",
        "| App | Version | Status | Download | Patch | Total |",
        "|---|---|---|--:|--:|--:|",
        *(_row(key, statuses.get(key)) for key in planned),
    ]

    slowest = [_slowest(stage, planned, statuses) for stage in ("download", "patch")]
    highlights = [line for line in slowest if line]
    if highlights:
        lines += ["", " · ".join(highlights)]
    lines += ["", "_Times are measured inside each build job and do not include runner setup._"]

    failures = _failures(planned, statuses)
    if failures:
        lines += ["", "### Failures", "", *failures]

    return "\n".join(lines)


def _planned_builds(statuses: dict[str, dict]) -> list[str]:
    try:
        return list(read_manifest()["builds"])
    except ManifestError:
        log.info("No bundle manifest found, so the table lists only the builds that reported a status.")
        return [key for key in catalog.BUILDS if key in statuses]


def render_summary() -> str:
    statuses = find_build_statuses(paths.artifacts_dir(), paths.signed_dir())
    planned = _planned_builds(statuses)
    if not planned:
        return ""
    return render_table(planned, statuses)
