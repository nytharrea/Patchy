import pytest
from pydantic import ValidationError

from patchy.core.settings import Settings


def _clean(monkeypatch):
    for name in ("SIGN_CONCURRENCY", "UPLOAD_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)


def test_release_concurrency_defaults(monkeypatch):
    _clean(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.sign_concurrency == 4
    assert settings.upload_concurrency == 10


def test_release_concurrency_can_be_set_from_the_environment(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("SIGN_CONCURRENCY", "6")
    monkeypatch.setenv("UPLOAD_CONCURRENCY", "12")

    settings = Settings(_env_file=None)

    assert settings.sign_concurrency == 6
    assert settings.upload_concurrency == 12


@pytest.mark.parametrize("name", ["SIGN_CONCURRENCY", "UPLOAD_CONCURRENCY"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_concurrency_below_one_is_rejected(monkeypatch, name, value):
    _clean(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
