import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from patchy import catalog
from patchy.engine import build, label
from patchy.engine.verify import SignatureError, UnpinnedSignature
from patchy.fetch import apkmirror, github
from patchy.fetch.bundles import Tools

from .axml import apk_labels, build_apk, build_manifest, reference_label, text_label

FINGERPRINT = "3d7a1223019aa39d9ea0e3436ab7c0896bfb4fb679f4de5fe7c23f326c8f994a"


def _fake_build(app_slug: str, source: dict, force_version: str | None = "1.2.3") -> dict:
    return {
        "key": app_slug,
        "app_slug": app_slug,
        "pkg": f"com.example.{app_slug}",
        "display_name": app_slug.title(),
        "label": None,
        "arch": "arm64-v8a",
        "icon": "https://example.com/icon.png",
        "apk_source": source,
        "bundles": ["some-source"],
        "exclude": [],
        "enable": [],
        "options": {},
        "force_version": force_version,
        "force_build": None,
    }


def _common_mocks(monkeypatch, tmp_path, apk_source: dict, force_version: str | None = "1.2.3"):
    build_key = "the-app"
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path / "build"))
    monkeypatch.setattr(catalog, "BUILDS", {build_key: _fake_build(build_key, apk_source, force_version)})
    monkeypatch.setattr(catalog, "BUNDLES", {"some-source": {"owner": "acme", "repo": "patches", "label": "x"}})
    monkeypatch.setattr(build.catalog, "get_release_naming", lambda key: ("The App", None))

    async def fake_verify(apk_path, app_slug):
        return None

    monkeypatch.setattr(build, "verify_apk_signature", fake_verify)

    patched_apk = tmp_path / "patched.apk"
    patched_apk.write_bytes(b"fake patched apk")

    async def fake_patch(*a, **kw):
        return str(patched_apk)

    monkeypatch.setattr(build, "patch_apk", fake_patch)

    async def fake_list_versions(cli_jar, bundles, pkg):
        return None

    monkeypatch.setattr(build, "list_versions", fake_list_versions)
    return build_key


def _list_versions_returns(monkeypatch, output):
    calls = []

    async def fake_list_versions(cli_jar, bundles, pkg):
        calls.append((str(cli_jar), [str(b) for b in bundles], pkg))
        return output

    monkeypatch.setattr(build, "list_versions", fake_list_versions)
    return calls


async def test_process_build_calls_apkmirror_fetcher_for_an_apkmirror_source(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    calls = []

    async def fake_apkmirror_download(version, app_slug, source, force_build, **kwargs):
        calls.append(("apkmirror", version, app_slug, source))
        return str(tmp_path / "downloaded.apk")

    async def fake_github_download(*a, **kw):
        raise AssertionError("github.download_apk should not be called for an apkmirror source")

    monkeypatch.setattr(apkmirror, "download_apk", fake_apkmirror_download)
    monkeypatch.setattr(github, "download_apk", fake_github_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert calls == [("apkmirror", "1.2.3", build_key, apk_source)]


async def test_process_build_calls_github_fetcher_for_a_github_source(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    calls = []

    async def fake_github_download(version, app_slug, source):
        calls.append(("github", version, app_slug, source))
        return str(tmp_path / "downloaded.apk")

    async def fake_apkmirror_download(*a, **kw):
        raise AssertionError("apkmirror.download_apk should not be called for a github source")

    monkeypatch.setattr(github, "download_apk", fake_github_download)
    monkeypatch.setattr(apkmirror, "download_apk", fake_apkmirror_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert calls == [("github", "1.2.3", build_key, apk_source)]


async def test_process_build_verifies_the_downloaded_apk_before_patching(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    order = []

    async def fake_download(version, app_slug, source):
        order.append("download")
        return str(tmp_path / "downloaded.apk")

    async def fake_verify(apk_path, app_slug):
        order.append(f"verify:{apk_path}:{app_slug}")

    async def fake_patch(*a, **kw):
        order.append("patch")
        return str(tmp_path / "patched.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)
    monkeypatch.setattr(build, "verify_apk_signature", fake_verify)
    monkeypatch.setattr(build, "patch_apk", fake_patch)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert order == ["download", f"verify:{tmp_path / 'downloaded.apk'}:{build_key}", "patch"]


async def test_process_build_does_not_patch_an_apk_that_fails_verification(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    async def failing_verify(apk_path, app_slug):
        raise SignatureError("SIGNATURE MISMATCH")

    async def fake_patch(*a, **kw):
        raise AssertionError("must not patch an unverified APK")

    monkeypatch.setattr(github, "download_apk", fake_download)
    monkeypatch.setattr(build, "verify_apk_signature", failing_verify)
    monkeypatch.setattr(build, "patch_apk", fake_patch)

    with pytest.raises(SignatureError):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])


async def test_process_build_writes_the_unsigned_apk_into_the_out_directory(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    expected = tmp_path / "build" / "out" / "The App-1.2.3.apk"
    assert result["path"] == str(expected)
    assert result["name"] == "The App-1.2.3.apk"
    assert result["version"] == "1.2.3"
    assert expected.read_bytes() == b"fake patched apk"


async def test_process_build_adds_the_disambiguating_suffix_to_the_file_name(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    monkeypatch.setattr(build.catalog, "get_release_naming", lambda key: ("The App", "acme"))

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result["name"] == "The App-1.2.3-acme.apk"


async def test_process_build_keeps_spaces_around_a_version_channel_out_of_the_file_name(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version="348.10 - Stable")

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result["name"] == "The App-348.10-Stable.apk"
    assert result["version"] == "348.10 - Stable"
    assert (tmp_path / "build" / "out" / "The App-348.10-Stable.apk").is_file()


async def test_process_build_returns_none_when_patch_apk_did_not_produce_a_file(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)

    async def fake_download(*a, **kw):
        return str(tmp_path / "downloaded.apk")

    async def fake_patch(*a, **kw):
        return str(tmp_path / "never-written.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)
    monkeypatch.setattr(build, "patch_apk", fake_patch)

    assert await build.process_build(build_key, "desktop.jar", ["patch1.mpp"]) is None


GITHUB_SOURCE = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
BROKEN_NAME = text_label("@string/four_ones")
WORKING_NAME = reference_label(0x7F130012)


def _patched_apk_with(monkeypatch, tmp_path, manifest, app_label=None):
    build_key = _common_mocks(monkeypatch, tmp_path, GITHUB_SOURCE)
    catalog.BUILDS[build_key]["label"] = app_label
    patched = build_apk(tmp_path / "patched.apk", manifest)

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)
    return build_key, patched


async def test_process_build_repairs_an_app_name_the_patcher_left_as_reference_text(monkeypatch, tmp_path):
    build_key, _ = _patched_apk_with(monkeypatch, tmp_path, build_manifest(BROKEN_NAME))

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert apk_labels(Path(result["path"]))[0] == ("application", label.TYPE_STRING, "The App")


async def test_process_build_gives_the_app_the_label_configured_for_the_build(monkeypatch, tmp_path):
    manifest = build_manifest(WORKING_NAME, launcher=WORKING_NAME)
    build_key, _ = _patched_apk_with(monkeypatch, tmp_path, manifest, app_label="1.1.1.1")

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert apk_labels(Path(result["path"])) == [
        ("application", label.TYPE_STRING, "1.1.1.1"),
        ("activity", label.TYPE_STRING, "1.1.1.1"),
        ("activity", label.TYPE_STRING, "Other"),
    ]


async def test_process_build_does_not_touch_an_apk_whose_app_name_is_fine(monkeypatch, tmp_path):
    build_key, patched = _patched_apk_with(monkeypatch, tmp_path, build_manifest(WORKING_NAME))

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert Path(result["path"]).read_bytes() == patched.read_bytes()


async def test_process_build_leaves_the_output_of_the_patcher_as_it_was(monkeypatch, tmp_path):
    build_key, patched = _patched_apk_with(monkeypatch, tmp_path, build_manifest(BROKEN_NAME))
    before = patched.read_bytes()

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert patched.read_bytes() == before
    assert Path(result["path"]).read_bytes() != before


async def test_process_build_goes_on_when_the_apk_cannot_be_examined(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, GITHUB_SOURCE)
    warnings = []
    monkeypatch.setattr(build.log, "warn", warnings.append)

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result["name"] == "The App-1.2.3.apk"
    assert Path(result["path"]).read_bytes() == b"fake patched apk"
    assert any("app name" in line and "The App-1.2.3.apk" in line for line in warnings)


async def test_process_build_goes_on_when_the_app_name_step_crashes(monkeypatch, tmp_path):
    build_key, patched = _patched_apk_with(monkeypatch, tmp_path, build_manifest(BROKEN_NAME))
    warnings = []
    monkeypatch.setattr(build.log, "warn", warnings.append)

    def crashing(apk, app_label, fallback):
        raise RuntimeError("boom")

    monkeypatch.setattr(build, "fix_apk_label", crashing)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert Path(result["path"]).read_bytes() == patched.read_bytes()
    assert any("boom" in line for line in warnings)


async def test_process_build_warns_when_the_configured_label_has_nothing_to_replace(monkeypatch, tmp_path):
    manifest = build_manifest(None, launcher=None)
    build_key, patched = _patched_apk_with(monkeypatch, tmp_path, manifest, app_label="1.1.1.1")
    warnings = []
    monkeypatch.setattr(build.log, "warn", warnings.append)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert Path(result["path"]).read_bytes() == patched.read_bytes()
    assert any("no android:label" in line for line in warnings)


async def test_process_build_falls_through_to_latest_for_github_without_version_data(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    ran = _list_versions_returns(monkeypatch, "Nothing useful here.\n")
    calls = []

    async def fake_download(version, app_slug, source):
        calls.append(version)
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert len(ran) == 1
    assert calls == ["latest"]


async def test_process_build_prefers_a_patch_recommended_version_for_a_github_source(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, "Most common compatible versions:\n9.9.9 (3 patches)\n\n")
    calls = []

    async def fake_download(version, app_slug, source):
        calls.append(version)
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert calls == ["9.9.9"]


async def test_process_build_runs_list_versions_for_an_apkmirror_source(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    ran = _list_versions_returns(monkeypatch, "Most common compatible versions:\n9.9.9 (3 patches)\n\n")
    calls = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        calls.append(version)
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert len(ran) == 1
    assert ran[0][2] == "com.example.the-app"
    assert calls == ["9.9.9"]


async def test_process_build_falls_back_to_the_apkmirror_listing_without_cli_versions(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, None)
    calls = []

    async def fake_listing(app_slug, source):
        return {"version": "5.5.5", "href": "/x"}

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        calls.append(version)
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "get_latest_listing", fake_listing)
    monkeypatch.setattr(apkmirror, "download_apk", fake_download)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == ["5.5.5"]


VERSIONS_WITH_CODES = (
    "Package name: com.example.the-app\n"
    "Most common compatible versions:\n"
    "\t9.9.9 [versionCodes: ARM64_V8A=990, ARMEABI_V7A=991] (3 patches)\n"
    "\t8.8.8 [versionCodes: ARM64_V8A=880] (2 patches)\n\n"
)


def _record_apkmirror_downloads(monkeypatch, tmp_path):
    calls = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        calls.append((version, kwargs))
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)
    return calls


async def test_process_build_hands_the_build_codes_of_the_chosen_version_to_the_apkmirror_fetcher(
    monkeypatch, tmp_path
):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == [("9.9.9", {"arch": "arm64-v8a", "build_codes": {"ARM64_V8A": 990, "ARMEABI_V7A": 991}})]


async def test_process_build_passes_the_arch_of_the_build(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    catalog.BUILDS[build_key]["arch"] = "armeabi-v7a"
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls[0][1]["arch"] == "armeabi-v7a"


async def test_process_build_passes_no_build_codes_when_the_bundle_declares_none(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, "Most common compatible versions:\n9.9.9 (3 patches)\n\n")
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == [("9.9.9", {"arch": "arm64-v8a", "build_codes": {}})]


async def test_process_build_passes_no_build_codes_without_cli_versions(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, None)
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    async def fake_listing(app_slug, source):
        return {"version": "9.9.9", "href": "/x"}

    monkeypatch.setattr(apkmirror, "get_latest_listing", fake_listing)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == [("9.9.9", {"arch": "arm64-v8a", "build_codes": {}})]


NO_BUILD_CODES = "Most common compatible versions:\n9.9.9 (3 patches)\n\n"


def _rejecting_patch(monkeypatch, tmp_path, *, rejections):
    patched = []

    async def fake_patch(cli_jar, bundles, apk, **kwargs):
        patched.append(apk)
        if len(patched) <= rejections:
            raise build.UnsupportedBuild("Patch failed (exit 1)", 990, frozenset({880, 881}))
        return str(tmp_path / "patched.apk")

    monkeypatch.setattr(build, "patch_apk", fake_patch)
    return patched


def _numbered_apkmirror_downloads(monkeypatch, tmp_path):
    downloads = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        downloads.append({"force_build": force_build, **kwargs})
        return str(tmp_path / f"downloaded-{len(downloads)}.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)
    return downloads


async def test_process_build_fetches_a_build_the_patch_accepts_when_it_rejects_the_first_one(
    monkeypatch, tmp_path
):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, NO_BUILD_CODES)
    downloads = _numbered_apkmirror_downloads(monkeypatch, tmp_path)
    patched = _rejecting_patch(monkeypatch, tmp_path, rejections=1)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert downloads == [
        {"force_build": None, "arch": "arm64-v8a", "build_codes": {}},
        {"force_build": None, "arch": "arm64-v8a", "build_codes": {}, "accepted_codes": frozenset({880, 881})},
    ]
    assert patched == [str(tmp_path / "downloaded-1.apk"), str(tmp_path / "downloaded-2.apk")]


async def test_process_build_asks_for_the_same_version_again(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    versions = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        versions.append((version, kwargs["build_codes"]))
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)
    _rejecting_patch(monkeypatch, tmp_path, rejections=1)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert versions == [("9.9.9", {"ARM64_V8A": 990, "ARMEABI_V7A": 991})] * 2


async def test_process_build_keeps_the_force_build_pin_when_it_asks_for_another_build(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    catalog.BUILDS[build_key]["force_build"] = "240-640dpi"
    _list_versions_returns(monkeypatch, NO_BUILD_CODES)
    downloads = _numbered_apkmirror_downloads(monkeypatch, tmp_path)
    _rejecting_patch(monkeypatch, tmp_path, rejections=1)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert [download["force_build"] for download in downloads] == ["240-640dpi", "240-640dpi"]


async def test_process_build_verifies_the_replacement_apk_before_patching_it(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, NO_BUILD_CODES)
    order = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        order.append("download")
        return str(tmp_path / f"downloaded-{order.count('download')}.apk")

    async def fake_verify(apk_path, app_slug):
        order.append(f"verify:{apk_path.rsplit('/', 1)[-1]}")

    async def fake_patch(cli_jar, bundles, apk, **kwargs):
        order.append(f"patch:{apk.rsplit('/', 1)[-1]}")
        if order.count("download") == 1:
            raise build.UnsupportedBuild("Patch failed (exit 1)", 990, frozenset({880}))
        return str(tmp_path / "patched.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)
    monkeypatch.setattr(build, "verify_apk_signature", fake_verify)
    monkeypatch.setattr(build, "patch_apk", fake_patch)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert order == [
        "download",
        "verify:downloaded-1.apk",
        "patch:downloaded-1.apk",
        "download",
        "verify:downloaded-2.apk",
        "patch:downloaded-2.apk",
    ]


async def test_process_build_does_not_ask_for_a_third_build(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, NO_BUILD_CODES)
    downloads = _numbered_apkmirror_downloads(monkeypatch, tmp_path)
    patched = _rejecting_patch(monkeypatch, tmp_path, rejections=2)

    with pytest.raises(build.UnsupportedBuild):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert len(downloads) == 2
    assert len(patched) == 2


async def test_process_build_does_not_refetch_after_a_failure_that_is_not_a_rejected_build(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, NO_BUILD_CODES)
    downloads = _numbered_apkmirror_downloads(monkeypatch, tmp_path)

    async def fake_patch(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(build, "patch_apk", fake_patch)

    with pytest.raises(RuntimeError, match="boom"):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert len(downloads) == 1


async def test_process_build_does_not_look_for_another_build_of_a_github_apk(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    downloads = []

    async def fake_github_download(version, app_slug, source):
        downloads.append(version)
        return str(tmp_path / "downloaded.apk")

    async def fake_apkmirror_download(*a, **kw):
        raise AssertionError("apkmirror.download_apk should not be called for a github source")

    monkeypatch.setattr(github, "download_apk", fake_github_download)
    monkeypatch.setattr(apkmirror, "download_apk", fake_apkmirror_download)
    _rejecting_patch(monkeypatch, tmp_path, rejections=1)

    with pytest.raises(build.UnsupportedBuild):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert downloads == ["1.2.3"]


FOUR_SUPPORTED_VERSIONS = (
    "Most common compatible versions:\n"
    "\t9.9.9 (3 patches)\n"
    "\t8.8.8 (3 patches)\n"
    "\t7.7.7 (3 patches)\n"
    "\t6.6.6 (3 patches)\n\n"
)


def _apkmirror_without_pages_for(monkeypatch, tmp_path, missing):
    calls = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        calls.append((version, kwargs))
        if version in missing:
            raise apkmirror.ReleaseNotFound(f"No APKMirror release page found for version {version}")
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)
    return calls


async def test_process_build_moves_on_to_the_next_supported_version_when_apkmirror_has_no_page(
    monkeypatch, tmp_path
):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _apkmirror_without_pages_for(monkeypatch, tmp_path, missing={"9.9.9"})
    warnings = []
    monkeypatch.setattr(build.log, "warn", warnings.append)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result["version"] == "8.8.8"
    assert result["name"] == "The App-8.8.8.apk"
    assert calls == [
        ("9.9.9", {"arch": "arm64-v8a", "build_codes": {"ARM64_V8A": 990, "ARMEABI_V7A": 991}}),
        ("8.8.8", {"arch": "arm64-v8a", "build_codes": {"ARM64_V8A": 880}}),
    ]
    assert any("version 9.9.9" in line and "Trying 8.8.8" in line for line in warnings)


async def test_process_build_does_not_move_to_another_version_when_the_version_is_pinned(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version="9.9.9")
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _apkmirror_without_pages_for(monkeypatch, tmp_path, missing={"9.9.9"})

    with pytest.raises(apkmirror.ReleaseNotFound, match="9.9.9"):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert [version for version, _ in calls] == ["9.9.9"]


async def test_process_build_fails_with_the_last_version_it_tried_when_none_has_a_page(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _apkmirror_without_pages_for(monkeypatch, tmp_path, missing={"9.9.9", "8.8.8"})

    with pytest.raises(apkmirror.ReleaseNotFound, match="8.8.8"):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert [version for version, _ in calls] == ["9.9.9", "8.8.8"]


async def test_process_build_tries_at_most_three_versions(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, FOUR_SUPPORTED_VERSIONS)
    calls = _apkmirror_without_pages_for(monkeypatch, tmp_path, missing={"9.9.9", "8.8.8", "7.7.7", "6.6.6"})

    with pytest.raises(apkmirror.ReleaseNotFound, match="7.7.7"):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert [version for version, _ in calls] == ["9.9.9", "8.8.8", "7.7.7"]


async def test_process_build_does_not_try_another_version_after_a_different_download_error(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = []

    async def fake_download(version, app_slug, source, force_build, **kwargs):
        calls.append(version)
        raise RuntimeError("Download did not start / file not detected.")

    monkeypatch.setattr(apkmirror, "download_apk", fake_download)

    with pytest.raises(RuntimeError, match="Download did not start"):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == ["9.9.9"]


async def test_process_build_looks_up_the_build_codes_of_a_pinned_apkmirror_version(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version="8.8.8")
    ran = _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert len(ran) == 1
    assert result["version"] == "8.8.8"
    assert calls == [("8.8.8", {"arch": "arm64-v8a", "build_codes": {"ARM64_V8A": 880}})]


async def test_process_build_keeps_the_pinned_version_when_the_cli_does_not_list_it(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version="1.2.3")
    _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == [("1.2.3", {"arch": "arm64-v8a", "build_codes": {}})]


async def test_process_build_goes_on_without_build_codes_when_the_pinned_lookup_fails(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version="1.2.3")
    monkeypatch.setattr(build.log, "warn", lambda msg: None)

    async def exploding(cli_jar, bundles, pkg):
        raise OSError("java is missing")

    monkeypatch.setattr(build, "list_versions", exploding)
    calls = _record_apkmirror_downloads(monkeypatch, tmp_path)

    result = await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert result is not None
    assert calls == [("1.2.3", {"arch": "arm64-v8a", "build_codes": {}})]


async def test_process_build_does_not_ask_the_cli_about_a_pinned_github_version(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version="1.2.3")
    ran = _list_versions_returns(monkeypatch, VERSIONS_WITH_CODES)

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert ran == []


async def test_process_build_survives_a_list_versions_crash(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    monkeypatch.setattr(build.log, "warn", lambda msg: None)

    async def exploding(cli_jar, bundles, pkg):
        raise OSError("java is missing")

    calls = []

    async def fake_download(version, app_slug, source):
        calls.append(version)
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(build, "list_versions", exploding)
    monkeypatch.setattr(github, "download_apk", fake_download)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == ["latest"]


def _status(tmp_path, build_key):
    return json.loads((tmp_path / "build" / "out" / f"status-{build_key}.json").read_text())


def _tools(tmp_path):
    cli = tmp_path / "cli.jar"
    bundle = tmp_path / "some.mpp"
    return Tools(cli=cli, bundles={"some-source": bundle})


async def test_run_builds_records_a_successful_status(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})

    async def fake_process(key, cli_jar, bundle_paths):
        return {"name": "The App-1.2.3.apk", "version": "1.2.3"}

    monkeypatch.setattr(build, "process_build", fake_process)

    failed = await build.run_builds([build_key], _tools(tmp_path))

    assert failed == []
    status = _status(tmp_path, build_key)
    assert status["ok"] is True
    assert status["error"] is None
    assert status["file"] == "The App-1.2.3.apk"
    assert status["version"] == "1.2.3"


async def test_run_builds_records_the_error_of_a_failed_build(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})

    async def fake_process(key, cli_jar, bundle_paths):
        raise RuntimeError("HTTP 500 fetching listing page")

    monkeypatch.setattr(build, "process_build", fake_process)

    failed = await build.run_builds([build_key], _tools(tmp_path))

    assert failed == [build_key]
    status = _status(tmp_path, build_key)
    assert status["ok"] is False
    assert status["error"] == "HTTP 500 fetching listing page"
    assert status["pending_pin"] is None


async def test_run_builds_hands_an_unpinned_fingerprint_to_the_release_job_through_the_status_file(
    monkeypatch, tmp_path
):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})

    async def fake_process(key, cli_jar, bundle_paths):
        raise UnpinnedSignature("the-app", FINGERPRINT)

    monkeypatch.setattr(build, "process_build", fake_process)

    failed = await build.run_builds([build_key], _tools(tmp_path))

    assert failed == [build_key]
    status = _status(tmp_path, build_key)
    assert status["ok"] is False
    assert "No pinned signature" in status["error"]
    assert status["pending_pin"] == {"app": "the-app", "sha256": FINGERPRINT}


async def test_run_builds_records_a_missing_output_as_a_failure(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})

    async def fake_process(key, cli_jar, bundle_paths):
        return None

    monkeypatch.setattr(build, "process_build", fake_process)

    assert await build.run_builds([build_key], _tools(tmp_path)) == [build_key]
    assert "no output file" in _status(tmp_path, build_key)["error"]


async def test_run_builds_hands_each_build_its_own_bundle_files(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})
    seen = []

    async def fake_process(key, cli_jar, bundle_paths):
        seen.append((key, cli_jar, list(bundle_paths)))
        return {"name": "x.apk", "version": "1"}

    monkeypatch.setattr(build, "process_build", fake_process)
    tools = _tools(tmp_path)

    await build.run_builds([build_key], tools)

    assert seen == [(build_key, tools.cli, [tools.bundles["some-source"]])]


async def test_run_builds_fails_a_build_whose_bundle_was_not_fetched(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})
    tools = Tools(cli=tmp_path / "cli.jar", bundles={})

    assert await build.run_builds([build_key], tools) == [build_key]
    assert "some-source" in _status(tmp_path, build_key)["error"]


async def test_run_builds_pauses_between_apkmirror_builds_but_not_after_the_last(monkeypatch, tmp_path):
    _common_mocks(monkeypatch, tmp_path, {"type": "apkmirror", "org": "a", "slug": "b"})
    monkeypatch.setattr(
        catalog,
        "BUILDS",
        {
            "one": _fake_build("one", {"type": "apkmirror", "org": "a", "slug": "b"}),
            "two": _fake_build("two", {"type": "apkmirror", "org": "a", "slug": "b"}),
        },
    )
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def fake_process(key, cli_jar, bundle_paths):
        return {"name": f"{key}.apk", "version": "1"}

    monkeypatch.setattr(build, "asyncio", SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(build, "process_build", fake_process)

    await build.run_builds(["one", "two"], _tools(tmp_path))

    assert len(sleeps) == 1
    assert 6.0 <= sleeps[0] <= 14.0


class _TickingClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 1.0
        return self.now


async def test_process_build_times_every_stage(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    monkeypatch.setattr(build.log, "time", _TickingClock())

    async def fake_download(version, app_slug, source):
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(github, "download_apk", fake_download)

    with build.log.collect_timings() as timings:
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert timings == {"select": 1.0, "download": 1.0, "verify": 1.0, "patch": 1.0}


async def test_process_build_still_times_a_download_that_fails(monkeypatch, tmp_path):
    apk_source = {"type": "github", "owner": "acme-inc", "repo": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source)
    monkeypatch.setattr(build.log, "time", _TickingClock())

    async def failing_download(version, app_slug, source):
        raise RuntimeError("HTTP 403")

    monkeypatch.setattr(github, "download_apk", failing_download)

    with build.log.collect_timings() as timings, pytest.raises(RuntimeError, match="HTTP 403"):
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert timings == {"select": 1.0, "download": 1.0}


async def test_process_build_adds_the_refetch_of_a_rejected_build_to_the_stage_times(monkeypatch, tmp_path):
    apk_source = {"type": "apkmirror", "org": "acme-inc", "slug": "acme-app"}
    build_key = _common_mocks(monkeypatch, tmp_path, apk_source, force_version=None)
    _list_versions_returns(monkeypatch, NO_BUILD_CODES)
    monkeypatch.setattr(build.log, "time", _TickingClock())
    _numbered_apkmirror_downloads(monkeypatch, tmp_path)
    _rejecting_patch(monkeypatch, tmp_path, rejections=1)

    with build.log.collect_timings() as timings:
        await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert timings == {"select": 1.0, "download": 2.0, "verify": 2.0, "patch": 2.0}


async def test_run_builds_records_the_stage_times_and_the_total(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})
    clock = _TickingClock()
    monkeypatch.setattr(build, "time", clock)
    monkeypatch.setattr(build.log, "time", clock)

    async def fake_process(key, cli_jar, bundle_paths):
        with build.log.timed("download"):
            pass
        with build.log.timed("patch"):
            pass
        return {"name": "The App-1.2.3.apk", "version": "1.2.3"}

    monkeypatch.setattr(build, "process_build", fake_process)

    assert await build.run_builds([build_key], _tools(tmp_path)) == []

    assert _status(tmp_path, build_key)["timings"] == {"download": 1.0, "patch": 1.0, "total": 5.0}


async def test_run_builds_keeps_the_times_of_a_build_that_failed_midway(monkeypatch, tmp_path):
    build_key = _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})
    clock = _TickingClock()
    monkeypatch.setattr(build, "time", clock)
    monkeypatch.setattr(build.log, "time", clock)

    async def fake_process(key, cli_jar, bundle_paths):
        with build.log.timed("download"):
            raise RuntimeError("HTTP 503")

    monkeypatch.setattr(build, "process_build", fake_process)

    assert await build.run_builds([build_key], _tools(tmp_path)) == [build_key]

    status = _status(tmp_path, build_key)
    assert status["ok"] is False
    assert status["timings"] == {"download": 1.0, "total": 3.0}


async def test_run_builds_gives_every_build_its_own_timings(monkeypatch, tmp_path):
    _common_mocks(monkeypatch, tmp_path, {"type": "github", "owner": "a", "repo": "b"})
    monkeypatch.setattr(
        catalog,
        "BUILDS",
        {
            "one": _fake_build("one", {"type": "github", "owner": "a", "repo": "b"}),
            "two": _fake_build("two", {"type": "github", "owner": "a", "repo": "b"}),
        },
    )
    clock = _TickingClock()
    monkeypatch.setattr(build, "time", clock)
    monkeypatch.setattr(build.log, "time", clock)

    async def fake_process(key, cli_jar, bundle_paths):
        with build.log.timed("download" if key == "one" else "patch"):
            pass
        return {"name": f"{key}.apk", "version": "1"}

    monkeypatch.setattr(build, "process_build", fake_process)

    await build.run_builds(["one", "two"], _tools(tmp_path))

    assert list(_status(tmp_path, "one")["timings"]) == ["download", "total"]
    assert list(_status(tmp_path, "two")["timings"]) == ["patch", "total"]


def test_write_status_rounds_timings_to_a_tenth_of_a_second(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path / "build"))

    build.write_status("the-app", version="1", timings={"download": 12.3456, "patch": 0.04})

    assert _status(tmp_path, "the-app")["timings"] == {"download": 12.3, "patch": 0.0}


def test_write_status_leaves_timings_out_when_none_were_measured(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path / "build"))

    build.write_status("the-app", version="1")
    build.write_status("other-app", version="1", timings={})

    assert "timings" not in _status(tmp_path, "the-app")
    assert "timings" not in _status(tmp_path, "other-app")
