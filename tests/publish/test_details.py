from patchy.publish import details


def test_every_reader_tolerates_a_missing_status():
    assert details.applied_patches(None) == []
    assert details.failed_patches(None) == []
    assert details.attempt_list(None) == []
    assert details.warning_texts(None) == []
    assert details.is_forced(None) is False
    assert details.tried_versions(None) == []


def test_every_reader_ignores_garbled_values():
    status = {
        "patches": ["not", "a", "dict"],
        "attempts": "none",
        "warnings": {"a": 1},
        "forced": "yes",
    }

    assert details.applied_patches(status) == []
    assert details.failed_patches(status) == []
    assert details.attempt_list(status) == []
    assert details.warning_texts(status) == []
    assert details.is_forced(status) is False


def test_the_applied_and_failed_patches_are_read_from_the_report():
    status = {
        "patches": {
            "applied": ["Hide ads", 3, "", "Video ads"],
            "failed": [{"name": "Broken", "error": "boom"}, {"name": ""}, "junk", {"name": "Quiet"}],
        }
    }

    assert details.applied_patches(status) == ["Hide ads", "Video ads"]
    assert details.failed_patches(status) == [("Broken", "boom"), ("Quiet", "")]


def test_attempts_keep_their_order_and_fill_in_missing_parts():
    status = {
        "attempts": [
            {"version": "9.9.9", "stage": "patch", "reason": "boom"},
            {"version": "8.8.8"},
            {"stage": "patch"},
            "junk",
            {"version": "9.9.9", "stage": "download", "reason": "again"},
        ]
    }

    assert details.attempt_list(status) == [
        ("9.9.9", "patch", "boom"),
        ("8.8.8", "build", "unknown reason"),
        ("9.9.9", "download", "again"),
    ]
    assert details.tried_versions(status) == ["9.9.9", "8.8.8"]


def test_warnings_and_the_force_flag_are_read():
    assert details.warning_texts({"warnings": ["one", "", 2, "two"]}) == ["one", "two"]
    assert details.is_forced({"forced": True}) is True


def test_text_is_squashed_to_one_line_and_cut_with_an_ellipsis():
    assert details.one_line("a\n  b\tc") == "a b c"
    cut = details.one_line("x" * 500, 20)

    assert len(cut) == 20
    assert cut.endswith("…")
    assert details.attempt_text(("1.2", "patch", "bad\nthing")) == "1.2 (patch): bad thing"
