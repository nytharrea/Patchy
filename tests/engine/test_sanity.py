import io
import zipfile

import pytest

from patchy.engine import sanity
from patchy.engine.sanity import ApkFacts, SanityError

from .axml import build_apk, build_manifest

MANIFEST = build_manifest(None, package="com.example.app", version_name="19.35.36", version_code=1535)


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path


def _apk_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _facts(**fields):
    values = {
        "package": "com.example.app",
        "version_name": "19.35.36",
        "version_code": 1535,
        "abis": frozenset({"arm64-v8a"}),
        "has_dex": True,
    }
    return ApkFacts(**{**values, **fields})


def test_the_facts_of_a_plain_apk_are_read_from_its_manifest_and_files(tmp_path):
    facts = sanity.inspect_apk(build_apk(tmp_path / "app.apk", MANIFEST))

    assert facts == ApkFacts("com.example.app", "19.35.36", 1535, frozenset({"arm64-v8a"}), True, None)


def test_every_architecture_with_a_library_is_listed_but_folders_alone_are_not(tmp_path):
    apk = _zip(
        tmp_path / "app.apk",
        {
            "AndroidManifest.xml": MANIFEST,
            "classes.dex": b"dex",
            "lib/arm64-v8a/libone.so": b"1",
            "lib/arm64-v8a/libtwo.so": b"2",
            "lib/armeabi-v7a/libone.so": b"3",
            "lib/x86_64/": b"",
            "lib/readme.txt": b"not a library folder",
            "assets/lib/x86/libfake.so": b"not under lib/",
        },
    )

    assert sanity.inspect_apk(apk).abis == frozenset({"arm64-v8a", "armeabi-v7a"})


def test_an_apk_without_classes_dex_is_reported_as_having_none(tmp_path):
    apk = _zip(tmp_path / "app.apk", {"AndroidManifest.xml": MANIFEST})

    assert sanity.inspect_apk(apk).has_dex is False


def test_a_bundle_is_inspected_through_its_base_apk(tmp_path):
    inner = _apk_bytes({"AndroidManifest.xml": MANIFEST, "classes.dex": b"dex", "lib/arm64-v8a/liba.so": b"x"})
    bundle = _zip(
        tmp_path / "app.apkm", {"info.json": b"{}", "base.apk": inner, "split_config.xxhdpi.apk": b"junk"}
    )

    facts = sanity.inspect_apk(bundle)

    assert (facts.package, facts.version_name, facts.version_code) == ("com.example.app", "19.35.36", 1535)
    assert facts.abis == frozenset({"arm64-v8a"})
    assert facts.has_dex is True


def test_a_base_apk_in_a_folder_is_found_and_preferred_over_other_inner_apks(tmp_path):
    inner = _apk_bytes({"AndroidManifest.xml": MANIFEST, "classes.dex": b"dex"})
    other = _apk_bytes({"AndroidManifest.xml": build_manifest(None, package="com.other.app")})
    bundle = _zip(tmp_path / "app.xapk", {"a_first.apk": other, "splits/base.apk": inner})

    assert sanity.inspect_apk(bundle).package == "com.example.app"


def test_without_a_base_apk_the_first_inner_apk_is_used(tmp_path):
    inner = _apk_bytes({"AndroidManifest.xml": MANIFEST, "classes.dex": b"dex"})
    bundle = _zip(tmp_path / "app.xapk", {"readme.txt": b"hi", "main.apk": inner})

    assert sanity.inspect_apk(bundle).package == "com.example.app"


def test_an_archive_with_neither_a_manifest_nor_an_inner_apk_is_refused(tmp_path):
    archive = _zip(tmp_path / "app.apk", {"readme.txt": b"hi"})

    with pytest.raises(SanityError, match="holds no AndroidManifest.xml and no inner .apk"):
        sanity.inspect_apk(archive)


def test_an_inner_apk_without_a_manifest_is_refused(tmp_path):
    bundle = _zip(tmp_path / "app.apkm", {"base.apk": _apk_bytes({"classes.dex": b"dex"})})

    with pytest.raises(SanityError, match=r"base.apk inside app.apkm holds no AndroidManifest.xml"):
        sanity.inspect_apk(bundle)


def test_a_file_that_is_not_a_zip_is_refused(tmp_path):
    path = tmp_path / "app.apk"
    path.write_bytes(b"<html>Not found</html>")

    with pytest.raises(SanityError, match="app.apk is not a readable APK"):
        sanity.inspect_apk(path)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(SanityError, match="is not a readable APK"):
        sanity.inspect_apk(tmp_path / "missing.apk")


def test_an_inner_apk_that_is_not_a_zip_is_refused(tmp_path):
    bundle = _zip(tmp_path / "app.apkm", {"base.apk": b"not a zip"})

    with pytest.raises(SanityError, match="is not a readable APK"):
        sanity.inspect_apk(bundle)


def test_a_manifest_that_cannot_be_read_is_kept_as_a_fact_instead_of_an_error(tmp_path):
    apk = _zip(
        tmp_path / "app.apk",
        {"AndroidManifest.xml": b"plain text", "classes.dex": b"dex", "lib/arm64-v8a/liba.so": b"x"},
    )

    facts = sanity.inspect_apk(apk)

    assert facts.manifest_error
    assert (facts.package, facts.version_name, facts.version_code) == (None, None, None)
    assert facts.abis == frozenset({"arm64-v8a"})
    assert facts.has_dex is True


def test_the_facts_are_plain_data_with_sorted_architectures():
    facts = _facts(abis=frozenset({"x86_64", "arm64-v8a"}))

    assert facts.as_dict() == {
        "package": "com.example.app",
        "version_name": "19.35.36",
        "version_code": 1535,
        "abis": ["arm64-v8a", "x86_64"],
    }


def test_inspecting_quietly_gives_nothing_for_a_bad_file(tmp_path):
    bad = tmp_path / "bad.apk"
    bad.write_bytes(b"nope")

    assert sanity.inspect_quietly(bad) is None
    assert sanity.inspect_quietly(build_apk(tmp_path / "app.apk", MANIFEST)).package == "com.example.app"


@pytest.mark.parametrize(
    ("requested", "actual", "expected"),
    [
        ("19.35.36", "19.35.36", True),
        ("19.35.36", "19.35.36.1", True),
        ("19.35", "19.35.36", True),
        ("2.1.0", "2.1.0-beta", True),
        ("2.1.0-beta", "2.1.0", True),
        ("6.7.1-release.1", "6.7.1", True),
        ("19.35.36", "19.36.0", False),
        ("19.35.36", "20.0", False),
        ("1.2.3", "1.2.4", False),
    ],
)
def test_versions_agree_when_one_is_a_prefix_of_the_other(requested, actual, expected):
    assert sanity.same_version(requested, actual) is expected


def test_a_download_that_matches_the_build_has_no_problems():
    assert sanity.input_problems(_facts(), package="com.example.app", version="19.35.36", arch="arm64-v8a") == []


def test_nothing_is_said_about_a_download_that_could_not_be_inspected():
    assert sanity.input_problems(None, package="com.example.app", version="1.0", arch="arm64-v8a") == []
    unreadable = ApkFacts(None, None, None, frozenset(), True, "damaged")
    assert sanity.input_problems(unreadable, package="com.example.app", version="1.0", arch="arm64-v8a") == []


def test_a_download_for_another_package_is_reported():
    problems = sanity.input_problems(
        _facts(package="com.other.app"), package="com.example.app", version="19.35.36", arch="arm64-v8a"
    )

    assert problems == ["The downloaded APK is com.other.app, but this build is configured for com.example.app."]


def test_a_download_with_another_version_is_reported():
    problems = sanity.input_problems(
        _facts(version_name="19.36.1"), package="com.example.app", version="19.35.36", arch="arm64-v8a"
    )

    assert problems == ["The downloaded APK reports version 19.36.1, but 19.35.36 was requested."]


@pytest.mark.parametrize("version", ["latest", ""])
def test_no_version_is_expected_when_the_latest_was_asked_for(version):
    problems = sanity.input_problems(
        _facts(version_name="99.0"), package="com.example.app", version=version, arch="arm64-v8a"
    )

    assert problems == []


def test_a_download_without_a_version_name_is_not_compared():
    problems = sanity.input_problems(
        _facts(version_name=None), package="com.example.app", version="19.35.36", arch="arm64-v8a"
    )

    assert problems == []


def test_a_download_without_the_wanted_architecture_is_reported():
    problems = sanity.input_problems(
        _facts(abis=frozenset({"x86_64", "armeabi-v7a"})),
        package="com.example.app",
        version="19.35.36",
        arch="arm64-v8a",
    )

    assert problems == [
        "The downloaded APK ships native libraries for armeabi-v7a, x86_64 but not for arm64-v8a, "
        "the only architecture the patcher keeps."
    ]


def test_a_download_without_native_libraries_is_fine_for_any_architecture():
    problems = sanity.input_problems(
        _facts(abis=frozenset()), package="com.example.app", version="19.35.36", arch="arm64-v8a"
    )

    assert problems == []


def test_no_architecture_is_expected_when_none_is_configured():
    problems = sanity.input_problems(
        _facts(abis=frozenset({"x86"})), package="com.example.app", version="19.35.36", arch=""
    )

    assert problems == []


def test_every_problem_of_a_download_is_listed():
    original = _facts(package="com.other.app", version_name="1.0", abis=frozenset({"x86"}))

    problems = sanity.input_problems(original, package="com.example.app", version="2.0", arch="arm64-v8a")

    assert len(problems) == 3


def test_a_healthy_patched_apk_has_no_problems():
    assert sanity.output_problems(_facts(), arch="arm64-v8a", original=_facts()) == []


def test_a_patched_apk_without_classes_dex_is_an_error():
    with pytest.raises(SanityError, match="no classes.dex"):
        sanity.output_problems(_facts(has_dex=False), arch="arm64-v8a")


def test_a_patched_apk_with_an_unreadable_manifest_is_reported():
    patched = ApkFacts(None, None, None, frozenset({"arm64-v8a"}), True, "damaged string pool")

    problems = sanity.output_problems(patched, arch="arm64-v8a")

    assert problems == ["The manifest of the patched APK could not be read: damaged string pool"]


def test_leftover_architectures_in_a_patched_apk_are_reported_in_order():
    patched = _facts(abis=frozenset({"x86_64", "arm64-v8a", "armeabi-v7a"}))

    problems = sanity.output_problems(patched, arch="arm64-v8a")

    assert problems == ["The patched APK still holds native libraries for armeabi-v7a, x86_64."]


def test_losing_the_kept_architecture_is_reported():
    patched = _facts(abis=frozenset())

    problems = sanity.output_problems(patched, arch="arm64-v8a", original=_facts())

    assert problems == ["The patched APK lost the arm64-v8a native libraries of the original."]


def test_losing_an_architecture_the_original_never_had_is_not_reported():
    original = _facts(abis=frozenset({"x86"}))

    assert sanity.output_problems(_facts(abis=frozenset()), arch="arm64-v8a", original=original) == []


def test_no_architecture_checks_are_made_when_none_is_configured():
    patched = _facts(abis=frozenset({"x86", "arm64-v8a"}))

    assert sanity.output_problems(patched, arch="", original=_facts()) == []
