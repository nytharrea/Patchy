import asyncio
import json
from pathlib import Path

import pytest

from patchy import catalog
from patchy.engine.signer import Credentials, SigningError
from patchy.publish import pipeline
from patchy.publish.release import ReleaseBodyRejected

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

    async def fake_sign(source, dest, credentials, timings=None):
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

    async def fake_sign(source, dest, credentials, timings=None):
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

    async def fake_sign(source, dest, credentials, timings=None):
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

    async def fake_sign(source, dest, credentials, timings=None):
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

    async def fake_sign(source, dest, credentials, timings=None):
        dest.write_bytes(b"signed")
        return FINGERPRINT if source.name.startswith("YouTube") else "b" * 64

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    assert any("different signing certificates" in w for w in warnings)


async def test_run_sign_signs_the_largest_apks_first(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    monkeypatch.setattr(pipeline.settings, "sign_concurrency", 1)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk", b"y" * 300)
    _artifact(root, "apk-gboard", "Gboard-2.0.apk", b"g" * 20)
    _artifact(root, "apk-brave", "Brave-1.0.apk", b"b" * 9000)
    _artifact(root, "apk-inshot", "InShot-1.0.apk", b"i" * 1200)
    order = []

    async def fake_sign(source, dest, credentials, timings=None):
        order.append(source.name)
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    assert order == ["Brave-1.0.apk", "InShot-1.0.apk", "YouTube-19.1.apk", "Gboard-2.0.apk"]


async def test_run_sign_never_signs_more_apks_at_once_than_configured(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    monkeypatch.setattr(pipeline.settings, "sign_concurrency", 2)
    for name in ("YouTube-1.apk", "Gboard-1.apk", "Brave-1.apk", "InShot-1.apk", "Reddit-1.apk", "Twitter-1.apk"):
        _artifact(root, f"apk-{name}", name)
    state = {"active": 0, "peak": 0}

    async def fake_sign(source, dest, credentials, timings=None):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        for _ in range(4):
            await asyncio.sleep(0)
        state["active"] -= 1
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    fingerprints = await pipeline.run_sign()

    assert state["peak"] == 2
    assert len(fingerprints) == 6


async def test_run_sign_reports_the_time_of_every_signing_stage(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk", b"y" * 2048)
    messages = []
    monkeypatch.setattr(pipeline.log, "success", messages.append)
    monkeypatch.setattr(pipeline.log, "info", messages.append)

    async def fake_sign(source, dest, credentials, timings=None):
        timings.update({"align": 1.5, "sign": 2.5, "verify": 0.5})
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    await pipeline.run_sign()

    signed = next(m for m in messages if m.startswith("Signed and verified: YouTube-19.1.apk"))
    assert "align 1.5, sign 2.5, verify 0.5" in signed
    assert any(m.startswith("Signed 1 of 1 APK(s)") for m in messages)


async def test_a_failed_apk_does_not_stop_the_others_from_being_signed(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    _quiet(monkeypatch)
    monkeypatch.setattr(pipeline.settings, "sign_concurrency", 1)
    _artifact(root, "apk-brave", "Brave-1.0.apk", b"b" * 900)
    _artifact(root, "apk-youtube", "YouTube-19.1.apk", b"y" * 100)
    signed = []

    async def fake_sign(source, dest, credentials, timings=None):
        if source.name.startswith("Brave"):
            raise SigningError("apksigner sign failed for Brave-1.0.apk: out of space")
        signed.append(source.name)
        dest.write_bytes(b"signed")
        return FINGERPRINT

    monkeypatch.setattr(pipeline.toolchain, "prepare", _prepare_ok)
    monkeypatch.setattr(pipeline, "load_credentials", lambda: None)
    monkeypatch.setattr(pipeline, "sign_apk", fake_sign)

    fingerprints = await pipeline.run_sign()

    assert signed == ["YouTube-19.1.apk"]
    assert list(fingerprints) == ["YouTube-19.1.apk"]
    assert (root / "signed" / "status-brave.json").is_file()


class _Recorder:
    def __init__(self):
        self.release_args = None
        self.uploaded = []
        self.companions = None
        self.upload_calls = 0
        self.deleted_keep = None
        self.deleted_retention = None
        self.notifications = []
        self.delete_error = None
        self.previous = None
        self.previous_error = None
        self.previous_state = None
        self.lookups = []
        self.downloaded = []
        self.download_errors = {}
        self.state_uploads = []
        self.state_error = None


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

    async def fake_upload(rel, paths, companions):
        recorder.upload_calls += 1
        recorder.uploaded = list(paths)
        recorder.companions = [c["key"] for c in companions]

    async def fake_delete(keep_id, keep=0):
        recorder.deleted_keep = keep_id
        recorder.deleted_retention = keep
        if recorder.delete_error:
            raise recorder.delete_error

    async def fake_previous(exclude_tag=""):
        recorder.lookups.append(exclude_tag)
        if recorder.previous_error:
            raise recorder.previous_error
        return recorder.previous

    async def fake_download(asset, destination):
        if asset["name"] in recorder.download_errors:
            raise recorder.download_errors[asset["name"]]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"carried " + asset["name"].encode())
        recorder.downloaded.append(asset["name"])
        return destination

    async def fake_state(release):
        return recorder.previous_state

    async def fake_upload_state(rel, path):
        if recorder.state_error:
            raise recorder.state_error
        recorder.state_uploads.append(json.loads(Path(path).read_text()))

    async def fake_notify(text):
        recorder.notifications.append(text)

    monkeypatch.setattr(pipeline, "create_new_release", fake_create)
    monkeypatch.setattr(pipeline, "upload_assets", fake_upload)
    monkeypatch.setattr(pipeline, "delete_other_releases", fake_delete)
    monkeypatch.setattr(pipeline, "previous_release", fake_previous)
    monkeypatch.setattr(pipeline, "download_asset", fake_download)
    monkeypatch.setattr(pipeline, "read_release_state", fake_state)
    monkeypatch.setattr(pipeline, "upload_with_replace", fake_upload_state)
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
    assert recorder.upload_calls == 1
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

    assert recorder.companions == []


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


async def test_run_publish_keeps_the_description_under_githubs_limit_however_long_the_notes_are(
    monkeypatch, tmp_path
):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    manifest = _manifest(["youtube", "gboard"])
    for entry in manifest["bundles"].values():
        entry["body"] = "- a change\n" * 40_000
    _wire_publish(monkeypatch, recorder, manifest)
    _signed(root, "YouTube-19.1.apk")
    _signed(root, "Gboard-2.0.apk")

    assert await pipeline.run_publish() is True

    body = recorder.release_args[2]
    assert len(body) < 125_000
    assert "shortened to fit GitHub's size limit" in body
    assert recorder.upload_calls == 1


async def test_run_publish_retries_without_bundle_notes_when_github_still_refuses_the_description(
    monkeypatch, tmp_path
):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")
    bodies = []
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)

    async def fake_create(tag, name, body, draft=False):
        bodies.append(body)
        if len(bodies) == 1:
            raise ReleaseBodyRejected("Failed to create release: body is too long")
        return {"id": 42, "tag_name": tag, "html_url": "https://github.com/owner/repo/releases/tag/x"}

    monkeypatch.setattr(pipeline, "create_new_release", fake_create)

    assert await pipeline.run_publish() is True

    assert len(bodies) == 2
    assert "<details>" in bodies[0]
    assert "<details>" not in bodies[1]
    assert "**YouTube** - `19.1`" in bodies[1]
    assert recorder.upload_calls == 1
    assert recorder.deleted_keep == 42
    assert any("rejected the release description" in w for w in warnings)


async def test_run_publish_does_not_retry_when_the_release_fails_for_another_reason(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")
    attempts = []

    async def fake_create(tag, name, body, draft=False):
        attempts.append(body)
        raise RuntimeError("Failed to create release: Bad credentials")

    monkeypatch.setattr(pipeline, "create_new_release", fake_create)

    with pytest.raises(RuntimeError, match="Bad credentials"):
        await pipeline.run_publish()

    assert len(attempts) == 1
    assert recorder.upload_calls == 0


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


PREVIOUS_TAG = "build-2026-10-03T10-00-00"


def _previous_release(*names):
    return {
        "id": 7,
        "tag_name": PREVIOUS_TAG,
        "assets": [{"name": name, "url": f"https://api.github.com/assets/{name}", "size": 5} for name in names],
    }


def _status(root, key, **payload):
    directory = root / "artifacts" / f"apk-{key}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"status-{key}.json").write_text(json.dumps({"build_key": key, **payload}))


async def test_run_publish_carries_over_the_apps_that_were_not_built(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.previous = _previous_release(
        "Gboard-2.0.apk", "YouTube-18.0.apk", "MicroG.apk", "Proton.VPN-4.1.apk", "patchy-state.json"
    )
    _wire_publish(monkeypatch, recorder, _manifest(["youtube", "gboard"]))
    _signed(root, "YouTube-19.1.apk")
    _status(root, "gboard", ok=False, error="HTTP 500 fetching listing page")

    assert await pipeline.run_publish() is True

    assert recorder.lookups == ["build-2026-10-04T10-00-00"]
    assert sorted(recorder.downloaded) == ["Gboard-2.0.apk", "Proton.VPN-4.1.apk"]
    assert sorted(Path(p).name for p in recorder.uploaded) == [
        "Gboard-2.0.apk",
        "Proton.VPN-4.1.apk",
        "YouTube-19.1.apk",
    ]
    assert "Carried over from `build-2026-10-03T10-00-00`" in recorder.release_args[2]
    assert "The new build failed: `HTTP 500 fetching listing page`" in recorder.release_args[2]
    summary = recorder.notifications[0]
    assert "1 app(s) patched" in summary
    assert "2 app(s) carried over from the previous release" in summary
    assert "Gboard — 2.0" in summary
    assert "gboard — HTTP 500 fetching listing page — previous build kept" in summary


async def test_carried_apps_bring_their_companion_apps_along(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.previous = _previous_release("YouTube-18.0.apk")
    _wire_publish(monkeypatch, recorder, _manifest(["gboard"]))
    _signed(root, "Gboard-2.0.apk")

    await pipeline.run_publish()

    assert sorted(recorder.companions) == ["microg", "pothelper"]


async def test_the_carry_over_can_be_switched_off(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.previous = _previous_release("Gboard-2.0.apk")
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    monkeypatch.setattr(pipeline.settings, "carry_forward", False)
    _signed(root, "YouTube-19.1.apk")

    await pipeline.run_publish()

    assert recorder.lookups == []
    assert recorder.downloaded == []
    assert [Path(p).name for p in recorder.uploaded] == ["YouTube-19.1.apk"]
    assert list(recorder.state_uploads[0]["builds"]) == ["youtube"]


async def test_a_carried_apk_that_cannot_be_downloaded_is_skipped_with_a_warning(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.previous = _previous_release("Gboard-2.0.apk", "Brave-1.0.apk")
    recorder.download_errors["Gboard-2.0.apk"] = RuntimeError("HTTP 502")
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)
    _signed(root, "YouTube-19.1.apk")

    assert await pipeline.run_publish() is True

    assert sorted(Path(p).name for p in recorder.uploaded) == ["Brave-1.0.apk", "YouTube-19.1.apk"]
    assert any("Could not carry Gboard-2.0.apk" in w and "HTTP 502" in w for w in warnings)


async def test_a_failing_previous_release_lookup_does_not_stop_publishing(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.previous_error = RuntimeError("API down")
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)
    _signed(root, "YouTube-19.1.apk")

    assert await pipeline.run_publish() is True

    assert [Path(p).name for p in recorder.uploaded] == ["YouTube-19.1.apk"]
    assert any("API down" in w for w in warnings)


async def test_the_state_file_records_what_was_built_and_what_was_carried(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.previous = _previous_release("Gboard-2.0.apk", "patchy-state.json")
    recorder.previous_state = {
        "version": 1,
        "release_tag": PREVIOUS_TAG,
        "builds": {"gboard": {"version": "2.0", "file": "Gboard-2.0.apk", "fingerprint": "kept"}},
    }
    manifest = _manifest(["youtube", "gboard"])
    manifest["fingerprints"] = {"youtube": "fresh", "gboard": "ignored"}
    _wire_publish(monkeypatch, recorder, manifest)
    _signed(root, "YouTube-19.1.apk")
    _status(
        root, "youtube", ok=True, version="19.1", attempts=[{"version": "19.2", "stage": "patch", "reason": "x"}]
    )

    await pipeline.run_publish()

    assert recorder.state_uploads == [
        {
            "version": 1,
            "release_tag": "build-2026-10-04T10-00-00",
            "builds": {
                "gboard": {"version": "2.0", "file": "Gboard-2.0.apk", "fingerprint": "kept"},
                "youtube": {"version": "19.1", "file": "YouTube-19.1.apk", "fingerprint": "fresh", "retry": True},
            },
        }
    ]


async def test_a_state_that_cannot_be_uploaded_only_warns(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    recorder.state_error = RuntimeError("upload refused")
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    warnings = []
    monkeypatch.setattr(pipeline.log, "warn", warnings.append)
    _signed(root, "YouTube-19.1.apk")

    assert await pipeline.run_publish() is True

    assert any("patchy-state.json" in w and "upload refused" in w for w in warnings)
    assert recorder.deleted_keep == 42
    assert len(recorder.notifications) == 1


async def test_old_releases_are_deleted_with_the_configured_retention(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")

    await pipeline.run_publish()
    assert recorder.deleted_retention == pipeline.settings.keep_releases == 1

    monkeypatch.setattr(pipeline.settings, "keep_releases", 4)
    await pipeline.run_publish()
    assert recorder.deleted_retention == 4


async def test_the_release_notes_and_the_notification_show_what_was_patched(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _signed(root, "YouTube-19.1.apk")
    _status(
        root,
        "youtube",
        ok=True,
        version="19.1",
        patches={"applied": ["Hide ads", "Video ads"], "failed": []},
        attempts=[{"version": "19.2", "stage": "patch", "reason": "Hide ads: boom"}],
        warnings=["The patched APK still holds native libraries for x86."],
        forced=True,
    )

    await pipeline.run_publish()

    body = recorder.release_args[2]
    assert "YouTube - 2 patches applied" in body
    assert "`Hide ads`, `Video ads`" in body
    assert "Newer versions could not be used: `19.2` (patch: `Hide ads: boom`)" in body
    assert "Patched with `--force`" in body
    assert "native libraries for x86" in body
    summary = recorder.notifications[0]
    assert "YouTube — 19.1 (2 patch(es); newer not usable: 19.2; forced; 1 warning(s))" in summary


async def test_a_run_without_any_new_apk_still_reports_the_attempts(monkeypatch, tmp_path):
    root = _build_dir(monkeypatch, tmp_path)
    recorder = _Recorder()
    _wire_publish(monkeypatch, recorder, _manifest(["youtube"]))
    _status(
        root,
        "youtube",
        ok=False,
        error="Hide ads: boom",
        attempts=[
            {"version": "19.2", "stage": "patch", "reason": "x"},
            {"version": "19.1", "stage": "patch", "reason": "y"},
        ],
    )

    assert await pipeline.run_publish() is False

    assert "youtube — Hide ads: boom (tried 19.2, 19.1)" in recorder.notifications[0]
    assert recorder.lookups == []
