import re
import time

from ..core import log, paths

_VERSION_LINE_RE = re.compile(r"^(.+?)(?:\s+\[[^\]]*\])?\s+\((\d+)\s+patch(?:es)?\)$")


def extract_cli_versions(output: str, app_slug: str | None = None) -> list[dict]:
    results = []
    lines = output.split("\n")
    in_section = False
    found_header = False
    saw_any = False

    for line in lines:
        trimmed = line.strip()

        if trimmed.startswith("Most common compatible versions"):
            in_section = True
            found_header = True
            continue

        if in_section and not trimmed:
            break

        if in_section:
            if trimmed == "Any":
                saw_any = True
                continue
            match = _VERSION_LINE_RE.match(trimmed)
            if match:
                results.append({"version": match.group(1), "patches": int(match.group(2))})

    if found_header and not results and not saw_any:
        log.warn(
            "Found the 'Most common compatible versions' section but couldn't parse any lines under it - the "
            "CLI's output format may have changed. Falling through to the actual latest version instead of a "
            "patch-recommended one."
        )
        _save_diagnostic_output(output, app_slug)

    return results


def _save_diagnostic_output(output: str, app_slug: str | None) -> None:
    try:
        diagnostics_dir = paths.diagnostics_dir()
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        label = f"list-versions-{app_slug or 'unknown'}"
        path = diagnostics_dir / f"{label}-{int(time.time())}.txt"
        path.write_text(output or "", encoding="utf-8", errors="replace")
        log.info(f"Diagnostic CLI output saved: {path}")
    except OSError as e:
        log.warn(f"Could not save diagnostic CLI output: {e}")


def _version_core(version: str) -> str:
    return version.split("-")[0]


def pick_latest_version(versions: list[dict]) -> str | None:
    if not versions:
        return None

    def sort_key(item: dict):
        parts = _version_core(item["version"]).split(".")
        try:
            core = tuple(int(p) for p in parts)
        except ValueError:
            core = (0,)
        return (item["patches"], core)

    best = max(versions, key=sort_key)
    return best["version"]


def to_apkmirror_version(version: str) -> str:
    return version.replace(".", "-")
