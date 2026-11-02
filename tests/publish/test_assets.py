import json

from patchy import catalog
from patchy.fetch.bundles import Manifest
from patchy.publish import assets
from patchy.publish.assets import (
    build_release_body,
    find_failure_reasons,
    find_patched_apks,
    find_pending_pins,
    match_asset,
    neutralize_github_mentions,
)

A = "a" * 64


def test_match_asset_simple_app():
    assert match_asset("YouTube-19.35.36.apk") == ("youtube", "YouTube", "19.35.36")


def test_match_asset_reads_a_version_that_carries_a_channel():
    assert match_asset("Discord-348.10-Stable.apk") == ("discord", "Discord", "348.10-Stable")


def test_match_asset_prefix_collision_resolved_by_longest_match_first():
    assert match_asset("Reddit-Adobo-2024.15.0.apk") == ("reddit-adobo", "Reddit-Adobo", "2024.15.0")


def test_match_asset_plain_reddit_still_resolves_correctly():
    assert match_asset("Reddit-2024.15.0.apk") == ("reddit", "Reddit", "2024.15.0")


def test_match_asset_disambiguates_same_display_name_by_bundle_owner():
    assert match_asset("TikTok-46.2.3-icysymmetra.apk") == ("tiktok", "TikTok", "46.2.3")
    assert match_asset("TikTok-46.2.3-hxreborn.apk") == ("tiktok-hxreborn", "TikTok", "46.2.3")
    assert match_asset("TikTok-46.4.3-BlueDragon4251.apk") == ("tiktok-bluedragon", "TikTok", "46.4.3")


def test_match_asset_ignores_microg():
    assert match_asset("MicroG-25.09.32.apk") is None


def test_match_asset_ignores_pothelper():
    assert match_asset("PotHelper-1.1.1.apk") is None


def test_match_asset_unknown_app_returns_none():
    assert match_asset("SomeRandomApp-1.0.apk") is None


def test_match_asset_non_apk_file_returns_none():
    assert match_asset("readme.txt") is None


def test_find_patched_apks_splits_matched_and_unmatched(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    (artifacts_dir / "youtube").mkdir(parents=True)
    (artifacts_dir / "reddit").mkdir(parents=True)
    (artifacts_dir / "unknown").mkdir(parents=True)

    (artifacts_dir / "youtube" / "YouTube-19.35.36.apk").write_bytes(b"fake apk")
    (artifacts_dir / "reddit" / "Reddit-2024.15.0.apk").write_bytes(b"fake apk")
    (artifacts_dir / "unknown" / "Something-1.0.apk").write_bytes(b"fake apk")
    (artifacts_dir / "notes.txt").write_bytes(b"not an apk")

    matched, unmatched = find_patched_apks(artifacts_dir)

    assert {m["build_key"] for m in matched} == {"youtube", "reddit"}
    assert unmatched == ["Something-1.0.apk"]

    youtube_entry = next(m for m in matched if m["build_key"] == "youtube")
    assert youtube_entry["version"] == "19.35.36"
    assert youtube_entry["display_name"] == "YouTube"
    assert youtube_entry["name"] == "YouTube-19.35.36.apk"


def test_find_patched_apks_empty_dir(tmp_path):
    artifacts_dir = tmp_path / "empty"
    artifacts_dir.mkdir()
    matched, unmatched = find_patched_apks(artifacts_dir)
    assert matched == []
    assert unmatched == []


def test_find_patched_apks_on_a_missing_directory_finds_nothing(tmp_path):
    assert find_patched_apks(tmp_path / "does-not-exist") == ([], [])


def test_find_failure_reasons_reads_status_files_from_every_matrix_jobs_artifact(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    (artifacts_dir / "apk-gboard").mkdir(parents=True)
    (artifacts_dir / "apk-brave").mkdir(parents=True)
    (artifacts_dir / "apk-youtube").mkdir(parents=True)

    (artifacts_dir / "apk-gboard" / "status-gboard.json").write_text(
        '{"build_key": "gboard", "ok": false, "error": "HTTP 500 fetching listing page"}'
    )
    (artifacts_dir / "apk-brave" / "status-brave.json").write_text(
        '{"build_key": "brave", "error": "patch_apk produced no output file"}'
    )
    (artifacts_dir / "apk-youtube" / "YouTube-19.35.36.apk").write_bytes(b"fake apk")
    (artifacts_dir / "apk-youtube" / "status-youtube.json").write_text(
        '{"build_key": "youtube", "ok": true, "error": null, "version": "19.35.36"}'
    )

    assert find_failure_reasons(artifacts_dir) == {
        "gboard": "HTTP 500 fetching listing page",
        "brave": "patch_apk produced no output file",
    }


def test_find_failure_reasons_skips_a_corrupt_status_file_instead_of_crashing(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    (artifacts_dir / "apk-gboard").mkdir(parents=True)
    (artifacts_dir / "apk-gboard" / "status-gboard.json").write_text("not valid json{{{")

    assert find_failure_reasons(artifacts_dir) == {}


def test_find_failure_reasons_empty_when_everything_succeeded(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    (artifacts_dir / "apk-youtube").mkdir(parents=True)
    (artifacts_dir / "apk-youtube" / "YouTube-19.35.36.apk").write_bytes(b"fake apk")

    assert find_failure_reasons(artifacts_dir) == {}


def test_find_failure_reasons_ignores_keys_that_are_not_in_the_catalog(tmp_path):
    (tmp_path / "status-evil.json").write_text('{"build_key": "../../etc/passwd", "ok": false, "error": "x"}')
    (tmp_path / "status-nokey.json").write_text('{"ok": false, "error": "x"}')
    (tmp_path / "status-list.json").write_text("[1, 2]")

    assert find_failure_reasons(tmp_path) == {}


def test_find_failure_reasons_defaults_to_unknown_error(tmp_path):
    (tmp_path / "status-gboard.json").write_text('{"build_key": "gboard", "ok": false}')
    assert find_failure_reasons(tmp_path) == {"gboard": "unknown error"}


def test_find_failure_reasons_merges_several_directories_with_later_ones_winning(tmp_path):
    built = tmp_path / "artifacts"
    signed = tmp_path / "signed"
    built.mkdir()
    signed.mkdir()
    (built / "status-gboard.json").write_text('{"build_key": "gboard", "ok": false, "error": "build broke"}')
    (built / "status-brave.json").write_text('{"build_key": "brave", "ok": true}')
    (signed / "status-brave.json").write_text('{"build_key": "brave", "ok": false, "error": "signing failed: x"}')
    (signed / "status-gboard.json").write_text('{"build_key": "gboard", "ok": false, "error": "later"}')

    assert find_failure_reasons(built, signed) == {"gboard": "later", "brave": "signing failed: x"}


def test_find_pending_pins_collects_records_from_failed_builds(tmp_path):
    (tmp_path / "apk-youtube").mkdir()
    (tmp_path / "apk-youtube" / "status-youtube.json").write_text(
        json.dumps({"build_key": "youtube", "ok": False, "pending_pin": {"app": "youtube", "sha256": A}})
    )
    (tmp_path / "status-gboard.json").write_text(json.dumps({"build_key": "gboard", "pending_pin": None}))
    (tmp_path / "status-brave.json").write_text(json.dumps({"build_key": "brave", "pending_pin": {"app": 3}}))
    (tmp_path / "status-broken.json").write_text("{{{")

    assert find_pending_pins(tmp_path) == {"youtube": A}


def test_neutralize_github_mentions_strips_the_at_sign_only():
    text = "Thanks @octocat and @some-user_1! Contact me at dev@example.com"
    assert neutralize_github_mentions(text) == "Thanks octocat and some-user_1! Contact me at devexample.com"


def _matched(*keys):
    result = []
    for key in keys:
        display_name, _ = catalog.get_release_naming(key)
        entry = {"build_key": key, "display_name": display_name, "version": "1.0.0", "path": "x", "name": "x"}
        result.append(entry)
    return result


def _manifest() -> Manifest:
    entry = {"name": "x.mpp", "tag": "v1.2.3", "prerelease": False}
    bundles = {
        key: {**entry, "body": f"Notes for {key} by @maintainer"}
        for key in ("morphe", "piko", "rufusin")
        if key in catalog.BUNDLES
    }
    return {"builds": ["youtube"], "cli": {**entry, "body": ""}, "bundles": bundles}


def test_release_body_lists_every_app_with_its_icon_and_version():
    body = build_release_body(_matched("youtube", "gboard"), None)

    assert body.startswith("### Latest Patched APKs")
    assert "**YouTube** - `1.0.0`" in body
    assert "**Gboard** - `1.0.0`" in body
    assert catalog.BUILDS["youtube"]["icon"] in body


def test_release_body_has_no_notes_without_a_manifest():
    assert "<details>" not in build_release_body(_matched("youtube"), None)


def test_release_body_includes_notes_only_for_the_bundles_that_were_used():
    manifest = _manifest()
    used = catalog.bundles_for("youtube")

    body = build_release_body(_matched("youtube"), manifest)

    for key in used:
        if key in manifest["bundles"]:
            assert f"Notes for {key}" in body
            assert catalog.BUNDLES[key]["label"] in body
    unused = [k for k in manifest["bundles"] if k not in used]
    for key in unused:
        assert f"Notes for {key}" not in body
    assert "v1.2.3" in body


def test_release_body_neutralizes_mentions_in_bundle_notes_and_everywhere_else():
    body = build_release_body(_matched("youtube"), _manifest())
    assert "@maintainer" not in body
    assert "maintainer" in body


def test_release_body_skips_manifest_entries_that_left_the_catalog():
    manifest = _manifest()
    manifest["bundles"]["ghost"] = {"name": "g.mpp", "tag": "v9", "body": "ghost notes", "prerelease": False}
    assert "ghost notes" not in build_release_body(_matched("youtube"), manifest)


def test_details_block_structure():
    block = assets._details_block("Label", "v1", "body text")
    assert block.startswith("\n<details>")
    assert "<summary>Label Release Notes (v1)</summary>" in block
    assert block.rstrip().endswith("</details>")


SHORTENED = "shortened to fit GitHub's size limit"


def _notes(label, text):
    return assets.BundleNotes(label, "v1", f"https://example.test/{label}", text)


def _manifest_with(body_for):
    entry = {"name": "x.mpp", "tag": "v1.2.3", "prerelease": False}
    bundles = {key: {**entry, "body": body_for(key)} for key in catalog.BUNDLES}
    return {"builds": ["youtube"], "cli": {**entry, "body": ""}, "bundles": bundles}


def test_release_body_does_not_touch_notes_that_fit():
    body = build_release_body(_matched("youtube"), _manifest())

    assert SHORTENED not in body
    assert "Notes for morphe by maintainer" in body


def test_release_body_stays_under_the_limit_when_the_bundle_notes_are_enormous():
    manifest = _manifest_with(lambda key: "- a change\n" * 40_000)

    body = build_release_body(_matched("youtube", "gboard", "brave"), manifest)

    assert len(body) <= assets.RELEASE_BODY_LIMIT
    assert body.count(SHORTENED) == 3
    for key in ("morphe", "jasonwu", "kveld"):
        bundle = catalog.BUNDLES[key]
        assert f"https://github.com/{bundle['owner']}/{bundle['repo']}/releases/tag/v1.2.3" in body


def test_release_body_keeps_small_notes_whole_when_another_bundle_is_huge():
    manifest = _manifest_with(lambda key: "- a change\n" * 40_000 if key == "morphe" else f"Notes for {key}")

    body = build_release_body(_matched("youtube", "gboard"), manifest)

    assert len(body) <= assets.RELEASE_BODY_LIMIT
    assert "Notes for jasonwu" in body
    assert body.count(SHORTENED) == 1


def test_release_body_closes_a_code_block_that_the_size_limit_cut_open():
    manifest = _manifest_with(lambda key: "```\n" + "code line\n" * 5000 + "```\n")

    body = build_release_body(_matched("youtube", "gboard"), manifest, limit=4000)

    assert len(body) <= 4000
    assert body.count("```") % 2 == 0


def test_release_body_never_exceeds_even_an_absurdly_small_limit():
    body = build_release_body(_matched("youtube", "gboard"), _manifest(), limit=200)

    assert len(body) <= 200


def test_notes_section_keeps_small_notes_whole_and_shortens_only_the_big_one():
    small = "- small fix\n"
    entries = [_notes("Small", small), _notes("Big", "- big entry\n" * 50_000)]

    section = assets._notes_section(entries, 10_000)

    assert len(section) <= 10_000
    assert small in section
    assert section.count(SHORTENED) == 1
    assert "https://example.test/Big" in section
    assert "https://example.test/Small" not in section


def test_notes_section_gives_equally_large_notes_an_equal_share():
    entries = [_notes(name, "- line\n" * 30_000) for name in ("A", "B", "C")]

    section = assets._notes_section(entries, 30_000)

    sizes = [len(part) for part in section.split("</details>")[:-1]]
    assert len(sizes) == 3
    assert sum(sizes) <= 30_000
    assert max(sizes) - min(sizes) < 50


def test_fair_shares_give_small_items_everything_and_split_the_rest_evenly():
    assert assets._fair_shares([10, 100, 100], 130) == [10, 60, 60]
    assert assets._fair_shares([5, 5], 100) == [5, 5]
    assert assets._fair_shares([100, 100, 100], 100) == [33, 33, 34]
    assert assets._fair_shares([50, 50], 0) == [0, 0]
    assert assets._fair_shares([], 10) == []


def test_cut_notes_leaves_text_that_fits_alone():
    assert assets._cut_notes("short", 5) == "short"


def test_cut_notes_cuts_between_lines_and_stays_within_the_room():
    notes = "\n".join(f"line {i:03d}" for i in range(100))

    cut = assets._cut_notes(notes, 100)

    assert 0 < len(cut) <= 100
    assert set(cut.split("\n")) <= set(notes.split("\n"))


def test_cut_notes_closes_an_open_code_block_within_the_room():
    notes = "intro\n```\n" + "code line\n" * 200 + "```\n"

    cut = assets._cut_notes(notes, 300)

    assert len(cut) <= 300
    assert cut.endswith("\n```")
    assert cut.count("```") % 2 == 0
