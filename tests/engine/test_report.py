import json

import pytest

from patchy.engine import report


def test_squash_collapses_every_kind_of_whitespace_into_single_spaces():
    assert report.squash("  first \n\n second\tthird  ") == "first second third"


def test_squash_leaves_text_that_fits_alone():
    text = "x" * report.REASON_LIMIT

    assert report.squash(text) == text


def test_squash_cuts_long_text_to_the_limit_and_marks_the_cut():
    result = report.squash("x" * 500)

    assert len(result) == report.REASON_LIMIT
    assert result.endswith("…")
    assert result[:-1] == "x" * (report.REASON_LIMIT - 1)


def test_squash_takes_a_custom_limit_and_drops_the_space_before_the_mark():
    assert report.squash("hello world", 7) == "hello…"
    assert report.squash("abcdefghijklmnop", 10) == "abcdefghi…"


def test_parse_report_reads_a_successful_run():
    data = {
        "success": True,
        "outputPath": "/work/out/app-patched.apk",
        "packageName": "com.example.app",
        "appliedPatches": ["Hide ads", "Custom branding"],
        "failedPatches": [],
    }

    assert report.parse_report(data) == {
        "applied": ["Hide ads", "Custom branding"],
        "failed": [],
        "output": "/work/out/app-patched.apk",
    }


@pytest.mark.parametrize("data", [None, [], "text", 12, ["success"]])
def test_parse_report_refuses_data_that_is_not_an_object(data):
    assert report.parse_report(data) is None


def test_parse_report_keeps_the_failure_reason_of_a_failed_run():
    data = {
        "success": False,
        "appliedPatches": ["Hide ads"],
        "failedPatches": [{"name": "Custom branding", "error": "boom"}],
        "failureReason": "Patching failed",
        "failureDetail": "ignored while a reason exists",
    }

    assert report.parse_report(data) == {
        "applied": ["Hide ads"],
        "failed": [{"name": "Custom branding", "error": "boom"}],
        "reason": "Patching failed",
    }


def test_parse_report_falls_back_to_the_failure_detail():
    result = report.parse_report({"success": False, "failureDetail": "the detail"})

    assert result is not None
    assert result["reason"] == "the detail"


def test_parse_report_falls_back_to_the_first_failed_step_with_an_error():
    data = {
        "success": False,
        "stepResults": [
            {"step": "load", "success": True},
            {"step": "verify", "success": False},
            {"step": "patch", "success": False, "error": "kaboom"},
            {"step": "write", "success": False, "error": "later"},
        ],
    }

    result = report.parse_report(data)

    assert result is not None
    assert result["reason"] == "kaboom"


@pytest.mark.parametrize(
    "data",
    [
        {"success": False},
        {"success": False, "stepResults": "not a list"},
        {"success": False, "stepResults": [{"step": "patch", "success": False}]},
        {"success": False, "stepResults": ["junk", 3]},
    ],
)
def test_parse_report_has_no_reason_when_the_run_names_none(data):
    result = report.parse_report(data)

    assert result is not None
    assert "reason" not in result


def test_parse_report_gives_no_reason_for_a_successful_run_even_if_one_is_present():
    result = report.parse_report({"success": True, "failureReason": "stale"})

    assert result is not None
    assert "reason" not in result


def test_parse_report_treats_a_missing_success_flag_as_a_failure():
    result = report.parse_report({"failureReason": "no flag"})

    assert result is not None
    assert result["reason"] == "no flag"


def test_parse_report_drops_junk_duplicate_and_empty_patch_names():
    result = report.parse_report({"success": True, "appliedPatches": ["A", 1, "", None, "A", "B", ["C"]]})

    assert result is not None
    assert result["applied"] == ["A", "B"]


@pytest.mark.parametrize("value", [None, "A", {"A": 1}, 5])
def test_parse_report_reads_a_patch_list_that_is_not_a_list_as_empty(value):
    result = report.parse_report({"success": True, "appliedPatches": value, "failedPatches": value})

    assert result is not None
    assert result["applied"] == []
    assert result["failed"] == []


def test_parse_report_reads_failed_patches_defensively():
    data = {
        "success": False,
        "failedPatches": [
            {"name": "Complete", "error": "boom"},
            {"name": "No error"},
            {"name": "Empty error", "error": ""},
            {"name": "Numeric error", "error": 12},
            {"name": "", "error": "nameless"},
            {"error": "no name at all"},
            {"name": 7, "error": "name is not text"},
            "not an object",
        ],
    }

    result = report.parse_report(data)

    assert result is not None
    assert result["failed"] == [
        {"name": "Complete", "error": "boom"},
        {"name": "No error", "error": ""},
        {"name": "Empty error", "error": ""},
        {"name": "Numeric error", "error": "12"},
    ]


@pytest.mark.parametrize("value", [None, "", 5, ["x"]])
def test_parse_report_ignores_an_output_path_that_is_not_text(value):
    result = report.parse_report({"success": True, "outputPath": value})

    assert result is not None
    assert "output" not in result


def test_read_report_parses_a_result_file(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"success": True, "appliedPatches": ["A"], "outputPath": "/o.apk"}))

    assert report.read_report(path) == {"applied": ["A"], "failed": [], "output": "/o.apk"}
    assert report.read_report(str(path)) == {"applied": ["A"], "failed": [], "output": "/o.apk"}


def test_read_report_returns_none_for_a_missing_file(tmp_path):
    assert report.read_report(tmp_path / "missing.json") is None


def test_read_report_returns_none_when_the_path_is_a_directory(tmp_path):
    assert report.read_report(tmp_path) is None


@pytest.mark.parametrize("content", ["", "{not json", "[1, 2]", '"text"'])
def test_read_report_returns_none_for_a_file_that_holds_no_report(tmp_path, content):
    path = tmp_path / "result.json"
    path.write_text(content)

    assert report.read_report(path) is None


def test_read_report_returns_none_for_bytes_that_are_not_text(tmp_path):
    path = tmp_path / "result.json"
    path.write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")

    assert report.read_report(path) is None


def _failed(*patches):
    return {"applied": [], "failed": [{"name": name, "error": error} for name, error in patches]}


def test_failure_reason_names_the_first_failed_patch_and_its_error():
    assert report.failure_reason("ignored", _failed(("Hide ads", "boom"))) == "Hide ads: boom"


def test_failure_reason_counts_the_other_failed_patches():
    result = report.failure_reason("ignored", _failed(("Hide ads", "boom"), ("Branding", "x"), ("Ads 2", "y")))

    assert result == "Hide ads: boom (+2 more)"


def test_failure_reason_names_a_failed_patch_that_has_no_error():
    assert report.failure_reason("ignored", _failed(("Hide ads", ""))) == "Hide ads"
    assert report.failure_reason("ignored", _failed(("Hide ads", ""), ("Other", ""))) == "Hide ads (+1 more)"


def test_failure_reason_puts_a_multi_line_patch_error_on_one_line():
    assert report.failure_reason("ignored", _failed(("Hide ads", "line one\n  line two"))) == (
        "Hide ads: line one line two"
    )


def test_failure_reason_shortens_a_long_patch_error():
    result = report.failure_reason("ignored", _failed(("Hide ads", "e" * 400)))

    assert result == "Hide ads: " + "e" * (report.PATCH_ERROR_LIMIT - 1) + "…"
    assert len(result) <= report.REASON_LIMIT


def test_failure_reason_never_exceeds_the_overall_limit():
    result = report.failure_reason("ignored", _failed(("N" * 150, "e" * 400), ("Other", "x")))

    assert len(result) == report.REASON_LIMIT
    assert result.endswith("…")


def test_failure_reason_prefers_the_failed_patches_over_the_report_reason_and_the_message():
    data = {"applied": [], "failed": [{"name": "Hide ads", "error": "boom"}], "reason": "Patching failed"}

    assert report.failure_reason("ERROR: something else", data) == "Hide ads: boom"


def test_failure_reason_uses_the_report_reason_when_no_patch_failed():
    data = {"applied": ["A"], "failed": [], "reason": "  Patching   aborted  "}

    assert report.failure_reason("ERROR: something else", data) == "Patching aborted"


def test_failure_reason_reads_the_message_when_the_report_has_nothing_to_say():
    data = {"applied": ["A"], "failed": []}

    assert report.failure_reason("Patch failed (exit 1):\nERROR: from the log", data) == "from the log"


def test_failure_reason_reads_the_message_without_a_report():
    assert report.failure_reason("Patch failed (exit 1):\nERROR: from the log") == "from the log"
    assert report.failure_reason("Patch failed (exit 1):\nERROR: from the log", None) == "from the log"


def test_failure_reason_joins_at_most_two_error_lines():
    message = (
        "Patch failed (exit 1):\n"
        "INFO: starting\n"
        "ERROR: first problem\n"
        "  FAILED: second problem\n"
        "ERROR: third problem\n"
    )

    assert report.failure_reason(message) == "first problem | second problem"


def test_failure_reason_matches_the_error_prefix_in_any_case_and_with_spacing():
    assert report.failure_reason("error : lower case") == "lower case"
    assert report.failure_reason("Failed:\tnarrow") == "narrow"


def test_failure_reason_ignores_a_prefix_that_has_no_text_after_it():
    assert report.failure_reason("Patch failed (exit 1):\nERROR:\nreal cause here") == "real cause here"


def test_failure_reason_takes_the_first_useful_line_when_no_line_is_marked_as_an_error():
    message = "Patch failed (exit 1):\n\n   \nSomething crashed badly\nat Some.Place(Some.kt:1)\n"

    assert report.failure_reason(message) == "Something crashed badly"


def test_failure_reason_keeps_a_bare_failure_header_when_there_is_nothing_better():
    assert report.failure_reason("Patch failed (exit 1)") == "Patch failed (exit 1)"
    assert report.failure_reason("Patch failed (exit 137):") == "Patch failed (exit 137):"


def test_failure_reason_shortens_error_lines_to_the_limit():
    result = report.failure_reason("ERROR: " + "e" * 500)

    assert len(result) == report.REASON_LIMIT
    assert result.endswith("…")


@pytest.mark.parametrize("message", ["", "   ", "\n\n"])
def test_failure_reason_has_a_last_resort_for_an_empty_message(message):
    assert report.failure_reason(message) == "unknown error"
