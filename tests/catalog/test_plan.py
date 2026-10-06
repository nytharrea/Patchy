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


def test_write_github_output_writes_tag_name_and_matrix(tmp_path):
    output_file = tmp_path / "github_output.txt"
    result = plan.make_plan("youtube")

    assert plan.write_github_output(result, str(output_file)) is True

    lines = _read_output(output_file)
    assert set(lines) == {"tag", "name", "matrix"}
    assert json.loads(lines["matrix"]) == ["youtube"]


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
