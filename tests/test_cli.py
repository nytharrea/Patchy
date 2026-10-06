import json

import pytest

from patchy import catalog, cli
from patchy.core import toolchain
from patchy.engine import build as build_module
from patchy.engine import pins
from patchy.fetch import apkmirror, bundles

A = "a" * 64


def test_every_subcommand_is_registered():
    parser = cli.build_parser()
    for command in ("validate", "plan", "fetch", "build", "sign", "publish", "pin", "toolchain"):
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
    seen = []

    async def fake_fetch_all(builds):
        seen.append(list(builds))
        return {"builds": builds, "cli": {}, "bundles": {"morphe": {}}}

    monkeypatch.setattr(bundles, "fetch_all", fake_fetch_all)

    assert cli.main(["fetch", "--builds", "youtube"]) == 0
    assert seen == [["youtube"]]


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
