import json

import pytest

from patchy import catalog
from patchy.fetch.bundles import ManifestError
from patchy.publish import telemetry


def _status(key, ok=True, version="1.0", error=None, **timings):
    data = {
        "build_key": key,
        "ok": ok,
        "error": error,
        "version": version,
        "file": f"{key}.apk",
        "pending_pin": None,
    }
    if timings:
        data["timings"] = timings
    return data


def _rows(table):
    return [line for line in table.splitlines() if line.startswith("| `")]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "–"),
        (0, "0.0 s"),
        (4.26, "4.3 s"),
        (59.96, "1m 00s"),
        (60, "1m 00s"),
        (125.4, "2m 05s"),
        (3599.4, "59m 59s"),
        (3600, "1h 00m"),
        (7384, "2h 03m"),
    ],
)
def test_durations_are_short_and_readable(seconds, expected):
    assert telemetry.format_duration(seconds) == expected


def test_the_table_has_one_row_per_planned_build_in_plan_order():
    statuses = {
        "youtube": _status("youtube", version="20.1.2", download=12.3, patch=61.0, total=80.4),
        "gboard": _status("gboard", ok=False, version=None, error="HTTP 500", download=3.0, total=3.5),
    }

    table = telemetry.render_table(["gboard", "youtube", "brave"], statuses)

    assert _rows(table) == [
        "| `gboard` | – | ❌ failed | 3.0 s | – | 3.5 s |",
        "| `youtube` | 20.1.2 | ✅ ok | 12.3 s | 1m 01s | 1m 20s |",
        "| `brave` | – | ⚠️ no status | – | – | – |",
    ]
    assert "| App | Version | Status | Download | Patch | Total |" in table
    assert "1 of 3 build(s) succeeded." in table


def test_the_table_names_the_slowest_download_and_patch():
    statuses = {
        "youtube": _status("youtube", download=12.3, patch=61.0, total=80.0),
        "gboard": _status("gboard", download=130.0, patch=5.0, total=140.0),
    }

    table = telemetry.render_table(["youtube", "gboard"], statuses)

    assert "Slowest download: `gboard` (2m 10s) · Slowest patch: `youtube` (1m 01s)" in table


def test_nothing_is_called_slowest_when_no_times_were_measured():
    table = telemetry.render_table(["youtube"], {"youtube": _status("youtube")})

    assert "Slowest" not in table


def test_failed_and_missing_builds_are_listed_with_a_reason():
    statuses = {"gboard": _status("gboard", ok=False, error="HTTP 500 fetching listing page")}

    table = telemetry.render_table(["gboard", "brave"], statuses)

    assert "### Failures" in table
    assert "- `gboard` — HTTP 500 fetching listing page" in table
    assert "- `brave` — no status file was uploaded" in table


def test_there_is_no_failure_section_when_every_build_succeeded():
    table = telemetry.render_table(["youtube"], {"youtube": _status("youtube", total=1.0)})

    assert "Failures" not in table
    assert "1 of 1 build(s) succeeded." in table


def test_a_failure_reason_is_cut_to_one_escaped_line():
    error = "boom | <b>bad</b> & `x` *y*\nsecond line"
    table = telemetry.render_table(["gboard"], {"gboard": _status("gboard", ok=False, error=error)})

    assert "- `gboard` — boom \\| \\<b\\>bad\\</b\\> \\& \\`x\\` \\*y\\*" in table
    assert "second line" not in table


def test_a_very_long_failure_reason_is_shortened():
    table = telemetry.render_table(["gboard"], {"gboard": _status("gboard", ok=False, error="x" * 500)})

    reason = next(line for line in table.splitlines() if line.startswith("- `gboard`"))
    assert reason.endswith("…")
    assert len(reason) < 140


def test_a_failed_build_without_an_error_message_still_gets_a_reason():
    table = telemetry.render_table(["gboard"], {"gboard": _status("gboard", ok=False, error=None)})

    assert "- `gboard` — unknown error" in table


def test_garbled_timings_are_shown_as_missing():
    status = _status("youtube")
    status["timings"] = {"download": "slow", "patch": True, "total": 3.0}

    table = telemetry.render_table(["youtube"], {"youtube": status})

    assert _rows(table) == ["| `youtube` | 1.0 | ✅ ok | – | – | 3.0 s |"]


def test_a_version_cannot_break_out_of_its_table_cell():
    table = telemetry.render_table(["youtube"], {"youtube": _status("youtube", version="1|2")})

    assert _rows(table) == ["| `youtube` | 1\\|2 | ✅ ok | – | – | – |"]


def _write_status(root, folder, build_key, payload):
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"status-{build_key}.json").write_text(json.dumps(payload))


def test_the_summary_merges_the_build_and_signing_statuses(monkeypatch, tmp_path):
    root = tmp_path / "build"
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(root))
    monkeypatch.setattr(telemetry, "read_manifest", lambda: {"builds": ["youtube", "gboard"]})
    _write_status(root, "artifacts/apk-youtube", "youtube", _status("youtube", download=2.0, patch=3.0, total=6.0))
    _write_status(root, "artifacts/apk-gboard", "gboard", _status("gboard", download=4.0, patch=5.0, total=10.0))
    _write_status(
        root, "signed", "gboard", {"build_key": "gboard", "ok": False, "error": "signing failed: bad keystore"}
    )

    summary = telemetry.render_summary()

    assert _rows(summary) == [
        "| `youtube` | 1.0 | ✅ ok | 2.0 s | 3.0 s | 6.0 s |",
        "| `gboard` | 1.0 | ❌ failed | 4.0 s | 5.0 s | 10.0 s |",
    ]
    assert "- `gboard` — signing failed: bad keystore" in summary


def test_the_summary_lists_the_reporting_builds_when_the_manifest_is_missing(monkeypatch, tmp_path):
    root = tmp_path / "build"
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(root))

    def missing():
        raise ManifestError("manifest not found")

    monkeypatch.setattr(telemetry, "read_manifest", missing)
    _write_status(root, "artifacts/apk-gboard", "gboard", _status("gboard", total=2.0))
    _write_status(root, "artifacts/apk-youtube", "youtube", _status("youtube", total=1.0))

    summary = telemetry.render_summary()

    expected = [f"`{key}`" for key in catalog.BUILDS if key in ("gboard", "youtube")]
    assert len(expected) == 2
    assert [row.split("|")[1].strip() for row in _rows(summary)] == expected


def test_the_summary_is_empty_when_nothing_was_planned_or_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(tmp_path / "build"))

    def missing():
        raise ManifestError("manifest not found")

    monkeypatch.setattr(telemetry, "read_manifest", missing)

    assert telemetry.render_summary() == ""


def test_statuses_of_unknown_builds_are_ignored(monkeypatch, tmp_path):
    root = tmp_path / "build"
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(root))

    def missing():
        raise ManifestError("manifest not found")

    monkeypatch.setattr(telemetry, "read_manifest", missing)
    _write_status(root, "artifacts/apk-ghost", "ghost", _status("ghost", total=1.0))

    assert telemetry.render_summary() == ""
