import pytest

from patchy.catalog import validate


def test_real_catalog_passes_validation():
    validate.validate_catalog()


def _youtube_build():
    return dict(validate.BUILDS["youtube"])


def test_unknown_patch_source_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "bundles": ["totally-made-up-source"]})
    with pytest.raises(validate.ConfigError, match="totally-made-up-source"):
        validate.validate_catalog()


def test_build_with_no_bundles_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "bundles": []})
    with pytest.raises(validate.ConfigError, match="no bundles"):
        validate.validate_catalog()


def test_exclude_as_string_instead_of_list_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "exclude": "Dynamic color"})
    with pytest.raises(validate.ConfigError, match="should be a list"):
        validate.validate_catalog()


def test_enable_as_string_instead_of_list_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "enable": "Clone app"})
    with pytest.raises(validate.ConfigError, match="should be a list"):
        validate.validate_catalog()


def test_multiple_problems_are_all_reported_together(monkeypatch):
    monkeypatch.setitem(
        validate.BUILDS,
        "youtube",
        {**_youtube_build(), "bundles": ["made-up"], "exclude": "not-a-list"},
    )
    with pytest.raises(validate.ConfigError) as exc_info:
        validate.validate_catalog()
    message = str(exc_info.value)
    assert "made-up" in message
    assert "should be a list" in message


def test_apkmirror_source_missing_a_required_field_is_caught(monkeypatch):
    build = _youtube_build()
    broken_source = {**build["apk_source"]}
    del broken_source["slug"]
    monkeypatch.setitem(validate.BUILDS, "youtube", {**build, "apk_source": broken_source})
    with pytest.raises(validate.ConfigError, match='apkmirror.*no "slug"'):
        validate.validate_catalog()


def test_github_source_missing_required_fields_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "apk_source": {"type": "github"}})
    with pytest.raises(validate.ConfigError) as exc_info:
        validate.validate_catalog()
    message = str(exc_info.value)
    assert 'no "owner"' in message
    assert 'no "repo"' in message


def test_apk_source_with_no_recognized_type_has_no_field_requirements(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "apk_source": {"type": "carrier-pigeon"}})
    validate.validate_catalog()


def test_valid_options_pass(monkeypatch):
    monkeypatch.setitem(
        validate.BUILDS,
        "youtube",
        {**_youtube_build(), "options": {"Custom branding.App name": "YouTube Özel"}},
    )
    validate.validate_catalog()


def test_options_as_a_list_instead_of_a_dict_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "options": ["not-a-dict"]})
    with pytest.raises(validate.ConfigError, match="should be a mapping"):
        validate.validate_catalog()


def test_options_key_without_a_dot_is_caught(monkeypatch):
    monkeypatch.setitem(validate.BUILDS, "youtube", {**_youtube_build(), "options": {"NoDotHere": "x"}})
    with pytest.raises(validate.ConfigError, match="Patch name.optionKey"):
        validate.validate_catalog()


def test_companion_for_an_unknown_build_is_caught(monkeypatch):
    companion = {**validate.COMPANIONS["microg"], "for_builds": ["no-such-build"]}
    monkeypatch.setitem(validate.COMPANIONS, "microg", companion)
    with pytest.raises(validate.ConfigError, match="no-such-build"):
        validate.validate_catalog()


def test_companion_without_variants_is_caught(monkeypatch):
    companion = {**validate.COMPANIONS["microg"], "variants": []}
    monkeypatch.setitem(validate.COMPANIONS, "microg", companion)
    with pytest.raises(validate.ConfigError, match="no variants"):
        validate.validate_catalog()
