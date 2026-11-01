import json
import re
from pathlib import Path

from .notes import FailedPatch, PatchReport

REASON_LIMIT = 200
PATCH_ERROR_LIMIT = 120
MAX_ERROR_LINES = 2

ERROR_LINE = re.compile(r"^\s*(?:ERROR|FAILED)\s*:\s*(.+?)\s*$", re.IGNORECASE)
FAILURE_HEADER = re.compile(r"^Patch failed \(exit \d+\):?$", re.IGNORECASE)
BARE_MARKER = re.compile(r"^(?:ERROR|FAILED|WARN|WARNING|INFO)\s*:?$", re.IGNORECASE)


def squash(text: str, limit: int = REASON_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in names:
            names.append(item)
    return names


def _failed(value: object) -> list[FailedPatch]:
    if not isinstance(value, list):
        return []
    failed: list[FailedPatch] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            failed.append({"name": name, "error": str(item.get("error") or "")})
    return failed


def _step_error(value: object) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if isinstance(item, dict) and item.get("success") is False and item.get("error"):
            return str(item["error"])
    return ""


def parse_report(data: object) -> PatchReport | None:
    if not isinstance(data, dict):
        return None
    report: PatchReport = {
        "applied": _names(data.get("appliedPatches")),
        "failed": _failed(data.get("failedPatches")),
    }
    if data.get("success") is not True:
        reason = data.get("failureReason") or data.get("failureDetail") or _step_error(data.get("stepResults"))
        if reason:
            report["reason"] = str(reason)
    output = data.get("outputPath")
    if isinstance(output, str) and output:
        report["output"] = output
    return report


def read_report(path: str | Path) -> PatchReport | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parse_report(data)


def failure_reason(message: str, report: PatchReport | None = None) -> str:
    if report is not None:
        failed = report["failed"]
        if failed:
            first = failed[0]
            reason = first["name"]
            if first["error"]:
                reason += f": {squash(first['error'], PATCH_ERROR_LIMIT)}"
            if len(failed) > 1:
                reason += f" (+{len(failed) - 1} more)"
            return squash(reason)
        if report.get("reason"):
            return squash(report["reason"])

    lines = message.splitlines()
    errors = [match.group(1) for line in lines if (match := ERROR_LINE.match(line))]
    if errors:
        return squash(" | ".join(errors[:MAX_ERROR_LINES]))
    for line in lines:
        text = line.strip()
        if text and not FAILURE_HEADER.match(text) and not BARE_MARKER.match(text):
            return squash(text)
    return squash(message) or "unknown error"
