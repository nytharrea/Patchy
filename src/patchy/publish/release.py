import asyncio
from pathlib import Path
from urllib.parse import quote

from ..catalog.models import Companion, CompanionVariant
from ..catalog.plan import TAG_PREFIX
from ..core import log
from ..core.http import github_headers, new_session
from ..core.settings import settings
from ..fetch.bundles import fetch_companion

PAGE_SIZE = 100


def _headers() -> dict[str, str]:
    return github_headers({"User-Agent": "python", "Accept": "application/vnd.github+json"})


def _api(path: str) -> str:
    return f"https://api.github.com/repos/{settings.github_repository}{path}"


def _json(res) -> object:
    try:
        return res.json()
    except Exception:
        return {"message": (getattr(res, "text", "") or "")[:300] or f"HTTP {res.status_code}"}


def _assert_configured():
    if not settings.github_token.get_secret_value():
        raise RuntimeError("Missing GITHUB_TOKEN")
    if not settings.github_repository:
        raise RuntimeError("Missing GITHUB_REPOSITORY")


def _asset_name(file_name: str) -> str:
    return Path(file_name).name.replace(" ", ".")


def _names_match(a: str, b: str) -> bool:
    if a == b:
        return True
    return a.replace(" ", ".") == b.replace(" ", ".")


async def get_release_by_tag(tag: str) -> dict | None:
    _assert_configured()
    async with new_session(timeout=30) as client:
        res = await client.get(_api(f"/releases/tags/{quote(tag)}"), headers=_headers())
        if res.status_code == 404:
            return None
        data = _json(res)
        if not isinstance(data, dict) or "id" not in data:
            return None
        return data


async def create_new_release(tag: str, release_name: str, release_body: str = "", draft: bool = False) -> dict:
    _assert_configured()

    payload = {
        "name": release_name,
        "body": release_body,
        "draft": draft,
        "prerelease": False,
        "make_latest": "false" if draft else "true",
    }

    existing = await get_release_by_tag(tag)
    if existing:
        log.warn(f"Release already exists for tag {tag} (id={existing['id']}), reusing it")
        async with new_session(timeout=30) as client:
            res = await client.patch(_api(f"/releases/{existing['id']}"), headers=_headers(), json=payload)
            data = _json(res)
        if not isinstance(data, dict) or "id" not in data:
            raise RuntimeError(f"Failed to update existing release: {data}")
        return data

    log.step(f"Creating new release: {tag}")
    async with new_session(timeout=30) as client:
        res = await client.post(_api("/releases"), headers=_headers(), json={"tag_name": tag, **payload})
        data = _json(res)

    if not isinstance(data, dict) or "id" not in data:
        raise RuntimeError(f"Failed to create release: {data}")

    return data


async def list_releases() -> list[dict]:
    releases: list[dict] = []
    page = 1
    async with new_session(timeout=30) as client:
        while True:
            res = await client.get(
                _api("/releases"), headers=_headers(), params={"per_page": PAGE_SIZE, "page": page}
            )
            data = _json(res)
            if res.status_code >= 400 or not isinstance(data, list):
                raise RuntimeError(f"Failed to list releases: {data}")
            releases.extend(data)
            if len(data) < PAGE_SIZE:
                break
            page += 1
    return releases


async def delete_release(release_id: int) -> None:
    async with new_session(timeout=30) as client:
        res = await client.delete(_api(f"/releases/{release_id}"), headers=_headers())
    if res.status_code not in (204, 404):
        raise RuntimeError(f"Failed to delete release {release_id}: status={res.status_code} {_json(res)}")


async def delete_tag(tag: str) -> None:
    async with new_session(timeout=30) as client:
        res = await client.delete(_api(f"/git/refs/tags/{quote(tag)}"), headers=_headers())
    if res.status_code not in (204, 404, 422):
        raise RuntimeError(f"Failed to delete tag {tag}: status={res.status_code} {_json(res)}")


async def delete_other_releases(keep_release_id: int) -> None:
    releases = await list_releases()
    errors: list[str] = []

    for release in releases:
        if release["id"] == keep_release_id:
            continue

        tag = release.get("tag_name") or ""
        if not tag.startswith(TAG_PREFIX):
            log.info(f"Keeping release that is not a Patchy build: {tag or release['id']}")
            continue

        log.warn(f"Deleting old release: {tag}")
        try:
            await delete_release(release["id"])
            await delete_tag(tag)
        except RuntimeError as e:
            errors.append(str(e))

    if errors:
        raise RuntimeError("; ".join(errors))


async def get_assets(release_id: int) -> list[dict]:
    all_assets: list[dict] = []
    page = 1
    async with new_session(timeout=30) as client:
        while True:
            res = await client.get(
                _api(f"/releases/{release_id}/assets"),
                headers=_headers(),
                params={"per_page": PAGE_SIZE, "page": page},
            )
            data = _json(res)
            if not isinstance(data, list):
                raise RuntimeError(f"Failed to list assets: {data}")
            if not data:
                break
            all_assets.extend(data)
            if len(data) < PAGE_SIZE:
                break
            page += 1
    return all_assets


async def delete_asset(asset_id: int) -> None:
    async with new_session(timeout=30) as client:
        res = await client.delete(_api(f"/releases/assets/{asset_id}"), headers=_headers())
        if res.status_code not in (204, 404):
            raise RuntimeError(f"Failed to delete asset {asset_id}: status={res.status_code} {_json(res)}")


def _iter_file_chunks(file_path: str, chunk_size: int = 8 * 1024 * 1024):
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk


async def _upload(upload_url: str, file_path: str, asset_name: str) -> dict:
    file_size = Path(file_path).stat().st_size

    url = upload_url.replace("{?name,label}", "") + f"?name={quote(asset_name)}"

    async with new_session(timeout=None) as client:
        res = await client.post(
            url,
            headers={
                **_headers(),
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Length": str(file_size),
            },
            content=_iter_file_chunks(file_path),
        )
        data = _json(res)

        if res.status_code not in (200, 201) or not isinstance(data, dict):
            raise RuntimeError(
                f"Upload failed for {asset_name} (size={file_size} bytes, status={res.status_code}): {data}"
            )

        uploaded_size = data.get("size")
        if uploaded_size is not None and uploaded_size != file_size:
            raise RuntimeError(
                f"Upload size mismatch for {asset_name}: "
                f"local={file_size} bytes, github={uploaded_size} bytes. "
                f"Response: {data}"
            )

        return data


def _is_already_exists_error(exc: BaseException) -> bool:
    return "already_exists" in str(exc)


async def _delete_asset_by_name(release_id: int, asset_name: str) -> bool:
    assets = await get_assets(release_id)
    existing = next((a for a in assets if _names_match(a["name"], asset_name)), None)
    if not existing:
        return False
    log.warn(f"Replacing existing asset: {existing['name']} (id={existing['id']})")
    await delete_asset(existing["id"])
    await asyncio.sleep(0.5)
    return True


async def upload_with_replace(release: dict, file_path: str):
    local_name = Path(file_path).name
    asset_name = _asset_name(local_name)
    file_size = Path(file_path).stat().st_size
    release_id = release["id"]

    await _delete_asset_by_name(release_id, asset_name)

    log.download(f"Uploading: {asset_name} ({file_size / (1024 * 1024):.1f} MB)")

    for attempt in range(3):
        try:
            result = await _upload(release["upload_url"], file_path, asset_name)
            break
        except RuntimeError as e:
            if not _is_already_exists_error(e) or attempt == 2:
                raise
            log.warn(
                f"Asset already exists during upload (attempt {attempt + 1}/3), "
                f"deleting and retrying: {asset_name}"
            )
            deleted = await _delete_asset_by_name(release_id, asset_name)
            if not deleted:
                names = [a["name"] for a in await get_assets(release_id)]
                log.warn(f"Could not find {asset_name} in assets list ({len(names)} assets): {names[:30]}")
            await asyncio.sleep(1.0 * (attempt + 1))
    else:
        raise RuntimeError(f"Upload failed for {asset_name} after retries")

    uploaded_size = result.get("size", file_size)
    log.info(f"✅ Uploaded {asset_name} ({uploaded_size / (1024 * 1024):.1f} MB, id={result.get('id')})")
    return result


async def upload_patched_apks(release: dict, apk_paths: list[str]) -> None:
    _assert_configured()
    semaphore = asyncio.Semaphore(settings.upload_concurrency)

    async def _upload_one(path: str) -> None:
        async with semaphore:
            await upload_with_replace(release, path)

    await asyncio.gather(*(_upload_one(path) for path in apk_paths))


async def _upload_companion_variant(release: dict, companion: Companion, variant: CompanionVariant) -> None:
    result = await fetch_companion(companion, variant)

    base_name = variant["file"]
    final_name = base_name.replace(".apk", "-PRERELEASE.apk") if result.get("prerelease") else base_name
    final_name = _asset_name(final_name)

    original_path = Path(result["path"])
    new_path = original_path.with_name(final_name)
    if original_path.exists() and original_path != new_path:
        original_path.rename(new_path)

    if result.get("prerelease"):
        log.warn(f"{base_name} latest release ({result['tag']}) is a PRERELEASE")

    assets = await get_assets(release["id"])
    if any(_names_match(a["name"], final_name) for a in assets):
        log.info(f"{final_name} already up to date on this release, skipping upload")
        return

    await upload_with_replace(release, str(new_path))


async def upload_companions(release: dict, companions: list[Companion]) -> None:
    _assert_configured()
    jobs = [
        _upload_companion_variant(release, companion, variant)
        for companion in companions
        for variant in companion["variants"]
    ]
    if jobs:
        log.step(f"Fetching companion app(s): {', '.join(c['key'] for c in companions)}...")
    await asyncio.gather(*jobs)
