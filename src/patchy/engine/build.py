import asyncio
import json
import random
import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from .. import catalog
from ..catalog.models import ApkMirrorSource, BuildConfig
from ..core import log, paths
from ..fetch import apkmirror, github
from ..fetch.bundles import Tools
from .patcher import UnsupportedBuild, list_versions, patch_apk
from .verify import UnpinnedSignature, verify_apk_signature
from .versions import extract_cli_version_codes, extract_cli_versions, file_name_version, rank_versions

MAX_VERSION_ATTEMPTS = 3


class VersionChoice(NamedTuple):
    version: str
    build_codes: dict[str, int]


def write_status(
    build_key: str,
    *,
    error: str | None = None,
    version: str | None = None,
    file: str | None = None,
    pending_pin: dict[str, str] | None = None,
    timings: dict[str, float] | None = None,
) -> None:
    try:
        directory = paths.out_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "build_key": build_key,
            "ok": error is None,
            "error": error,
            "version": version,
            "file": file,
            "pending_pin": pending_pin,
        }
        if timings:
            payload["timings"] = {stage: round(seconds, 1) for stage, seconds in timings.items()}
        (directory / f"status-{build_key}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        log.warn(f"Could not write status for {build_key}: {e}")


async def _select_versions(
    build_key: str, cli_jar: str | Path, bundle_paths: Sequence[str | Path]
) -> list[VersionChoice]:
    build = catalog.BUILDS[build_key]
    app_slug = build["app_slug"]
    source = build["apk_source"]

    forced_version = build.get("force_version")
    ranked: list[str] = []
    build_codes_by_version: dict[str, dict[str, int]] = {}

    if not forced_version or source["type"] == "apkmirror":
        try:
            output = await list_versions(cli_jar, bundle_paths, build["pkg"])
            if output is not None:
                build_codes_by_version = extract_cli_version_codes(output)
                if not forced_version:
                    ranked = rank_versions(extract_cli_versions(output, app_slug))
        except Exception as e:
            log.warn(f"Could not fetch version list: {e}")

    attempts = MAX_VERSION_ATTEMPTS if source["type"] == "apkmirror" else 1
    versions = [forced_version] if forced_version else ranked[:attempts]

    if not versions:
        if source["type"] == "apkmirror":
            latest = await apkmirror.get_latest_listing(app_slug, source)
            if latest and latest.get("version"):
                versions = [latest["version"]]
        elif source["type"] == "github":
            versions = ["latest"]
        else:
            raise RuntimeError(f"Unknown apk_source.type {source['type']!r} for build {build_key!r}")

    if not versions:
        raise RuntimeError("Could not determine a suitable version number.")

    return [VersionChoice(version, build_codes_by_version.get(version, {})) for version in versions]


async def _download_from_apkmirror(
    build: BuildConfig, source: ApkMirrorSource, choices: list[VersionChoice]
) -> tuple[str, VersionChoice]:
    async def download(choice: VersionChoice) -> str:
        return await apkmirror.download_apk(
            choice.version,
            build["app_slug"],
            source,
            build.get("force_build"),
            arch=build["arch"],
            build_codes=choice.build_codes,
        )

    for index, choice in enumerate(choices[:-1]):
        try:
            return await download(choice), choice
        except apkmirror.ReleaseNotFound as e:
            log.warn(f"{e}. Trying {choices[index + 1].version}, the next version the patch bundle supports.")

    return await download(choices[-1]), choices[-1]


async def _refetch_accepted(
    build: BuildConfig, source: ApkMirrorSource, selected: VersionChoice, rejected: UnsupportedBuild
) -> str:
    app_slug = build["app_slug"]
    accepted = ", ".join(str(code) for code in sorted(rejected.accepted))
    log.warn(
        f"The patch rejected build code {rejected.rejected} and accepts {accepted}. "
        f"Fetching one of those builds from APKMirror."
    )

    with log.timed("download"):
        apk_path = await apkmirror.download_apk(
            selected.version,
            app_slug,
            source,
            build.get("force_build"),
            arch=build["arch"],
            build_codes=selected.build_codes,
            accepted_codes=rejected.accepted,
        )

    with log.timed("verify"):
        await verify_apk_signature(apk_path, app_slug)

    return apk_path


async def process_build(build_key: str, cli_jar: str | Path, bundle_paths: Sequence[str | Path]) -> dict | None:
    build = catalog.BUILDS[build_key]
    app_slug = build["app_slug"]
    source = build["apk_source"]

    log.header(f"PROCESSING: {app_slug.upper()}")

    with log.timed("select"):
        choices = await _select_versions(build_key, cli_jar, bundle_paths)

    with log.timed("download"):
        if source["type"] == "apkmirror":
            apk_path, selected = await _download_from_apkmirror(build, source, choices)
        elif source["type"] == "github":
            selected = choices[0]
            apk_path = await github.download_apk(selected.version, app_slug, source)
        else:
            raise RuntimeError(f"Unknown apk_source.type {source['type']!r} for build {build_key!r}")

    selected_version = selected.version

    with log.timed("verify"):
        await verify_apk_signature(apk_path, app_slug)

    async def patch(path: str) -> str:
        return await patch_apk(
            cli_jar,
            bundle_paths,
            path,
            exclude=build.get("exclude"),
            enable=build.get("enable"),
            options=build.get("options"),
            arch=build["arch"],
        )

    try:
        with log.timed("patch"):
            patched_apk = await patch(apk_path)
    except UnsupportedBuild as err:
        if source["type"] != "apkmirror":
            raise
        apk_path = await _refetch_accepted(build, source, selected, err)
        with log.timed("patch"):
            patched_apk = await patch(apk_path)

    if not Path(patched_apk).exists():
        return None

    display_name, source_tag = catalog.get_release_naming(build_key)
    suffix = f"-{source_tag}" if source_tag else ""
    final_name = f"{display_name}-{file_name_version(selected_version)}{suffix}.apk"

    out_dir = paths.out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / final_name

    shutil.copyfile(patched_apk, final_path)

    return {
        "app_name": app_slug,
        "display_name": display_name,
        "icon": build["icon"],
        "bundles": build["bundles"],
        "name": final_name,
        "path": str(final_path),
        "version": selected_version,
    }


def _bundle_paths(build_key: str, tools: Tools) -> list[Path]:
    resolved: list[Path] = []
    for key in catalog.bundles_for(build_key):
        path = tools.bundles.get(key)
        if path is None:
            raise RuntimeError(f"No patch bundle file resolved for '{key}'")
        resolved.append(path)
    return resolved


def _with_total(timings: dict[str, float], began: float) -> dict[str, float]:
    return {**timings, "total": time.monotonic() - began}


async def run_builds(build_keys: list[str], tools: Tools) -> list[str]:
    failed: list[str] = []

    for index, build_key in enumerate(build_keys):
        began = time.monotonic()
        with log.collect_timings() as timings:
            try:
                result = await process_build(build_key, tools.cli, _bundle_paths(build_key, tools))
                if result:
                    log.success(f"{build_key.upper()} done: {result['name']}")
                    write_status(
                        build_key,
                        version=result["version"],
                        file=result["name"],
                        timings=_with_total(timings, began),
                    )
                else:
                    failed.append(build_key)
                    write_status(
                        build_key, error="patch_apk produced no output file", timings=_with_total(timings, began)
                    )
            except UnpinnedSignature as err:
                log.error(f"{build_key.upper()} failed, skipping: {err}")
                failed.append(build_key)
                write_status(
                    build_key,
                    error=str(err),
                    pending_pin={"app": err.app_name, "sha256": err.fingerprint},
                    timings=_with_total(timings, began),
                )
            except Exception as err:
                log.error(f"{build_key.upper()} failed, skipping: {err}")
                failed.append(build_key)
                write_status(build_key, error=str(err), timings=_with_total(timings, began))

        is_last = index == len(build_keys) - 1
        if catalog.BUILDS[build_key]["apk_source"]["type"] == "apkmirror" and not is_last:
            delay = random.uniform(6.0, 14.0)
            log.wait(f"Waiting {delay:.0f}s before the next app (to reduce APKMirror request rate)...")
            await asyncio.sleep(delay)

    return failed
