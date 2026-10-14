import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from patchy.publish import release


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Router:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def session(self, **kwargs):
        return _Session(self)


class _Session:
    def __init__(self, router):
        self.router = router

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def _call(self, method, url, **kwargs):
        self.router.calls.append((method, url, kwargs))
        return self.router.handler(method, url, **kwargs)

    async def get(self, url, **kwargs):
        return await self._call("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        if "content" in kwargs:
            kwargs["content"] = b"".join(kwargs["content"])
        return await self._call("POST", url, **kwargs)

    async def patch(self, url, **kwargs):
        return await self._call("PATCH", url, **kwargs)

    async def delete(self, url, **kwargs):
        return await self._call("DELETE", url, **kwargs)


def _configure(monkeypatch, handler):
    monkeypatch.setattr(release.settings, "github_token", SecretStr("token"))
    monkeypatch.setattr(release.settings, "github_repository", "owner/repo")
    router = _Router(handler)
    monkeypatch.setattr(release, "new_session", router.session)
    monkeypatch.setattr(release.log, "warn", lambda msg: None)
    monkeypatch.setattr(release.log, "info", lambda msg: None)
    monkeypatch.setattr(release.log, "step", lambda msg: None)
    monkeypatch.setattr(release.log, "download", lambda msg: None)
    return router


def test_missing_credentials_are_reported_clearly(monkeypatch):
    monkeypatch.setattr(release.settings, "github_token", SecretStr(""))
    monkeypatch.setattr(release.settings, "github_repository", "owner/repo")
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        release._assert_configured()

    monkeypatch.setattr(release.settings, "github_token", SecretStr("token"))
    monkeypatch.setattr(release.settings, "github_repository", "")
    with pytest.raises(RuntimeError, match="GITHUB_REPOSITORY"):
        release._assert_configured()


def test_asset_names_replace_spaces_with_dots_like_github_does():
    assert release._asset_name("dir/Reddit Adobo-1.0.apk") == "Reddit.Adobo-1.0.apk"
    assert release._names_match("Reddit Adobo-1.0.apk", "Reddit.Adobo-1.0.apk")
    assert not release._names_match("A.apk", "B.apk")


async def test_list_releases_follows_pagination(monkeypatch):
    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": 100}, {"id": 101}]}

    def handler(method, url, **kwargs):
        return _Response(200, pages[kwargs["params"]["page"]])

    router = _configure(monkeypatch, handler)

    releases = await release.list_releases()

    assert [r["id"] for r in releases] == list(range(102))
    assert [c[2]["params"]["page"] for c in router.calls] == [1, 2]


async def test_list_releases_stops_after_a_short_first_page(monkeypatch):
    router = _configure(monkeypatch, lambda m, u, **k: _Response(200, [{"id": 1}]))
    assert await release.list_releases() == [{"id": 1}]
    assert len(router.calls) == 1


async def test_list_releases_raises_on_an_api_error_instead_of_returning_a_partial_list(monkeypatch):
    _configure(monkeypatch, lambda m, u, **k: _Response(403, {"message": "API rate limit exceeded"}))
    with pytest.raises(RuntimeError, match="rate limit"):
        await release.list_releases()


@pytest.mark.parametrize("status", [204, 404])
async def test_delete_release_accepts_success_and_already_gone(monkeypatch, status):
    _configure(monkeypatch, lambda m, u, **k: _Response(status))
    await release.delete_release(7)


async def test_delete_release_raises_on_other_statuses(monkeypatch):
    _configure(monkeypatch, lambda m, u, **k: _Response(403, {"message": "Resource not accessible"}))
    with pytest.raises(RuntimeError, match="status=403"):
        await release.delete_release(7)


@pytest.mark.parametrize("status", [204, 404, 422])
async def test_delete_tag_accepts_success_and_missing_refs(monkeypatch, status):
    _configure(monkeypatch, lambda m, u, **k: _Response(status))
    await release.delete_tag("build-2026-01-01T00-00-00")


async def test_delete_tag_raises_on_other_statuses(monkeypatch):
    _configure(monkeypatch, lambda m, u, **k: _Response(500, text="boom"))
    with pytest.raises(RuntimeError, match="status=500"):
        await release.delete_tag("build-2026-01-01T00-00-00")


def _listing_handler(releases, failing_ids=()):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(200, releases)
        if method == "DELETE" and "/releases/" in url:
            release_id = int(url.rsplit("/", 1)[1])
            return _Response(500 if release_id in failing_ids else 204)
        return _Response(204)

    return handler


async def test_delete_other_releases_only_touches_patchy_builds(monkeypatch):
    releases = [
        {"id": 1, "tag_name": "build-2026-10-04T10-00-00"},
        {"id": 2, "tag_name": "build-2026-10-03T10-00-00"},
        {"id": 3, "tag_name": "v1.0.0-hand-made"},
        {"id": 4, "tag_name": ""},
    ]
    router = _configure(monkeypatch, _listing_handler(releases))

    await release.delete_other_releases(keep_release_id=1)

    deletes = [(c[0], c[1].split("/repos/owner/repo")[1]) for c in router.calls if c[0] == "DELETE"]
    assert deletes == [
        ("DELETE", "/releases/2"),
        ("DELETE", "/git/refs/tags/build-2026-10-03T10-00-00"),
    ]


async def test_delete_other_releases_keeps_going_after_one_failure_and_reports_it(monkeypatch):
    releases = [
        {"id": 1, "tag_name": "build-2026-10-04T10-00-00"},
        {"id": 2, "tag_name": "build-2026-10-03T10-00-00"},
        {"id": 3, "tag_name": "build-2026-10-02T10-00-00"},
    ]
    router = _configure(monkeypatch, _listing_handler(releases, failing_ids={2}))

    with pytest.raises(RuntimeError, match="Failed to delete release 2"):
        await release.delete_other_releases(keep_release_id=1)

    deleted_tags = [c[1].rsplit("/", 1)[1] for c in router.calls if "/git/refs/tags/" in c[1]]
    assert deleted_tags == ["build-2026-10-02T10-00-00"]


async def test_create_new_release_posts_a_new_release_when_the_tag_is_free(monkeypatch):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(404, {"message": "Not Found"})
        return _Response(201, {"id": 11, "upload_url": "https://uploads/x{?name,label}", "tag_name": "t"})

    router = _configure(monkeypatch, handler)

    created = await release.create_new_release("t", "Name", "Body")

    assert created["id"] == 11
    method, url, kwargs = router.calls[-1]
    assert method == "POST" and url.endswith("/repos/owner/repo/releases")
    assert kwargs["json"] == {
        "tag_name": "t",
        "name": "Name",
        "body": "Body",
        "draft": False,
        "prerelease": False,
        "make_latest": "true",
    }


async def test_create_new_release_reuses_a_release_that_already_has_the_tag(monkeypatch):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(200, {"id": 5, "tag_name": "t"})
        return _Response(200, {"id": 5, "tag_name": "t", "upload_url": "u"})

    router = _configure(monkeypatch, handler)

    created = await release.create_new_release("t", "Name", "Body")

    assert created["id"] == 5
    assert router.calls[-1][0] == "PATCH"


async def test_create_new_release_raises_with_the_api_message_on_failure(monkeypatch):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(404, {"message": "Not Found"})
        return _Response(422, {"message": "Validation Failed"})

    _configure(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="Validation Failed"):
        await release.create_new_release("t", "Name")


def _body_too_long():
    return {
        "message": "Validation Failed",
        "errors": [
            {
                "resource": "Release",
                "code": "custom",
                "field": "body",
                "message": "body is too long (maximum is 125000 characters)",
            }
        ],
        "documentation_url": "https://docs.github.com/rest/releases/releases#create-a-release",
        "status": "422",
    }


async def test_create_new_release_flags_a_description_that_github_refuses(monkeypatch):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(404, {"message": "Not Found"})
        return _Response(422, _body_too_long())

    _configure(monkeypatch, handler)

    with pytest.raises(release.ReleaseBodyRejected, match="body is too long"):
        await release.create_new_release("t", "Name", "Body")


async def test_a_refused_description_is_flagged_when_an_existing_release_is_updated_too(monkeypatch):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(200, {"id": 5, "tag_name": "t"})
        return _Response(422, _body_too_long())

    _configure(monkeypatch, handler)

    with pytest.raises(release.ReleaseBodyRejected, match="update existing release"):
        await release.create_new_release("t", "Name", "Body")


async def test_other_validation_errors_are_not_mistaken_for_a_refused_description(monkeypatch):
    def handler(method, url, **kwargs):
        if method == "GET":
            return _Response(404, {"message": "Not Found"})
        errors = [{"resource": "Release", "code": "already_exists", "field": "tag_name"}]
        return _Response(422, {"message": "Validation Failed", "errors": errors})

    _configure(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="Validation Failed") as caught:
        await release.create_new_release("t", "Name", "Body")

    assert not isinstance(caught.value, release.ReleaseBodyRejected)


@pytest.mark.parametrize(
    "data",
    [None, "body", [], {}, {"errors": "body"}, {"errors": [None, "body"]}, {"errors": [{"field": "tag_name"}]}],
)
def test_only_a_validation_error_on_the_body_field_counts_as_a_refused_description(data):
    assert release._body_rejected(data) is False


def test_a_validation_error_on_the_body_field_counts_as_a_refused_description():
    assert release._body_rejected(_body_too_long()) is True


async def test_get_assets_paginates(monkeypatch):
    pages = {1: [{"id": i, "name": f"a{i}"} for i in range(100)], 2: [{"id": 100, "name": "a100"}]}
    _configure(monkeypatch, lambda m, u, **k: _Response(200, pages[k["params"]["page"]]))

    assets = await release.get_assets(9)

    assert len(assets) == 101


async def test_delete_asset_raises_on_unexpected_status(monkeypatch):
    _configure(monkeypatch, lambda m, u, **k: _Response(500))
    with pytest.raises(RuntimeError, match="status=500"):
        await release.delete_asset(3)


def _apk(tmp_path, name="YouTube-1.0.apk", content=b"signed apk bytes"):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


async def test_upload_sends_the_file_and_checks_the_reported_size(monkeypatch, tmp_path):
    path = _apk(tmp_path)

    def handler(method, url, **kwargs):
        return _Response(201, {"id": 1, "size": len(b"signed apk bytes")})

    router = _configure(monkeypatch, handler)

    result = await release._upload("https://uploads/x{?name,label}", path, "YouTube-1.0.apk")

    assert result["id"] == 1
    method, url, kwargs = router.calls[0]
    assert url == "https://uploads/x?name=YouTube-1.0.apk"
    assert kwargs["content"] == b"signed apk bytes"
    assert kwargs["headers"]["Content-Type"] == "application/vnd.android.package-archive"
    assert kwargs["headers"]["Content-Length"] == str(len(b"signed apk bytes"))


async def test_upload_reports_the_status_when_github_answers_with_a_non_json_error(monkeypatch, tmp_path):
    path = _apk(tmp_path)
    _configure(monkeypatch, lambda m, u, **k: _Response(502, None, text="<html>Bad Gateway</html>"))

    with pytest.raises(RuntimeError, match=r"status=502.*Bad Gateway"):
        await release._upload("https://uploads/x{?name,label}", path, "YouTube-1.0.apk")


async def test_upload_detects_a_size_mismatch(monkeypatch, tmp_path):
    path = _apk(tmp_path)
    _configure(monkeypatch, lambda m, u, **k: _Response(201, {"id": 1, "size": 3}))

    with pytest.raises(RuntimeError, match="size mismatch"):
        await release._upload("https://uploads/x{?name,label}", path, "YouTube-1.0.apk")


async def test_upload_with_replace_removes_an_existing_asset_with_the_same_name_first(monkeypatch, tmp_path):
    path = _apk(tmp_path, "Reddit Adobo-1.0.apk")
    events = []

    async def fake_get_assets(release_id):
        return [{"id": 77, "name": "Reddit.Adobo-1.0.apk"}, {"id": 78, "name": "other.apk"}]

    async def fake_delete_asset(asset_id):
        events.append(("delete", asset_id))

    async def fake_upload(upload_url, file_path, asset_name):
        events.append(("upload", asset_name))
        return {"id": 99, "size": len(b"signed apk bytes")}

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(release, "get_assets", fake_get_assets)
    monkeypatch.setattr(release, "delete_asset", fake_delete_asset)
    monkeypatch.setattr(release, "_upload", fake_upload)
    monkeypatch.setattr(release, "asyncio", SimpleNamespace(sleep=no_sleep))
    monkeypatch.setattr(release.log, "warn", lambda msg: None)
    monkeypatch.setattr(release.log, "download", lambda msg: None)
    monkeypatch.setattr(release.log, "info", lambda msg: None)

    result = await release.upload_with_replace({"id": 5, "upload_url": "u"}, path)

    assert result["id"] == 99
    assert events == [("delete", 77), ("upload", "Reddit.Adobo-1.0.apk")]


async def test_upload_with_replace_retries_when_github_says_the_asset_already_exists(monkeypatch, tmp_path):
    path = _apk(tmp_path)
    attempts = []

    async def fake_get_assets(release_id):
        return []

    async def fake_upload(upload_url, file_path, asset_name):
        attempts.append(asset_name)
        if len(attempts) < 3:
            raise RuntimeError('Upload failed: {"errors":[{"code":"already_exists"}]}')
        return {"id": 1, "size": len(b"signed apk bytes")}

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(release, "get_assets", fake_get_assets)
    monkeypatch.setattr(release, "_upload", fake_upload)
    monkeypatch.setattr(release, "asyncio", SimpleNamespace(sleep=no_sleep))
    monkeypatch.setattr(release.log, "warn", lambda msg: None)
    monkeypatch.setattr(release.log, "download", lambda msg: None)
    monkeypatch.setattr(release.log, "info", lambda msg: None)

    result = await release.upload_with_replace({"id": 5, "upload_url": "u"}, path)

    assert result["id"] == 1
    assert len(attempts) == 3


async def test_upload_with_replace_does_not_retry_other_errors(monkeypatch, tmp_path):
    path = _apk(tmp_path)

    async def fake_get_assets(release_id):
        return []

    async def fake_upload(upload_url, file_path, asset_name):
        raise RuntimeError("Upload failed: status=500")

    monkeypatch.setattr(release, "get_assets", fake_get_assets)
    monkeypatch.setattr(release, "_upload", fake_upload)
    monkeypatch.setattr(release.log, "download", lambda msg: None)

    with pytest.raises(RuntimeError, match="status=500"):
        await release.upload_with_replace({"id": 5, "upload_url": "u"}, path)


async def test_upload_with_replace_reports_how_long_the_upload_took(monkeypatch, tmp_path):
    path = _apk(tmp_path, content=b"x" * 2048)
    messages = []

    async def fake_get_assets(release_id):
        return []

    async def fake_upload(upload_url, file_path, asset_name):
        return {"id": 1, "size": 2048}

    monkeypatch.setattr(release, "get_assets", fake_get_assets)
    monkeypatch.setattr(release, "_upload", fake_upload)
    monkeypatch.setattr(release.log, "download", lambda msg: None)
    monkeypatch.setattr(release.log, "info", messages.append)

    await release.upload_with_replace({"id": 5, "upload_url": "u"}, path)

    assert len(messages) == 1
    assert "Uploaded YouTube-1.0.apk" in messages[0]
    assert "MB/s" in messages[0]


def _configure_uploads(monkeypatch, concurrency):
    monkeypatch.setattr(release.settings, "github_token", SecretStr("token"))
    monkeypatch.setattr(release.settings, "github_repository", "owner/repo")
    monkeypatch.setattr(release.settings, "upload_concurrency", concurrency)
    monkeypatch.setattr(release.log, "step", lambda msg: None)
    monkeypatch.setattr(release.log, "info", lambda msg: None)


def _apks(tmp_path, sizes):
    paths = []
    for name, size in sizes.items():
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        paths.append(str(path))
    return paths


async def test_upload_assets_uploads_every_file(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 3)
    uploaded = []

    async def fake_upload(rel, path):
        uploaded.append(path)

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    paths = _apks(tmp_path, {"a.apk": 1, "b.apk": 2, "c.apk": 3})

    await release.upload_assets({"id": 1}, paths, [])

    assert sorted(uploaded) == sorted(paths)


async def test_upload_assets_sends_the_largest_files_first(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 1)
    uploaded = []

    async def fake_upload(rel, path):
        uploaded.append(Path(path).name)

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    paths = _apks(tmp_path, {"small.apk": 10, "huge.apk": 4000, "medium.apk": 300, "large.apk": 900})

    await release.upload_assets({"id": 1}, paths, [])

    assert uploaded == ["huge.apk", "large.apk", "medium.apk", "small.apk"]


async def test_upload_assets_never_runs_more_uploads_than_configured(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 3)
    state = {"active": 0, "peak": 0}

    async def fake_upload(rel, path):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        for _ in range(4):
            await asyncio.sleep(0)
        state["active"] -= 1

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    paths = _apks(tmp_path, {f"app{i}.apk": i + 1 for i in range(9)})

    await release.upload_assets({"id": 1}, paths, [])

    assert state["peak"] == 3


async def test_upload_assets_shares_the_same_limit_with_companions(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 2)
    state = {"active": 0, "peak": 0}

    async def occupy():
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        for _ in range(4):
            await asyncio.sleep(0)
        state["active"] -= 1

    async def fake_upload(rel, path):
        await occupy()

    async def fake_variant(rel, companion, variant):
        await occupy()

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    monkeypatch.setattr(release, "_upload_companion_variant", fake_variant)
    paths = _apks(tmp_path, {f"app{i}.apk": i + 1 for i in range(5)})
    companion = _companion([{"file": "MicroG.apk", "suffix": "a"}, {"file": "MicroG-NoIcon.apk", "suffix": "b"}])

    await release.upload_assets({"id": 1}, paths, [companion])

    assert state["peak"] == 2


async def test_upload_assets_starts_the_companions_before_the_apks(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 1)
    order = []

    async def fake_upload(rel, path):
        order.append(Path(path).name)

    async def fake_variant(rel, companion, variant):
        order.append(variant["file"])

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    monkeypatch.setattr(release, "_upload_companion_variant", fake_variant)
    paths = _apks(tmp_path, {"big.apk": 500, "small.apk": 5})
    companion = _companion([{"file": "MicroG.apk", "suffix": "a"}, {"file": "MicroG-NoIcon.apk", "suffix": "b"}])

    await release.upload_assets({"id": 1}, paths, [companion])

    assert order == ["MicroG.apk", "MicroG-NoIcon.apk", "big.apk", "small.apk"]


async def test_upload_assets_lets_a_failed_upload_fail_the_run(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 2)

    async def fake_upload(rel, path):
        if Path(path).name == "bad.apk":
            raise RuntimeError("Upload failed for bad.apk (status=500)")

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    paths = _apks(tmp_path, {"good.apk": 5, "bad.apk": 3})

    with pytest.raises(RuntimeError, match="bad.apk"):
        await release.upload_assets({"id": 1}, paths, [])


async def test_upload_assets_reports_the_overall_speed(monkeypatch, tmp_path):
    _configure_uploads(monkeypatch, 2)
    messages = []
    monkeypatch.setattr(release.log, "info", messages.append)

    async def fake_upload(rel, path):
        return {}

    monkeypatch.setattr(release, "upload_with_replace", fake_upload)

    await release.upload_assets({"id": 1}, _apks(tmp_path, {"a.apk": 5}), [])

    assert any("Uploads finished" in m and "MB/s" in m for m in messages)


def _companion(variants=None):
    return {
        "key": "microg",
        "owner": "MorpheApp",
        "repo": "MicroG-RE",
        "for_builds": ["youtube"],
        "variants": variants or [{"file": "MicroG.apk", "suffix": "-arm64-v8a.apk", "exclude": "noicon"}],
    }


async def test_companion_is_uploaded_under_its_stable_name(monkeypatch, tmp_path):
    source = tmp_path / "microg-v1-arm64-v8a.apk"
    source.write_bytes(b"microg")
    uploaded = []

    async def fake_fetch(companion, variant, dest_dir=None):
        return {"name": source.name, "path": str(source), "body": "", "tag": "v1", "prerelease": False}

    async def fake_assets(release_id):
        return []

    async def fake_upload(rel, path):
        uploaded.append(path)

    monkeypatch.setattr(release, "fetch_companion", fake_fetch)
    monkeypatch.setattr(release, "get_assets", fake_assets)
    monkeypatch.setattr(release, "upload_with_replace", fake_upload)

    companion = _companion()
    await release._upload_companion_variant({"id": 1}, companion, companion["variants"][0])

    assert uploaded == [str(tmp_path / "MicroG.apk")]


async def test_prerelease_companions_get_a_prerelease_suffix(monkeypatch, tmp_path):
    source = tmp_path / "microg-v1-arm64-v8a.apk"
    source.write_bytes(b"microg")
    uploaded = []

    async def fake_fetch(companion, variant, dest_dir=None):
        return {"name": source.name, "path": str(source), "body": "", "tag": "v1", "prerelease": True}

    async def fake_assets(release_id):
        return []

    async def fake_upload(rel, path):
        uploaded.append(path)

    monkeypatch.setattr(release, "fetch_companion", fake_fetch)
    monkeypatch.setattr(release, "get_assets", fake_assets)
    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    monkeypatch.setattr(release.log, "warn", lambda msg: None)

    companion = _companion()
    await release._upload_companion_variant({"id": 1}, companion, companion["variants"][0])

    assert uploaded == [str(tmp_path / "MicroG-PRERELEASE.apk")]


async def test_companion_already_on_the_release_is_not_uploaded_again(monkeypatch, tmp_path):
    source = tmp_path / "microg-v1-arm64-v8a.apk"
    source.write_bytes(b"microg")

    async def fake_fetch(companion, variant, dest_dir=None):
        return {"name": source.name, "path": str(source), "body": "", "tag": "v1", "prerelease": False}

    async def fake_assets(release_id):
        return [{"id": 3, "name": "MicroG.apk"}]

    async def fake_upload(rel, path):
        raise AssertionError("must not upload twice")

    monkeypatch.setattr(release, "fetch_companion", fake_fetch)
    monkeypatch.setattr(release, "get_assets", fake_assets)
    monkeypatch.setattr(release, "upload_with_replace", fake_upload)
    monkeypatch.setattr(release.log, "info", lambda msg: None)

    companion = _companion()
    await release._upload_companion_variant({"id": 1}, companion, companion["variants"][0])


async def test_upload_assets_handles_every_companion_variant(monkeypatch):
    _configure_uploads(monkeypatch, 4)
    seen = []

    async def fake_variant(rel, companion, variant):
        seen.append(variant["file"])

    monkeypatch.setattr(release, "_upload_companion_variant", fake_variant)

    companion = _companion([{"file": "MicroG.apk", "suffix": "a"}, {"file": "MicroG-NoIcon.apk", "suffix": "b"}])
    await release.upload_assets({"id": 1}, [], [companion])

    assert sorted(seen) == ["MicroG-NoIcon.apk", "MicroG.apk"]


async def test_upload_assets_with_nothing_to_do_is_a_noop(monkeypatch):
    _configure_uploads(monkeypatch, 4)

    async def boom(rel, path):
        raise AssertionError("nothing to upload")

    monkeypatch.setattr(release, "upload_with_replace", boom)

    await release.upload_assets({"id": 1}, [], [])


async def test_upload_assets_requires_credentials(monkeypatch):
    monkeypatch.setattr(release.settings, "github_token", SecretStr(""))
    monkeypatch.setattr(release.settings, "github_repository", "owner/repo")

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        await release.upload_assets({"id": 1}, [], [])
