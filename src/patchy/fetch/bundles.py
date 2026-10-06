import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from .. import catalog
from ..catalog.models import Companion, CompanionVariant
from ..core import log, paths
from .github import ReleaseAsset, download_latest_release_asset


class ManifestEntry(TypedDict):
    name: str
    tag: str
    body: str
    prerelease: bool


class Manifest(TypedDict):
    builds: list[str]
    cli: ManifestEntry
    bundles: dict[str, ManifestEntry]


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class Tools:
    cli: Path
    bundles: dict[str, Path]


def is_cli_asset(name: str) -> bool:
    return "desktop" in name and name.endswith(".jar")


def is_bundle_asset(name: str) -> bool:
    return name.endswith(".mpp")


def companion_matcher(variant: CompanionVariant) -> Callable[[str], bool]:
    suffix = variant["suffix"]
    excluded = (variant.get("exclude") or "").lower()

    def _match(name: str) -> bool:
        return name.endswith(suffix) and not (excluded and excluded in name.lower())

    return _match


def _entry(asset: ReleaseAsset) -> ManifestEntry:
    return {
        "name": asset["name"],
        "tag": asset["tag"],
        "body": asset["body"],
        "prerelease": asset["prerelease"],
    }


async def fetch_cli(dest_dir: Path | None = None) -> ReleaseAsset:
    return await download_latest_release_asset(
        owner=catalog.CLI["owner"],
        repo=catalog.CLI["repo"],
        prerelease=True,
        match=is_cli_asset,
        dest_dir=dest_dir,
    )


async def fetch_bundle(key: str, dest_dir: Path | None = None) -> ReleaseAsset:
    source = catalog.BUNDLES[key]
    log.step(f"Fetching bundle '{key}' ({source['owner']}/{source['repo']})...")
    return await download_latest_release_asset(
        owner=source["owner"],
        repo=source["repo"],
        prerelease=True,
        match=is_bundle_asset,
        dest_dir=dest_dir,
    )


def bundle_keys_for(builds: Iterable[str]) -> list[str]:
    needed: list[str] = []
    for build_key in builds:
        for key in catalog.bundles_for(build_key):
            if key not in needed:
                needed.append(key)
    return needed


async def fetch_all(builds: list[str]) -> Manifest:
    cli = await fetch_cli()
    entries: dict[str, ManifestEntry] = {}
    for key in bundle_keys_for(builds):
        entries[key] = _entry(await fetch_bundle(key))

    manifest: Manifest = {"builds": list(builds), "cli": _entry(cli), "bundles": entries}
    write_manifest(manifest)
    return manifest


def write_manifest(manifest: Manifest, path: Path | None = None) -> Path:
    target = path or paths.manifest_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def read_manifest(path: Path | None = None) -> Manifest:
    source = path or paths.manifest_file()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ManifestError(f"Bundle manifest not found: {source} (did the plan job's artifact download?)") from e
    except json.JSONDecodeError as e:
        raise ManifestError(f"Bundle manifest {source} is not valid JSON: {e}") from e

    if not isinstance(data, dict) or not {"builds", "cli", "bundles"} <= set(data):
        raise ManifestError(f"Bundle manifest {source} is missing required keys (builds, cli, bundles).")
    return data


def resolve_tools(manifest: Manifest, tools_dir: Path | None = None) -> Tools:
    directory = tools_dir or paths.tools_dir()
    cli = directory / manifest["cli"]["name"]
    if not cli.is_file():
        raise ManifestError(f"CLI jar listed in the manifest is missing on disk: {cli}")

    bundles: dict[str, Path] = {}
    for key, entry in manifest["bundles"].items():
        path = directory / entry["name"]
        if not path.is_file():
            raise ManifestError(f"Bundle '{key}' listed in the manifest is missing on disk: {path}")
        bundles[key] = path
    return Tools(cli=cli, bundles=bundles)


def companions_for(build_keys: Iterable[str]) -> list[Companion]:
    built = set(build_keys)
    return [c for c in catalog.COMPANIONS.values() if built & set(c["for_builds"])]


async def fetch_companion(
    companion: Companion, variant: CompanionVariant, dest_dir: Path | None = None
) -> ReleaseAsset:
    return await download_latest_release_asset(
        owner=companion["owner"],
        repo=companion["repo"],
        prerelease=True,
        match=companion_matcher(variant),
        dest_dir=dest_dir or paths.companions_dir(),
    )
