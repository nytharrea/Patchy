import struct
import zipfile

import pytest

from patchy.engine import label
from patchy.engine.label import LabelChange, LabelError

from .axml import build_apk, build_manifest, reference_label, text_label

BROKEN = text_label("@string/four_ones")
RESOURCE = reference_label(0x7F130012)


def _labels(manifest: bytes) -> list[tuple[str, int, str | None]]:
    _, elements, _ = label._parse_manifest(manifest)
    return [(e.name, e.label_type, e.label_text) for e in elements if e.label_offset is not None]


def _walk(manifest: bytes) -> list[int]:
    total = struct.unpack_from("<I", manifest, 4)[0]
    sizes = []
    position = 8
    while position < total:
        kind, _, size = struct.unpack_from("<HHI", manifest, position)
        sizes.append(kind)
        position += size
    assert position == total == len(manifest)
    return sizes


@pytest.mark.parametrize("utf8", [True, False])
def test_a_label_that_is_plain_reference_text_is_replaced_by_the_fallback(utf8):
    manifest = build_manifest(BROKEN, utf8=utf8)

    updated, changes = label.rewrite_manifest(manifest, None, "1.1.1.1")

    assert changes == [LabelChange("application", "@string/four_ones", "1.1.1.1", False)]
    assert _labels(updated) == [
        ("application", label.TYPE_STRING, "1.1.1.1"),
        ("activity", label.TYPE_STRING, "Other"),
    ]


@pytest.mark.parametrize("utf8", [True, False])
def test_a_real_resource_reference_is_left_alone(utf8):
    manifest = build_manifest(RESOURCE, utf8=utf8)

    updated, changes = label.rewrite_manifest(manifest, None, "1.1.1.1")

    assert changes == []
    assert updated == manifest


def test_a_plain_name_is_left_alone():
    manifest = build_manifest(text_label("1.1.1.1"))

    assert label.rewrite_manifest(manifest, None, "Something else") == (manifest, [])


@pytest.mark.parametrize("utf8", [True, False])
def test_an_explicit_label_replaces_a_working_reference(utf8):
    manifest = build_manifest(RESOURCE, utf8=utf8)

    updated, changes = label.rewrite_manifest(manifest, "1.1.1.1", "ignored")

    assert changes == [LabelChange("application", "@0x7f130012", "1.1.1.1", True)]
    assert _labels(updated)[0] == ("application", label.TYPE_STRING, "1.1.1.1")


def test_an_explicit_label_equal_to_the_current_one_changes_nothing():
    manifest = build_manifest(text_label("1.1.1.1"))

    assert label.rewrite_manifest(manifest, "1.1.1.1", "ignored") == (manifest, [])


def test_the_launcher_activity_label_is_replaced_and_other_activities_are_not():
    manifest = build_manifest(BROKEN, launcher=reference_label(0x7F130013), other="Settings")

    updated, changes = label.rewrite_manifest(manifest, "WARP", "ignored")

    assert [(c.element, c.after) for c in changes] == [("application", "WARP"), ("activity", "WARP")]
    assert _labels(updated) == [
        ("application", label.TYPE_STRING, "WARP"),
        ("activity", label.TYPE_STRING, "WARP"),
        ("activity", label.TYPE_STRING, "Settings"),
    ]


def test_a_broken_launcher_label_is_repaired_without_an_explicit_label():
    manifest = build_manifest(RESOURCE, launcher=text_label("@string/four_ones"), other="@string/other")

    updated, changes = label.rewrite_manifest(manifest, None, "1.1.1.1")

    assert [(c.element, c.before, c.after, c.forced) for c in changes] == [
        ("activity", "@string/four_ones", "1.1.1.1", False)
    ]
    assert _labels(updated)[2] == ("activity", label.TYPE_STRING, "@string/other")


def test_an_explicit_label_needs_a_label_attribute_to_replace():
    manifest = build_manifest(None, launcher=None)

    with pytest.raises(LabelError, match="no android:label"):
        label.rewrite_manifest(manifest, "1.1.1.1", "ignored")


def test_a_manifest_without_labels_is_fine_when_no_name_is_forced():
    manifest = build_manifest(None, launcher=None)

    assert label.rewrite_manifest(manifest, None, "1.1.1.1") == (manifest, [])


@pytest.mark.parametrize("utf8", [True, False])
def test_only_the_label_and_the_string_pool_change(utf8):
    manifest = build_manifest(BROKEN, launcher=RESOURCE, utf8=utf8)
    pool_before, elements_before, _ = label._parse_manifest(manifest)

    updated, _ = label.rewrite_manifest(manifest, None, "1.1.1.1")
    pool_after, elements_after, _ = label._parse_manifest(updated)

    assert pool_after.strings[: len(pool_before.strings)] == pool_before.strings
    assert pool_after.strings[len(pool_before.strings) :] == ["1.1.1.1"]
    assert [(e.name, e.parent, e.android_name, e.launcher) for e in elements_after] == [
        (e.name, e.parent, e.android_name, e.launcher) for e in elements_before
    ]
    assert elements_after[2].label_type == elements_before[2].label_type == label.TYPE_REFERENCE
    assert elements_after[2].label_data == elements_before[2].label_data


@pytest.mark.parametrize("utf8", [True, False])
def test_the_chunk_sizes_of_the_result_add_up(utf8):
    updated, _ = label.rewrite_manifest(build_manifest(BROKEN, utf8=utf8), None, "1.1.1.1")

    kinds = _walk(updated)

    assert kinds[0] == label.STRING_POOL
    assert kinds[1] == label.RESOURCE_MAP
    assert kinds.count(label.START_ELEMENT) == kinds.count(label.END_ELEMENT) == 7


@pytest.mark.parametrize("utf8", [True, False])
@pytest.mark.parametrize("name", ["Çağrı Ağı 🌐", "x" * 200, "WARP"])
def test_unusual_names_round_trip(utf8, name):
    updated, _ = label.rewrite_manifest(build_manifest(BROKEN, utf8=utf8), name, "ignored")

    assert _labels(updated)[0][2] == name
    assert _walk(updated)


def test_fixing_twice_changes_nothing_the_second_time():
    once, _ = label.rewrite_manifest(build_manifest(BROKEN), None, "1.1.1.1")

    assert label.rewrite_manifest(once, None, "1.1.1.1") == (once, [])


def test_a_pool_with_styled_strings_is_refused():
    with pytest.raises(LabelError, match="styled strings"):
        label.rewrite_manifest(build_manifest(BROKEN, styles=1), None, "1.1.1.1")


@pytest.mark.parametrize("data", [b"", b"not a manifest at all", b"\x03\x00\x08\x00\xff\xff\xff\x7f"])
def test_data_that_is_not_a_manifest_is_refused(data):
    with pytest.raises(LabelError):
        label.rewrite_manifest(data, None, "1.1.1.1")


def test_a_truncated_manifest_is_refused():
    manifest = build_manifest(BROKEN)

    with pytest.raises(LabelError):
        label.rewrite_manifest(manifest[:-40], None, "1.1.1.1")


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
def test_names_that_cannot_be_used_are_refused(name):
    with pytest.raises(LabelError, match="between 1 and 255"):
        label.rewrite_manifest(build_manifest(BROKEN), name, "ignored")


def test_the_fallback_is_checked_too():
    with pytest.raises(LabelError, match="between 1 and 255"):
        label.rewrite_manifest(build_manifest(BROKEN), None, "")


def test_fix_apk_label_replaces_only_the_manifest_entry(tmp_path):
    apk = build_apk(tmp_path / "app.apk", build_manifest(BROKEN))
    with zipfile.ZipFile(apk) as archive:
        before = [(i.filename, i.CRC, i.file_size, i.compress_type) for i in archive.infolist()]

    changes = label.fix_apk_label(apk, None, "1.1.1.1")

    assert changes == [LabelChange("application", "@string/four_ones", "1.1.1.1", False)]
    with zipfile.ZipFile(apk) as archive:
        after = [(i.filename, i.CRC, i.file_size, i.compress_type) for i in archive.infolist()]
        assert archive.testzip() is None
        assert _labels(archive.read("AndroidManifest.xml"))[0] == ("application", label.TYPE_STRING, "1.1.1.1")
    assert [row[0] for row in after] == [row[0] for row in before]
    assert [row for row in after if row[0] != "AndroidManifest.xml"] == [
        row for row in before if row[0] != "AndroidManifest.xml"
    ]
    assert dict((row[0], row[3]) for row in after) == dict((row[0], row[3]) for row in before)


def test_fix_apk_label_keeps_the_payload_of_every_other_entry(tmp_path):
    apk = build_apk(tmp_path / "app.apk", build_manifest(BROKEN))
    with zipfile.ZipFile(apk) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist() if name != "AndroidManifest.xml"}

    label.fix_apk_label(apk, None, "1.1.1.1")

    with zipfile.ZipFile(apk) as archive:
        assert {
            name: archive.read(name) for name in archive.namelist() if name != "AndroidManifest.xml"
        } == payloads


def test_fix_apk_label_does_not_touch_a_healthy_apk(tmp_path):
    apk = build_apk(tmp_path / "app.apk", build_manifest(RESOURCE))
    before = apk.read_bytes()

    assert label.fix_apk_label(apk, None, "1.1.1.1") == []
    assert apk.read_bytes() == before


def test_fix_apk_label_is_repeatable(tmp_path):
    apk = build_apk(tmp_path / "app.apk", build_manifest(BROKEN))

    label.fix_apk_label(apk, "1.1.1.1", "ignored")
    settled = apk.read_bytes()

    assert label.fix_apk_label(apk, "1.1.1.1", "ignored") == []
    assert apk.read_bytes() == settled


def test_fix_apk_label_leaves_no_temporary_file_behind(tmp_path):
    apk = build_apk(tmp_path / "app.apk", build_manifest(BROKEN))

    label.fix_apk_label(apk, None, "1.1.1.1")

    assert sorted(path.name for path in tmp_path.iterdir()) == ["app.apk"]


def test_fix_apk_label_leaves_the_apk_alone_when_the_manifest_cannot_be_used(tmp_path):
    apk = build_apk(tmp_path / "app.apk", build_manifest(BROKEN, styles=1))
    before = apk.read_bytes()

    with pytest.raises(LabelError):
        label.fix_apk_label(apk, None, "1.1.1.1")

    assert apk.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["app.apk"]


def test_fix_apk_label_reports_an_apk_without_a_manifest(tmp_path):
    apk = tmp_path / "app.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"dex")

    with pytest.raises(LabelError, match="cannot read AndroidManifest.xml"):
        label.fix_apk_label(apk, None, "1.1.1.1")


def test_fix_apk_label_reports_a_file_that_is_not_a_zip(tmp_path):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"this is not an apk")

    with pytest.raises(LabelError, match="cannot read AndroidManifest.xml"):
        label.fix_apk_label(apk, None, "1.1.1.1")


def test_fix_apk_label_reports_a_missing_file(tmp_path):
    with pytest.raises(LabelError, match="cannot read AndroidManifest.xml"):
        label.fix_apk_label(tmp_path / "missing.apk", None, "1.1.1.1")
