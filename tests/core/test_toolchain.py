from pathlib import Path

import pytest

from patchy.core import toolchain
from patchy.core.process import Completed, ProcessTimeout

SDKMANAGER_LIST = """Installed packages:
  Path                 | Version | Description                | Location
  -------              | ------- | -------                    | -------
  build-tools;35.0.0   | 35.0.0  | Android SDK Build-Tools 35 | build-tools/35.0.0
  platform-tools       | 36.0.0  | Android SDK Platform-Tools | platform-tools

Available Packages:
  Path                 | Version      | Description                      | Location
  -------              | -------      | -------                          | -------
  build-tools;36.0.0   | 36.0.0       | Android SDK Build-Tools 36       | build-tools/36.0.0
  build-tools;36.1.0   | 36.1.0       | Android SDK Build-Tools 36.1     | build-tools/36.1.0
  build-tools;37.0.0   | 37.0.0       | Android SDK Build-Tools 37       | build-tools/37.0.0
  build-tools;38.0.0-rc1 | 38.0.0 rc1 | Android SDK Build-Tools 38 RC1   | build-tools/38.0.0-rc1
  build-tools;9.0.0    | 9.0.0        | Android SDK Build-Tools 9        | build-tools/9.0.0
  platforms;android-36 | 2            | Android SDK Platform 36          | platforms/android-36
"""


def _make_tools(root: Path, versions, with_zipalign=True):
    for version in versions:
        directory = root / "build-tools" / version
        directory.mkdir(parents=True)
        (directory / "apksigner").write_text("#!/bin/sh\n")
        if with_zipalign:
            (directory / "zipalign").write_text("#!/bin/sh\n")


def test_version_key_orders_numerically_not_lexically():
    versions = ["9.0.0", "36.0.0", "36.1.0", "37.0.0", "100.0.0"]
    assert sorted(versions, key=toolchain.version_key) == ["9.0.0", "36.0.0", "36.1.0", "37.0.0", "100.0.0"]


def test_installed_versions_ignores_release_candidates_and_stray_directories(tmp_path):
    _make_tools(tmp_path, ["34.0.0", "36.1.0", "9.0.0"])
    (tmp_path / "build-tools" / "38.0.0-rc1").mkdir()
    (tmp_path / "build-tools" / "notes").mkdir()
    (tmp_path / "build-tools" / "readme.txt").write_text("x")

    assert toolchain.installed_versions(tmp_path) == ["9.0.0", "34.0.0", "36.1.0"]


def test_installed_versions_is_empty_without_a_build_tools_directory(tmp_path):
    assert toolchain.installed_versions(tmp_path) == []


def test_resolve_tool_prefers_an_explicit_override(monkeypatch, tmp_path):
    custom = tmp_path / "my-apksigner"
    custom.write_text("x")
    assert toolchain.resolve_tool("apksigner", custom) == custom


def test_resolve_tool_rejects_an_override_that_does_not_exist(tmp_path):
    with pytest.raises(toolchain.ToolchainError, match="does not exist"):
        toolchain.resolve_tool("apksigner", tmp_path / "nope")


def test_resolve_tool_picks_the_newest_installed_build_tools(monkeypatch, tmp_path):
    _make_tools(tmp_path, ["34.0.0", "37.0.0", "36.1.0"])
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", tmp_path)
    monkeypatch.setattr(toolchain.settings, "android_home", None)

    assert toolchain.resolve_tool("apksigner") == tmp_path / "build-tools" / "37.0.0" / "apksigner"


def test_resolve_tool_skips_versions_that_lack_the_tool(monkeypatch, tmp_path):
    _make_tools(tmp_path, ["34.0.0"])
    (tmp_path / "build-tools" / "37.0.0").mkdir()
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", tmp_path)
    monkeypatch.setattr(toolchain.settings, "android_home", None)

    assert toolchain.resolve_tool("apksigner") == tmp_path / "build-tools" / "34.0.0" / "apksigner"


def test_resolve_tool_uses_android_home_when_sdk_root_is_unset(monkeypatch, tmp_path):
    _make_tools(tmp_path, ["36.0.0"])
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", None)
    monkeypatch.setattr(toolchain.settings, "android_home", tmp_path)

    assert toolchain.resolve_tool("apksigner") == tmp_path / "build-tools" / "36.0.0" / "apksigner"


def test_resolve_tool_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", None)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert toolchain.resolve_tool("apksigner") == Path("/usr/bin/apksigner")


def test_resolve_tool_explains_what_to_do_when_nothing_is_found(monkeypatch):
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", None)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: None)

    with pytest.raises(toolchain.ToolchainError, match="APKSIGNER"):
        toolchain.resolve_tool("apksigner")


def test_resolve_zipalign_is_optional(monkeypatch):
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", None)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: None)

    assert toolchain.resolve_zipalign() is None


def test_latest_build_tools_picks_the_newest_stable_release():
    assert toolchain.latest_build_tools(SDKMANAGER_LIST) == "37.0.0"


def test_latest_build_tools_is_none_when_nothing_is_listed():
    assert toolchain.latest_build_tools("Installed packages:\n  platform-tools | 36.0.0 | x | y\n") is None


def test_latest_build_tools_ignores_release_candidates_even_when_they_are_newest():
    listing = "  build-tools;36.0.0 | 36.0.0 | x | y\n  build-tools;99.0.0-rc2 | 99.0.0 rc2 | x | y\n"
    assert toolchain.latest_build_tools(listing) == "36.0.0"


def test_find_sdkmanager_prefers_the_latest_cmdline_tools(tmp_path):
    for name in ("10.0", "latest"):
        binary = tmp_path / "cmdline-tools" / name / "bin" / "sdkmanager"
        binary.parent.mkdir(parents=True)
        binary.write_text("x")

    assert toolchain.find_sdkmanager(tmp_path) == tmp_path / "cmdline-tools" / "latest" / "bin" / "sdkmanager"


def test_find_sdkmanager_falls_back_to_a_versioned_cmdline_tools_directory(tmp_path):
    binary = tmp_path / "cmdline-tools" / "12.0" / "bin" / "sdkmanager"
    binary.parent.mkdir(parents=True)
    binary.write_text("x")

    assert toolchain.find_sdkmanager(tmp_path) == binary


def _sdk(monkeypatch, tmp_path, installed):
    _make_tools(tmp_path, installed)
    sdkmanager = tmp_path / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    sdkmanager.parent.mkdir(parents=True)
    sdkmanager.write_text("x")
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", tmp_path)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    for name in ("info", "step", "warn", "success"):
        monkeypatch.setattr(toolchain.log, name, lambda msg: None)
    return sdkmanager


async def test_install_latest_is_a_noop_when_the_newest_build_tools_are_installed(monkeypatch, tmp_path):
    sdkmanager = _sdk(monkeypatch, tmp_path, ["35.0.0", "37.0.0"])
    calls = []

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        calls.append(cmd)
        return Completed(0, SDKMANAGER_LIST)

    monkeypatch.setattr(toolchain, "run_capture", fake_run)

    assert await toolchain.install_latest_build_tools() == "37.0.0"
    assert calls == [[str(sdkmanager), f"--sdk_root={tmp_path}", "--list"]]


async def test_install_latest_installs_the_newest_stable_build_tools_when_missing(monkeypatch, tmp_path):
    sdkmanager = _sdk(monkeypatch, tmp_path, ["35.0.0"])
    calls = []

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        calls.append(cmd)
        if cmd[2] == "--list":
            return Completed(0, SDKMANAGER_LIST)
        return Completed(0, "done")

    monkeypatch.setattr(toolchain, "run_capture", fake_run)

    assert await toolchain.install_latest_build_tools() == "37.0.0"
    assert calls[1] == [str(sdkmanager), f"--sdk_root={tmp_path}", "--install", "build-tools;37.0.0"]


async def test_install_latest_survives_a_failed_listing(monkeypatch, tmp_path):
    _sdk(monkeypatch, tmp_path, ["35.0.0"])
    warnings = []
    monkeypatch.setattr(toolchain.log, "warn", warnings.append)

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        raise ProcessTimeout("sdkmanager did not finish")

    monkeypatch.setattr(toolchain, "run_capture", fake_run)

    assert await toolchain.install_latest_build_tools() is None
    assert any("Could not list" in w for w in warnings)


async def test_install_latest_survives_a_failed_install(monkeypatch, tmp_path):
    _sdk(monkeypatch, tmp_path, ["35.0.0"])
    warnings = []
    monkeypatch.setattr(toolchain.log, "warn", warnings.append)

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        if cmd[2] == "--list":
            return Completed(0, SDKMANAGER_LIST)
        return Completed(1, "Warning: Failed to download\nlicense not accepted\n")

    monkeypatch.setattr(toolchain, "run_capture", fake_run)

    assert await toolchain.install_latest_build_tools() is None
    assert any("failed to install" in w for w in warnings)


async def test_install_latest_without_an_sdk_just_warns(monkeypatch):
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", None)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    warnings = []
    monkeypatch.setattr(toolchain.log, "warn", warnings.append)

    assert await toolchain.install_latest_build_tools() is None
    assert any("No Android SDK" in w for w in warnings)


async def test_prepare_returns_apksigner_and_zipalign_after_the_install_step(monkeypatch, tmp_path):
    _make_tools(tmp_path, ["37.0.0"])
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", tmp_path)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    monkeypatch.setattr(toolchain.settings, "apksigner", None)
    monkeypatch.setattr(toolchain.settings, "zipalign", None)
    installs = []

    async def fake_install():
        installs.append(True)
        return "37.0.0"

    monkeypatch.setattr(toolchain, "install_latest_build_tools", fake_install)

    tools = await toolchain.prepare(install_latest=True)

    assert installs == [True]
    assert tools["APKSIGNER"] == tmp_path / "build-tools" / "37.0.0" / "apksigner"
    assert tools["ZIPALIGN"] == tmp_path / "build-tools" / "37.0.0" / "zipalign"


async def test_prepare_can_skip_the_install_step(monkeypatch, tmp_path):
    _make_tools(tmp_path, ["37.0.0"], with_zipalign=False)
    monkeypatch.setattr(toolchain.settings, "android_sdk_root", tmp_path)
    monkeypatch.setattr(toolchain.settings, "android_home", None)
    monkeypatch.setattr(toolchain.settings, "apksigner", None)
    monkeypatch.setattr(toolchain.settings, "zipalign", None)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: None)

    async def boom():
        raise AssertionError("must not install")

    monkeypatch.setattr(toolchain, "install_latest_build_tools", boom)

    tools = await toolchain.prepare(install_latest=False)

    assert set(tools) == {"APKSIGNER"}
