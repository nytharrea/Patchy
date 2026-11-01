from collections.abc import Mapping

REASON_LIMIT = 160


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _patches(status: Mapping[str, object] | None) -> Mapping[str, object]:
    patches = (status or {}).get("patches")
    return patches if isinstance(patches, dict) else {}


def applied_patches(status: Mapping[str, object] | None) -> list[str]:
    return _strings(_patches(status).get("applied"))


def failed_patches(status: Mapping[str, object] | None) -> list[tuple[str, str]]:
    value = _patches(status).get("failed")
    if not isinstance(value, list):
        return []
    failed: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]:
            failed.append((item["name"], str(item.get("error") or "")))
    return failed


def attempt_list(status: Mapping[str, object] | None) -> list[tuple[str, str, str]]:
    value = (status or {}).get("attempts")
    if not isinstance(value, list):
        return []
    found: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        version = item.get("version")
        if isinstance(version, str) and version:
            found.append((version, str(item.get("stage") or "build"), str(item.get("reason") or "unknown reason")))
    return found


def warning_texts(status: Mapping[str, object] | None) -> list[str]:
    return _strings((status or {}).get("warnings"))


def is_forced(status: Mapping[str, object] | None) -> bool:
    return (status or {}).get("forced") is True


def one_line(text: str, limit: int = REASON_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def attempt_text(attempt: tuple[str, str, str], limit: int = REASON_LIMIT) -> str:
    version, stage, reason = attempt
    return f"{version} ({stage}): {one_line(reason, limit)}"


def tried_versions(status: Mapping[str, object] | None) -> list[str]:
    seen: list[str] = []
    for version, _, _ in attempt_list(status):
        if version not in seen:
            seen.append(version)
    return seen
