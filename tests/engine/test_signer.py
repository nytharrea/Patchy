from pathlib import Path

import pytest
from pydantic import SecretStr

from patchy.core.process import Completed, ProcessTimeout
from patchy.core.toolchain import ToolchainError
from patchy.engine import signer

APKSIGNER = Path("/sdk/build-tools/37.0.0/apksigner")
ZIPALIGN = Path("/sdk/build-tools/37.0.0/zipalign")
FINGERPRINT = "3d7a1223019aa39d9ea0e3436ab7c0896bfb4fb679f4de5fe7c23f326c8f994a"
VERIFY_OUTPUT = f"Signer #1 certificate SHA-256 digest: {FINGERPRINT}\n"


def _creds(tmp_path):
    keystore = tmp_path / "release.keystore"
    keystore.write_bytes(b"fake keystore")
    return signer.Credentials(keystore, "release-key", "storepass123", "keypass456")


class _Runner:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    async def __call__(self, cmd, *, timeout, env=None, stderr_to_stdout=True):
        self.calls.append({"cmd": list(cmd), "env": env})
        tool = Path(cmd[0]).name
        action = cmd[1] if len(cmd) > 1 else ""
        key = (tool, action) if tool == "apksigner" else (tool,)
        result = self.results.get(key)
        if isinstance(result, list):
            result = result.pop(0) if result else None
        if callable(result):
            result = result(cmd)
        if tool == "zipalign" and result is None:
            Path(cmd[-1]).write_bytes(Path(cmd[-2]).read_bytes())
            return Completed(0, "")
        if tool == "apksigner" and action == "sign" and result is None:
            out = cmd[cmd.index("--out") + 1]
            Path(out).write_bytes(b"signed apk")
            return Completed(0, "")
        if tool == "apksigner" and action == "verify" and result is None:
            return Completed(0, VERIFY_OUTPUT)
        return result

    def tools(self):
        names = []
        for call in self.calls:
            tool = Path(call["cmd"][0]).name
            names.append(f"{tool}:{call['cmd'][1]}" if tool == "apksigner" else f"{tool}:")
        return names


def _install(monkeypatch, runner, zipalign=ZIPALIGN):
    monkeypatch.setattr(signer, "run_capture", runner)
    monkeypatch.setattr(signer, "resolve_apksigner", lambda: APKSIGNER)
    monkeypatch.setattr(signer, "resolve_zipalign", lambda: zipalign)
    monkeypatch.setattr(signer.log, "warn", lambda msg: None)


def test_load_credentials_requires_every_part(monkeypatch, tmp_path):
    keystore = tmp_path / "release.keystore"
    keystore.write_bytes(b"fake keystore")
    monkeypatch.setattr(signer.settings, "ks_path", keystore)
    monkeypatch.setattr(signer.settings, "ks_password", SecretStr("storepass123"))
    monkeypatch.setattr(signer.settings, "ks_alias", "release-key")
    monkeypatch.setattr(signer.settings, "key_password", SecretStr("keypass456"))

    creds = signer.load_credentials()
    assert creds == signer.Credentials(keystore, "release-key", "storepass123", "keypass456")

    monkeypatch.setattr(signer.settings, "key_password", None)
    assert signer.load_credentials() is None


def test_load_credentials_is_none_when_the_keystore_file_is_missing_or_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(signer.settings, "ks_password", SecretStr("storepass123"))
    monkeypatch.setattr(signer.settings, "ks_alias", "release-key")
    monkeypatch.setattr(signer.settings, "key_password", SecretStr("keypass456"))

    monkeypatch.setattr(signer.settings, "ks_path", tmp_path / "does-not-exist.keystore")
    assert signer.load_credentials() is None

    empty = tmp_path / "empty.keystore"
    empty.write_bytes(b"")
    monkeypatch.setattr(signer.settings, "ks_path", empty)
    assert signer.load_credentials() is None


def test_load_credentials_is_none_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(signer.settings, "ks_path", None)
    monkeypatch.setattr(signer.settings, "ks_password", None)
    monkeypatch.setattr(signer.settings, "ks_alias", None)
    monkeypatch.setattr(signer.settings, "key_password", None)
    assert signer.load_credentials() is None


def test_sign_command_reads_passwords_from_the_environment_not_argv(tmp_path):
    creds = _creds(tmp_path)
    cmd = signer.build_sign_command(APKSIGNER, creds, Path("in.apk"), Path("out.apk"))

    assert cmd[:2] == [str(APKSIGNER), "sign"]
    assert cmd[cmd.index("--ks") + 1] == str(creds.keystore)
    assert cmd[cmd.index("--ks-key-alias") + 1] == "release-key"
    assert cmd[cmd.index("--ks-pass") + 1] == f"env:{signer.KS_PASSWORD_VAR}"
    assert cmd[cmd.index("--key-pass") + 1] == f"env:{signer.KEY_PASSWORD_VAR}"
    assert cmd[cmd.index("--out") + 1] == "out.apk"
    assert cmd[-1] == "in.apk"
    assert "storepass123" not in " ".join(cmd)
    assert "keypass456" not in " ".join(cmd)


def test_sign_command_does_not_produce_an_idsig_file(tmp_path):
    cmd = signer.build_sign_command(APKSIGNER, _creds(tmp_path), Path("in.apk"), Path("out.apk"))
    assert cmd[cmd.index("--v4-signing-enabled") + 1] == "false"


async def test_sign_apk_aligns_signs_and_verifies_in_that_order(monkeypatch, tmp_path):
    runner = _Runner()
    _install(monkeypatch, runner)
    source = tmp_path / "in" / "YouTube-1.0.apk"
    source.parent.mkdir()
    source.write_bytes(b"patched apk")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    fingerprint = await signer.sign_apk(source, dest, _creds(tmp_path))

    assert fingerprint == FINGERPRINT
    assert runner.tools() == ["zipalign:", "apksigner:sign", "apksigner:verify"]
    assert dest.read_bytes() == b"signed apk"


async def test_sign_apk_passes_the_passwords_only_through_a_minimal_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret")
    runner = _Runner()
    _install(monkeypatch, runner)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")

    await signer.sign_apk(source, tmp_path / "signed" / "YouTube-1.0.apk", _creds(tmp_path))

    sign_call = next(c for c in runner.calls if c["cmd"][1:2] == ["sign"])
    assert sign_call["env"][signer.KS_PASSWORD_VAR] == "storepass123"
    assert sign_call["env"][signer.KEY_PASSWORD_VAR] == "keypass456"
    assert "GITHUB_TOKEN" not in sign_call["env"]


async def test_sign_apk_removes_the_intermediate_aligned_file(monkeypatch, tmp_path):
    _install(monkeypatch, _Runner())
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    await signer.sign_apk(source, dest, _creds(tmp_path))

    assert [p.name for p in dest.parent.iterdir()] == ["YouTube-1.0.apk"]


async def test_sign_apk_removes_a_stray_idsig_file(monkeypatch, tmp_path):
    def sign(cmd):
        out = Path(cmd[cmd.index("--out") + 1])
        out.write_bytes(b"signed apk")
        out.with_name(out.name + ".idsig").write_bytes(b"idsig")
        return Completed(0, "")

    _install(monkeypatch, _Runner({("apksigner", "sign"): sign}))
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    await signer.sign_apk(source, dest, _creds(tmp_path))

    assert [p.name for p in dest.parent.iterdir()] == ["YouTube-1.0.apk"]


async def test_sign_apk_surfaces_apksigner_errors_and_cleans_up(monkeypatch, tmp_path):
    runner = _Runner({("apksigner", "sign"): Completed(1, "Failed to load signer: Keystore was tampered with\n")})
    _install(monkeypatch, runner)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    with pytest.raises(signer.SigningError, match="apksigner sign failed for YouTube-1.0.apk.*tampered"):
        await signer.sign_apk(source, dest, _creds(tmp_path))

    assert not dest.exists()
    assert list(dest.parent.iterdir()) == []


async def test_sign_apk_surfaces_zipalign_errors(monkeypatch, tmp_path):
    runner = _Runner({("zipalign",): Completed(1, "Unable to open input\n")})
    _install(monkeypatch, runner)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")

    with pytest.raises(signer.SigningError, match="zipalign failed"):
        await signer.sign_apk(source, tmp_path / "signed" / "YouTube-1.0.apk", _creds(tmp_path))

    assert runner.tools() == ["zipalign:", "zipalign:"]


async def test_sign_apk_aligns_native_libraries_to_16_kb_pages_first(monkeypatch, tmp_path):
    runner = _Runner()
    _install(monkeypatch, runner)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")

    await signer.sign_apk(source, tmp_path / "signed" / "YouTube-1.0.apk", _creds(tmp_path))

    zipalign_call = runner.calls[0]["cmd"]
    assert zipalign_call[:6] == [str(ZIPALIGN), "-f", "-P", "16", "4", str(source)]


async def test_sign_apk_falls_back_to_4_kb_alignment_for_older_build_tools(monkeypatch, tmp_path):
    runner = _Runner({("zipalign",): [Completed(1, "Unknown option 'P'\n")]})
    _install(monkeypatch, runner)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    await signer.sign_apk(source, dest, _creds(tmp_path))

    assert runner.tools() == ["zipalign:", "zipalign:", "apksigner:sign", "apksigner:verify"]
    assert "-P" in runner.calls[0]["cmd"]
    assert "-p" in runner.calls[1]["cmd"] and "-P" not in runner.calls[1]["cmd"]
    assert dest.read_bytes() == b"signed apk"


async def test_sign_apk_still_signs_when_zipalign_is_unavailable(monkeypatch, tmp_path):
    runner = _Runner()
    _install(monkeypatch, runner, zipalign=None)
    warnings = []
    monkeypatch.setattr(signer.log, "warn", warnings.append)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")

    await signer.sign_apk(source, tmp_path / "signed" / "YouTube-1.0.apk", _creds(tmp_path))

    assert runner.tools() == ["apksigner:sign", "apksigner:verify"]
    assert any("zipalign not found" in w for w in warnings)


async def test_sign_apk_without_credentials_keeps_the_patchers_signature_and_warns_loudly(monkeypatch, tmp_path):
    runner = _Runner()
    _install(monkeypatch, runner)
    warnings = []
    monkeypatch.setattr(signer.log, "warn", warnings.append)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched apk")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    fingerprint = await signer.sign_apk(source, dest, None)

    assert fingerprint == FINGERPRINT
    assert dest.read_bytes() == b"patched apk"
    assert runner.tools() == ["apksigner:verify"]
    assert any("test key" in w for w in warnings)


async def test_verify_signed_reports_a_failed_verification(monkeypatch, tmp_path):
    runner = _Runner({("apksigner", "verify"): Completed(1, "DOES NOT VERIFY\nERROR: bad digest\n")})
    _install(monkeypatch, runner)

    with pytest.raises(signer.SigningError, match="verify failed for app.apk.*DOES NOT VERIFY"):
        await signer.verify_signed(tmp_path / "app.apk")


async def test_verify_signed_requires_a_printed_certificate(monkeypatch, tmp_path):
    _install(monkeypatch, _Runner({("apksigner", "verify"): Completed(0, "Verifies\n")}))

    with pytest.raises(signer.SigningError, match="no certificate"):
        await signer.verify_signed(tmp_path / "app.apk")


async def test_a_missing_apksigner_becomes_a_signing_error(monkeypatch, tmp_path):
    def missing():
        raise ToolchainError("apksigner was not found.")

    monkeypatch.setattr(signer, "resolve_apksigner", missing)

    with pytest.raises(signer.SigningError, match="apksigner was not found"):
        await signer.verify_signed(tmp_path / "app.apk")


async def test_a_timeout_becomes_a_signing_error(monkeypatch, tmp_path):
    async def slow(cmd, *, timeout, env=None, stderr_to_stdout=True):
        raise ProcessTimeout("apksigner did not finish within 1s and was killed.")

    monkeypatch.setattr(signer, "run_capture", slow)
    monkeypatch.setattr(signer, "resolve_apksigner", lambda: APKSIGNER)

    with pytest.raises(signer.SigningError, match="did not finish"):
        await signer.verify_signed(tmp_path / "app.apk")
