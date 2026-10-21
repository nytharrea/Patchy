import importlib.util
import json
from pathlib import Path

from patchy import catalog
from patchy.publish.assets import match_asset

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "site_catalog.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("site_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_payload_lists_every_build_and_companion():
    payload = _load_script().build_payload()

    assert [b["key"] for b in payload["builds"]] == list(catalog.BUILDS)
    assert [c["key"] for c in payload["companions"]] == list(catalog.COMPANIONS)


def test_release_naming_is_copied_from_the_catalog():
    payload = _load_script().build_payload()

    for build in payload["builds"]:
        assert (build["name"], build["tag"]) == catalog.get_release_naming(build["key"])


def test_generated_asset_names_resolve_back_to_their_build():
    payload = _load_script().build_payload()

    for build in payload["builds"]:
        suffix = f"-{build['tag']}" if build["tag"] else ""
        assert match_asset(f"{build['name']}-1.2.3{suffix}.apk")[0] == build["key"]


def test_bundle_labels_drop_their_leading_emoji():
    payload = _load_script().build_payload()

    for build in payload["builds"]:
        assert build["variant"][0].isalnum()
        assert all(bundle["label"][0].isalnum() for bundle in build["bundles"])


def test_titles_and_categories_are_filled_in():
    payload = _load_script().build_payload()
    titles = {b["app"]: b["title"] for b in payload["builds"]}

    assert titles["youtube-music"] == "YouTube Music"
    assert titles["reddit"] == "Reddit"
    assert all(b["category"] for b in payload["builds"])


def test_companion_files_use_the_uploaded_asset_names():
    payload = _load_script().build_payload()
    files = {c["key"]: c["files"] for c in payload["companions"]}

    assert files["microg"] == ["MicroG.apk", "MicroG-NoIcon.apk"]
    assert files["pothelper"] == ["PotHelper.apk"]


def test_main_writes_json_with_the_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/Patchy")
    target = tmp_path / "data" / "catalog.json"

    _load_script().main(str(target))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["repo"] == "owner/Patchy"
    assert len(data["builds"]) == len(catalog.BUILDS)


def test_repository_is_null_outside_github_actions(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    target = tmp_path / "catalog.json"

    _load_script().main(str(target))

    assert json.loads(target.read_text(encoding="utf-8"))["repo"] is None
