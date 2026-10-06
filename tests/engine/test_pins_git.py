import json
import subprocess

import pytest

from patchy.engine import pins

A = "a" * 64
B = "b" * 64


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def _commit(cwd, message):
    _git(cwd, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", message)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _repo(tmp_path, known, pending):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(origin), str(work))
    _write(work / "pins" / "known.json", known)
    _write(work / "pins" / "pending.json", pending)
    _git(work, "checkout", "-b", "main")
    _git(work, "add", "-A")
    _commit(work, "initial")
    _git(work, "push", "origin", "HEAD:main")
    return origin, work


def _point_settings_at(monkeypatch, work):
    monkeypatch.chdir(work)
    monkeypatch.setattr(pins.settings, "known_pins_path", work / "pins" / "known.json")
    monkeypatch.setattr(pins.settings, "pending_pins_path", work / "pins" / "pending.json")


def _remote_json(origin, name):
    return json.loads(_git(origin, "show", f"main:pins/{name}"))


def test_commit_promotion_pushes_the_moved_fingerprint_to_the_remote(monkeypatch, tmp_path):
    origin, work = _repo(tmp_path, known={"gboard": B}, pending={"youtube": A})
    _point_settings_at(monkeypatch, work)

    assert pins.commit_promotion("youtube", A) == A

    assert _remote_json(origin, "known.json") == {"gboard": B, "youtube": A}
    assert _remote_json(origin, "pending.json") == {}
    assert "pin signing certificate for youtube" in _git(origin, "log", "-1", "--format=%s", "main")


def test_commit_promotion_starts_from_whatever_the_remote_currently_has(monkeypatch, tmp_path):
    origin, work = _repo(tmp_path, known={}, pending={"youtube": A})
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(origin), str(other))
    _write(other / "pins" / "known.json", {"gboard": B})
    _git(other, "add", "-A")
    _commit(other, "someone else pinned gboard")
    _git(other, "push", "origin", "HEAD:main")
    _point_settings_at(monkeypatch, work)

    pins.commit_promotion("youtube", A)

    assert _remote_json(origin, "known.json") == {"gboard": B, "youtube": A}


def test_commit_pending_records_a_new_fingerprint_on_the_remote(monkeypatch, tmp_path):
    origin, work = _repo(tmp_path, known={"gboard": B}, pending={})
    _point_settings_at(monkeypatch, work)

    assert pins.commit_pending({"youtube": A}) is True

    assert _remote_json(origin, "pending.json") == {"youtube": A}
    assert _remote_json(origin, "known.json") == {"gboard": B}


def test_commit_pending_makes_no_commit_when_the_fingerprint_is_already_recorded(monkeypatch, tmp_path):
    origin, work = _repo(tmp_path, known={}, pending={"youtube": A})
    _point_settings_at(monkeypatch, work)
    before = _git(origin, "rev-parse", "main")

    assert pins.commit_pending({"youtube": A}) is False

    assert _git(origin, "rev-parse", "main") == before


def test_a_failed_promotion_leaves_the_remote_untouched(monkeypatch, tmp_path):
    origin, work = _repo(tmp_path, known={}, pending={})
    _point_settings_at(monkeypatch, work)
    before = _git(origin, "rev-parse", "main")

    with pytest.raises(pins.PinsError, match="no pending fingerprint"):
        pins.commit_promotion("youtube")

    assert _git(origin, "rev-parse", "main") == before
