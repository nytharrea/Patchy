from patchy.engine import versions as versions_module
from patchy.engine.versions import (
    extract_cli_version_codes,
    extract_cli_versions,
    pick_latest_version,
    to_apkmirror_version,
)


def test_extract_versions_from_compatible_section():
    output = (
        "Some preamble text from the CLI\n"
        "Most common compatible versions:\n"
        "19.35.36 (5 patches)\n"
        "19.34.42 (3 patches)\n"
        "\n"
        "Trailing text that should not be reached\n"
    )
    result = extract_cli_versions(output)
    assert result == [
        {"version": "19.35.36", "patches": 5},
        {"version": "19.34.42", "patches": 3},
    ]


def test_extract_versions_ignores_non_matching_lines_in_section():
    output = "Most common compatible versions:\nsome unrelated note\n19.35.36 (5 patches)\n\n"
    result = extract_cli_versions(output)
    assert result == [{"version": "19.35.36", "patches": 5}]


def test_extract_versions_handles_singular_patch_count():
    output = "Most common compatible versions:\n19.35.34 (1 patch)\n\n"
    assert extract_cli_versions(output) == [{"version": "19.35.34", "patches": 1}]


def test_extract_versions_handles_the_versioncodes_bracket(monkeypatch):
    warnings = []
    monkeypatch.setattr(versions_module.log, "warn", warnings.append)

    output = (
        "Most common compatible versions:\n"
        "439.0.0.37.89 [versionCodes: ARM64_V8A=331058270, ARMEABI_V7A=331058271] (5 patches)\n\n"
    )
    assert extract_cli_versions(output) == [{"version": "439.0.0.37.89", "patches": 5}]
    assert warnings == []


def test_extract_versions_keeps_every_listed_version_when_codes_are_declared():
    output = (
        "Most common compatible versions:\n"
        "\t582.0.0.50.54 [versionCodes: ARM64_V8A=475417104, ARMEABI_V7A=475417036] (86 patches)\n"
        "\t581.0.0.1.1 (40 patches)\n\n"
    )
    assert extract_cli_versions(output) == [
        {"version": "582.0.0.50.54", "patches": 86},
        {"version": "581.0.0.1.1", "patches": 40},
    ]


def test_extract_version_codes_reads_every_arch_of_the_bracket():
    output = (
        "Package name: com.facebook.katana\n"
        "Most common compatible versions:\n"
        "\t582.0.0.50.54 [versionCodes: ARM64_V8A=475417104, ARMEABI_V7A=475417036] (86 patches)\n\n"
    )
    assert extract_cli_version_codes(output) == {
        "582.0.0.50.54": {"ARM64_V8A": 475417104, "ARMEABI_V7A": 475417036},
    }


def test_extract_version_codes_only_lists_versions_that_declare_codes():
    output = (
        "Most common compatible versions:\n"
        "439.0.0.37.89 [versionCodes: ARM64_V8A=331058270] (5 patches)\n"
        "438.0.0.1.1 (3 patches)\n"
        "437.0.0.1.1 [versionCodes: X86_64=7] (1 patch)\n\n"
    )
    assert extract_cli_version_codes(output) == {
        "439.0.0.37.89": {"ARM64_V8A": 331058270},
        "437.0.0.1.1": {"X86_64": 7},
    }


def test_extract_version_codes_ignores_a_bracket_that_is_not_a_version_code_list():
    output = "Most common compatible versions:\n1.2.3 [experimental] (2 patches)\n\n"
    assert extract_cli_versions(output) == [{"version": "1.2.3", "patches": 2}]
    assert extract_cli_version_codes(output) == {}


def test_extract_version_codes_is_empty_without_codes_for_any_or_a_missing_section(monkeypatch):
    warnings = []
    monkeypatch.setattr(versions_module.log, "warn", warnings.append)

    assert extract_cli_version_codes("Most common compatible versions:\nAny\n\n") == {}
    assert extract_cli_version_codes("Most common compatible versions:\n19.35.36 (5 patches)\n\n") == {}
    assert extract_cli_version_codes("Nothing version-looking in here at all.") == {}
    assert extract_cli_version_codes("") == {}
    assert warnings == []


def test_extract_version_codes_does_not_warn_or_dump_an_unparseable_section(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(versions_module.log, "warn", warnings.append)
    monkeypatch.setattr(versions_module.paths, "diagnostics_dir", lambda: tmp_path)

    assert extract_cli_version_codes("Most common compatible versions:\n* v19.35.36 - 5 patches\n\n") == {}
    assert warnings == []
    assert list(tmp_path.iterdir()) == []


def test_extract_version_codes_stops_at_the_first_blank_line_like_the_version_list():
    output = (
        "Most common compatible versions:\n"
        "1.0.0 [versionCodes: ARM64_V8A=100] (2 patches)\n"
        "\n"
        "2.0.0 [versionCodes: ARM64_V8A=200] (2 patches)\n"
    )
    assert extract_cli_version_codes(output) == {"1.0.0": {"ARM64_V8A": 100}}


def test_extract_versions_returns_empty_for_any_without_warning(monkeypatch):
    warnings = []
    monkeypatch.setattr(versions_module.log, "warn", warnings.append)

    output = "Most common compatible versions:\nAny\n\n"

    assert extract_cli_versions(output) == []
    assert warnings == []


def test_extract_versions_returns_empty_when_no_section_header():
    output = "App: com.example.app\nLatest available version: 439.0.0.37.89\n"
    assert extract_cli_versions(output) == []


def test_extract_versions_returns_empty_when_nothing_version_looking_is_present():
    assert extract_cli_versions("Nothing version-looking in here at all.") == []


def test_no_section_header_logs_nothing(monkeypatch):
    warnings = []
    monkeypatch.setattr(versions_module.log, "warn", warnings.append)

    extract_cli_versions("Available versions: 1.2.3, 1.2.4 and 2.0.0-beta.1 are supported")

    assert warnings == []


def test_section_header_present_but_unparseable_logs_warn_and_returns_empty(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(versions_module.log, "warn", warnings.append)
    monkeypatch.setattr(versions_module.paths, "diagnostics_dir", lambda: tmp_path)

    raw_output = "Most common compatible versions:\n* v19.35.36 - 5 patches\n\n"
    result = extract_cli_versions(raw_output, app_slug="instagram")

    assert result == []
    assert len(warnings) == 1
    dumped = list(tmp_path.glob("list-versions-instagram-*.txt"))
    assert len(dumped) == 1
    assert dumped[0].read_text() == raw_output


def test_extract_versions_empty_input():
    assert extract_cli_versions("") == []


def test_pick_latest_version_prefers_higher_patch_count():
    versions = [
        {"version": "1.2.2", "patches": 10},
        {"version": "1.2.4", "patches": 5},
    ]
    assert pick_latest_version(versions) == "1.2.2"


def test_pick_latest_version_breaks_ties_numerically_not_lexically():
    versions = [
        {"version": "1.2.3", "patches": 5},
        {"version": "1.2.10", "patches": 5},
    ]
    assert pick_latest_version(versions) == "1.2.10"


def test_pick_latest_version_empty_list():
    assert pick_latest_version([]) is None


def test_pick_latest_version_handles_unparseable_version_gracefully():
    versions = [{"version": "abc", "patches": 1}]
    assert pick_latest_version(versions) == "abc"


def test_to_apkmirror_version_replaces_dots_with_dashes():
    assert to_apkmirror_version("19.35.36") == "19-35-36"


def test_to_apkmirror_version_no_dots():
    assert to_apkmirror_version("19") == "19"
