import zipfile

import pytest

from patchy.engine import bundle_compat
from patchy.engine.bundle_compat import (
    BundleSplit,
    behavior_generation,
    declared_patcher_version,
    format_patcher_version,
    parse_patcher_version,
    split_by_generation,
)

from .bundles import write_bundle

HXREBORN_MANIFEST = (
    "Manifest-Version: 1.0\r\n"
    "Name: hxreborn TikTok Patches\r\n"
    "Description: TikTok patches for Morphe, forked from icysymmetra.\r\n"
    "Version: 1.4.0\r\n"
    "Timestamp: 1790533757253\r\n"
    "Source: https://github.com/hxreborn/hxreborn-tiktok-patches\r\n"
    "Author: hxreborn\r\n"
    "Contact: hxreborn@duck.com\r\n"
    "Website: https://github.com/hxreborn/hxreborn-tiktok-patches\r\n"
    "License: GNU General Public License v3.0, with additional GPL section 7 \r\n"
    " requirements\r\n"
    "Patcher-Version: 1.5.1\r\n"
    "\r\n"
)


def _bundle_with_manifest(tmp_path, manifest, name="bundle.mpp"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", manifest)
    return path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5.1", (1, 5, 1)),
        ("2.0.0", (2, 0, 0)),
        ("  1.8.0\r\n", (1, 8, 0)),
        ("2.0.0-dev.3", (2, 0, 0)),
        ("2.0.0-0", (2, 0, 0)),
        ("2.1.4+build.7", (2, 1, 4)),
        ("10.20.30", (10, 20, 30)),
    ],
)
def test_parse_patcher_version_reads_the_numbers_of_a_version(text, expected):
    assert parse_patcher_version(text) == expected


@pytest.mark.parametrize("text", [None, "", "  ", "2", "2.0", "v2.0.0", "na", "2.0.0.1", "two.zero.zero", "2.0.x"])
def test_parse_patcher_version_rejects_what_is_not_a_version(text):
    assert parse_patcher_version(text) is None


def test_format_patcher_version_writes_the_three_numbers():
    assert format_patcher_version((2, 0, 0)) == "2.0.0"
    assert format_patcher_version((1, 8, 12)) == "1.8.12"


def test_declared_patcher_version_reads_a_real_bundle_manifest(tmp_path):
    bundle = _bundle_with_manifest(tmp_path, HXREBORN_MANIFEST)

    assert declared_patcher_version(bundle) == (1, 5, 1)


def test_declared_patcher_version_accepts_a_path_as_text(tmp_path):
    bundle = write_bundle(tmp_path, "patches.mpp", "2.0.0")

    assert declared_patcher_version(str(bundle)) == (2, 0, 0)


@pytest.mark.parametrize("newline", ["\r\n", "\n", "\r"])
def test_declared_patcher_version_accepts_every_kind_of_line_break(tmp_path, newline):
    bundle = write_bundle(tmp_path, "patches.mpp", "1.8.0", newline=newline)

    assert declared_patcher_version(bundle) == (1, 8, 0)


def test_declared_patcher_version_ignores_the_case_of_the_attribute_name(tmp_path):
    bundle = _bundle_with_manifest(tmp_path, "Manifest-Version: 1.0\r\npatcher-VERSION: 2.0.0\r\n\r\n")

    assert declared_patcher_version(bundle) == (2, 0, 0)


def test_declared_patcher_version_joins_a_value_continued_on_the_next_line(tmp_path):
    bundle = _bundle_with_manifest(tmp_path, "Manifest-Version: 1.0\r\nPatcher-Version: 2.0.\r\n 0\r\n\r\n")

    assert declared_patcher_version(bundle) == (2, 0, 0)


def test_declared_patcher_version_does_not_read_the_continuation_of_another_attribute(tmp_path):
    bundle = _bundle_with_manifest(
        tmp_path, "Manifest-Version: 1.0\r\nDescription: Patches\r\n Patcher-Version: 2.0.0\r\n\r\n"
    )

    assert declared_patcher_version(bundle) is None


def test_declared_patcher_version_reads_only_the_main_section(tmp_path):
    bundle = _bundle_with_manifest(
        tmp_path,
        "Manifest-Version: 1.0\r\n\r\nName: classes.dex\r\nPatcher-Version: 2.0.0\r\n\r\n",
    )

    assert declared_patcher_version(bundle) is None


def test_declared_patcher_version_takes_the_last_of_a_repeated_attribute(tmp_path):
    bundle = _bundle_with_manifest(
        tmp_path, "Manifest-Version: 1.0\r\nPatcher-Version: 1.5.1\r\nPatcher-Version: 2.0.0\r\n\r\n"
    )

    assert declared_patcher_version(bundle) == (2, 0, 0)


def test_declared_patcher_version_is_unknown_without_the_attribute(tmp_path):
    bundle = write_bundle(tmp_path, "patches.mpp", None)

    assert declared_patcher_version(bundle) is None


def test_declared_patcher_version_is_unknown_for_a_value_that_is_not_a_version(tmp_path):
    bundle = write_bundle(tmp_path, "patches.mpp", "na")

    assert declared_patcher_version(bundle) is None


def test_declared_patcher_version_is_unknown_without_a_manifest(tmp_path):
    path = tmp_path / "patches.mpp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("classes.dex", b"dex")

    assert declared_patcher_version(path) is None


def test_declared_patcher_version_is_unknown_for_a_file_that_is_not_a_zip(tmp_path):
    path = tmp_path / "patches.mpp"
    path.write_bytes(b"this is not a zip file")

    assert declared_patcher_version(path) is None


def test_declared_patcher_version_is_unknown_for_a_missing_file(tmp_path):
    assert declared_patcher_version(tmp_path / "missing.mpp") is None


def test_declared_patcher_version_survives_a_manifest_that_is_not_utf8(tmp_path):
    path = tmp_path / "patches.mpp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\nAuthor: \xff\xfe\r\nPatcher-Version: 1.5.1\r\n\r\n"
        )

    assert declared_patcher_version(path) == (1, 5, 1)


@pytest.mark.parametrize(
    ("version", "generation"),
    [
        ((1, 5, 1), 0),
        ((1, 8, 0), 0),
        ((1, 99, 99), 0),
        ((2, 0, 0), 1),
        ((2, 3, 0), 1),
        ((10, 0, 0), 1),
    ],
)
def test_behavior_generation_changes_with_patcher_2(version, generation):
    assert behavior_generation(version) == generation


def test_behavior_generation_counts_every_listed_change(monkeypatch):
    monkeypatch.setattr(bundle_compat, "BEHAVIOR_CHANGES", ((2, 0, 0), (3, 0, 0)))

    assert [behavior_generation(version) for version in [(1, 5, 1), (2, 0, 0), (2, 9, 9), (3, 0, 0)]] == [
        0,
        1,
        1,
        2,
    ]


def test_split_by_generation_leaves_out_the_bundle_built_for_the_newer_patcher(tmp_path):
    legacy = write_bundle(tmp_path, "legacy.mpp", "1.5.1")
    current = write_bundle(tmp_path, "current.mpp", "2.0.0")

    split = split_by_generation([legacy, current])

    assert split == BundleSplit(kept=[0], dropped=[1], versions=[(1, 5, 1), (2, 0, 0)])


def test_split_by_generation_follows_the_first_bundle(tmp_path):
    current = write_bundle(tmp_path, "current.mpp", "2.0.0")
    legacy = write_bundle(tmp_path, "legacy.mpp", "1.8.0")

    split = split_by_generation([current, legacy])

    assert split == BundleSplit(kept=[0], dropped=[1], versions=[(2, 0, 0), (1, 8, 0)])


def test_split_by_generation_keeps_every_bundle_of_the_generation_of_the_first_one(tmp_path):
    first = write_bundle(tmp_path, "first.mpp", "1.5.1")
    newer = write_bundle(tmp_path, "newer.mpp", "2.0.0-dev.1")
    last = write_bundle(tmp_path, "last.mpp", "1.8.0")

    split = split_by_generation([first, newer, last])

    assert split is not None
    assert split.kept == [0, 2]
    assert split.dropped == [1]


def test_split_by_generation_counts_a_prerelease_of_patcher_2_as_the_new_generation(tmp_path):
    legacy = write_bundle(tmp_path, "legacy.mpp", "1.99.99")
    prerelease = write_bundle(tmp_path, "prerelease.mpp", "2.0.0-dev.1")

    split = split_by_generation([legacy, prerelease])

    assert split is not None
    assert split.dropped == [1]


def test_split_by_generation_has_nothing_to_split_when_all_bundles_share_a_generation(tmp_path):
    older = write_bundle(tmp_path, "older.mpp", "1.5.1")
    newer = write_bundle(tmp_path, "newer.mpp", "1.8.0")

    assert split_by_generation([older, newer]) is None


def test_split_by_generation_has_nothing_to_split_when_all_bundles_are_current(tmp_path):
    first = write_bundle(tmp_path, "first.mpp", "2.0.0")
    second = write_bundle(tmp_path, "second.mpp", "2.1.0")

    assert split_by_generation([first, second]) is None


def test_split_by_generation_has_nothing_to_split_for_a_single_bundle(tmp_path):
    only = write_bundle(tmp_path, "only.mpp", "2.0.0")

    assert split_by_generation([only]) is None
    assert split_by_generation([]) is None


def test_split_by_generation_does_not_open_a_single_bundle(tmp_path):
    assert split_by_generation([tmp_path / "missing.mpp"]) is None


def test_split_by_generation_does_not_guess_when_a_bundle_declares_no_version(tmp_path):
    legacy = write_bundle(tmp_path, "legacy.mpp", "1.5.1")
    undeclared = write_bundle(tmp_path, "undeclared.mpp", None)
    current = write_bundle(tmp_path, "current.mpp", "2.0.0")

    assert split_by_generation([legacy, undeclared, current]) is None
    assert split_by_generation([legacy, current, undeclared]) is None


def test_split_by_generation_does_not_guess_when_the_first_bundle_cannot_be_read(tmp_path):
    current = write_bundle(tmp_path, "current.mpp", "2.0.0")

    assert split_by_generation([tmp_path / "missing.mpp", current]) is None


def test_split_by_generation_accepts_paths_given_as_text(tmp_path):
    legacy = write_bundle(tmp_path, "legacy.mpp", "1.5.1")
    current = write_bundle(tmp_path, "current.mpp", "2.0.0")

    split = split_by_generation([str(legacy), str(current)])

    assert split is not None
    assert split.kept == [0]
