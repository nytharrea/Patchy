import json

import pytest

from patchy import catalog, cli
from patchy.core import toolchain
from patchy.engine import build as build_module
from patchy.engine import pins
from patchy.fetch import apkmirror, bundles, morphe

A = "a" * 64


def test_every_subcommand_is_registered():
    parser = cli.build_parser()
    for command in (
        "validate",
        "plan",
        "fetch",
        "build",
        "sign",
        "publish",
        "summary",
        "pin",
        "discover",
        "toolchain",
    ):
        args = parser.parse_args([command]) if command != "pin" else parser.parse_args([command, "youtube"])
        assert args.command == command
        assert callable(args.func)


def test_a_command_is_required():
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


def test_unknown_commands_are_rejected():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["frobnicate"])
    assert exc_info.value.code == 2


def test_builds_option_defaults_to_the_builds_environment_variable(monkeypatch):
    monkeypatch.setenv("BUILDS", "youtube,gboard")
    assert cli.build_parser().parse_args(["plan"]).builds == "youtube,gboard"
    assert cli.build_parser().parse_args(["fetch"]).builds == "youtube,gboard"


def test_builds_option_defaults_to_all(monkeypatch):
    monkeypatch.delenv("BUILDS", raising=False)
    assert cli.build_parser().parse_args(["plan"]).builds == "all"


def test_pin_promotes_the_pending_fingerprint(monkeypatch):
    calls = []

    def fake_promotion(app, sha256=None):
        calls.append((app, sha256))
        return A

    monkeypatch.setattr(pins, "commit_promotion", fake_promotion)

    assert cli.main(["pin", "youtube"]) == 0
    assert cli.main(["pin", "youtube", "--sha256", A]) == 0
    assert calls == [("youtube", None), ("youtube", A)]


def test_pin_reports_a_problem_with_exit_code_1(monkeypatch):
    def failing(app, sha256=None):
        raise pins.PinsError("There is no pending fingerprint for 'youtube'")

    monkeypatch.setattr(pins, "commit_promotion", failing)

    assert cli.main(["pin", "youtube"]) == 1


def test_pin_without_an_app_or_collect_is_a_usage_error():
    assert cli.main(["pin"]) == 2


def test_pin_collect_reads_build_statuses_and_records_the_pending_fingerprints(monkeypatch, tmp_path):
    (tmp_path / "apk-youtube").mkdir()
    (tmp_path / "apk-youtube" / "status-youtube.json").write_text(
        json.dumps({"build_key": "youtube", "ok": False, "pending_pin": {"app": "youtube", "sha256": A}})
    )
    recorded = []
    monkeypatch.setattr(pins, "commit_pending", lambda candidates: recorded.append(candidates) or True)

    assert cli.main(["pin", "--collect", str(tmp_path)]) == 0
    assert recorded == [{"youtube": A}]


def test_pin_collect_failures_do_not_crash_the_command(monkeypatch, tmp_path):
    def failing(candidates):
        raise pins.PinsError("pins/known.json is not valid JSON (line 3, column 1)")

    monkeypatch.setattr(pins, "commit_pending", failing)

    assert cli.main(["pin", "--collect", str(tmp_path)]) == 1


async def _unused():
    return None


def test_build_rejects_unknown_build_keys():
    assert cli.main(["build", "--app", "not-a-build"]) == 1


def test_build_reports_a_missing_manifest(monkeypatch):
    def missing():
        raise bundles.ManifestError("Bundle manifest not found")

    closed = []

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr(bundles, "read_manifest", missing)
    monkeypatch.setattr(apkmirror, "close_session", fake_close)

    assert cli.main(["build", "--app", "youtube"]) == 1


def test_build_runs_the_requested_build_and_always_closes_the_apkmirror_session(monkeypatch):
    seen = []
    closed = []

    async def fake_run(keys, tools):
        seen.append((list(keys), tools))
        return []

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr(bundles, "read_manifest", lambda: {"manifest": True})
    monkeypatch.setattr(bundles, "resolve_tools", lambda manifest: "TOOLS")
    monkeypatch.setattr(build_module, "run_builds", fake_run)
    monkeypatch.setattr(apkmirror, "close_session", fake_close)

    assert cli.main(["build", "--app", "youtube"]) == 0
    assert seen == [(["youtube"], "TOOLS")]
    assert closed == [True]


def test_build_exits_non_zero_when_a_build_failed(monkeypatch):
    async def fake_run(keys, tools):
        return ["youtube"]

    async def fake_close():
        return None

    monkeypatch.setattr(bundles, "read_manifest", lambda: {})
    monkeypatch.setattr(bundles, "resolve_tools", lambda manifest: "TOOLS")
    monkeypatch.setattr(build_module, "run_builds", fake_run)
    monkeypatch.setattr(apkmirror, "close_session", fake_close)

    assert cli.main(["build", "--app", "youtube"]) == 1


def test_build_all_expands_to_every_build_in_the_catalog(monkeypatch):
    seen = []

    async def fake_run(keys, tools):
        seen.append(list(keys))
        return []

    async def fake_close():
        return None

    monkeypatch.setattr(bundles, "read_manifest", lambda: {})
    monkeypatch.setattr(bundles, "resolve_tools", lambda manifest: "TOOLS")
    monkeypatch.setattr(build_module, "run_builds", fake_run)
    monkeypatch.setattr(apkmirror, "close_session", fake_close)

    assert cli.main(["build", "--app", "all"]) == 0
    assert seen == [list(catalog.BUILDS)]


def test_build_falls_back_to_the_target_app_environment_setting(monkeypatch):
    from patchy.core.settings import settings

    seen = []

    async def fake_run(keys, tools):
        seen.append(list(keys))
        return []

    async def fake_close():
        return None

    monkeypatch.setattr(settings, "target_app", "gboard")
    monkeypatch.setattr(bundles, "read_manifest", lambda: {})
    monkeypatch.setattr(bundles, "resolve_tools", lambda manifest: "TOOLS")
    monkeypatch.setattr(build_module, "run_builds", fake_run)
    monkeypatch.setattr(apkmirror, "close_session", fake_close)

    assert cli.main(["build"]) == 0
    assert seen == [["gboard"]]


def test_fetch_downloads_only_what_the_selected_builds_need(monkeypatch):
    from patchy.publish import incremental

    seen = []
    recorded = []

    async def fake_fetch_all(builds):
        seen.append(list(builds))
        return {"builds": builds, "cli": {}, "bundles": {"morphe": {}}}

    async def fake_record(manifest):
        recorded.append(manifest)
        return manifest

    monkeypatch.setattr(bundles, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(incremental, "record_fingerprints", fake_record)

    assert cli.main(["fetch", "--builds", "youtube"]) == 0
    assert seen == [["youtube"]]
    assert recorded == [{"builds": ["youtube"], "cli": {}, "bundles": {"morphe": {}}}]


def test_fetch_still_succeeds_when_the_fingerprints_cannot_be_recorded(monkeypatch):
    from patchy.publish import incremental

    warnings = []

    async def fake_fetch_all(builds):
        return {"builds": builds, "cli": {}, "bundles": {}}

    async def failing(manifest):
        raise RuntimeError("GitHub API error: 403")

    monkeypatch.setattr(bundles, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(incremental, "record_fingerprints", failing)
    monkeypatch.setattr(cli.log, "warn", warnings.append)

    assert cli.main(["fetch", "--builds", "youtube"]) == 0
    assert any("403" in line and "only-changed" in line for line in warnings)


def test_fetch_rejects_unknown_build_keys(monkeypatch):
    async def boom(builds):
        raise AssertionError("must not download anything")

    monkeypatch.setattr(bundles, "fetch_all", boom)

    assert cli.main(["fetch", "--builds", "nope"]) == 1


def test_toolchain_prints_the_tools_and_exports_them_to_github_env(monkeypatch, tmp_path):
    github_env = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    requested = []

    async def fake_prepare(install_latest=True):
        requested.append(install_latest)
        return {"APKSIGNER": tmp_path / "apksigner", "ZIPALIGN": tmp_path / "zipalign"}

    monkeypatch.setattr(toolchain, "prepare", fake_prepare)

    assert cli.main(["toolchain"]) == 0
    assert cli.main(["toolchain", "--no-install"]) == 0

    assert requested == [True, False]
    lines = github_env.read_text().splitlines()
    assert f"APKSIGNER={tmp_path / 'apksigner'}" in lines
    assert f"ZIPALIGN={tmp_path / 'zipalign'}" in lines


def test_toolchain_fails_cleanly_when_apksigner_cannot_be_found(monkeypatch):
    async def fake_prepare(install_latest=True):
        raise toolchain.ToolchainError("apksigner was not found.")

    monkeypatch.setattr(toolchain, "prepare", fake_prepare)

    assert cli.main(["toolchain"]) == 1


def test_sign_and_publish_delegate_to_the_pipeline(monkeypatch):
    from patchy.publish import pipeline

    calls = []

    async def fake_sign():
        calls.append("sign")
        return {}

    async def fake_publish():
        calls.append("publish")
        return True

    monkeypatch.setattr(pipeline, "run_sign", fake_sign)
    monkeypatch.setattr(pipeline, "run_publish", fake_publish)

    assert cli.main(["sign"]) == 0
    assert cli.main(["publish"]) == 0
    assert calls == ["sign", "publish"]


def test_summary_writes_the_table_to_the_github_job_summary(monkeypatch, tmp_path):
    from patchy.publish import telemetry

    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    monkeypatch.setattr(telemetry, "render_summary", lambda: "## table")

    assert cli.main(["summary"]) == 0
    assert target.read_text(encoding="utf-8") == "## table\n"


def test_summary_prints_the_table_when_there_is_no_job_summary_file(monkeypatch, capsys):
    from patchy.publish import telemetry

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(telemetry, "render_summary", lambda: "## table")

    assert cli.main(["summary"]) == 0
    assert "## table" in capsys.readouterr().out


def test_summary_with_nothing_to_report_still_succeeds(monkeypatch, tmp_path):
    from patchy.publish import telemetry

    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    monkeypatch.setattr(telemetry, "render_summary", lambda: "")

    assert cli.main(["summary"]) == 0
    assert not target.exists()


def _morphe_catalog():
    return morphe.parse_catalog(
        {
            "store": {"com.example.newapp": {"name": "New App", "category": "Social"}},
            "bundles": [
                {
                    "name": "Fancy",
                    "repo": "fancy/newapp-patches",
                    "source": "github",
                    "targetApps": ["com.example.newapp"],
                }
            ],
        }
    )


def _serve_catalog(monkeypatch, result=None, error=None):
    async def fake_fetch_catalog(url=None):
        if error is not None:
            raise error
        return result or _morphe_catalog()

    monkeypatch.setattr(morphe, "fetch_catalog", fake_fetch_catalog)


def test_discover_writes_the_report_to_the_github_job_summary(monkeypatch, tmp_path, capsys):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    _serve_catalog(monkeypatch)

    assert cli.main(["discover", "--package", "com.example.newapp"]) == 0

    report = target.read_text(encoding="utf-8")
    assert report.startswith("## Morphe catalog: `com.example.newapp`")
    assert "Patchy does not build it yet." in report
    assert "## Morphe catalog" not in capsys.readouterr().out


def test_discover_prints_the_report_when_there_is_no_job_summary_file(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    _serve_catalog(monkeypatch)

    assert cli.main(["discover", "--query", "new"]) == 0

    assert "## Morphe catalog search: `new`" in capsys.readouterr().out


def test_discover_without_arguments_gives_the_overview(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    for name in ("DISCOVER_PACKAGE", "DISCOVER_QUERY", "DISCOVER_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    _serve_catalog(monkeypatch)

    assert cli.main(["discover"]) == 0

    assert "## Morphe catalog overview" in capsys.readouterr().out


def test_discover_fails_when_the_catalog_cannot_be_loaded(monkeypatch, tmp_path):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    errors = []
    monkeypatch.setattr(cli.log, "error", errors.append)
    _serve_catalog(monkeypatch, error=morphe.MorpheCatalogError("Could not load the Morphe catalog: HTTP 503"))

    assert cli.main(["discover"]) == 1

    assert errors == ["Could not load the Morphe catalog: HTTP 503"]
    assert not target.exists()


def test_discover_hands_what_was_asked_for_to_the_report(monkeypatch):
    from patchy.catalog import discover

    seen = []

    def fake_report(catalog, **kwargs):
        seen.append(kwargs)
        return "report"

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    for name in ("DISCOVER_PACKAGE", "DISCOVER_QUERY", "DISCOVER_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(discover, "build_report", fake_report)
    _serve_catalog(monkeypatch)

    assert cli.main(["discover", "--query", "reddit", "--limit", "5"]) == 0
    assert cli.main(["discover", "--package", "com.reddit.frontpage"]) == 0

    assert seen == [
        {"package": "", "query": "reddit", "limit": 5},
        {"package": "com.reddit.frontpage", "query": "", "limit": 20},
    ]


def test_discover_takes_its_defaults_from_the_environment(monkeypatch):
    monkeypatch.setenv("DISCOVER_PACKAGE", "com.example.app")
    monkeypatch.setenv("DISCOVER_QUERY", "example")
    monkeypatch.setenv("DISCOVER_LIMIT", "7")

    args = cli.build_parser().parse_args(["discover"])

    assert (args.package, args.query, args.limit) == ("com.example.app", "example", 7)


def test_discover_treats_empty_environment_values_as_not_given(monkeypatch):
    monkeypatch.setenv("DISCOVER_PACKAGE", "")
    monkeypatch.setenv("DISCOVER_QUERY", "")
    monkeypatch.setenv("DISCOVER_LIMIT", "")

    args = cli.build_parser().parse_args(["discover"])

    assert (args.package, args.query, args.limit) == ("", "", 20)


@pytest.mark.parametrize("limit", ["0", "-3", "many", "2.5"])
def test_discover_rejects_a_limit_that_is_not_a_positive_whole_number(limit, monkeypatch):
    for name in ("DISCOVER_PACKAGE", "DISCOVER_QUERY", "DISCOVER_LIMIT"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["discover", "--limit", limit])

    assert exc_info.value.code == 2
