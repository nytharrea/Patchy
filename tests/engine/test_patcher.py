import asyncio
from pathlib import Path

import pytest

from patchy.core.process import Completed
from patchy.engine import patcher


class _FakeStdout:
    def __init__(self, lines, delay=0.0, hang=None):
        self._lines = [line.encode() for line in lines]
        self._delay = delay
        self._hang = hang

    async def readline(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._lines:
            return self._lines.pop(0)
        if self._hang is not None:
            await self._hang.wait()
        return b""


class _FakeProcess:
    def __init__(self, lines, returncode=0, delay=0.0, hang=False):
        self._release = asyncio.Event() if hang else None
        self.stdout = _FakeStdout(lines, delay, self._release)
        self.returncode = returncode if not hang else None
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9
        if self._release is not None:
            self._release.set()

    async def wait(self):
        return self.returncode


def _install(monkeypatch, process_factory):
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return process_factory()

    monkeypatch.setattr(patcher.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(patcher.log, "patch_line", lambda line: None)
    monkeypatch.setattr(patcher.log, "notice", lambda msg: None)
    return captured


def _patch_common(monkeypatch, tmp_path, output_lines, returncode=0):
    apk_path = tmp_path / "Youtube-patched.apk"
    apk_path.write_bytes(b"fake patched apk")
    lines = [line.format(apk_path=apk_path) + "\n" for line in output_lines]
    captured = _install(monkeypatch, lambda: _FakeProcess(list(lines), returncode=returncode))
    return apk_path, captured


def test_command_includes_patches_arch_exclude_and_enable_flags():
    cmd = patcher.build_patch_command(
        "desktop.jar",
        ["patch-a.mpp", "patch-b.mpp"],
        "input.apk",
        exclude=["Bad patch"],
        enable=["Extra patch"],
        arch="arm64-v8a",
    )

    assert cmd[:4] == ["java", "-jar", "desktop.jar", "patch"]
    assert cmd.count("--patches") == 2
    assert "patch-a.mpp" in cmd and "patch-b.mpp" in cmd
    assert "--striplibs" in cmd and "arm64-v8a" in cmd
    assert "--disable" in cmd and "Bad patch" in cmd
    assert "--enable" in cmd and "Extra patch" in cmd
    assert cmd[-1] == "input.apk"


def test_command_never_carries_signing_credentials():
    cmd = patcher.build_patch_command("desktop.jar", ["patch-a.mpp"], "input.apk")
    assert not [part for part in cmd if part.startswith("--keystore")]


def test_command_asks_the_patcher_not_to_sign_so_it_needs_no_keystore():
    cmd = patcher.build_patch_command("desktop.jar", ["patch-a.mpp"], "input.apk")

    assert cmd.count("--unsigned") == 1
    assert cmd.index("--unsigned") < cmd.index("input.apk")
    assert cmd[-1] == "input.apk"


def test_options_precede_the_enable_flag_of_their_own_patch():
    cmd = patcher.build_patch_command(
        "desktop.jar",
        ["patch-a.mpp"],
        "input.apk",
        options={"Custom branding.App name": "YouTube Özel", "Custom branding.App icon": "black"},
    )

    enable_idx = cmd.index("Custom branding") - 1
    assert cmd[enable_idx] == "--enable"
    assert cmd[enable_idx - 2 : enable_idx] == ['-OApp name="YouTube Özel"', '-OApp icon="black"']
    assert not any(part.startswith("-O") for part in cmd[enable_idx + 1 :])


def test_options_for_different_patches_are_not_interleaved():
    cmd = patcher.build_patch_command(
        "desktop.jar",
        ["patch-a.mpp"],
        "input.apk",
        options={"Patch A.key1": "v1", "Patch B.key2": "v2", "Patch A.key3": "v3"},
    )

    idx_a = cmd.index("Patch A")
    idx_b = cmd.index("Patch B")
    assert cmd[idx_a - 3 : idx_a] == ['-Okey1="v1"', '-Okey3="v3"', "--enable"]
    assert cmd[idx_b - 2 : idx_b] == ['-Okey2="v2"', "--enable"]
    assert idx_a < idx_b


def test_option_groups_come_before_plain_enable_and_disable_flags():
    cmd = patcher.build_patch_command(
        "desktop.jar",
        ["patch-a.mpp"],
        "input.apk",
        exclude=["Bad patch"],
        enable=["Extra patch"],
        options={"Custom branding.customName": "YouTube", "Custom branding.appIcon": "original"},
    )

    first_option_idx = cmd.index('-OcustomName="YouTube"')
    assert cmd[first_option_idx : first_option_idx + 4] == [
        '-OcustomName="YouTube"',
        '-OappIcon="original"',
        "--enable",
        "Custom branding",
    ]
    assert first_option_idx < cmd.index("--disable")
    assert first_option_idx < cmd.index("Extra patch")


def test_option_with_none_value_omits_the_equals_sign():
    cmd = patcher.build_patch_command(
        "desktop.jar", ["patch-a.mpp"], "input.apk", options={"Some patch.flag": None}
    )

    assert "-Oflag" in cmd
    assert "-Oflag=None" not in cmd


def test_option_values_are_quoted_against_the_clis_own_type_inference():
    cmd = patcher.build_patch_command(
        "desktop.jar",
        ["patch-a.mpp"],
        "input.apk",
        options={
            "Some patch.a": "true",
            "Some patch.b": "123",
            "Some patch.c": "Half",
            "Some patch.d": "9001L",
        },
    )

    assert '-Oa="true"' in cmd
    assert '-Ob="123"' in cmd
    assert '-Oc="Half"' in cmd
    assert '-Od="9001L"' in cmd


def test_options_key_without_a_dot_raises_a_clear_error():
    with pytest.raises(ValueError, match="Patch name.optionKey"):
        patcher.build_patch_command("desktop.jar", ["patch-a.mpp"], "input.apk", options={"NoDotHere": "x"})


def test_paths_are_stringified():
    cmd = patcher.build_patch_command(Path("tools/cli.jar"), [Path("tools/a.mpp")], Path("in/app.apk"))
    assert cmd[2] == "tools/cli.jar"
    assert "tools/a.mpp" in cmd
    assert cmd[-1] == "in/app.apk"


async def test_the_cli_runs_with_a_clean_environment_that_has_no_secrets(monkeypatch, tmp_path):
    for name, value in {
        "GITHUB_TOKEN": "ghs_secret",
        "KS_PASSWORD": "storepass123",
        "KEY_PASSWORD": "keypass456",
        "ACTIONS_RUNTIME_TOKEN": "runtime-secret",
        "DISCORD_WEBHOOK_URL": "https://discord.example/hook",
        "PATH": "/usr/bin",
        "JAVA_HOME": "/opt/java",
    }.items():
        monkeypatch.setenv(name, value)

    _, captured = _patch_common(monkeypatch, tmp_path, ["INFO: Saved to {apk_path}"])

    await patcher.patch_apk("desktop.jar", ["patch1"], "input.apk")

    env = captured["kwargs"]["env"]
    assert env["PATH"] == "/usr/bin"
    assert env["JAVA_HOME"] == "/opt/java"
    secrets = {"GITHUB_TOKEN", "KS_PASSWORD", "KEY_PASSWORD", "ACTIONS_RUNTIME_TOKEN", "DISCORD_WEBHOOK_URL"}
    assert not secrets & set(env)
    assert "storepass123" not in " ".join(captured["cmd"])


async def test_patch_apk_tells_the_user_that_signing_happens_later(monkeypatch, tmp_path):
    _, captured = _patch_common(monkeypatch, tmp_path, ["INFO: Saved to {apk_path}"])
    notices = []
    monkeypatch.setattr(patcher.log, "notice", notices.append)

    await patcher.patch_apk("desktop.jar", ["patch1"], "input.apk")

    assert any("release job" in n for n in notices)
    assert "--unsigned" in captured["cmd"]
    assert "--keystore" not in captured["cmd"]


async def test_raises_when_zero_patches_applied(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["Applying 0 patches..."])

    with pytest.raises(RuntimeError, match="0 patches"):
        await patcher.patch_apk("desktop.jar", [], "input.apk")


async def test_a_run_that_applies_no_patch_is_a_patch_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["Applying 0 patches..."])

    with pytest.raises(patcher.PatchFailed, match="0 patches"):
        await patcher.patch_apk("desktop.jar", [], "input.apk")


async def test_raises_on_nonzero_exit_code(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["some error output"], returncode=1)

    with pytest.raises(RuntimeError, match="exit 1"):
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")


async def test_a_failed_patch_run_is_a_patch_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["some error output"], returncode=1)

    with pytest.raises(patcher.PatchFailed, match="exit 1"):
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")


def test_patch_failures_are_runtime_errors_and_a_rejected_build_is_one_of_them():
    assert issubclass(patcher.PatchFailed, RuntimeError)
    assert issubclass(patcher.UnsupportedBuild, patcher.PatchFailed)


def test_a_timeout_is_not_a_patch_failure():
    assert not issubclass(patcher.PatchTimeout, patcher.PatchFailed)


HUSH_REJECTION = [
    'ERROR: Patching aborted: Patching failed: Patch "Allow chat bubbles" failed: The patch "Allow chat bubbles" '
    'depends on "BytecodePatch@556906020", which raised an exception:',
    "app.morphe.patcher.patch.PatchException: Install beside Meta apps: version code 346611418 is not supported. "
    "Use an unmodified arm64 Messenger 583.0.0.29.95 APK (version code 346611351 or 346611369 or 346611423 "
    "or 346611438 or 346611439 or 346611440).",
]
HUSH_ACCEPTED = frozenset({346611351, 346611369, 346611423, 346611438, 346611439, 346611440})


def test_unsupported_build_reads_the_rejected_and_the_accepted_codes_from_the_patch_message():
    assert patcher.unsupported_build("\n".join(HUSH_REJECTION)) == (346611418, HUSH_ACCEPTED)


def test_unsupported_build_collects_the_codes_of_every_version_name():
    output = (
        "Install beside Meta apps: version code 1 is not supported. Use an unmodified arm64 Messenger "
        "583.0.0.29.95 APK (version code 346611351 or 346611369) or 584.0.0.1.91 APK (version code 347000001)."
    )

    assert patcher.unsupported_build(output) == (1, frozenset({346611351, 346611369, 347000001}))


def test_unsupported_build_never_offers_the_rejected_code_back():
    output = "version code 5 is not supported. Use a build (version code 5 or 6)."

    assert patcher.unsupported_build(output) == (5, frozenset({6}))


def test_unsupported_build_is_none_when_the_patch_names_no_other_code():
    assert patcher.unsupported_build("version code 5 is not supported.") is None
    assert patcher.unsupported_build("version code 5 is not supported (version code 5).") is None


def test_unsupported_build_is_none_for_other_failures():
    assert patcher.unsupported_build("ERROR: FAILED: Some patch (version code 6 or 7)") is None
    assert patcher.unsupported_build("") is None


HUSH_REWORDED_REJECTION = [
    'ERROR: Patching aborted: Patching failed: Patch "Allow chat bubbles" failed: The patch "Allow chat bubbles" '
    'depends on "BytecodePatch@685244920", which raised an exception:',
    'app.morphe.patcher.patch.PatchException: The patch "BytecodePatch@685244920" depends on '
    '"ResourcePatch@458816147", which raised an exception:',
    "app.morphe.patcher.patch.PatchException: This Messenger build (version code 346611349) isn't supported yet, "
    "so nothing was patched. Use an unmodified arm64 Messenger 583.0.0.29.95 APK (version code 346611350 or "
    "346611351 or 346611353 or 346611369 or 346611386 or 346611418 or 346611420 or 346611422 or 346611423 or "
    "346611435 or 346611436 or 346611438 or 346611439 or 346611440). APKMirror lists the version code of every "
    "download.",
]
HUSH_REWORDED_ACCEPTED = frozenset(
    {
        346611350,
        346611351,
        346611353,
        346611369,
        346611386,
        346611418,
        346611420,
        346611422,
        346611423,
        346611435,
        346611436,
        346611438,
        346611439,
        346611440,
    }
)


def test_unsupported_build_reads_the_codes_from_the_reworded_patch_message():
    output = "\n".join(HUSH_REWORDED_REJECTION)

    assert patcher.unsupported_build(output) == (346611349, HUSH_REWORDED_ACCEPTED)


@pytest.mark.parametrize(
    "wording",
    [
        "is not supported",
        "isn't supported yet",
        "isn’t supported yet",
        "is not yet supported",
        "is unsupported",
        "is incompatible",
        "is not compatible",
        "doesn't support this build",
        "does not support this build",
        "IS NOT SUPPORTED",
    ],
)
def test_unsupported_build_recognises_the_ways_a_patch_may_word_a_rejection(wording):
    output = f"This build (version code 5) {wording}. Use a build (version code 6 or 7)."

    assert patcher.unsupported_build(output) == (5, frozenset({6, 7}))


def test_unsupported_build_ignores_messages_that_do_not_reject_a_build():
    assert patcher.unsupported_build("Supported builds (version code 6 or 7), yours is (version code 5).") is None
    assert patcher.unsupported_build("Patched (version code 5). Other builds: (version code 6 or 7).") is None


async def test_a_rejected_build_raises_unsupported_build_with_the_accepted_codes(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, HUSH_REJECTION, returncode=1)

    with pytest.raises(patcher.UnsupportedBuild, match="exit 1") as exc_info:
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")

    assert exc_info.value.rejected == 346611418
    assert exc_info.value.accepted == HUSH_ACCEPTED
    assert "version code 346611418 is not supported" in str(exc_info.value)


async def test_a_rejected_build_is_recognised_from_the_reworded_message_too(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, HUSH_REWORDED_REJECTION, returncode=1)

    with pytest.raises(patcher.UnsupportedBuild, match="exit 1") as exc_info:
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")

    assert exc_info.value.rejected == 346611349
    assert exc_info.value.accepted == HUSH_REWORDED_ACCEPTED


def test_unsupported_build_is_a_runtime_error_so_callers_report_it_like_any_failure():
    assert issubclass(patcher.UnsupportedBuild, RuntimeError)


async def test_a_plain_failure_is_not_reported_as_an_unsupported_build(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["some error output"], returncode=1)

    with pytest.raises(RuntimeError) as exc_info:
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")

    assert not isinstance(exc_info.value, patcher.UnsupportedBuild)


async def test_raises_when_saved_path_not_found_in_output(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["patching finished, no path line here"])

    with pytest.raises(RuntimeError, match="Cannot find patched APK path"):
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")


async def test_raises_when_reported_output_file_does_not_actually_exist(monkeypatch, tmp_path):
    missing_path = tmp_path / "never-written.apk"
    _install(monkeypatch, lambda: _FakeProcess([f"INFO: Saved to {missing_path}\n"]))

    with pytest.raises(RuntimeError, match="does not exist"):
        await patcher.patch_apk("desktop.jar", ["p"], "input.apk")


async def test_returns_the_patched_apk_path_on_success(monkeypatch, tmp_path):
    apk_path, _ = _patch_common(monkeypatch, tmp_path, ["INFO: Saved to {apk_path}"])

    result = await patcher.patch_apk("desktop.jar", ["p"], "input.apk")

    assert result == str(apk_path)
    assert Path(result).exists()


async def test_output_lines_are_forwarded_to_the_log(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, ["INFO: step one", "INFO: Saved to {apk_path}"])
    forwarded = []
    monkeypatch.setattr(patcher.log, "patch_line", forwarded.append)

    await patcher.patch_apk("desktop.jar", ["p"], "input.apk")

    assert forwarded[0] == "INFO: step one\n"
    assert len(forwarded) == 2


async def test_patch_apk_kills_a_hung_process_instead_of_hanging_forever(monkeypatch):
    monkeypatch.setattr(patcher.settings, "patch_timeout", 0.2)
    process = {}

    def factory():
        process["p"] = _FakeProcess(["INFO: starting up\n"], hang=True)
        return process["p"]

    _install(monkeypatch, factory)

    with pytest.raises(patcher.PatchTimeout, match="timed out"):
        await patcher.patch_apk("desktop.jar", ["patch1"], "input.apk")

    assert process["p"].killed is True


async def test_patch_timeout_is_a_runtime_error_so_callers_report_it_like_any_failure():
    assert issubclass(patcher.PatchTimeout, RuntimeError)


async def test_patch_apk_does_not_kill_a_slow_but_still_producing_process(monkeypatch, tmp_path):
    monkeypatch.setattr(patcher.settings, "patch_timeout", 0.3)
    apk_path = tmp_path / "Youtube-patched.apk"
    apk_path.write_bytes(b"fake patched apk")
    lines = [f"INFO: step {i}\n" for i in range(3)] + [f"INFO: Saved to {apk_path}\n"]
    process = {}

    def factory():
        process["p"] = _FakeProcess(lines, delay=0.1)
        return process["p"]

    _install(monkeypatch, factory)

    result = await patcher.patch_apk("desktop.jar", ["p"], "input.apk")

    assert result == str(apk_path)
    assert process["p"].killed is False


async def test_list_versions_returns_stdout_and_keeps_stderr_separate(monkeypatch):
    captured = {}

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        captured.update(cmd=cmd, timeout=timeout, env=env, stderr_to_stdout=stderr_to_stdout)
        return Completed(0, "Most common compatible versions:\n9.9.9 (3 patches)\n", "some stderr")

    monkeypatch.setattr(patcher, "run_capture", fake_run)

    output = await patcher.list_versions("cli.jar", ["a.mpp", Path("b.mpp")], "com.example.app")

    assert output == "Most common compatible versions:\n9.9.9 (3 patches)\n"
    assert captured["cmd"] == [
        "java",
        "-jar",
        "cli.jar",
        "list-versions",
        "-f",
        "com.example.app",
        "--patches",
        "a.mpp",
        "--patches",
        "b.mpp",
        "--include-experimental",
    ]
    assert captured["stderr_to_stdout"] is False
    assert captured["env"] is None


async def test_list_versions_leaves_experimental_versions_out_when_asked_to(monkeypatch):
    captured = {}

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        captured["cmd"] = cmd
        return Completed(0, "Most common compatible versions:\n9.9.9 (3 patches)\n", "")

    monkeypatch.setattr(patcher, "run_capture", fake_run)

    await patcher.list_versions("cli.jar", ["a.mpp"], "com.example.app", include_experimental=False)

    assert "--include-experimental" not in captured["cmd"]
    assert captured["cmd"][-2:] == ["--patches", "a.mpp"]


async def test_list_versions_includes_experimental_versions_unless_told_otherwise(monkeypatch):
    captured = {}

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        captured["cmd"] = cmd
        return Completed(0, "", "")

    monkeypatch.setattr(patcher, "run_capture", fake_run)

    await patcher.list_versions("cli.jar", ["a.mpp"], "com.example.app")

    assert captured["cmd"][-1] == "--include-experimental"


async def test_list_versions_returns_none_and_warns_when_the_cli_fails(monkeypatch):
    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        return Completed(2, "", "Exception in thread main\nat Something\n")

    warnings = []
    monkeypatch.setattr(patcher, "run_capture", fake_run)
    monkeypatch.setattr(patcher.log, "warn", warnings.append)

    assert await patcher.list_versions("cli.jar", ["a.mpp"], "com.example.app") is None
    assert any("code 2" in w for w in warnings)
