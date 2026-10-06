import json
from types import SimpleNamespace

import pytest

from patchy import catalog
from patchy.engine import pins

A = "a" * 64
B = "b" * 64
C = "c" * 64


def _setup(monkeypatch, tmp_path, known=None, pending=None):
    known_path = tmp_path / "known.json"
    pending_path = tmp_path / "pending.json"
    known_path.write_text(json.dumps(known or {}))
    pending_path.write_text(json.dumps(pending or {}))
    monkeypatch.setattr(pins.settings, "known_pins_path", known_path)
    monkeypatch.setattr(pins.settings, "pending_pins_path", pending_path)
    return known_path, pending_path


def test_normalize_sha256_accepts_colons_and_uppercase():
    assert pins.normalize_sha256(":".join(["AB"] * 32)) == "ab" * 32


@pytest.mark.parametrize("value", ["", "abc", "z" * 64, "a" * 63, "a" * 65])
def test_normalize_sha256_rejects_anything_else(value):
    with pytest.raises(pins.PinsError, match="SHA-256"):
        pins.normalize_sha256(value)


def test_load_pins_missing_file_is_empty(tmp_path):
    assert pins.load_pins(tmp_path / "nope.json") == {}


def test_load_pins_reads_a_valid_file(tmp_path):
    path = tmp_path / "known.json"
    path.write_text(json.dumps({"youtube": A}))
    assert pins.load_pins(path) == {"youtube": A}


def test_load_pins_reports_line_and_column_for_broken_json(tmp_path):
    path = tmp_path / "known.json"
    path.write_text('{\n  "youtube": "' + A + '",\n}\n')
    with pytest.raises(pins.PinsError, match=r"line 3, column 1") as exc_info:
        pins.load_pins(path)
    assert "nothing was changed" in str(exc_info.value)


def test_load_pins_rejects_a_non_object(tmp_path):
    path = tmp_path / "known.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(pins.PinsError, match="JSON object"):
        pins.load_pins(path)


def test_load_pins_rejects_entries_that_are_not_fingerprints(tmp_path):
    path = tmp_path / "known.json"
    path.write_text(json.dumps({"youtube": "not-a-fingerprint"}))
    with pytest.raises(pins.PinsError, match="youtube"):
        pins.load_pins(path)


def test_save_pins_writes_sorted_json_with_trailing_newline(tmp_path):
    path = tmp_path / "sub" / "known.json"
    pins.save_pins(path, {"zeta": A, "alpha": B})
    text = path.read_text()
    assert text.endswith("\n")
    assert list(json.loads(text)) == ["alpha", "zeta"]


def test_promote_moves_the_pending_fingerprint_into_known(monkeypatch, tmp_path):
    known_path, pending_path = _setup(monkeypatch, tmp_path, known={"gboard": B}, pending={"youtube": A})

    assert pins.promote("youtube") == A

    assert json.loads(known_path.read_text()) == {"gboard": B, "youtube": A}
    assert json.loads(pending_path.read_text()) == {}


def test_promote_checks_the_fingerprint_you_verified(monkeypatch, tmp_path):
    known_path, pending_path = _setup(monkeypatch, tmp_path, pending={"youtube": A})

    with pytest.raises(pins.PinsError, match="does not match"):
        pins.promote("youtube", B)

    assert json.loads(known_path.read_text()) == {}
    assert json.loads(pending_path.read_text()) == {"youtube": A}


def test_promote_accepts_the_matching_fingerprint_in_colon_form(monkeypatch, tmp_path):
    known_path, _ = _setup(monkeypatch, tmp_path, pending={"youtube": "ab" * 32})
    pins.promote("youtube", ":".join(["AB"] * 32))
    assert json.loads(known_path.read_text()) == {"youtube": "ab" * 32}


def test_promote_without_a_pending_entry_fails(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    with pytest.raises(pins.PinsError, match="no pending fingerprint"):
        pins.promote("youtube")


def test_promote_rejects_an_unknown_app(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, pending={"made-up-app": A})
    with pytest.raises(pins.PinsError, match="Unknown app"):
        pins.promote("made-up-app")


def test_promote_replaces_an_old_known_fingerprint(monkeypatch, tmp_path):
    known_path, pending_path = _setup(monkeypatch, tmp_path, known={"youtube": B}, pending={"youtube": A})
    pins.promote("youtube")
    assert json.loads(known_path.read_text()) == {"youtube": A}
    assert json.loads(pending_path.read_text()) == {}


def test_promote_is_idempotent_when_known_already_has_the_value(monkeypatch, tmp_path):
    known_path, pending_path = _setup(monkeypatch, tmp_path, known={"youtube": A}, pending={"youtube": A})
    assert pins.promote("youtube") == A
    assert json.loads(known_path.read_text()) == {"youtube": A}
    assert json.loads(pending_path.read_text()) == {}


def test_collect_pending_drops_unknown_apps_and_malformed_fingerprints():
    accepted = pins.collect_pending({"youtube": A, "made-up": B, "gboard": "oops", "reddit": C})
    assert accepted == {"youtube": A, "reddit": C}


class _FakeGit:
    def __init__(self, tmp_path, push_results=None, commit_returncode=0, on_reset=None):
        self.calls = []
        self.push_results = list(push_results or [0])
        self.commit_returncode = commit_returncode
        self.on_reset = on_reset

    def __call__(self, *args):
        self.calls.append(list(args))
        if args[0] == "reset" and self.on_reset:
            self.on_reset()
        if args[0] == "commit":
            return SimpleNamespace(returncode=self.commit_returncode, stderr="", stdout="")
        if args[0] == "push":
            code = self.push_results.pop(0) if self.push_results else 0
            return SimpleNamespace(returncode=code, stderr="rejected" if code else "", stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    def names(self):
        return [c[0] for c in self.calls]


def test_commit_with_retry_resets_to_origin_before_mutating_and_pushes(monkeypatch, tmp_path):
    fake = _FakeGit(tmp_path)
    monkeypatch.setattr(pins, "git", fake)
    order = []
    fake.on_reset = lambda: order.append("reset")

    def mutate():
        order.append("mutate")
        return True

    assert pins.commit_with_retry([tmp_path / "x.json"], mutate, "msg") is True

    assert order == ["reset", "mutate"]
    assert fake.names() == ["config", "config", "fetch", "reset", "add", "commit", "push"]
    assert ["reset", "--hard", "origin/main"] in fake.calls
    assert ["push", "origin", "HEAD:main"] in fake.calls


def test_commit_with_retry_does_nothing_when_nothing_changed(monkeypatch, tmp_path):
    fake = _FakeGit(tmp_path)
    monkeypatch.setattr(pins, "git", fake)

    assert pins.commit_with_retry([tmp_path / "x.json"], lambda: False, "msg") is False

    assert "commit" not in fake.names()
    assert "push" not in fake.names()


def test_commit_with_retry_retries_after_a_rejected_push(monkeypatch, tmp_path):
    fake = _FakeGit(tmp_path, push_results=[1, 1, 0])
    monkeypatch.setattr(pins, "git", fake)
    monkeypatch.setattr(pins.retry_conf, "incrementing", lambda **kw: lambda state: 0.0)
    mutations = []

    def mutate():
        mutations.append(1)
        return True

    assert pins.commit_with_retry([tmp_path / "x.json"], mutate, "msg") is True

    assert fake.names().count("push") == 3
    assert len(mutations) == 3


def test_commit_with_retry_gives_up_after_repeated_conflicts(monkeypatch, tmp_path):
    fake = _FakeGit(tmp_path, push_results=[1] * 10)
    monkeypatch.setattr(pins, "git", fake)
    monkeypatch.setattr(pins.retry_conf, "incrementing", lambda **kw: lambda state: 0.0)

    with pytest.raises(pins.PushConflict):
        pins.commit_with_retry([tmp_path / "x.json"], lambda: True, "msg")

    assert fake.names().count("push") == 6


def test_commit_with_retry_treats_an_empty_commit_as_nothing_to_do(monkeypatch, tmp_path):
    fake = _FakeGit(tmp_path, commit_returncode=1)
    monkeypatch.setattr(pins, "git", fake)

    assert pins.commit_with_retry([tmp_path / "x.json"], lambda: True, "msg") is False
    assert "push" not in fake.names()


def test_commit_pending_records_new_fingerprints_after_the_reset(monkeypatch, tmp_path):
    known_path, pending_path = _setup(monkeypatch, tmp_path, known={"gboard": B})
    fake = _FakeGit(tmp_path, on_reset=lambda: pending_path.write_text("{}"))
    monkeypatch.setattr(pins, "git", fake)

    assert pins.commit_pending({"youtube": A, "made-up": C}) is True

    assert json.loads(pending_path.read_text()) == {"youtube": A}
    commit = next(c for c in fake.calls if c[0] == "commit")
    assert "youtube" in commit[-1]
    assert "made-up" not in commit[-1]


def test_commit_pending_skips_fingerprints_that_are_already_trusted(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, known={"youtube": A})
    fake = _FakeGit(tmp_path)
    monkeypatch.setattr(pins, "git", fake)

    assert pins.commit_pending({"youtube": A}) is False
    assert "commit" not in fake.names()


def test_commit_pending_with_nothing_usable_never_touches_git(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fake = _FakeGit(tmp_path)
    monkeypatch.setattr(pins, "git", fake)

    assert pins.commit_pending({"made-up": A}) is False
    assert fake.calls == []


def test_commit_promotion_moves_the_value_on_the_freshly_reset_files(monkeypatch, tmp_path):
    known_path, pending_path = _setup(monkeypatch, tmp_path)
    fake = _FakeGit(tmp_path, on_reset=lambda: pending_path.write_text(json.dumps({"youtube": A})))
    monkeypatch.setattr(pins, "git", fake)

    assert pins.commit_promotion("youtube", A) == A

    assert json.loads(known_path.read_text()) == {"youtube": A}
    assert json.loads(pending_path.read_text()) == {}
    assert "push" in fake.names()


def test_every_catalog_app_slug_is_a_valid_pin_target():
    assert pins.known_slugs() == {b["app_slug"] for b in catalog.BUILDS.values()}
