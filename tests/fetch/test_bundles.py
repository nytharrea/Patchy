import json

import pytest

from patchy import catalog
from patchy.fetch import bundles


def _asset(name, tag="v1", body="notes", prerelease=False, path="x"):
    return {"name": name, "path": path, "body": body, "tag": tag, "prerelease": prerelease}


def test_is_cli_asset_matches_the_desktop_jar_only():
    assert bundles.is_cli_asset("morphe-desktop-v1.jar") is True
    assert bundles.is_cli_asset("morphe-desktop-v1.apk") is False
    assert bundles.is_cli_asset("other-tool.jar") is False


def test_is_bundle_asset_matches_mpp_only():
    assert bundles.is_bundle_asset("some-patches.mpp") is True
    assert bundles.is_bundle_asset("some-patches.apk") is False


def test_microg_variant_matchers_keep_the_plain_and_noicon_builds_apart():
    plain, noicon = catalog.COMPANIONS["microg"]["variants"]
    plain_match = bundles.companion_matcher(plain)
    noicon_match = bundles.companion_matcher(noicon)

    assert plain_match("MicroG-25.09.32-arm64-v8a.apk") is True
    assert plain_match("MicroG-25.09.32-noicon-arm64-v8a.apk") is False
    assert plain_match("MicroG-25.09.32-NoIcon-arm64-v8a.apk") is False
    assert noicon_match("MicroG-25.09.32-noicon-arm64-v8a.apk") is True
    assert noicon_match("MicroG-25.09.32-arm64-v8a.apk") is False


def test_pothelper_variant_matches_any_apk():
    (variant,) = catalog.COMPANIONS["pothelper"]["variants"]
    match = bundles.companion_matcher(variant)
    assert match("PotHelper-1.1.1.apk") is True
    assert match("PotHelper-1.1.1.zip") is False


def test_bundle_keys_for_dedupes_and_keeps_first_seen_order(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "BUILDS",
        {
            "one": {"bundles": ["a", "b"]},
            "two": {"bundles": ["b", "c"]},
        },
    )
    assert bundles.bundle_keys_for(["one", "two"]) == ["a", "b", "c"]


async def test_fetch_all_downloads_the_cli_once_and_only_the_bundles_the_builds_need(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path))
    monkeypatch.setattr(
        catalog,
        "BUILDS",
        {"one": {"bundles": ["src_a"]}, "two": {"bundles": ["src_a", "src_b"]}},
    )
    monkeypatch.setattr(
        catalog,
        "BUNDLES",
        {
            "src_a": {"owner": "acme", "repo": "patches-a", "label": "A"},
            "src_b": {"owner": "other", "repo": "patches-b", "label": "B"},
            "src_unused": {"owner": "nobody", "repo": "unused", "label": "U"},
        },
    )
    monkeypatch.setattr(catalog, "CLI", {"owner": "MorpheApp", "repo": "morphe-desktop"})

    calls = []

    async def fake_download(owner, repo, match, prerelease=False, dest_dir=None):
        calls.append((owner, repo, prerelease))
        if owner == "MorpheApp":
            assert match("morphe-desktop-v1.jar") is True
            assert match("morphe-desktop-v1.apk") is False
            return _asset("cli.jar", tag="cli-tag")
        assert match("some-patches.mpp") is True
        return _asset(f"{repo}.mpp", tag=f"{repo}-tag", body=f"notes for {repo}")

    monkeypatch.setattr(bundles, "download_latest_release_asset", fake_download)

    manifest = await bundles.fetch_all(["one", "two"])

    expected = [("MorpheApp", "morphe-desktop", True), ("acme", "patches-a", True), ("other", "patches-b", True)]
    assert calls == expected
    assert manifest["builds"] == ["one", "two"]
    assert manifest["cli"]["name"] == "cli.jar"
    assert set(manifest["bundles"]) == {"src_a", "src_b"}
    assert manifest["bundles"]["src_a"]["body"] == "notes for patches-a"

    written = json.loads((tmp_path / "manifest" / "bundles.json").read_text())
    assert written == manifest


async def test_two_bundles_in_the_same_repo_both_still_get_a_call(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path))
    monkeypatch.setattr(catalog, "BUILDS", {"one": {"bundles": ["src_a", "src_b"]}})
    monkeypatch.setattr(
        catalog,
        "BUNDLES",
        {
            "src_a": {"owner": "acme", "repo": "shared-repo", "label": "A"},
            "src_b": {"owner": "acme", "repo": "shared-repo", "label": "B"},
        },
    )

    calls = []

    async def fake_download(owner, repo, match, prerelease=False, dest_dir=None):
        calls.append((owner, repo))
        return _asset("asset")

    monkeypatch.setattr(bundles, "download_latest_release_asset", fake_download)

    await bundles.fetch_all(["one"])

    assert calls.count(("acme", "shared-repo")) == 2


def _manifest(**overrides):
    manifest = {
        "builds": ["youtube"],
        "cli": {"name": "cli.jar", "tag": "v1", "body": "", "prerelease": False},
        "bundles": {"morphe": {"name": "morphe.mpp", "tag": "v2", "body": "notes", "prerelease": True}},
    }
    manifest.update(overrides)
    return manifest


def test_manifest_round_trips(tmp_path):
    path = tmp_path / "m" / "bundles.json"
    bundles.write_manifest(_manifest(), path)
    assert bundles.read_manifest(path) == _manifest()


def test_read_manifest_missing_file_has_a_helpful_error(tmp_path):
    with pytest.raises(bundles.ManifestError, match="not found"):
        bundles.read_manifest(tmp_path / "nope.json")


def test_read_manifest_rejects_invalid_json(tmp_path):
    path = tmp_path / "bundles.json"
    path.write_text("{not json")
    with pytest.raises(bundles.ManifestError, match="not valid JSON"):
        bundles.read_manifest(path)


def test_read_manifest_rejects_missing_keys(tmp_path):
    path = tmp_path / "bundles.json"
    path.write_text(json.dumps({"builds": []}))
    with pytest.raises(bundles.ManifestError, match="missing required keys"):
        bundles.read_manifest(path)


def test_resolve_tools_maps_manifest_names_to_files(tmp_path):
    (tmp_path / "cli.jar").write_bytes(b"jar")
    (tmp_path / "morphe.mpp").write_bytes(b"mpp")

    tools = bundles.resolve_tools(_manifest(), tmp_path)

    assert tools.cli == tmp_path / "cli.jar"
    assert tools.bundles == {"morphe": tmp_path / "morphe.mpp"}


def test_resolve_tools_complains_when_the_cli_is_missing(tmp_path):
    (tmp_path / "morphe.mpp").write_bytes(b"mpp")
    with pytest.raises(bundles.ManifestError, match="CLI jar"):
        bundles.resolve_tools(_manifest(), tmp_path)


def test_resolve_tools_complains_when_a_bundle_is_missing(tmp_path):
    (tmp_path / "cli.jar").write_bytes(b"jar")
    with pytest.raises(bundles.ManifestError, match="morphe"):
        bundles.resolve_tools(_manifest(), tmp_path)


def test_companions_for_only_returns_companions_whose_builds_were_built():
    assert {c["key"] for c in bundles.companions_for(["youtube"])} == {"microg", "pothelper"}
    assert bundles.companions_for(["gboard"]) == []
