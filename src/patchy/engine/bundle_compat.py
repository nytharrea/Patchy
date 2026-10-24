import re
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

MANIFEST_NAME = "META-INF/MANIFEST.MF"
PATCHER_VERSION_ATTRIBUTE = "patcher-version"
LINE_BREAK = re.compile(r"\r\n|\r|\n")
VERSION_PATTERN = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")

PatcherVersion = tuple[int, int, int]

BEHAVIOR_CHANGES: tuple[PatcherVersion, ...] = ((2, 0, 0),)


class BundleSplit(NamedTuple):
    kept: list[int]
    dropped: list[int]
    versions: list[PatcherVersion]


def parse_patcher_version(text: str | None) -> PatcherVersion | None:
    if text is None:
        return None
    match = VERSION_PATTERN.fullmatch(text.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def format_patcher_version(version: PatcherVersion) -> str:
    return ".".join(str(part) for part in version)


def _main_attributes(manifest: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    name: str | None = None
    for line in LINE_BREAK.split(manifest):
        if not line:
            break
        if line.startswith(" "):
            if name is not None:
                attributes[name] += line[1:]
            continue
        header, separator, value = line.partition(":")
        if not separator:
            name = None
            continue
        name = header.strip().lower()
        attributes[name] = value
    return attributes


def declared_patcher_version(bundle: str | Path) -> PatcherVersion | None:
    try:
        with zipfile.ZipFile(bundle) as archive:
            manifest = archive.read(MANIFEST_NAME).decode("utf-8", errors="replace")
    except Exception:
        return None
    return parse_patcher_version(_main_attributes(manifest).get(PATCHER_VERSION_ATTRIBUTE))


def behavior_generation(version: PatcherVersion) -> int:
    return sum(version >= change for change in BEHAVIOR_CHANGES)


def split_by_generation(bundles: Sequence[str | Path]) -> BundleSplit | None:
    if len(bundles) < 2:
        return None

    declared = [declared_patcher_version(bundle) for bundle in bundles]
    versions = [version for version in declared if version is not None]
    if len(versions) != len(declared):
        return None

    main = behavior_generation(versions[0])
    kept = [index for index, version in enumerate(versions) if behavior_generation(version) == main]
    dropped = [index for index in range(len(versions)) if index not in kept]
    if not dropped:
        return None
    return BundleSplit(kept, dropped, versions)
