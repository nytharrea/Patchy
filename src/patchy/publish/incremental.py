from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass

from .. import catalog
from ..core import log, paths
from ..fetch.bundles import (
    Manifest,
    ManifestEntry,
    bundle_keys_for,
    is_bundle_asset,
    is_cli_asset,
    write_manifest,
)
from ..fetch.github import fetch_latest_release, latest_release_tag
from .release import download_asset, previous_release
from .state import STATE_FILE_NAME, Identity, State, changed_builds, fingerprint, read_state


@dataclass(frozen=True)
class Identities:
    cli: Identity | None
    bundles: dict[str, Identity | None]
    apps: dict[str, str | None]


def _entry_identity(entry: ManifestEntry) -> Identity:
    return {"tag": entry["tag"], "name": entry["name"]}


async def _identity(owner: str, repo: str, match: Callable[[str], bool]) -> Identity | None:
    try:
        release = await fetch_latest_release(owner, repo, prerelease=True, match=match)
    except Exception as e:
        log.warn(f"Could not look up the latest release of {owner}/{repo}: {e}")
        return None
    asset = next((item for item in release.get("assets") or [] if match(item["name"])), None)
    if asset is None:
        return None
    return {"tag": str(release.get("tag_name") or ""), "name": asset["name"]}


async def _app_tags(builds: Iterable[str]) -> dict[str, str | None]:
    tags: dict[str, str | None] = {}
    for key in builds:
        source = catalog.BUILDS[key]["apk_source"]
        if source["type"] == "github":
            tags[key] = await latest_release_tag(source["owner"], source["repo"])
    return tags


async def resolve_identities(selected: Collection[str]) -> Identities:
    cli = await _identity(catalog.CLI["owner"], catalog.CLI["repo"], is_cli_asset)
    bundles: dict[str, Identity | None] = {}
    for key in bundle_keys_for(selected):
        source = catalog.BUNDLES[key]
        bundles[key] = await _identity(source["owner"], source["repo"], is_bundle_asset)
    return Identities(cli=cli, bundles=bundles, apps=await _app_tags(selected))


async def read_release_state(release: dict | None) -> State | None:
    if release is None:
        return None
    tag = release.get("tag_name")
    asset = next((item for item in release.get("assets") or [] if item.get("name") == STATE_FILE_NAME), None)
    if asset is None:
        log.info(f"Release {tag} carries no {STATE_FILE_NAME}.")
        return None
    try:
        path = await download_asset(asset, paths.state_dir() / f"previous-{STATE_FILE_NAME}")
    except Exception as e:
        log.warn(f"Could not download {STATE_FILE_NAME} from {tag}: {e}")
        return None
    state = read_state(path)
    if state is None:
        log.warn(f"{STATE_FILE_NAME} from {tag} is not readable, so it is ignored.")
    return state


async def select_changed(selected: list[str]) -> list[str]:
    try:
        release = await previous_release()
    except Exception as e:
        log.warn(f"Could not look up the previous release, so every selected build runs: {e}")
        release = None

    previous = await read_release_state(release)
    identities = await resolve_identities(selected)
    current = {
        key: fingerprint(catalog.BUILDS[key], identities.cli, identities.bundles, identities.apps.get(key))
        for key in selected
    }
    changed = changed_builds(selected, previous, current)

    since = previous["release_tag"] if previous is not None else "the start"
    for key in selected:
        if key in changed:
            log.info(f"{key}: builds, because {changed[key]}.")
        else:
            log.info(f"{key}: skipped, nothing changed since {since}.")
    return list(changed)


async def record_fingerprints(manifest: Manifest) -> Manifest:
    cli = _entry_identity(manifest["cli"])
    bundles: dict[str, Identity | None] = {
        key: _entry_identity(entry) for key, entry in manifest["bundles"].items()
    }
    apps = await _app_tags(manifest["builds"])
    manifest["fingerprints"] = {
        key: fingerprint(catalog.BUILDS[key], cli, bundles, apps.get(key)) for key in manifest["builds"]
    }
    write_manifest(manifest)
    return manifest
