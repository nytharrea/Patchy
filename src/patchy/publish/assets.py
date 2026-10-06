import json
import re
from pathlib import Path

from .. import catalog
from ..core import log
from ..fetch.bundles import Manifest


def _asset_candidates() -> list[tuple[str, str, str | None]]:
    candidates = []
    for build_key in catalog.BUILDS:
        display_name, tag = catalog.get_release_naming(build_key)
        candidates.append((build_key, display_name, tag))
    candidates.sort(key=lambda c: -len(c[1]))
    return candidates


def match_asset(file_name: str):
    if not file_name.lower().endswith(".apk"):
        return None
    if file_name.lower().startswith(tuple(catalog.COMPANIONS)):
        return None

    base = file_name[:-4]

    for build_key, display_name, tag in _asset_candidates():
        prefix = display_name + "-"
        if not base.lower().startswith(prefix.lower()):
            continue

        remainder = base[len(prefix) :]

        if tag:
            suffix = f"-{tag}"
            if not remainder.lower().endswith(suffix.lower()):
                continue
            remainder = remainder[: -len(suffix)]

        return build_key, display_name, remainder

    return None


def find_patched_apks(directory: Path):
    matched = []
    unmatched = []

    for apk_path in sorted(directory.rglob("*.apk")):
        result = match_asset(apk_path.name)
        if result:
            build_key, display_name, version = result
            matched.append(
                {
                    "build_key": build_key,
                    "display_name": display_name,
                    "version": version,
                    "path": str(apk_path),
                    "name": apk_path.name,
                }
            )
        else:
            unmatched.append(apk_path.name)

    return matched, unmatched


def _read_statuses(*directories: Path) -> list[dict]:
    statuses: list[dict] = []
    for directory in directories:
        for status_path in sorted(directory.rglob("status-*.json")):
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warn(f"Could not read build status {status_path}: {e}")
                continue
            if isinstance(data, dict):
                statuses.append(data)
    return statuses


def find_failure_reasons(*directories: Path) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for data in _read_statuses(*directories):
        build_key = data.get("build_key")
        if not isinstance(build_key, str) or build_key not in catalog.BUILDS:
            continue
        if data.get("ok") is True:
            continue
        reasons[build_key] = str(data.get("error") or "unknown error")
    return reasons


def find_pending_pins(*directories: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for data in _read_statuses(*directories):
        record = data.get("pending_pin")
        if not isinstance(record, dict):
            continue
        app, sha256 = record.get("app"), record.get("sha256")
        if isinstance(app, str) and isinstance(sha256, str):
            pins[app] = sha256
    return pins


def neutralize_github_mentions(text: str) -> str:
    return re.sub(r"@([A-Za-z0-9_-]+)", r"\1", text)


def _details_block(label: str, tag: str, notes: str) -> str:
    return f"\n<details>\n<summary>{label} Release Notes ({tag})</summary>\n<br>\n\n{notes}\n\n</details>\n"


def build_release_body(matched: list[dict], manifest: Manifest | None) -> str:
    body = "### Latest Patched APKs\n\n"
    for apk in matched:
        icon = catalog.BUILDS[apk["build_key"]]["icon"]
        body += f'* <img src="{icon}" width="16" height="16"> **{apk["display_name"]}** - `{apk["version"]}`\n'

    body += "\n---\n\n"

    if manifest is not None:
        used: set[str] = set()
        for apk in matched:
            used.update(catalog.bundles_for(apk["build_key"]))

        for key in sorted(used):
            entry = manifest["bundles"].get(key)
            if entry is None or key not in catalog.BUNDLES:
                continue
            notes = neutralize_github_mentions(entry["body"] or "")
            body += _details_block(catalog.BUNDLES[key]["label"], entry["tag"], notes)

    return neutralize_github_mentions(body)
