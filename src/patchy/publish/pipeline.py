import asyncio
import json
from pathlib import Path

from .. import catalog
from ..core import log, paths, toolchain
from ..core.settings import settings
from ..engine.signer import SigningError, load_credentials, sign_apk
from ..fetch.bundles import Manifest, ManifestError, companions_for, read_manifest
from . import notify
from .assets import (
    build_release_body,
    find_failure_reasons,
    find_patched_apks,
)
from .release import (
    create_new_release,
    delete_other_releases,
    upload_companions,
    upload_patched_apks,
)

SIGN_CONCURRENCY = 4


def _write_signing_failure(build_key: str, reason: str) -> None:
    directory = paths.signed_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"build_key": build_key, "ok": False, "error": f"signing failed: {reason}"}
    (directory / f"status-{build_key}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


async def run_sign() -> dict[str, str]:
    artifacts_dir = paths.artifacts_dir()
    signed_dir = paths.signed_dir()
    signed_dir.mkdir(parents=True, exist_ok=True)

    matched, unmatched = find_patched_apks(artifacts_dir)
    for name in unmatched:
        log.warn(f"Could not match asset to a known app: {name}")

    if not matched:
        log.warn(f"No patched APKs found in {artifacts_dir}, nothing to sign.")
        return {}

    await toolchain.prepare(install_latest=True)
    creds = load_credentials()
    if creds is None:
        log.warn("Signing credentials are missing or incomplete (KS_PATH, KS_PASSWORD, KS_ALIAS, KEY_PASSWORD).")

    semaphore = asyncio.Semaphore(SIGN_CONCURRENCY)
    fingerprints: dict[str, str] = {}

    async def _sign_one(apk: dict) -> None:
        async with semaphore:
            try:
                fingerprints[apk["name"]] = await sign_apk(Path(apk["path"]), signed_dir / apk["name"], creds)
                log.success(f"Signed and verified: {apk['name']}")
            except SigningError as e:
                log.error(f"Signing failed for {apk['name']}: {e}")
                _write_signing_failure(apk["build_key"], str(e))

    await asyncio.gather(*(_sign_one(apk) for apk in matched))

    distinct = set(fingerprints.values())
    if len(distinct) == 1:
        fingerprint = next(iter(distinct))
        log.lock(f"All {len(fingerprints)} signed APK(s) share certificate SHA-256 {fingerprint}")
    elif len(distinct) > 1:
        log.warn(f"Signed APKs carry {len(distinct)} different signing certificates: {sorted(distinct)}")

    return fingerprints


def _load_manifest() -> Manifest | None:
    try:
        return read_manifest()
    except ManifestError as e:
        log.warn(f"{e} Release notes for patch bundles will be left out.")
        return None


async def run_publish() -> bool:
    if not settings.release_tag or not settings.release_name:
        raise RuntimeError("Missing RELEASE_TAG/RELEASE_NAME (expected to be set by `patchy plan`'s output)")
    release_tag = settings.release_tag
    release_name = settings.release_name

    manifest = _load_manifest()
    planned = list(manifest["builds"]) if manifest else list(catalog.BUILDS)

    signed_dir = paths.signed_dir()
    log.step(f"Scanning {signed_dir} for signed APKs...")
    matched, unmatched = find_patched_apks(signed_dir)

    for name in unmatched:
        log.warn(f"Could not match asset to a known app: {name}")

    log.info(f"Matched {len(matched)} app asset(s).")

    succeeded_keys = {apk["build_key"] for apk in matched}
    failed_keys = [key for key in planned if key not in succeeded_keys]
    failure_reasons = find_failure_reasons(paths.artifacts_dir(), signed_dir)

    if not matched:
        log.error("No apps patched successfully in this run, skipping release creation.")
        await notify.notify(notify.format_all_failed(release_name, failed_keys, failure_reasons))
        return False

    body = build_release_body(matched, manifest)

    log.step(f"Creating release: {release_tag}")
    release = await create_new_release(release_tag, release_name, body, draft=False)
    log.success(f"Release created: {release['tag_name']} (id={release['id']})")

    log.step(f"Uploading {len(matched)} patched APK(s) (up to {settings.upload_concurrency} at once)...")
    await upload_patched_apks(release, [apk["path"] for apk in matched])

    companions = companions_for(apk["build_key"] for apk in matched)
    if companions:
        await upload_companions(release, companions)

    log.success("All apps successfully published under one release!")

    try:
        await delete_other_releases(release["id"])
        log.info("Old releases deleted.")
    except Exception as e:
        log.warn(f"Failed to delete old releases: {e}")

    release_url = release.get("html_url") or (
        f"https://github.com/{settings.github_repository}/releases/tag/{release_tag}"
    )
    await notify.notify(notify.format_summary(release_name, release_url, matched, failed_keys, failure_reasons))
    return True
