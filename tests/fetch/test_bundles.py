import json

import pytest

from patchy import catalog
from patchy.core import paths
from patchy.fetch import bundles, github


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
    destinations = {}

    async def fake_download(owner, repo, match, prerelease=False, dest_dir=None):
        calls.append((owner, repo, prerelease))
        destinations[repo] = dest_dir
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
    assert destinations["morphe-desktop"] is None
    assert destinations["patches-a"] == paths.tools_dir() / "bundles" / "src_a"
    assert destinations["patches-b"] == paths.tools_dir() / "bundles" / "src_b"

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


async def test_bundles_that_ship_the_same_asset_name_each_keep_their_own_file(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path))
    monkeypatch.setattr(catalog, "BUILDS", {"one": {"bundles": ["upstream", "fork"]}})
    monkeypatch.setattr(
        catalog,
        "BUNDLES",
        {
            "upstream": {"owner": "acme", "repo": "patches", "label": "U"},
            "fork": {"owner": "someone", "repo": "patches", "label": "F"},
        },
    )
    monkeypatch.setattr(catalog, "CLI", {"owner": "MorpheApp", "repo": "morphe-desktop"})

    contents = {
        "MorpheApp": b"cli jar" * 200,
        "acme": b"the upstream bundle" * 100,
        "someone": b"the fork, which has another size" * 100,
    }

    async def fake_release(owner, repo, prerelease=False, match=None):
        name = "morphe-desktop-1.0-all.jar" if owner == "MorpheApp" else "patches-1.0.0.mpp"
        return {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "body": f"notes from {owner}",
            "assets": [
                {
                    "name": name,
                    "size": len(contents[owner]),
                    "browser_download_url": f"https://dl.test/{owner}/{name}",
                }
            ],
        }

    async def fake_download_file(url, output_path, expected_size=None):
        output_path.write_bytes(contents[url.split("/")[3]])
        return str(output_path)

    monkeypatch.setattr(github, "fetch_latest_release", fake_release)
    monkeypatch.setattr(github, "_download_file", fake_download_file)

    manifest = await bundles.fetch_all(["one"])
    tools = bundles.resolve_tools(manifest)

    assert manifest["bundles"]["upstream"]["name"] == manifest["bundles"]["fork"]["name"] == "patches-1.0.0.mpp"
    assert tools.bundles["upstream"] != tools.bundles["fork"]
    assert tools.bundles["upstream"].read_bytes() == contents["acme"]
    assert tools.bundles["fork"].read_bytes() == contents["someone"]
    assert tools.cli.read_bytes() == contents["MorpheApp"]


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


def _put_bundle(tools_dir, key, name):
    path = bundles.bundle_dir(tools_dir, key) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"mpp")
    return path


def test_bundle_dir_is_one_folder_per_bundle_key(tmp_path):
    assert bundles.bundle_dir(tmp_path, "morphe") == tmp_path / "bundles" / "morphe"
    assert bundles.bundle_dir(tmp_path, "hxreborn") != bundles.bundle_dir(tmp_path, "morphe")


def test_resolve_tools_maps_manifest_names_to_files(tmp_path):
    (tmp_path / "cli.jar").write_bytes(b"jar")
    bundle = _put_bundle(tmp_path, "morphe", "morphe.mpp")

    tools = bundles.resolve_tools(_manifest(), tmp_path)

    assert tools.cli == tmp_path / "cli.jar"
    assert tools.bundles == {"morphe": bundle}


def test_resolve_tools_complains_when_the_cli_is_missing(tmp_path):
    _put_bundle(tmp_path, "morphe", "morphe.mpp")
    with pytest.raises(bundles.ManifestError, match="CLI jar"):
        bundles.resolve_tools(_manifest(), tmp_path)


def test_resolve_tools_complains_when_a_bundle_is_missing(tmp_path):
    (tmp_path / "cli.jar").write_bytes(b"jar")
    with pytest.raises(bundles.ManifestError, match="morphe"):
        bundles.resolve_tools(_manifest(), tmp_path)


def test_companions_for_only_returns_companions_whose_builds_were_built():
    assert {c["key"] for c in bundles.companions_for(["youtube"])} == {"microg", "pothelper"}
    assert bundles.companions_for(["gboard"]) == []
