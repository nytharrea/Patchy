import pytest
import yaml

from patchy import catalog
from patchy.catalog import loader
from patchy.core.settings import settings


def _write_config(tmp_path, apps: dict, bundles: dict | None = None, cli: dict | None = None):
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir(exist_ok=True)
    for slug, app in apps.items():
        (apps_dir / f"{slug}.yaml").write_text(yaml.safe_dump(app))
    bundles_path = tmp_path / "bundles.yaml"
    bundles_path.write_text(
        yaml.safe_dump(
            {
                "cli": cli or {"owner": "MorpheApp", "repo": "morphe-desktop"},
                "bundles": bundles or {"morphe": {"owner": "MorpheApp", "repo": "morphe-patches"}},
            }
        )
    )
    return apps_dir, bundles_path


def _load(monkeypatch, tmp_path, apps: dict, bundles: dict | None = None):
    apps_dir, bundles_path = _write_config(tmp_path, apps, bundles)
    monkeypatch.setattr(settings, "apps_dir", apps_dir)
    monkeypatch.setattr(settings, "bundles_path", bundles_path)
    return loader.load_bundles(), loader.load_builds()


def test_reddit_has_two_builds_sharing_the_same_apk_source():
    reddit = catalog.BUILDS["reddit"]
    reddit_adobo = catalog.BUILDS["reddit-adobo"]

    assert reddit["app_slug"] == reddit_adobo["app_slug"] == "reddit"
    assert reddit["pkg"] == reddit_adobo["pkg"]
    assert reddit["apk_source"] == reddit_adobo["apk_source"]
    assert reddit["bundles"] != reddit_adobo["bundles"]


def test_all_five_tiktok_builds_share_app_level_fields():
    tiktok_keys = ["tiktok", "tiktok-hxreborn", "tiktok-bluedragon", "tiktok-hushfeed", "tiktok-kveld"]
    builds = [catalog.BUILDS[k] for k in tiktok_keys]

    assert all(b["app_slug"] == "tiktok" for b in builds)
    assert len({b["pkg"] for b in builds}) == 1
    assert len({b["icon"] for b in builds}) == 1
    assert len({b["display_name"] for b in builds}) == 1
    assert len({tuple(b["bundles"]) for b in builds}) == 5


def test_speedtest_build_combines_multiple_bundles_into_one_build():
    assert catalog.BUILDS["speedtest"]["bundles"] == ["rushi", "morphe"]


def test_bundles_for_matches_build_field():
    assert catalog.bundles_for("speedtest") == catalog.BUILDS["speedtest"]["bundles"]


def test_every_app_file_name_is_the_app_slug_of_its_builds():
    for build in catalog.BUILDS.values():
        assert (settings.apps_dir / f"{build['app_slug']}.yaml").is_file()


def test_cli_source_is_loaded_from_the_bundles_file():
    assert catalog.CLI == {"owner": "MorpheApp", "repo": "morphe-desktop"}


def test_companions_are_loaded_with_their_variants():
    microg = catalog.COMPANIONS["microg"]
    assert microg["for_builds"] == ["youtube", "youtube-music"]
    assert [v["file"] for v in microg["variants"]] == ["MicroG.apk", "MicroG-NoIcon.apk"]
    assert microg["variants"][0]["exclude"] == "noicon"
    assert "exclude" not in microg["variants"][1]


def test_get_release_naming_no_collision_returns_no_suffix():
    assert catalog.get_release_naming("youtube") == ("YouTube", None)


def test_get_release_naming_disambiguates_colliding_tiktok_builds():
    name, suffix = catalog.get_release_naming("tiktok-hxreborn")
    assert name == "TikTok"
    assert suffix == catalog.BUNDLES["hxreborn-tiktok"]["owner"]


def test_get_release_naming_reddit_adobo_has_its_own_name_so_no_suffix_needed():
    assert catalog.get_release_naming("reddit-adobo") == ("Reddit-Adobo", None)


def _minimal_app(**overrides):
    app = {
        "pkg": "com.example.app",
        "display_name": "Example",
        "arch": "arm64-v8a",
        "icon": "https://example.com/icon.png",
        "apk_source": {"type": "apkmirror", "org": "example-org", "slug": "example"},
        "builds": [{"key": "example", "bundles": ["morphe"]}],
    }
    app.update(overrides)
    return app


def test_build_inherits_app_level_fields_when_not_overridden(monkeypatch, tmp_path):
    _, builds = _load(monkeypatch, tmp_path, {"myapp": _minimal_app()})
    build = builds["example"]
    assert build["pkg"] == "com.example.app"
    assert build["display_name"] == "Example"
    assert build["arch"] == "arm64-v8a"
    assert build["app_slug"] == "myapp"


def test_build_level_display_name_overrides_app_level(monkeypatch, tmp_path):
    app = _minimal_app(builds=[{"key": "example-variant", "bundles": ["morphe"], "display_name": "Custom Name"}])
    _, builds = _load(monkeypatch, tmp_path, {"myapp": app})
    assert builds["example-variant"]["display_name"] == "Custom Name"


def test_multiple_builds_under_one_app_each_get_their_own_bundles(monkeypatch, tmp_path):
    app = _minimal_app(
        builds=[
            {"key": "myapp", "bundles": ["morphe"]},
            {"key": "myapp-alt", "bundles": ["adobo"]},
        ]
    )
    _, builds = _load(
        monkeypatch,
        tmp_path,
        {"myapp": app},
        bundles={
            "morphe": {"owner": "MorpheApp", "repo": "morphe-patches"},
            "adobo": {"owner": "jkennethcarino", "repo": "adobo"},
        },
    )
    assert set(builds) == {"myapp", "myapp-alt"}
    assert builds["myapp"]["app_slug"] == builds["myapp-alt"]["app_slug"] == "myapp"
    assert builds["myapp"]["bundles"] == ["morphe"]
    assert builds["myapp-alt"]["bundles"] == ["adobo"]


def test_exclude_and_enable_default_to_empty_list_when_absent(monkeypatch, tmp_path):
    _, builds = _load(monkeypatch, tmp_path, {"myapp": _minimal_app()})
    assert builds["example"]["exclude"] == []
    assert builds["example"]["enable"] == []


def test_force_version_and_force_build_default_to_none(monkeypatch, tmp_path):
    _, builds = _load(monkeypatch, tmp_path, {"myapp": _minimal_app()})
    assert builds["example"]["force_version"] is None
    assert builds["example"]["force_build"] is None


def test_options_defaults_to_empty_dict_when_absent(monkeypatch, tmp_path):
    _, builds = _load(monkeypatch, tmp_path, {"myapp": _minimal_app()})
    assert builds["example"]["options"] == {}


def test_options_are_loaded_from_yaml(monkeypatch, tmp_path):
    app = _minimal_app(
        builds=[
            {
                "key": "example",
                "bundles": ["morphe"],
                "options": {
                    "Custom branding.App name": "YouTube Özel",
                    "Custom branding.App icon": "Black",
                },
            }
        ]
    )
    _, builds = _load(monkeypatch, tmp_path, {"myapp": app})
    assert builds["example"]["options"] == {
        "Custom branding.App name": "YouTube Özel",
        "Custom branding.App icon": "Black",
    }


def test_github_apk_source_is_preserved_as_is(monkeypatch, tmp_path):
    app = _minimal_app(apk_source={"type": "github", "owner": "SomeOrg", "repo": "some-repo"})
    _, builds = _load(monkeypatch, tmp_path, {"myapp": app})
    assert builds["example"]["apk_source"] == {"type": "github", "owner": "SomeOrg", "repo": "some-repo"}


def test_unknown_apk_source_type_raises_a_clear_error(monkeypatch, tmp_path):
    app = _minimal_app(apk_source={"type": "apkmirrorr", "org": "example-org", "slug": "example"})
    with pytest.raises(catalog.CatalogError, match="apkmirror"):
        _load(monkeypatch, tmp_path, {"myapp": app})


def test_duplicate_build_key_across_different_apps_raises(monkeypatch, tmp_path):
    apps = {
        "app-one": _minimal_app(builds=[{"key": "shared-key", "bundles": ["morphe"]}]),
        "app-two": _minimal_app(builds=[{"key": "shared-key", "bundles": ["morphe"]}]),
    }
    with pytest.raises(catalog.CatalogError, match="shared-key"):
        _load(monkeypatch, tmp_path, apps)


def test_build_with_no_bundles_raises_at_load_time(monkeypatch, tmp_path):
    app = _minimal_app(builds=[{"key": "example", "bundles": []}])
    with pytest.raises(catalog.CatalogError, match="no bundles"):
        _load(monkeypatch, tmp_path, {"myapp": app})


def test_app_with_empty_builds_list_raises_at_load_time(monkeypatch, tmp_path):
    app = _minimal_app(builds=[])
    with pytest.raises(catalog.CatalogError, match="no builds"):
        _load(monkeypatch, tmp_path, {"myapp": app})


def test_app_with_missing_builds_key_raises_at_load_time(monkeypatch, tmp_path):
    app = _minimal_app()
    del app["builds"]
    with pytest.raises(catalog.CatalogError, match="no builds"):
        _load(monkeypatch, tmp_path, {"myapp": app})


def test_app_missing_a_required_field_raises_a_clear_error(monkeypatch, tmp_path):
    app = _minimal_app()
    del app["icon"]
    with pytest.raises(catalog.CatalogError, match="icon"):
        _load(monkeypatch, tmp_path, {"myapp": app})


def test_bundle_missing_required_field_raises_a_clear_error(monkeypatch, tmp_path):
    with pytest.raises(catalog.CatalogError, match="repo"):
        _load(monkeypatch, tmp_path, {"myapp": _minimal_app()}, bundles={"morphe": {"owner": "MorpheApp"}})


def test_non_mapping_yaml_file_raises_a_clear_error(monkeypatch, tmp_path):
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "broken.yaml").write_text("- just\n- a\n- list\n")
    monkeypatch.setattr(settings, "apps_dir", apps_dir)
    with pytest.raises(catalog.CatalogError, match="mapping"):
        loader.load_builds()


def test_app_file_name_must_be_a_lowercase_slug(monkeypatch, tmp_path):
    with pytest.raises(catalog.CatalogError, match="slug"):
        _load(monkeypatch, tmp_path, {"My App": _minimal_app()})


def test_missing_apps_directory_raises_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "apps_dir", tmp_path / "does-not-exist")
    with pytest.raises(catalog.CatalogError, match="Apps directory not found"):
        loader.load_builds()


def test_empty_apps_directory_raises_a_clear_error(monkeypatch, tmp_path):
    (tmp_path / "apps").mkdir()
    monkeypatch.setattr(settings, "apps_dir", tmp_path / "apps")
    with pytest.raises(catalog.CatalogError, match="No app files"):
        loader.load_builds()


def test_bundles_file_without_a_cli_section_raises(monkeypatch, tmp_path):
    bundles_path = tmp_path / "bundles.yaml"
    bundles_path.write_text(yaml.safe_dump({"bundles": {"morphe": {"owner": "a", "repo": "b"}}}))
    monkeypatch.setattr(settings, "bundles_path", bundles_path)
    with pytest.raises(catalog.CatalogError, match="cli"):
        loader.load_cli()


def test_bundles_file_without_a_bundles_section_raises(monkeypatch, tmp_path):
    bundles_path = tmp_path / "bundles.yaml"
    bundles_path.write_text(yaml.safe_dump({"cli": {"owner": "a", "repo": "b"}}))
    monkeypatch.setattr(settings, "bundles_path", bundles_path)
    with pytest.raises(catalog.CatalogError, match="bundles"):
        loader.load_bundles()


def test_missing_companions_file_means_no_companions(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "companions_path", tmp_path / "nope.yaml")
    assert loader.load_companions() == {}


def test_companion_missing_a_field_raises_a_clear_error(monkeypatch, tmp_path):
    path = tmp_path / "companions.yaml"
    path.write_text(yaml.safe_dump({"microg": {"owner": "MorpheApp", "variants": []}}))
    monkeypatch.setattr(settings, "companions_path", path)
    with pytest.raises(catalog.CatalogError, match="repo"):
        loader.load_companions()
