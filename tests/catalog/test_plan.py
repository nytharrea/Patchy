import json
import re
from datetime import UTC, datetime

import pytest

from patchy import catalog, cli
from patchy.catalog import plan, validate


def _read_output(path):
    return {line.split("=", 1)[0]: line.split("=", 1)[1] for line in path.read_text().splitlines()}


def test_make_plan_defaults_to_every_build():
    result = plan.make_plan()
    assert result.matrix == list(catalog.BUILDS)
    assert "youtube" in result.matrix
    assert "tiktok-hxreborn" in result.matrix


def test_make_plan_tag_and_name_format():
    result = plan.make_plan(now=datetime(2026, 10, 4, 14, 30, 5, tzinfo=UTC))
    assert result.tag == "build-2026-10-04T14-30-05"
    assert result.name == "Patched APKs - 4 October 2026"
    assert re.match(r"^build-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$", plan.make_plan().tag)


def test_tag_prefix_is_what_release_cleanup_relies_on():
    assert plan.make_plan().tag.startswith(plan.TAG_PREFIX)


@pytest.mark.parametrize("selection", [None, "", "  ", "all", "ALL"])
def test_select_builds_all_variants(selection):
    assert plan.select_builds(selection) == list(catalog.BUILDS)


def test_select_builds_keeps_catalog_order_not_request_order():
    assert plan.select_builds("tiktok, youtube") == [k for k in catalog.BUILDS if k in ("youtube", "tiktok")]


def test_select_builds_accepts_newlines_and_ignores_duplicates():
    assert plan.select_builds("youtube\nyoutube,\n") == ["youtube"]


def test_select_builds_rejects_unknown_keys_and_lists_the_known_ones():
    with pytest.raises(plan.PlanError, match="nope") as exc_info:
        plan.select_builds("youtube,nope")
    assert "youtube" in str(exc_info.value)


def test_write_github_output_writes_tag_name_matrix_and_the_build_list(tmp_path):
    output_file = tmp_path / "github_output.txt"
    result = plan.make_plan("youtube")

    assert plan.write_github_output(result, str(output_file)) is True

    lines = _read_output(output_file)
    assert set(lines) == {"tag", "name", "matrix", "builds", "has_builds"}
    assert json.loads(lines["matrix"]) == ["youtube"]
    assert lines["builds"] == "youtube"
    assert lines["has_builds"] == "true"


def test_write_github_output_is_a_noop_without_a_destination(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert plan.write_github_output(plan.make_plan()) is False


def test_cli_plan_writes_outputs(monkeypatch, tmp_path):
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    assert cli.main(["plan", "--builds", "youtube,gboard"]) == 0

    lines = _read_output(output_file)
    assert json.loads(lines["matrix"]) == [k for k in catalog.BUILDS if k in ("youtube", "gboard")]


def test_cli_plan_does_not_crash_when_github_output_is_unset(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert cli.main(["plan"]) == 0


def test_cli_plan_fails_before_writing_anything_for_an_unknown_build(monkeypatch, tmp_path):
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    assert cli.main(["plan", "--builds", "not-a-build"]) == 1
    assert not output_file.exists()


def test_cli_plan_fails_before_writing_anything_when_config_is_invalid(monkeypatch, tmp_path):
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    def broken_validate():
        raise validate.ConfigError("config is broken on purpose")

    monkeypatch.setattr(validate, "validate_catalog", broken_validate)

    assert cli.main(["plan"]) == 1
    assert not output_file.exists()


def test_cli_validate_passes_for_the_real_config():
    assert cli.main(["validate"]) == 0


def test_cli_validate_reports_problems(monkeypatch):
    def broken_validate():
        raise validate.ConfigError("config is broken on purpose")

    monkeypatch.setattr(validate, "validate_catalog", broken_validate)
    assert cli.main(["validate"]) == 1


def test_a_plan_lists_its_builds_as_a_comma_separated_string():
    result = plan.make_plan("youtube,gboard")

    assert result.has_builds is True
    assert result.builds == ",".join(key for key in catalog.BUILDS if key in ("youtube", "gboard"))


def test_narrow_keeps_the_plan_order_and_the_tag_and_name():
    result = plan.make_plan("youtube,gboard,brave", now=datetime(2026, 10, 4, 14, 30, 5, tzinfo=UTC))

    narrowed = plan.narrow(result, {"brave", "youtube", "not-in-the-plan"})

    assert narrowed.matrix == [key for key in result.matrix if key in ("youtube", "brave")]
    assert (narrowed.tag, narrowed.name) == (result.tag, result.name)


def test_a_plan_narrowed_to_nothing_has_no_builds(tmp_path):
    output_file = tmp_path / "github_output.txt"
    narrowed = plan.narrow(plan.make_plan("youtube"), [])

    assert narrowed.has_builds is False
    plan.write_github_output(narrowed, str(output_file))

    lines = _read_output(output_file)
    assert json.loads(lines["matrix"]) == []
    assert lines["builds"] == ""
    assert lines["has_builds"] == "false"


def _fake_select_changed(monkeypatch, changed):
    from patchy.publish import incremental

    seen = []

    async def fake(selected):
        seen.append(list(selected))
        return [key for key in selected if key in changed]

    monkeypatch.setattr(incremental, "select_changed", fake)
    return seen


def test_cli_plan_only_changed_narrows_the_matrix_to_what_changed(monkeypatch, tmp_path):
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    seen = _fake_select_changed(monkeypatch, {"gboard"})

    assert cli.main(["plan", "--builds", "youtube,gboard", "--only-changed"]) == 0

    lines = _read_output(output_file)
    assert json.loads(lines["matrix"]) == ["gboard"]
    assert lines["builds"] == "gboard"
    assert lines["has_builds"] == "true"
    assert seen == [[key for key in catalog.BUILDS if key in ("youtube", "gboard")]]


def test_cli_plan_only_changed_with_nothing_changed_writes_an_empty_plan_and_says_so(monkeypatch, tmp_path):
    output_file = tmp_path / "github_output.txt"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _fake_select_changed(monkeypatch, set())

    assert cli.main(["plan", "--only-changed"]) == 0

    lines = _read_output(output_file)
    assert json.loads(lines["matrix"]) == []
    assert lines["has_builds"] == "false"
    assert "Nothing to build" in summary.read_text(encoding="utf-8")


def test_cli_plan_looks_nothing_up_unless_asked_to(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github_output.txt"))
    monkeypatch.delenv("ONLY_CHANGED", raising=False)
    seen = _fake_select_changed(monkeypatch, set())

    assert cli.main(["plan", "--builds", "youtube"]) == 0

    assert seen == []


@pytest.mark.parametrize(
    ("value", "expected"), [("true", True), ("TRUE", True), ("1", True), ("false", False), ("", False)]
)
def test_only_changed_can_come_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("ONLY_CHANGED", value)

    assert cli.build_parser().parse_args(["plan"]).only_changed is expected
