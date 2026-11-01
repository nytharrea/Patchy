import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from .. import catalog
from ..core import log
from ..fetch.bundles import Manifest
from . import details

RELEASE_BODY_LIMIT = 100_000
CODE_FENCE = "```"
APPLIED_SHOWN_LIMIT = 80
WARNINGS_SHOWN_LIMIT = 3
ATTEMPT_REASON_LIMIT = 110


class BundleNotes(NamedTuple):
    label: str
    tag: str
    url: str
    text: str


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
        plain = display_name + "-"
        prefix = next((p for p in (plain, plain.replace(" ", ".")) if base.lower().startswith(p.lower())), None)
        if prefix is None:
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


def find_build_statuses(*directories: Path) -> dict[str, dict]:
    statuses: dict[str, dict] = {}
    for data in _read_statuses(*directories):
        build_key = data.get("build_key")
        if isinstance(build_key, str) and build_key in catalog.BUILDS:
            statuses.setdefault(build_key, {}).update(data)
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


def _release_url(key: str, tag: str) -> str:
    bundle = catalog.BUNDLES[key]
    return f"https://github.com/{bundle['owner']}/{bundle['repo']}/releases/tag/{quote(tag)}"


def _shortened_notice(url: str) -> str:
    return f"\n\n_These notes were shortened to fit GitHub's size limit. Full notes: {url}_"


def _cut_notes(notes: str, room: int) -> str:
    if len(notes) <= room:
        return notes
    cut = notes[: max(room - len(CODE_FENCE) - 1, 0)]
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]
    cut = cut.rstrip()
    if cut.count(CODE_FENCE) % 2:
        cut += f"\n{CODE_FENCE}"
    return cut


def _fair_shares(sizes: list[int], budget: int) -> list[int]:
    shares = [0] * len(sizes)
    remaining = max(budget, 0)
    for turn, index in enumerate(sorted(range(len(sizes)), key=sizes.__getitem__)):
        shares[index] = min(sizes[index], remaining // (len(sizes) - turn))
        remaining -= shares[index]
    return shares


def _notes_section(entries: list[BundleNotes], budget: int) -> str:
    blocks = [_details_block(entry.label, entry.tag, entry.text) for entry in entries]
    if sum(len(block) for block in blocks) <= budget:
        return "".join(blocks)

    shares = _fair_shares([len(block) for block in blocks], budget)
    section = ""
    for entry, block, share in zip(entries, blocks, shares, strict=True):
        if len(block) <= share:
            section += block
            continue
        notice = _shortened_notice(entry.url)
        room = share - (len(block) - len(entry.text)) - len(notice)
        section += _details_block(entry.label, entry.tag, _cut_notes(entry.text, room) + notice)
    return section


def _code(text: str) -> str:
    return "`" + " ".join(text.split()).replace("`", "'") + "`"


def _version_text(apk: dict, status: Mapping[str, object] | None) -> str:
    shown = _code(str(apk["version"]))
    facts = (status or {}).get("apk")
    reported = facts.get("version_name") if isinstance(facts, dict) else None
    if apk["version"] == "latest" and isinstance(reported, str) and reported:
        shown += f" ({_code(reported)})"
    return shown


def _attempt_phrase(attempt: tuple[str, str, str]) -> str:
    version, stage, reason = attempt
    return f"{_code(version)} ({stage}: {_code(details.one_line(reason, ATTEMPT_REASON_LIMIT))})"


def _app_notes(apk: dict, status: Mapping[str, object] | None) -> list[str]:
    if apk.get("carried"):
        origin = f" from {_code(str(apk['carried_from']))}" if apk.get("carried_from") else ""
        note = f"Carried over{origin}, because this app was not rebuilt in this run."
        if apk.get("carried_reason"):
            note += f" The new build failed: {_code(details.one_line(str(apk['carried_reason'])))}"
        return [note]

    notes: list[str] = []
    attempts = details.attempt_list(status)
    if attempts:
        notes.append("Newer versions could not be used: " + ", ".join(_attempt_phrase(item) for item in attempts))
    if details.is_forced(status):
        notes.append("Patched with `--force`, so the patches were not checked against this version.")
    warnings = details.warning_texts(status)
    for text in warnings[:WARNINGS_SHOWN_LIMIT]:
        notes.append("⚠️ " + _code(details.one_line(text)))
    if len(warnings) > WARNINGS_SHOWN_LIMIT:
        notes.append(f"⚠️ and {len(warnings) - WARNINGS_SHOWN_LIMIT} more warning(s)")
    return notes


def _patches_block(label: str, applied: list[str]) -> str:
    shown = ", ".join(_code(name) for name in applied[:APPLIED_SHOWN_LIMIT])
    hidden = len(applied) - APPLIED_SHOWN_LIMIT
    if hidden > 0:
        shown += f", and {hidden} more"
    noun = "patch" if len(applied) == 1 else "patches"
    summary = f"{html.escape(label, quote=False)} - {len(applied)} {noun} applied"
    return f"\n<details>\n<summary>{summary}</summary>\n<br>\n\n{shown}\n\n</details>\n"


def build_release_body(
    matched: list[dict],
    manifest: Manifest | None,
    limit: int = RELEASE_BODY_LIMIT,
    statuses: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    body = "### Latest Patched APKs\n\n"
    blocks = ""
    for apk in matched:
        icon = catalog.BUILDS[apk["build_key"]]["icon"]
        status = (statuses or {}).get(apk["build_key"])
        body += f'* <img src="{icon}" width="16" height="16"> **{apk["display_name"]}** - {_version_text(apk, status)}\n'
        for note in _app_notes(apk, status):
            body += f"  * {note}\n"
        applied = [] if apk.get("carried") else details.applied_patches(status)
        if applied:
            blocks += _patches_block(apk["display_name"], applied)

    body += blocks
    body += "\n---\n\n"

    if manifest is not None:
        used: set[str] = set()
        for apk in matched:
            used.update(catalog.bundles_for(apk["build_key"]))

        entries: list[BundleNotes] = []
        for key in sorted(used):
            entry = manifest["bundles"].get(key)
            if entry is None or key not in catalog.BUNDLES:
                continue
            notes = neutralize_github_mentions(entry["body"] or "")
            entries.append(
                BundleNotes(catalog.BUNDLES[key]["label"], entry["tag"], _release_url(key, entry["tag"]), notes)
            )

        body += _notes_section(entries, limit - len(body))

    if len(body) > limit:
        body = _cut_notes(body, limit)

    return neutralize_github_mentions(body)
