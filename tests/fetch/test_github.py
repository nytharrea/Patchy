import pytest

from patchy.fetch import github


def test_build_tag_formats_template_when_version_lacks_the_prefix():
    assert github._build_tag("build{version}", "123") == "build123"


def test_build_tag_passes_version_through_when_already_prefixed():
    assert github._build_tag("build{version}", "build123") == "build123"


def test_build_tag_with_no_prefix_template():
    assert github._build_tag("{version}", "7.4.0") == "7.4.0"


def test_pick_apk_asset_prefers_hinted_name():
    assets = [
        {"name": "Inure-play-arm64-v8a.apk", "size": 100},
        {"name": "Inure-github-arm64-v8a.apk", "size": 100},
    ]
    assert github._pick_apk_asset(assets, "github")["name"] == "Inure-github-arm64-v8a.apk"


def test_pick_apk_asset_prefers_arm64_among_hinted_candidates():
    assets = [
        {"name": "Inure-github-armeabi-v7a.apk", "size": 90},
        {"name": "Inure-github-arm64-v8a.apk", "size": 100},
        {"name": "Inure-play-arm64-v8a.apk", "size": 100},
    ]
    assert github._pick_apk_asset(assets, "github")["name"] == "Inure-github-arm64-v8a.apk"


def test_pick_apk_asset_falls_back_to_unhinted_when_hint_matches_nothing():
    assets = [{"name": "SomeOtherApp-arm64-v8a.apk", "size": 100}]
    assert github._pick_apk_asset(assets, "github")["name"] == "SomeOtherApp-arm64-v8a.apk"


def test_pick_apk_asset_ignores_non_apk_assets():
    assets = [{"name": "source.zip", "size": 10}, {"name": "checksums.txt", "size": 1}]
    assert github._pick_apk_asset(assets) is None


def test_pick_apk_asset_accepts_apkm_extension():
    assets = [{"name": "bundle.apkm", "size": 500}]
    assert github._pick_apk_asset(assets)["name"] == "bundle.apkm"


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        return self._responses.pop(0)


SOURCE = {"owner": "Hamza417", "repo": "Inure", "asset_hint": "github", "tag_template": "build{version}"}


async def test_download_apk_uses_the_matching_tag_when_found(monkeypatch, tmp_path):
    tag_response = _FakeResponse(
        200,
        {"assets": [{"name": "Inure-github-arm64-v8a.apk", "size": 2000, "browser_download_url": "https://x"}]},
    )
    monkeypatch.setattr(github, "new_session", lambda **kw: _FakeSession([tag_response]))

    async def fake_download_asset(client, asset):
        return str(tmp_path / asset["name"])

    monkeypatch.setattr(github, "_download_asset", fake_download_asset)

    result = await github.download_apk("123", "inure-github", SOURCE)
    assert result == str(tmp_path / "Inure-github-arm64-v8a.apk")


async def test_download_apk_falls_back_to_latest_when_tag_not_found(monkeypatch):
    tag_missing = _FakeResponse(404)
    latest_ok = _FakeResponse(
        200,
        {"assets": [{"name": "Inure-github-arm64-v8a.apk", "size": 2000, "browser_download_url": "https://x"}]},
    )
    monkeypatch.setattr(github, "new_session", lambda **kw: _FakeSession([tag_missing, latest_ok]))

    async def fake_download_asset(client, asset):
        return "downloaded"

    monkeypatch.setattr(github, "_download_asset", fake_download_asset)

    assert await github.download_apk("999", "inure-github", SOURCE) == "downloaded"


async def test_download_apk_raises_when_latest_release_api_call_fails(monkeypatch):
    monkeypatch.setattr(github, "new_session", lambda **kw: _FakeSession([_FakeResponse(500)]))
    with pytest.raises(RuntimeError, match="GitHub API error"):
        await github.download_apk("latest", "inure-github", SOURCE)


async def test_download_apk_raises_when_no_matching_asset_in_release(monkeypatch):
    empty_release = _FakeResponse(200, {"assets": [{"name": "source.zip", "size": 10}]})
    monkeypatch.setattr(github, "new_session", lambda **kw: _FakeSession([empty_release]))
    with pytest.raises(RuntimeError, match="No .apk or .apkm file found"):
        await github.download_apk("latest", "inure-github", SOURCE)


async def test_get_latest_listing_builds_releases_url():
    result = await github.get_latest_listing("inure-github", SOURCE)
    assert result == {"version": "latest", "href": "https://github.com/Hamza417/Inure/releases/latest"}


def _release(tag, *assets, draft=False):
    return {"tag_name": tag, "draft": draft, "assets": [{"name": name} for name in assets]}


def _is_patch_bundle(name):
    return name.endswith(".mpp")


def _releases():
    return [
        _release("theme-previews-v1", "theme-previews-v1.zip", "theme-previews-v1-manifest.json"),
        _release("v3.10.0", "patches-3.10.0.mpp"),
        _release("v3.9.0", "patches-3.9.0.mpp"),
    ]


def test_select_release_skips_newest_release_without_patch_bundle():
    release = github._select_release(_releases(), _is_patch_bundle)
    assert release is not None
    assert release["tag_name"] == "v3.10.0"


def test_select_release_prefers_newest_release_that_has_a_patch_bundle():
    releases = [_release("v4.0.0-dev.1", "patches-4.0.0-dev.1.mpp"), *_releases()]
    release = github._select_release(releases, _is_patch_bundle)
    assert release is not None
    assert release["tag_name"] == "v4.0.0-dev.1"


def test_select_release_skips_drafts():
    releases = [_release("v9.9.9", "patches-9.9.9.mpp", draft=True), *_releases()]
    release = github._select_release(releases, _is_patch_bundle)
    assert release is not None
    assert release["tag_name"] == "v3.10.0"


def test_select_release_returns_none_when_nothing_matches():
    assert github._select_release(_releases()[:1], _is_patch_bundle) is None


def test_select_release_without_matcher_returns_first_published_release():
    releases = [_release("v9.9.9", draft=True), *_releases()]
    release = github._select_release(releases)
    assert release is not None
    assert release["tag_name"] == "theme-previews-v1"


class _ReleasesSession:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(200, self._payload)


async def test_fetch_latest_release_prerelease_returns_release_with_patch_bundle(monkeypatch):
    monkeypatch.setattr(github, "new_session", lambda **kwargs: _ReleasesSession(_releases()))
    release = await github.fetch_latest_release("owner", "repo", True, _is_patch_bundle)
    assert release["tag_name"] == "v3.10.0"


async def test_fetch_latest_release_prerelease_raises_when_no_release_has_patch_bundle(monkeypatch):
    monkeypatch.setattr(github, "new_session", lambda **kwargs: _ReleasesSession(_releases()[:1]))
    with pytest.raises(RuntimeError, match="owner/repo"):
        await github.fetch_latest_release("owner", "repo", True, _is_patch_bundle)


def _asset_payload(size=2000):
    return {
        "tag_name": "v1.0.0",
        "body": "release notes",
        "prerelease": True,
        "assets": [{"name": "patches-1.0.0.mpp", "size": size, "browser_download_url": "https://x/patches.mpp"}],
    }


async def test_download_latest_release_asset_returns_tag_body_and_path(monkeypatch, tmp_path):
    async def fake_fetch(owner, repo, prerelease, match):
        return _asset_payload()

    async def fake_download(url, output_path, expected_size=None):
        output_path.write_bytes(b"x" * 2000)
        return str(output_path)

    monkeypatch.setattr(github, "fetch_latest_release", fake_fetch)
    monkeypatch.setattr(github, "_download_file", fake_download)

    result = await github.download_latest_release_asset("owner", "repo", _is_patch_bundle, True, tmp_path)

    assert result["name"] == "patches-1.0.0.mpp"
    assert result["path"] == str(tmp_path / "patches-1.0.0.mpp")
    assert result["tag"] == "v1.0.0"
    assert result["body"] == "release notes"
    assert result["prerelease"] is True


async def test_download_latest_release_asset_reuses_a_complete_cached_file(monkeypatch, tmp_path):
    (tmp_path / "patches-1.0.0.mpp").write_bytes(b"x" * 2000)

    async def fake_fetch(owner, repo, prerelease, match):
        return _asset_payload(size=2000)

    async def fake_download(*args, **kwargs):
        raise AssertionError("a complete cached file must not be downloaded again")

    monkeypatch.setattr(github, "fetch_latest_release", fake_fetch)
    monkeypatch.setattr(github, "_download_file", fake_download)

    result = await github.download_latest_release_asset("owner", "repo", _is_patch_bundle, True, tmp_path)
    assert result["path"] == str(tmp_path / "patches-1.0.0.mpp")


async def test_download_latest_release_asset_replaces_a_cached_file_with_the_wrong_size(monkeypatch, tmp_path):
    (tmp_path / "patches-1.0.0.mpp").write_bytes(b"x" * 1500)

    async def fake_fetch(owner, repo, prerelease, match):
        return _asset_payload(size=2000)

    downloads = []

    async def fake_download(url, output_path, expected_size=None):
        downloads.append(url)
        output_path.write_bytes(b"y" * 2000)
        return str(output_path)

    monkeypatch.setattr(github, "fetch_latest_release", fake_fetch)
    monkeypatch.setattr(github, "_download_file", fake_download)

    await github.download_latest_release_asset("owner", "repo", _is_patch_bundle, True, tmp_path)

    assert downloads == ["https://x/patches.mpp"]
    assert (tmp_path / "patches-1.0.0.mpp").stat().st_size == 2000
