import json

import pytest

from patchy import catalog
from patchy.publish import state

CLI = {"tag": "v1.20.0", "name": "morphe-desktop-1.20.0.jar"}


def _bundles(build, tag="v5", name="patches-5.mpp"):
    return {key: {"tag": tag, "name": name} for key in build["bundles"]}


def _digest(build=None, cli=CLI, bundles=None, app_tag=None):
    build = build or catalog.BUILDS["youtube"]
    return state.fingerprint(build, cli, _bundles(build) if bundles is None else bundles, app_tag)


def test_the_fingerprint_is_stable_for_identical_inputs():
    first = _digest()

    assert first == _digest()
    assert len(first) == state.FINGERPRINT_LENGTH


def test_the_fingerprint_changes_with_the_patcher_a_bundle_or_the_configuration():
    build = catalog.BUILDS["youtube"]
    reference = _digest()

    assert _digest(cli={"tag": "v1.21.0", "name": CLI["name"]}) != reference
    assert _digest(cli={"tag": CLI["tag"], "name": "other.jar"}) != reference
    assert _digest(bundles=_bundles(build, tag="v6")) != reference
    assert _digest(bundles=_bundles(build, name="patches-6.mpp")) != reference
    assert _digest(build={**build, "exclude": ["Some patch"]}) != reference
    assert _digest(build={**build, "arch": "armeabi-v7a"}) != reference


def test_the_fingerprint_follows_the_app_release_of_a_github_app():
    build = catalog.BUILDS["fairemail"]

    assert _digest(build, app_tag="1.2300") != _digest(build, app_tag="1.2301")
    assert _digest(build, app_tag="1.2300") == _digest(build, app_tag="1.2300")


def test_the_icon_does_not_change_the_fingerprint():
    build = catalog.BUILDS["youtube"]

    assert _digest(build={**build, "icon": "https://example.test/other.png"}) == _digest()


def test_the_fingerprint_is_unknown_when_an_input_cannot_be_resolved():
    build = catalog.BUILDS["youtube"]
    missing_bundle = {key: None for key in build["bundles"]}

    assert _digest(cli=None) is None
    assert _digest(bundles=missing_bundle) is None
    assert _digest(catalog.BUILDS["fairemail"], app_tag=None) is None


def test_an_apkmirror_build_that_forces_the_newest_version_has_no_fingerprint():
    build = {**catalog.BUILDS["youtube"], "force": True}

    assert _digest(build=build) is None
    assert _digest({**catalog.BUILDS["fairemail"], "force": True}, app_tag="1.2300") is not None


def test_a_state_round_trips_through_a_file(tmp_path):
    original = {
        "version": state.STATE_VERSION,
        "release_tag": "build-2026-10-04T10-00-00",
        "builds": {
            "youtube": state.make_record("19.1", "YouTube-19.1.apk", "abc", retry=True),
            "gboard": state.make_record("2.0", "Gboard-2.0.apk"),
        },
    }

    path = state.write_state(original, tmp_path / "nested" / state.STATE_FILE_NAME)

    assert state.read_state(path) == original
    assert json.loads(path.read_text())["builds"]["youtube"]["retry"] is True
    assert "retry" not in json.loads(path.read_text())["builds"]["gboard"]


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"version": 99, "release_tag": "t", "builds": {}},
        {"version": 1, "builds": {}},
        {"version": 1, "release_tag": 3, "builds": {}},
        {"version": 1, "release_tag": "t", "builds": []},
    ],
)
def test_a_state_with_the_wrong_shape_is_rejected(data):
    assert state.parse_state(data) is None


def test_broken_records_are_dropped_and_good_ones_kept():
    data = {
        "version": 1,
        "release_tag": "t",
        "builds": {
            "good": {"version": "1", "file": "A-1.apk", "fingerprint": "abc"},
            "no-file": {"version": "1"},
            "empty-file": {"version": "1", "file": ""},
            "not-a-dict": "x",
            "bad-digest": {"version": "1", "file": "B-1.apk", "fingerprint": 7, "retry": "yes"},
        },
    }

    parsed = state.parse_state(data)

    assert parsed is not None
    assert parsed["builds"] == {
        "good": {"version": "1", "file": "A-1.apk", "fingerprint": "abc"},
        "bad-digest": {"version": "1", "file": "B-1.apk"},
    }


def test_a_missing_or_unreadable_state_file_reads_as_nothing(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")

    assert state.read_state(tmp_path / "absent.json") is None
    assert state.read_state(tmp_path / "broken.json") is None


def _previous(**records):
    return {"version": 1, "release_tag": "build-2026-10-03T10-00-00", "builds": records}


def test_everything_changed_when_there_is_no_earlier_state():
    changed = state.changed_builds(["youtube", "gboard"], None, {"youtube": "a", "gboard": "b"})

    assert list(changed) == ["youtube", "gboard"]
    assert "no earlier state" in changed["youtube"]


def test_an_unchanged_build_is_left_out():
    previous = _previous(youtube=state.make_record("19.1", "YouTube-19.1.apk", "same"))

    assert state.changed_builds(["youtube"], previous, {"youtube": "same"}) == {}


def test_each_reason_for_a_rebuild_is_named():
    previous = _previous(
        youtube=state.make_record("19.1", "YouTube-19.1.apk", "old"),
        gboard=state.make_record("2.0", "Gboard-2.0.apk", "same"),
        brave=state.make_record("1.0", "Brave-1.0.apk", "same", retry=True),
        reddit=state.make_record("3.0", "Reddit-3.0.apk"),
    )
    current = {"youtube": "new", "gboard": None, "brave": "same", "reddit": "same", "capcut": "x"}

    changed = state.changed_builds(["youtube", "gboard", "brave", "reddit", "capcut"], previous, current)

    assert "changed" in changed["youtube"]
    assert "cannot be compared" in changed["gboard"]
    assert "older version" in changed["brave"]
    assert "changed" in changed["reddit"]
    assert "not part of the previous release" in changed["capcut"]


def test_changed_builds_follow_the_order_of_the_selection():
    changed = state.changed_builds(["gboard", "youtube"], None, {})

    assert list(changed) == ["gboard", "youtube"]


def test_the_next_state_adds_what_was_built_and_keeps_what_was_carried():
    previous = _previous(
        youtube=state.make_record("19.0", "YouTube-19.0.apk", "old-youtube"),
        gboard=state.make_record("2.0", "Gboard-2.0.apk", "kept-digest", retry=True),
    )
    built = {"youtube": state.make_record("19.1", "YouTube-19.1.apk", "new-youtube")}
    carried = {"gboard": state.make_record("2.0", "Gboard-2.0.apk")}

    result = state.next_state(previous, "build-2026-10-04T10-00-00", built, carried)

    assert result["release_tag"] == "build-2026-10-04T10-00-00"
    assert result["builds"]["youtube"]["fingerprint"] == "new-youtube"
    assert result["builds"]["gboard"] == {
        "version": "2.0",
        "file": "Gboard-2.0.apk",
        "fingerprint": "kept-digest",
        "retry": True,
    }


def test_a_carried_app_without_a_matching_earlier_record_has_no_fingerprint():
    previous = _previous(gboard=state.make_record("1.0", "Gboard-1.0.apk", "digest"))
    carried = {
        "gboard": state.make_record("2.0", "Gboard-2.0.apk"),
        "brave": state.make_record("1.0", "Brave-1.0.apk"),
    }

    result = state.next_state(previous, "t", {}, carried)

    assert result["builds"]["gboard"] == {"version": "2.0", "file": "Gboard-2.0.apk"}
    assert result["builds"]["brave"] == {"version": "1.0", "file": "Brave-1.0.apk"}
    assert state.next_state(None, "t", {}, carried)["builds"] == carried
