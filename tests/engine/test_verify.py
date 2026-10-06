import json
import shutil
import zipfile
from pathlib import Path

import pytest

from patchy.core.process import Completed
from patchy.core.toolchain import ToolchainError
from patchy.engine import verify

SAMPLE_OUTPUT = """Signer #1 certificate DN: CN=Android, O=Google Inc., C=US
Signer #1 certificate SHA-256 digest: 3D7A1223019AA39D9EA0E3436AB7C0896BFB4FB679F4DE5FE7C23F326C8F994A
Signer #1 certificate SHA-1 digest: 0000000000000000000000000000000000000000
Signer #1 certificate MD5 digest: 00000000000000000000000000000000
"""

FINGERPRINT = "3d7a1223019aa39d9ea0e3436ab7c0896bfb4fb679f4de5fe7c23f326c8f994a"
OTHER = "a" * 64


def _write_json(path, data):
    path.write_text(json.dumps(data))


def _setup_pins(monkeypatch, tmp_path, known=None):
    known_path = tmp_path / "known.json"
    pending_path = tmp_path / "pending.json"
    _write_json(known_path, known or {})
    monkeypatch.setattr(verify.settings, "known_pins_path", known_path)
    monkeypatch.setattr(verify.settings, "pending_pins_path", pending_path)
    monkeypatch.setattr(verify.settings, "skip_signature_verify", False)
    return known_path, pending_path


def _stub_fingerprints(monkeypatch, fingerprints):
    async def fake(path):
        return fingerprints

    monkeypatch.setattr(verify, "apk_certificate_fingerprints", fake)
    monkeypatch.setattr(verify, "_resolve_verifiable_apk", lambda p: (p, None))


def test_parse_cert_digests_lowercases_and_ignores_other_digest_types():
    assert verify.parse_cert_digests(SAMPLE_OUTPUT) == [FINGERPRINT]


def test_parse_cert_digests_handles_rotated_signers_and_removes_duplicates():
    output = (
        f"Signer (minSdkVersion=24, maxSdkVersion=32, lineage-index=0) certificate SHA-256 digest: {OTHER}\n"
        f"Signer (minSdkVersion=33, lineage-index=1) certificate SHA-256 digest: {FINGERPRINT}\n"
        f"Signer #1 certificate SHA-256 digest: {FINGERPRINT}\n"
    )
    assert verify.parse_cert_digests(output) == [OTHER, FINGERPRINT]


def test_parse_cert_digests_empty_for_unrelated_output():
    assert verify.parse_cert_digests("DOES NOT VERIFY\nERROR: nothing useful") == []


def _fake_apksigner(monkeypatch, result):
    calls = []

    async def fake_run(cmd, *, timeout, env=None, stderr_to_stdout=True):
        calls.append(cmd)
        return result

    monkeypatch.setattr(verify, "resolve_apksigner", lambda: Path("/sdk/build-tools/37.0.0/apksigner"))
    monkeypatch.setattr(verify, "run_capture", fake_run)
    return calls


async def test_apk_certificate_fingerprints_runs_apksigner_verify_with_print_certs(monkeypatch):
    calls = _fake_apksigner(monkeypatch, Completed(0, SAMPLE_OUTPUT))

    assert await verify.apk_certificate_fingerprints("/tmp/app.apk") == [FINGERPRINT]
    assert calls == [["/sdk/build-tools/37.0.0/apksigner", "verify", "--print-certs", "/tmp/app.apk"]]


async def test_apk_certificate_fingerprints_raises_when_apksigner_cannot_verify(monkeypatch):
    _fake_apksigner(monkeypatch, Completed(1, "DOES NOT VERIFY\nERROR: JAR signer CERT.RSA: digest mismatch\n"))

    with pytest.raises(verify.SignatureError, match="could not verify app.apk.*DOES NOT VERIFY"):
        await verify.apk_certificate_fingerprints("/tmp/app.apk")


async def test_apk_certificate_fingerprints_raises_when_no_certificate_is_printed(monkeypatch):
    _fake_apksigner(monkeypatch, Completed(0, "Verifies\n"))

    with pytest.raises(verify.SignatureError, match="no signing certificate"):
        await verify.apk_certificate_fingerprints("/tmp/app.apk")


async def test_apk_certificate_fingerprints_turns_a_missing_apksigner_into_a_signature_error(monkeypatch):
    def missing():
        raise ToolchainError("apksigner was not found.")

    monkeypatch.setattr(verify, "resolve_apksigner", missing)

    with pytest.raises(verify.SignatureError, match="apksigner was not found"):
        await verify.apk_certificate_fingerprints("/tmp/app.apk")


async def test_skip_signature_verify_bypasses_everything(monkeypatch):
    monkeypatch.setattr(verify.settings, "skip_signature_verify", True)

    async def boom(path):
        raise AssertionError("must not be called")

    monkeypatch.setattr(verify, "apk_certificate_fingerprints", boom)
    warnings = []
    monkeypatch.setattr(verify.log, "warn", warnings.append)

    await verify.verify_apk_signature("reddit.apk", "reddit")

    assert any("SKIP_SIGNATURE_VERIFY" in w for w in warnings)


async def test_no_pinned_entry_raises_unpinned_with_the_fingerprint_and_touches_no_files(monkeypatch, tmp_path):
    known_path, pending_path = _setup_pins(monkeypatch, tmp_path)
    _stub_fingerprints(monkeypatch, [FINGERPRINT])

    with pytest.raises(verify.UnpinnedSignature) as exc_info:
        await verify.verify_apk_signature("reddit.apk", "reddit")

    error = exc_info.value
    assert error.app_name == "reddit"
    assert error.fingerprint == FINGERPRINT
    assert "No pinned signature" in str(error)
    assert FINGERPRINT in str(error)
    assert isinstance(error, verify.SignatureError)
    assert json.loads(known_path.read_text()) == {}
    assert not pending_path.exists()


async def test_matching_pinned_signature_passes(monkeypatch, tmp_path):
    _setup_pins(monkeypatch, tmp_path, known={"reddit": FINGERPRINT})
    _stub_fingerprints(monkeypatch, [FINGERPRINT])

    successes = []
    monkeypatch.setattr(verify.log, "success", successes.append)

    await verify.verify_apk_signature("reddit.apk", "reddit")

    assert len(successes) == 1


async def test_mismatched_signature_raises(monkeypatch, tmp_path):
    _setup_pins(monkeypatch, tmp_path, known={"reddit": FINGERPRINT})
    _stub_fingerprints(monkeypatch, [OTHER])

    with pytest.raises(verify.SignatureError, match="MISMATCH"):
        await verify.verify_apk_signature("reddit.apk", "reddit")


async def test_mismatch_is_not_reported_as_an_unpinned_signature(monkeypatch, tmp_path):
    _setup_pins(monkeypatch, tmp_path, known={"reddit": FINGERPRINT})
    _stub_fingerprints(monkeypatch, [OTHER])

    with pytest.raises(verify.SignatureError) as exc_info:
        await verify.verify_apk_signature("reddit.apk", "reddit")

    assert not isinstance(exc_info.value, verify.UnpinnedSignature)


async def test_pinned_signature_can_match_any_of_multiple_certificates(monkeypatch, tmp_path):
    _setup_pins(monkeypatch, tmp_path, known={"reddit": FINGERPRINT})
    _stub_fingerprints(monkeypatch, [OTHER, FINGERPRINT])
    monkeypatch.setattr(verify.log, "success", lambda msg: None)

    await verify.verify_apk_signature("reddit.apk", "reddit")


async def test_corrupt_pins_file_fails_with_a_precise_error_instead_of_looking_unpinned(monkeypatch, tmp_path):
    known_path, _ = _setup_pins(monkeypatch, tmp_path)
    known_path.write_text('{\n  "reddit": "abc",\n}\n')
    _stub_fingerprints(monkeypatch, [FINGERPRINT])

    with pytest.raises(verify.SignatureError, match=r"line \d+, column \d+") as exc_info:
        await verify.verify_apk_signature("reddit.apk", "reddit")

    assert not isinstance(exc_info.value, verify.UnpinnedSignature)


def test_resolve_verifiable_apk_plain_apk_file(tmp_path):
    apk = tmp_path / "youtube.apk"
    apk.write_bytes(b"not actually a zip")
    path, temp_dir = verify._resolve_verifiable_apk(str(apk))
    assert path == str(apk)
    assert temp_dir is None


def test_resolve_verifiable_apk_rejects_non_apk_non_zip_files(tmp_path):
    other = tmp_path / "thing.bin"
    other.write_bytes(b"not a zip")
    with pytest.raises(verify.SignatureError, match="neither a single .apk"):
        verify._resolve_verifiable_apk(str(other))


def test_resolve_verifiable_apk_zip_with_manifest_is_used_directly(tmp_path):
    apk = tmp_path / "youtube.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", "x")
    path, temp_dir = verify._resolve_verifiable_apk(str(apk))
    assert path == str(apk)
    assert temp_dir is None


def test_resolve_verifiable_apk_bundle_extracts_base_apk(tmp_path):
    bundle = tmp_path / "reddit.apkm"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("info.json", "{}")
        zf.writestr("base.apk", "base-apk-content")
        zf.writestr("split_config.arm64_v8a.apk", "split-content")

    path, temp_dir = verify._resolve_verifiable_apk(str(bundle))
    try:
        assert path.endswith("base.apk")
        assert Path(path).exists()
        assert temp_dir is not None
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def test_resolve_verifiable_apk_bundle_without_base_apk_raises(tmp_path):
    bundle = tmp_path / "weird.apkm"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("readme.txt", "nothing useful here")

    with pytest.raises(verify.SignatureError, match="No verifiable .apk"):
        verify._resolve_verifiable_apk(str(bundle))


async def test_bundle_is_verified_through_its_extracted_base_apk_and_cleaned_up(monkeypatch, tmp_path):
    _setup_pins(monkeypatch, tmp_path, known={"reddit": FINGERPRINT})
    monkeypatch.setattr(verify.log, "success", lambda msg: None)
    seen = []

    async def fake(path):
        seen.append(path)
        assert Path(path).exists()
        return [FINGERPRINT]

    monkeypatch.setattr(verify, "apk_certificate_fingerprints", fake)

    bundle = tmp_path / "reddit.apkm"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("base.apk", "base-apk-content")

    await verify.verify_apk_signature(str(bundle), "reddit")

    assert seen[0].endswith("base.apk")
    assert not Path(seen[0]).exists()
