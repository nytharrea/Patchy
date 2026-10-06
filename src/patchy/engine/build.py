import asyncio
import json
import random
import shutil
from collections.abc import Sequence
from pathlib import Path

from .. import catalog
from ..core import log, paths
from ..fetch import apkmirror, github
from ..fetch.bundles import Tools
from .patcher import list_versions, patch_apk
from .verify import UnpinnedSignature, verify_apk_signature
from .versions import extract_cli_versions, pick_latest_version


def write_status(
    build_key: str,
    *,
    error: str | None = None,
    version: str | None = None,
    file: str | None = None,
    pending_pin: dict[str, str] | None = None,
) -> None:
    try:
        directory = paths.out_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "build_key": build_key,
            "ok": error is None,
            "error": error,
            "version": version,
            "file": file,
            "pending_pin": pending_pin,
        }
        (directory / f"status-{build_key}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        log.warn(f"Could not write status for {build_key}: {e}")


async def _select_version(build_key: str, cli_jar: str | Path, bundle_paths: Sequence[str | Path]) -> str:
    build = catalog.BUILDS[build_key]
    app_slug = build["app_slug"]
    source = build["apk_source"]

    selected_version = build.get("force_version")

    if not selected_version:
        try:
            output = await list_versions(cli_jar, bundle_paths, build["pkg"])
            if output is not None:
                versions = extract_cli_versions(output, app_slug)
                if versions:
                    selected_version = pick_latest_version(versions)
        except Exception as e:
            log.warn(f"Could not fetch version list: {e}")

    if not selected_version:
        if source["type"] == "apkmirror":
            latest = await apkmirror.get_latest_listing(app_slug, source)
            if latest and latest.get("version"):
                selected_version = latest["version"]
        elif source["type"] == "github":
            selected_version = "latest"
        else:
            raise RuntimeError(f"Unknown apk_source.type {source['type']!r} for build {build_key!r}")

    if not selected_version:
        raise RuntimeError("Could not determine a suitable version number.")

    return selected_version


async def process_build(build_key: str, cli_jar: str | Path, bundle_paths: Sequence[str | Path]) -> dict | None:
    build = catalog.BUILDS[build_key]
    app_slug = build["app_slug"]
    source = build["apk_source"]

    log.header(f"PROCESSING: {app_slug.upper()}")

    selected_version = await _select_version(build_key, cli_jar, bundle_paths)

    if source["type"] == "apkmirror":
        apk_path = await apkmirror.download_apk(selected_version, app_slug, source, build.get("force_build"))
    elif source["type"] == "github":
        apk_path = await github.download_apk(selected_version, app_slug, source)
    else:
        raise RuntimeError(f"Unknown apk_source.type {source['type']!r} for build {build_key!r}")

    await verify_apk_signature(apk_path, app_slug)

    patched_apk = await patch_apk(
        cli_jar,
        bundle_paths,
        apk_path,
        exclude=build.get("exclude"),
        enable=build.get("enable"),
        options=build.get("options"),
        arch=build["arch"],
    )

    if not Path(patched_apk).exists():
        return None

    display_name, source_tag = catalog.get_release_naming(build_key)
    suffix = f"-{source_tag}" if source_tag else ""
    final_name = f"{display_name}-{selected_version}{suffix}.apk"

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


async def run_builds(build_keys: list[str], tools: Tools) -> list[str]:
    failed: list[str] = []

    for index, build_key in enumerate(build_keys):
        try:
            result = await process_build(build_key, tools.cli, _bundle_paths(build_key, tools))
            if result:
                log.success(f"{build_key.upper()} done: {result['name']}")
                write_status(build_key, version=result["version"], file=result["name"])
            else:
                failed.append(build_key)
                write_status(build_key, error="patch_apk produced no output file")
        except UnpinnedSignature as err:
            log.error(f"{build_key.upper()} failed, skipping: {err}")
            failed.append(build_key)
            write_status(build_key, error=str(err), pending_pin={"app": err.app_name, "sha256": err.fingerprint})
        except Exception as err:
            log.error(f"{build_key.upper()} failed, skipping: {err}")
            failed.append(build_key)
            write_status(build_key, error=str(err))

        is_last = index == len(build_keys) - 1
        if catalog.BUILDS[build_key]["apk_source"]["type"] == "apkmirror" and not is_last:
            delay = random.uniform(6.0, 14.0)
            log.wait(f"Waiting {delay:.0f}s before the next app (to reduce APKMirror request rate)...")
            await asyncio.sleep(delay)

    return failed
