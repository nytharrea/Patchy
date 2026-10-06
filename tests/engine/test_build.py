import json
from types import SimpleNamespace

import pytest

from patchy import catalog
from patchy.engine import build
from patchy.engine.verify import SignatureError, UnpinnedSignature
from patchy.fetch import apkmirror, github
from patchy.fetch.bundles import Tools

FINGERPRINT = "3d7a1223019aa39d9ea0e3436ab7c0896bfb4fb679f4de5fe7c23f326c8f994a"


def _fake_build(app_slug: str, source: dict, force_version: str | None = "1.2.3") -> dict:
    return {
        "key": app_slug,
        "app_slug": app_slug,
        "pkg": f"com.example.{app_slug}",
        "display_name": app_slug.title(),
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

    async def fake_apkmirror_download(version, app_slug, source, force_build):
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

    async def fake_download(version, app_slug, source, force_build):
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

    async def fake_download(version, app_slug, source, force_build):
        calls.append(version)
        return str(tmp_path / "downloaded.apk")

    monkeypatch.setattr(apkmirror, "get_latest_listing", fake_listing)
    monkeypatch.setattr(apkmirror, "download_apk", fake_download)

    await build.process_build(build_key, "desktop.jar", ["patch1.mpp"])

    assert calls == ["5.5.5"]


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
