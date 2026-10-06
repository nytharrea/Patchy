from collections.abc import Callable
from pathlib import Path
from typing import NotRequired, TypedDict

from curl_cffi.requests import AsyncSession
from tenacity import retry, stop_after_attempt

from ..core import log, paths
from ..core import retry as retry_conf
from ..core.http import github_headers, new_session


class GithubAppSite(TypedDict):
    owner: str
    repo: str
    asset_hint: NotRequired[str]
    tag_template: NotRequired[str]


class ReleaseAsset(TypedDict):
    name: str
    path: str
    body: str
    tag: str
    prerelease: bool


def _select_release(releases: list[dict], match: Callable[[str], bool] | None = None) -> dict | None:
    for release in releases:
        if release.get("draft"):
            continue
        if match is None or any(match(a["name"]) for a in release.get("assets") or []):
            return release
        log.notice(f"Skipping release {release.get('tag_name')}: no matching asset")
    return None


async def fetch_latest_release(
    owner: str, repo: str, prerelease: bool = False, match: Callable[[str], bool] | None = None
) -> dict:
    url = (
        f"https://api.github.com/repos/{owner}/{repo}/releases"
        if prerelease
        else f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    )

    @retry(
        stop=stop_after_attempt(5),
        wait=retry_conf.exponential_with_jitter(max=30.0),
        before_sleep=retry_conf.before_sleep("GitHub request"),
        reraise=True,
    )
    async def _do():
        async with new_session(timeout=30) as client:
            res = await client.get(
                url,
                headers=github_headers({"User-Agent": "python", "Accept": "application/vnd.github+json"}),
            )
            if res.status_code >= 400:
                raise RuntimeError(f"GitHub API error: {res.status_code} ({owner}/{repo})")

            return res.json()

    data = await _do()

    if not prerelease:
        return data

    release = _select_release(data, match) if isinstance(data, list) else None
    if release is None:
        raise RuntimeError(f"No release with a matching asset found in {owner}/{repo}")

    return release


async def _download_file(url: str, output_path: Path, expected_size: int | None = None) -> str:
    temp_path = output_path.with_name(output_path.name + ".part")
    downloaded = temp_path.stat().st_size if temp_path.exists() else 0

    headers = {"User-Agent": "python", "Accept": "*/*"}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"
        log.download(f"Resuming at {downloaded} bytes")

    mode = "ab" if downloaded > 0 else "wb"

    async with (
        new_session(follow_redirects=True, timeout=None) as client,
        client.stream("GET", url, headers=headers) as res,
    ):
        if res.status_code >= 400:
            raise RuntimeError(f"HTTP {res.status_code}")

        with open(temp_path, mode) as f:
            async for chunk in res.aiter_content():
                f.write(chunk)
                downloaded += len(chunk)

    if expected_size and downloaded != expected_size:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Size mismatch: {downloaded}/{expected_size}")

    temp_path.rename(output_path)
    return str(output_path)


def _asset_info(asset: dict, release: dict, path: Path) -> ReleaseAsset:
    return {
        "name": asset["name"],
        "path": str(path),
        "body": release.get("body") or "",
        "tag": release.get("tag_name") or "",
        "prerelease": bool(release.get("prerelease")),
    }


async def download_latest_release_asset(
    owner: str,
    repo: str,
    match: Callable[[str], bool],
    prerelease: bool = False,
    dest_dir: Path | None = None,
) -> ReleaseAsset:
    log.step(f"Fetching release: {owner}/{repo}")

    release = await fetch_latest_release(owner, repo, prerelease, match)

    assets = release.get("assets") or []
    if not assets:
        raise RuntimeError(f"Repo {owner}/{repo} has no assets")

    asset = next((a for a in assets if match(a["name"])), None)
    if not asset:
        raise RuntimeError("Matching asset not found")

    log.info(f"Selected: {asset['name']} ({release.get('tag_name')})")

    target_dir = dest_dir if dest_dir is not None else paths.tools_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / asset["name"]

    if out_path.exists():
        size = out_path.stat().st_size
        expected = asset.get("size")
        if size < 1024 or (expected and size != expected):
            log.warn("Removing stale or corrupt cached file")
            out_path.unlink()
        else:
            log.info(f"Using cached file: {asset['name']}")
            return _asset_info(asset, release, out_path)

    @retry(
        stop=stop_after_attempt(5),
        wait=retry_conf.exponential_with_jitter(max=30.0),
        before_sleep=retry_conf.before_sleep("GitHub download"),
        reraise=True,
    )
    async def _do():
        await _download_file(asset["browser_download_url"], out_path, asset.get("size"))

    await _do()

    log.success(f"Done: {asset['name']}")

    return _asset_info(asset, release, out_path)


def _headers() -> dict[str, str]:
    return github_headers({"User-Agent": "Mozilla/5.0 (Python)"})


def _build_tag(tag_template: str, version: str) -> str:
    prefix = tag_template.split("{version}")[0]
    if prefix and version.startswith(prefix):
        return version
    return tag_template.format(version=version)


def _pick_apk_asset(assets: list[dict], name_hint: str | None = None) -> dict | None:
    candidates = [a for a in assets if a["name"].endswith(".apk") or a["name"].endswith(".apkm")]
    if not candidates:
        return None

    if name_hint:
        hinted = [a for a in candidates if name_hint.lower() in a["name"].lower()]
        if hinted:
            candidates = hinted

    arm64 = next((a for a in candidates if "arm64" in a["name"].lower()), None)
    return arm64 or candidates[0]


async def _download_asset(client: AsyncSession, asset: dict) -> str:
    size_mb = asset["size"] / (1024 * 1024)
    log.download(f"Found file to download: {asset['name']} ({size_mb:.2f} MB)")

    out_dir = paths.downloads_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / asset["name"]

    log.download("Downloading...")

    async with client.stream("GET", asset["browser_download_url"]) as file_res:
        if file_res.status_code >= 400:
            raise RuntimeError("Failed to download file from GitHub!")
        with open(file_path, "wb") as f:
            async for chunk in file_res.aiter_content():
                f.write(chunk)

    downloaded_size = Path(file_path).stat().st_size
    if downloaded_size < 1024:
        raise RuntimeError(f"Downloaded file is too small ({downloaded_size} bytes) - likely an error page")

    log.success(f"Done: {file_path}")
    return str(file_path)


async def download_apk(version: str, app_slug: str, source: GithubAppSite) -> str:
    owner = source["owner"]
    repo = source["repo"]
    name_hint = source.get("asset_hint")
    tag_template = source.get("tag_template") or "{version}"

    async with new_session(timeout=30, follow_redirects=True) as client:
        release_data = None
        wanted_tag = None

        if version and version != "latest":
            wanted_tag = _build_tag(tag_template, version)
            log.step(f"Fetching info from GitHub: {app_slug.upper()} ({owner}/{repo}, tag: {wanted_tag})")

            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{wanted_tag}"
            res = await client.get(api_url, headers=_headers())
            if res.status_code < 400:
                release_data = res.json()
            else:
                log.warn(f'Tag "{wanted_tag}" not found ({res.status_code}), falling back to latest release.')

        if release_data is None:
            log.step(f"Fetching info from GitHub: {app_slug.upper()} ({owner}/{repo}, latest release)")
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
            res = await client.get(api_url, headers=_headers())
            if res.status_code >= 400:
                raise RuntimeError(f"GitHub API error: {res.status_code}")
            release_data = res.json()

        asset = _pick_apk_asset(release_data.get("assets") or [], name_hint)
        if not asset:
            where = wanted_tag or "latest release"
            raise RuntimeError(f'No .apk or .apkm file found in "{owner}/{repo}" ({where}).')

        return await _download_asset(client, asset)


async def get_latest_listing(app_slug: str, source: GithubAppSite) -> dict:
    return {"version": "latest", "href": f"https://github.com/{source['owner']}/{source['repo']}/releases/latest"}
