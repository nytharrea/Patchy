import json
from pathlib import Path

import pytest

from patchy import catalog
from patchy.engine.signer import Credentials, SigningError
from patchy.publish import pipeline

FINGERPRINT = "3d7a1223019aa39d9ea0e3436ab7c0896bfb4fb679f4de5fe7c23f326c8f994a"


def _quiet(monkeypatch):
    for name in ("info", "step", "warn", "error", "success", "lock", "notice"):
        monkeypatch.setattr(pipeline.log, name, lambda msg: None)


def _build_dir(monkeypatch, tmp_path):
    root = tmp_path / "build"
    monkeypatch.setenv("PATCHY_BUILD_DIR", str(root))
    return root


def _artifact(root, job, name, content=b"patched"):
    directory = root / "artifacts" / job
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(content)


async def _prepare_ok(install_latest=True):
    return {}


async def test_run_sign_signs_every_matched_apk_into_the_signed_directory(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk")
    _artifact(root, "apk-gboard", "Gboard-2.0.apk")
    _artifact(root, "apk-weird", "Mystery-1.0.apk")
    creds = Credentials(tmp_path / "ks", "alias", "p1", "p2")
    signed = []

    async def fake_sign(source, dest, credentials):
        assert credentials is creds
        signed.append(source.name)
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: creds)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    fingerprints = await pipeline.run_sign()

    assert sorted(signed) == ["Gboard-2.0.apk", "YouTube-19.1.apk"]
    assert sorted(p.name for p in (root / "signed").glob("*.apk")) == ["Gboard-2.0.apk", "YouTube-19.1.apk"]
    assert fingerprints == {"YouTube-19.1.apk": FINGERPRINT, "Gboard-2.0.apk": FINGERPRINT}


async def test_run_sign_prepares_the_toolchain_with_the_latest_build_tools(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk")
    requested = []

    async def fake_prepare(install_latest=True):
        requested.append(install_latest)
        return {}

    async def fake_sign(source, dest, credentials):
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", fake_prepare)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    assert requested == [True]


async def test_a_signing_failure_drops_only_that_app_and_leaves_a_reason_behind(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk")
    _artifact(root, "apk-gboard", "Gboard-2.0.apk")

    async def fake_sign(source, dest, credentials):
        if source.name.startswith("Gboard"):
            raise SigningError("apksigner sign failed for Gboard-2.0.apk: bad keystore")
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    assert [p.name for p in (root / "signed").glob("*.apk")] == ["YouTube-19.1.apk"]
    status = json.loads((root / "signed" / "status-gboard.json").read_text())
    assert status["ok"] is False
    assert "signing failed" in status["error"]
    assert "bad keystore" in status["error"]


async def test_run_sign_warns_when_credentials_are_missing_but_still_runs(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk")
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)
    seen = []

    async def fake_sign(source, dest, credentials):
        seen.append(credentials)
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    assert seen == [None]
    assert any("credentials" in w for w in warnings)


async def test_run_sign_with_nothing_to_sign_does_not_touch_the_toolchain(monkeypatch, tmp_path):
    _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)

    async def boom(install_latest=True):
        raise AssertionError("no APKs, nothing to prepare")

    monkeypatch.setattr(pipeline.toolchain, "prepare", boom)

    assert await pipeline.run_sign() == {}


async def test_run_sign_warns_when_apks_carry_different_certificates(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk")
    _artifact(root, "apk-gboard", "Gboard-2.0.apk")
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)

    async def fake_sign(source, dest, credentials):
        dest.write_bytes(b"signed")
        return FINGERPRINT if source.name.startswith("YouTube") else "b" * 64

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    assert any("different signing certificates" in w for w in warnings)


class _Recorder:
    def __init__(self):
        self.release_args = None
        self.uploaded = []
        self.companions = None
        self.deleted_keep = None
        self.notifications = []
        self.delete_error = None


def _manifest(builds):
    entry = {"name": "x.mpp", "tag": "v1.2.3", "prerelease": False}
    return {
        "builds": builds,
        "cli": {**entry, "body": ""},
        "bundles": {key: {**entry, "body": f"notes for {key}"} for key in catalog.BUNDLES},
    }


def _wire_publish(monkeypatch, recorder, manifest):
    _quiet(monkeypatch)
    monkeypatch.setattr(pipeline.settings, "release_tag", "build-2026-10-04T10-00-00")
    monkeypatch.setattr(pipeline.settings, "release_name", "Patched APKs - 4 October 2026")
    monkeypatch.setattr(pipeline.settings, "github_repository", "owner/repo")
    monkeypatch.setattr(pipeline, "read_manifest", lambda: manifest)

    async def fake_create(tag, name, body, draft=False):
        recorder.release_args = (tag, name, body, draft)
        return {"id": 42, "tag_name": tag, "html_url": "https://github.com/owner/repo/releases/tag/x"}

    async def fake_upload(rel, paths):
        recorder.uploaded = list(paths)

    async def fake_companions(rel, companions):
        recorder.companions = [c["key"] for c in companions]

    async def fake_delete(keep_id):
        recorder.deleted_keep = keep_id
        if recorder.delete_error:
            raise recorder.delete_error

    async def fake_notify(text):
        recorder.notifications.append(text)

    monkeypatch.setattr(pipeline, "create_new_release", fake_create)
    monkeypatch.setattr(pipeline, "upload_patched_apks", fake_upload)
    monkeypatch.setattr(pipeline, "upload_companions", fake_companions)
    monkeypatch.setattr(pipeline, "delete_other_releases", fake_delete)
    monkeypatch.setattr(pipeline.notify, "notify", fake_notify)


def _signed(root, name):
    (root / "signed").mkdir(parents=True, exist_ok=True)
    (root / "signed" / name).write_bytes(b"signed")


async def test_run_publish_creates_the_release_uploads_and_cleans_up(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube", "gboard"]))
    _signed(root, "YouTube-19.1.apk")
    _signed(root, "Gboard-2.0.apk")

    assert await pipeline.run_publish() is True

    tag, name, body, draft = recorder.release_args
    assert tag == "build-2026-10-04T10-00-00"
    assert name == "Patched APKs - 4 October 2026"
    assert draft is False
    assert "**YouTube** - `19.1`" in body
    assert "**Gboard** - `2.0`" in body
    assert "notes for" in body
    assert sorted(Path(p).name for p in recorder.uploaded) == ["Gboard-2.0.apk", "YouTube-19.1.apk"]
    assert recorder.deleted_keep == 42
    assert len(recorder.notifications) == 1
    assert "https://github.com/owner/repo/releases/tag/x" in recorder.notifications[0]


async def test_run_publish_uploads_companions_only_for_the_builds_that_were_published(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")

    await pipeline.run_publish()

    assert sorted(recorder.companions) == ["microg", "pothelper"]


async def test_run_publish_skips_companions_when_no_companion_build_succeeded(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["gboard"]))
    _signed(root, "Gboard-2.0.apk")

    await pipeline.run_publish()

    assert recorder.companions is None


async def test_run_publish_reports_failed_builds_with_their_reasons(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube", "gboard", "brave"]))
    _signed(root, "YouTube-19.1.apk")
    (root / "artifacts" / "apk-gboard").mkdir(parents=True)
    (root / "artifacts" / "apk-gboard" / "status-gboard.json").write_text(
        json.dumps({"build_key": "gboard", "ok": False, "error": "HTTP 500 fetching listing page"})
    )
    (root / "signed" / "status-brave.json").write_text(
        json.dumps({"build_key": "brave", "ok": False, "error": "signing failed: bad keystore"})
    )

    await pipeline.run_publish()

    summary = recorder.notifications[0]
    assert "gboard — HTTP 500 fetching listing page" in summary
    assert "brave — signing failed: bad keystore" in summary


async def test_run_publish_only_counts_builds_that_were_planned(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")

    await pipeline.run_publish()

    assert "failed or produced no APK" not in recorder.notifications[0]


async def test_run_publish_with_no_signed_apks_creates_no_release_and_says_so(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    (root / "artifacts" / "apk-youtube").mkdir(parents=True)
    (root / "artifacts" / "apk-youtube" / "status-youtube.json").write_text(
        json.dumps({"build_key": "youtube", "ok": False, "error": "SIGNATURE MISMATCH"})
    )

    assert await pipeline.run_publish() is False

    assert recorder.release_args is None
    assert recorder.deleted_keep is None
    assert "no apps were patched successfully" in recorder.notifications[0]
    assert "youtube — SIGNATURE MISMATCH" in recorder.notifications[0]


async def test_a_failure_to_delete_old_releases_does_not_fail_the_run(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.delete_error = RuntimeError("Failed to delete release 2")
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)

    assert await pipeline.run_publish() is True

    assert any("Failed to delete old releases" in w for w in warnings)
    assert len(recorder.notifications) == 1


async def test_run_publish_works_without_a_manifest_but_leaves_out_bundle_notes(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, None)
    _signed(root, "YouTube-19.1.apk")

    assert await pipeline.run_publish() is True

    assert "<details>" not in recorder.release_args[2]


async def test_run_publish_requires_the_release_tag_and_name(monkeypatch, tmp_path):
    _build_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline.settings, "release_tag", None)
    monkeypatch.setattr(pipeline.settings, "release_name", None)

    with pytest.raises(RuntimeError, match="RELEASE_TAG"):
        await pipeline.run_publish()


def test_a_missing_manifest_is_survivable(monkeypatch):
    from patchy.fetch.bundles import ManifestError

    def missing():
        raise ManifestError("manifest not found")

    warnings = []
    monkeypatch.setattr(pipeline, "read_manifest", missing)
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)

    assert pipeline._load_manifest() is None
    assert any("manifest not found" in w for w in warnings)
