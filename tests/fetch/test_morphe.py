import pytest
from tenacity import wait_none

from patchy.core.settings import settings
from patchy.fetch import morphe


def _data():
    return {
        "store": {
            "com.google.android.youtube": {"name": "YouTube", "category": "Video", "iconUrl": "https://x/yt.png"},
            "com.reddit.frontpage": {"name": "Reddit", "category": "Social"},
            "__universal__": {"name": "Universal"},
            "not a package": {"name": "Broken"},
            "com.example.odd": "not a mapping",
        },
        "compatibilities": [
            ["com.google.android.youtube"],
            [{"packageName": "com.reddit.frontpage"}, {"package": "com.example.extra"}],
            [],
            ["__universal__"],
        ],
        "bundles": [
            {
                "name": "Morphe",
                "repo": "MorpheApp/morphe-patches",
                "source": "github",
                "targetApps": ["com.google.android.youtube"],
                "patches": [
                    {"name": "Hide ads", "compatiblePackagesKey": 0},
                    {"name": "Layout", "compatiblePackagesKey": 0},
                    {"name": "Reddit ads", "compatibilityKey": 1},
                    {"name": "Everywhere", "compatiblePackagesKey": 2},
                    {"name": "Also everywhere", "compatiblePackagesKey": 3},
                    "not a patch",
                ],
            },
            {"name": "", "repo": "https://github.com/someone/extras.git", "patches": []},
        ],
    }


def test_the_store_becomes_the_app_list_without_the_universal_entry_or_broken_packages():
    catalog = morphe.parse_catalog(_data())

    assert catalog["apps"]["com.google.android.youtube"] == {
        "package": "com.google.android.youtube",
        "name": "YouTube",
        "category": "Video",
        "icon": "https://x/yt.png",
    }
    assert catalog["apps"]["com.reddit.frontpage"]["icon"] == ""
    assert "__universal__" not in catalog["apps"]
    assert "not a package" not in catalog["apps"]
    assert catalog["apps"]["com.example.odd"]["name"] == "com.example.odd"


def test_a_bundle_supports_its_target_apps_and_every_app_its_patches_name():
    catalog = morphe.parse_catalog(_data())
    bundle = catalog["bundles"][0]

    assert bundle["name"] == "Morphe"
    assert (bundle["source"], bundle["owner"], bundle["repo"]) == ("github", "MorpheApp", "morphe-patches")
    assert bundle["packages"] == ["com.google.android.youtube", "com.reddit.frontpage", "com.example.extra"]
    assert bundle["patch_count"] == 5
    assert bundle["targeted"] == {
        "com.google.android.youtube": 2,
        "com.reddit.frontpage": 1,
        "com.example.extra": 1,
    }


def test_patches_for_every_app_do_not_add_packages():
    catalog = morphe.parse_catalog(_data())

    assert "__universal__" not in catalog["bundles"][0]["packages"]
    assert len(catalog["bundles"][0]["packages"]) == 3


def test_a_package_only_a_bundle_mentions_still_becomes_an_app():
    catalog = morphe.parse_catalog(_data())

    assert catalog["apps"]["com.example.extra"] == {
        "package": "com.example.extra",
        "name": "com.example.extra",
        "category": "",
        "icon": "",
    }


def test_a_bundle_without_a_name_is_called_after_its_repository():
    bundle = morphe.parse_catalog(_data())["bundles"][1]

    assert bundle["name"] == "extras"
    assert (bundle["source"], bundle["owner"], bundle["repo"]) == ("github", "someone", "extras")
    assert bundle["packages"] == []
    assert bundle["patch_count"] == 0


@pytest.mark.parametrize(
    ("source", "repo", "expected"),
    [
        ("github", "owner/repo", ("github", "owner", "repo")),
        ("", "owner/repo", ("github", "owner", "repo")),
        ("GitHub", "Owner/Repo", ("github", "Owner", "Repo")),
        ("github", "https://github.com/owner/repo.git", ("github", "owner", "repo")),
        ("github", "https://www.github.com/owner/repo/tree/main", ("github", "owner", "repo")),
        ("", "github.com/owner/repo/", ("github", "owner", "repo")),
        ("gitlab", "owner/repo", ("gitlab", "owner", "repo")),
        ("github", "https://gitlab.com/owner/repo", ("gitlab", "owner", "repo")),
        ("", "https://codeberg.org/owner/repo", ("codeberg", "owner", "repo")),
        ("github", "just-a-name", None),
        ("github", "", None),
        ("github", "https://github.com/owner", None),
    ],
)
def test_a_repository_is_located_from_its_source_and_address(source, repo, expected):
    assert morphe._locate(source, repo) == expected


def test_a_bundle_without_a_usable_repository_is_skipped():
    data = {
        "bundles": [{"name": "Ghost", "repo": "nowhere"}, {"name": "Real", "repo": "a/b", "targetApps": ["a.b"]}]
    }

    catalog = morphe.parse_catalog(data)

    assert [bundle["name"] for bundle in catalog["bundles"]] == ["Real"]


def test_compatibilities_can_be_a_mapping_and_keys_can_be_numeric_text():
    data = {
        "compatibilities": {"yt": ["com.google.android.youtube"], "1": [{"name": "com.reddit.frontpage"}]},
        "bundles": [
            {
                "name": "B",
                "repo": "a/b",
                "patches": [
                    {"name": "one", "compatiblePackagesKey": "yt"},
                    {"name": "two", "compatiblePackagesKey": 1},
                    {"name": "three", "compatiblePackagesKey": "missing"},
                    {"name": "four", "compatiblePackages": ["com.inline.pkg"]},
                ],
            }
        ],
    }

    bundle = morphe.parse_catalog(data)["bundles"][0]

    assert bundle["packages"] == ["com.google.android.youtube", "com.reddit.frontpage", "com.inline.pkg"]
    assert bundle["patch_count"] == 4


def test_a_compatibility_key_that_points_nowhere_is_ignored():
    data = {
        "compatibilities": [["a.b"]],
        "bundles": [
            {
                "name": "B",
                "repo": "a/b",
                "patches": [
                    {"compatiblePackagesKey": 7},
                    {"compatiblePackagesKey": True},
                    {"compatiblePackagesKey": [0]},
                ],
            }
        ],
    }

    bundle = morphe.parse_catalog(data)["bundles"][0]

    assert bundle["packages"] == []
    assert bundle["patch_count"] == 3


@pytest.mark.parametrize(
    "data", [[], "text", None, 3, {}, {"store": {}, "bundles": []}, {"store": "x", "bundles": "y"}]
)
def test_a_catalog_that_does_not_look_like_one_is_rejected(data):
    with pytest.raises(morphe.MorpheCatalogError, match="format has probably changed"):
        morphe.parse_catalog(data)


def test_a_catalog_with_only_a_store_or_only_bundles_is_still_usable():
    assert list(morphe.parse_catalog({"store": {"a.b": {"name": "AB"}}})["apps"]) == ["a.b"]
    assert len(morphe.parse_catalog({"bundles": [{"repo": "a/b", "targetApps": ["c.d"]}]})["bundles"]) == 1


class _Response:
    def __init__(self, status_code=200, payload=None, error=None):
        self.status_code = status_code
        self._payload = payload
        self._error = error

    def json(self):
        if self._error is not None:
            raise self._error
        return self._payload


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        self.requests.append((url, headers))
        return self._responses.pop(0)


def _use(monkeypatch, responses):
    session = _Session(responses)
    monkeypatch.setattr(morphe, "new_session", lambda **kwargs: session)
    monkeypatch.setattr(morphe.retry_conf, "exponential_with_jitter", lambda **kwargs: wait_none())
    return session


async def test_the_catalog_is_downloaded_from_the_configured_address_and_parsed(monkeypatch):
    session = _use(monkeypatch, [_Response(200, _data())])

    catalog = await morphe.fetch_catalog()

    assert session.requests[0][0] == settings.catalog_url
    assert session.requests[0][1]["Accept"] == "application/json"
    assert "com.google.android.youtube" in catalog["apps"]


async def test_another_address_can_be_given(monkeypatch):
    session = _use(monkeypatch, [_Response(200, _data())])

    await morphe.fetch_catalog("https://example.test/catalog.json")

    assert [url for url, _ in session.requests] == ["https://example.test/catalog.json"]


async def test_a_failed_request_is_retried_until_it_works(monkeypatch):
    session = _use(monkeypatch, [_Response(503), _Response(502), _Response(200, _data())])

    catalog = await morphe.fetch_catalog()

    assert len(session.requests) == 3
    assert catalog["bundles"]


async def test_a_request_that_keeps_failing_gives_up_with_a_clear_error(monkeypatch):
    session = _use(monkeypatch, [_Response(503), _Response(503), _Response(503)])

    with pytest.raises(morphe.MorpheCatalogError, match="Could not load the Morphe catalog: HTTP 503"):
        await morphe.fetch_catalog()

    assert len(session.requests) == morphe.FETCH_ATTEMPTS


async def test_a_response_that_is_not_json_is_an_error(monkeypatch):
    _use(monkeypatch, [_Response(200, error=ValueError("Expecting value")) for _ in range(3)])

    with pytest.raises(morphe.MorpheCatalogError, match="Expecting value"):
        await morphe.fetch_catalog()


async def test_a_json_answer_in_the_wrong_shape_is_an_error(monkeypatch):
    _use(monkeypatch, [_Response(200, ["not", "a", "catalog"])])

    with pytest.raises(morphe.MorpheCatalogError, match="format has probably changed"):
        await morphe.fetch_catalog()
