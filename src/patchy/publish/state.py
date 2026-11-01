import hashlib
import json
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import NotRequired, TypedDict

from ..catalog.models import BuildConfig

STATE_FILE_NAME = "patchy-state.json"
STATE_VERSION = 1
FINGERPRINT_LENGTH = 32
IGNORED_CONFIG_KEYS = frozenset({"icon"})


class Identity(TypedDict):
    tag: str
    name: str


class BuildRecord(TypedDict):
    version: str
    file: str
    fingerprint: NotRequired[str]
    retry: NotRequired[bool]


class State(TypedDict):
    version: int
    release_tag: str
    builds: dict[str, BuildRecord]


def fingerprint(
    build: BuildConfig,
    cli: Identity | None,
    bundles: Mapping[str, Identity | None],
    app_tag: str | None,
) -> str | None:
    source = build["apk_source"]
    if cli is None:
        return None
    if source["type"] == "github" and not app_tag:
        return None
    if build.get("force") and source["type"] != "github":
        return None

    resolved: dict[str, list[str]] = {}
    for key in build["bundles"]:
        identity = bundles.get(key)
        if identity is None:
            return None
        resolved[key] = [identity["tag"], identity["name"]]

    payload = {
        "config": {key: value for key, value in build.items() if key not in IGNORED_CONFIG_KEYS},
        "cli": [cli["tag"], cli["name"]],
        "bundles": resolved,
        "app": app_tag,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def make_record(version: str, file: str, digest: str | None = None, retry: bool = False) -> BuildRecord:
    record: BuildRecord = {"version": version, "file": file}
    if digest:
        record["fingerprint"] = digest
    if retry:
        record["retry"] = True
    return record


def _record(value: object) -> BuildRecord | None:
    if not isinstance(value, dict):
        return None
    version, file = value.get("version"), value.get("file")
    if not isinstance(version, str) or not isinstance(file, str) or not file:
        return None
    digest = value.get("fingerprint")
    return make_record(
        version,
        file,
        digest if isinstance(digest, str) else None,
        value.get("retry") is True,
    )


def parse_state(data: object) -> State | None:
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    release_tag, raw = data.get("release_tag"), data.get("builds")
    if not isinstance(release_tag, str) or not isinstance(raw, dict):
        return None
    builds: dict[str, BuildRecord] = {}
    for key, value in raw.items():
        record = _record(value)
        if isinstance(key, str) and record is not None:
            builds[key] = record
    return {"version": STATE_VERSION, "release_tag": release_tag, "builds": builds}


def read_state(path: str | Path) -> State | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parse_state(data)


def write_state(state: State, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def changed_builds(
    selected: Collection[str], previous: State | None, current: Mapping[str, str | None]
) -> dict[str, str]:
    changed: dict[str, str] = {}
    for key in selected:
        record = previous["builds"].get(key) if previous is not None else None
        digest = current.get(key)
        if previous is None:
            reason = "there is no earlier state to compare with"
        elif record is None:
            reason = "it was not part of the previous release"
        elif digest is None:
            reason = "its inputs cannot be compared"
        elif record.get("retry"):
            reason = "the previous build had to use an older version"
        elif record.get("fingerprint") != digest:
            reason = "the patcher, a patch bundle, the app or its configuration changed"
        else:
            continue
        changed[key] = reason
    return changed


def next_state(
    previous: State | None,
    release_tag: str,
    built: Mapping[str, BuildRecord],
    carried: Mapping[str, BuildRecord],
) -> State:
    earlier = previous["builds"] if previous is not None else {}
    builds: dict[str, BuildRecord] = {}
    for key, fallback in carried.items():
        kept = earlier.get(key)
        builds[key] = kept if kept is not None and kept["file"] == fallback["file"] else fallback
    builds.update(built)
    return {"version": STATE_VERSION, "release_tag": release_tag, "builds": builds}
