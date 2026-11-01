import json

import pytest

from patchy import catalog
from patchy.fetch.bundles import ManifestEntry, is_bundle_asset, is_cli_asset
from patchy.publish import incremental, state

CLI = {"tag": "v1.20.0", "name": "morphe-desktop-1.20.0.jar"}
BUNDLE = {"tag": "v5", "name": "patches-5.mpp"}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    for name in ("info", "warn", "step", "notice"):
        monkeypatch.setattr(incremental.log, name, lambda msg: None)


def _release(tag="build-2026-10-03T10-00-00", with_state=True):
    assets = [{"name": "YouTube-19.1.apk", "url": "https://api/1"}]
    if with_state:
        assets.append({"name": state.STATE_FILE_NAME, "url": "https://api/2", "size": 10})
    return {"tag_name": tag, "assets": assets}


def _entry(tag, name):
    entry: ManifestEntry = {"name": name, "tag": tag, "body": "", "prerelease": False}
    return entry


async def test_an_identity_is_the_release_tag_and_the_matching_asset(monkeypatch):
    async def fake_latest(owner, repo, prerelease=False, match=None):
        assert (owner, repo, prerelease) == ("o", "r", True)
        return {"tag_name": "v5", "assets": [{"name": "notes.txt"}, {"name": "patches-5.mpp"}]}

    monkeypatch.setattr(incremental, "fetch_latest_release", fake_latest)

    assert await incremental._identity("o", "r", is_bundle_asset) == BUNDLE


async def test_an_identity_is_unknown_when_the_lookup_fails_or_nothing_matches(monkeypatch):
    warnings = []
    monkeypatch.setattr(incremental.log, "warn", warnings.append)

    async def failing(owner, repo, prerelease=False, match=None):
        raise RuntimeError("GitHub API error: 404")

    monkeypatch.setattr(incremental, "fetch_latest_release", failing)
    assert await incremental._identity("o", "r", is_cli_asset) is None
    assert any("404" in line for line in warnings)

    async def without_asset(owner, repo, prerelease=False, match=None):
        return {"tag_name": "v1", "assets": [{"name": "readme.md"}]}

    monkeypatch.setattr(incremental, "fetch_latest_release", without_asset)
    assert await incremental._identity("o", "r", is_cli_asset) is None


async def test_identities_cover_the_patcher_the_needed_bundles_and_github_apps(monkeypatch):
    looked_up = []

    async def fake_identity(owner, repo, match):
        looked_up.append((owner, repo))
        return {"tag": f"tag-of-{repo}", "name": f"asset-of-{repo}"}

    async def fake_tag(owner, repo):
        return f"app-tag-of-{repo}"

    monkeypatch.setattr(incremental, "_identity", fake_identity)
    monkeypatch.setattr(incremental, "latest_release_tag", fake_tag)

    identities = await incremental.resolve_identities(["youtube", "fairemail"])

    assert identities.cli == {"tag": "tag-of-morphe-desktop", "name": "asset-of-morphe-desktop"}
    expected_bundles = {key for build in ("youtube", "fairemail") for key in catalog.BUILDS[build]["bundles"]}
    assert set(identities.bundles) == expected_bundles
    assert identities.apps == {"fairemail": "app-tag-of-FairEmail"}
    assert (catalog.CLI["owner"], catalog.CLI["repo"]) in looked_up


async def test_no_release_or_no_state_asset_means_no_state():
    assert await incremental.read_release_state(None) is None
    assert await incremental.read_release_state(_release(with_state=False)) is None


async def test_the_state_asset_of_a_release_is_downloaded_and_parsed(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path))
    payload = {
        "version": 1,
        "release_tag": "build-2026-10-03T10-00-00",
        "builds": {"youtube": {"version": "19.1", "file": "YouTube-19.1.apk", "fingerprint": "abc"}},
    }

    async def fake_download(asset, destination):
        assert asset["name"] == state.STATE_FILE_NAME
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload))
        return destination

    monkeypatch.setattr(incremental, "download_asset", fake_download)

    result = await incremental.read_release_state(_release())

    assert result is not None
    assert result["builds"]["youtube"]["fingerprint"] == "abc"


async def test_a_failed_download_or_an_unreadable_state_is_survivable(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path))
    warnings = []
    monkeypatch.setattr(incremental.log, "warn", warnings.append)

    async def failing(asset, destination):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(incremental, "download_asset", failing)
    assert await incremental.read_release_state(_release()) is None
    assert any("HTTP 500" in line for line in warnings)

    async def garbage(asset, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{not json")
        return destination

    monkeypatch.setattr(incremental, "download_asset", garbage)
    assert await incremental.read_release_state(_release()) is None
    assert any("not readable" in line for line in warnings)


def _wire(monkeypatch, previous, identities):
    async def fake_previous(exclude_tag=""):
        return _release()

    async def fake_state(release):
        return previous

    async def fake_identities(selected):
        return identities

    monkeypatch.setattr(incremental, "previous_release", fake_previous)
    monkeypatch.setattr(incremental, "read_release_state", fake_state)
    monkeypatch.setattr(incremental, "resolve_identities", fake_identities)


def _identities(builds=("youtube", "gboard")):
    bundles = {key: BUNDLE for build in builds for key in catalog.BUILDS[build]["bundles"]}
    return incremental.Identities(cli=CLI, bundles=bundles, apps={})


def _digest(build_key):
    build = catalog.BUILDS[build_key]
    return state.fingerprint(build, CLI, {key: BUNDLE for key in build["bundles"]}, None)


async def test_only_the_builds_whose_inputs_changed_are_selected(monkeypatch):
    previous = {
        "version": 1,
        "release_tag": "build-2026-10-03T10-00-00",
        "builds": {
            "youtube": state.make_record("19.1", "YouTube-19.1.apk", _digest("youtube")),
            "gboard": state.make_record("2.0", "Gboard-2.0.apk", "stale-digest"),
        },
    }
    _wire(monkeypatch, previous, _identities())

    assert await incremental.select_changed(["youtube", "gboard"]) == ["gboard"]


async def test_every_selected_build_runs_when_there_is_no_earlier_state(monkeypatch):
    _wire(monkeypatch, None, _identities())

    assert await incremental.select_changed(["youtube", "gboard"]) == ["youtube", "gboard"]


async def test_every_selected_build_runs_when_the_previous_release_cannot_be_looked_up(monkeypatch):
    warnings = []
    monkeypatch.setattr(incremental.log, "warn", warnings.append)
    _wire(monkeypatch, None, _identities())

    async def failing(exclude_tag=""):
        raise RuntimeError("API down")

    monkeypatch.setattr(incremental, "previous_release", failing)

    assert await incremental.select_changed(["youtube"]) == ["youtube"]
    assert any("API down" in line for line in warnings)


async def test_an_unresolvable_input_forces_a_rebuild(monkeypatch):
    previous = {
        "version": 1,
        "release_tag": "t",
        "builds": {"youtube": state.make_record("19.1", "YouTube-19.1.apk", _digest("youtube"))},
    }
    _wire(monkeypatch, previous, incremental.Identities(cli=None, bundles={}, apps={}))

    assert await incremental.select_changed(["youtube"]) == ["youtube"]


async def test_the_fingerprints_of_the_fetched_tools_are_recorded_in_the_manifest(monkeypatch):
    written = []

    async def no_app_tags(builds):
        return {}

    monkeypatch.setattr(incremental, "_app_tags", no_app_tags)
    monkeypatch.setattr(incremental, "write_manifest", written.append)
    bundles = {key: _entry(BUNDLE["tag"], BUNDLE["name"]) for key in catalog.BUNDLES}
    manifest = {"builds": ["youtube", "gboard"], "cli": _entry(CLI["tag"], CLI["name"]), "bundles": bundles}

    result = await incremental.record_fingerprints(manifest)

    assert result["fingerprints"] == {"youtube": _digest("youtube"), "gboard": _digest("gboard")}
    assert written == [manifest]
