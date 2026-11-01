import re
from typing import TypedDict
from urllib.parse import urlparse

from tenacity import retry, stop_after_attempt

from ..core import retry as retry_conf
from ..core.http import new_session
from ..core.settings import settings

GITHUB = "github"
KNOWN_HOSTS = ("github.com/", "gitlab.com/")
PACKAGE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
PACKAGE_KEYS = ("packageName", "package", "name")
FETCH_ATTEMPTS = 3


class MorpheCatalogError(Exception):
    pass


class CatalogApp(TypedDict):
    package: str
    name: str
    category: str
    icon: str


class CatalogBundle(TypedDict):
    name: str
    source: str
    owner: str
    repo: str
    packages: list[str]
    patch_count: int
    targeted: dict[str, int]


class Catalog(TypedDict):
    apps: dict[str, CatalogApp]
    bundles: list[CatalogBundle]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_package(value: str) -> bool:
    return PACKAGE_ID.match(value) is not None


def _locate(source: str, repo: str) -> tuple[str, str, str] | None:
    text = repo.strip()
    host = source.strip().lower() or GITHUB
    if "://" in text:
        parsed = urlparse(text)
        host = parsed.netloc.lower().removeprefix("www.").split(".")[0] or host
        text = parsed.path
    else:
        for known in KNOWN_HOSTS:
            if text.lower().startswith(known):
                host = known.split(".")[0]
                text = text[len(known) :]
    parts = [part for part in text.rstrip("/").removesuffix(".git").split("/") if part]
    if len(parts) < 2:
        return None
    return host, parts[0], parts[1]


def _entry_package(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in PACKAGE_KEYS:
            value = entry.get(key)
            if isinstance(value, str):
                return value
    return None


def _packages(entries: object) -> list[str]:
    if isinstance(entries, dict):
        candidates: list[str | None] = [key if isinstance(key, str) else None for key in entries]
    elif isinstance(entries, list):
        candidates = [_entry_package(entry) for entry in entries]
    else:
        return []
    found: list[str] = []
    for candidate in candidates:
        if candidate is not None and _is_package(candidate) and candidate not in found:
            found.append(candidate)
    return found


def _lookup(compatibilities: object, key: object) -> object:
    if isinstance(key, bool) or not isinstance(key, str | int):
        return None
    index = int(key) if isinstance(key, str) and key.isdigit() else key
    if isinstance(compatibilities, dict):
        return compatibilities.get(key, compatibilities.get(str(key)))
    if isinstance(compatibilities, list) and isinstance(index, int):
        return compatibilities[index] if 0 <= index < len(compatibilities) else None
    return None


def _patch_packages(patch: dict, compatibilities: object) -> list[str]:
    key = patch.get("compatiblePackagesKey", patch.get("compatibilityKey"))
    entries = _lookup(compatibilities, key) if key is not None else None
    if entries is None:
        entries = patch.get("compatiblePackages")
    return _packages(entries)


def _parse_bundle(item: object, compatibilities: object) -> CatalogBundle | None:
    if not isinstance(item, dict):
        return None
    location = _locate(_text(item.get("source")), _text(item.get("repo")))
    if location is None:
        return None
    source, owner, repo = location
    raw_patches = item.get("patches")
    patches = [patch for patch in raw_patches if isinstance(patch, dict)] if isinstance(raw_patches, list) else []
    packages = _packages(item.get("targetApps"))
    targeted: dict[str, int] = {}
    for patch in patches:
        for package in _patch_packages(patch, compatibilities):
            targeted[package] = targeted.get(package, 0) + 1
            if package not in packages:
                packages.append(package)
    return {
        "name": _text(item.get("name")) or repo,
        "source": source,
        "owner": owner,
        "repo": repo,
        "packages": packages,
        "patch_count": len(patches),
        "targeted": targeted,
    }


def _parse_apps(store: object) -> dict[str, CatalogApp]:
    apps: dict[str, CatalogApp] = {}
    if not isinstance(store, dict):
        return apps
    for package, info in store.items():
        if not isinstance(package, str) or not _is_package(package):
            continue
        data = info if isinstance(info, dict) else {}
        apps[package] = {
            "package": package,
            "name": _text(data.get("name")) or package,
            "category": _text(data.get("category")),
            "icon": _text(data.get("iconUrl")),
        }
    return apps


def parse_catalog(data: object) -> Catalog:
    if not isinstance(data, dict):
        raise MorpheCatalogError("The Morphe catalog is not a JSON object, so its format has probably changed.")
    apps = _parse_apps(data.get("store"))
    raw_bundles = data.get("bundles")
    compatibilities = data.get("compatibilities")
    bundles: list[CatalogBundle] = []
    for item in raw_bundles if isinstance(raw_bundles, list) else []:
        bundle = _parse_bundle(item, compatibilities)
        if bundle is not None:
            bundles.append(bundle)
    if not apps and not bundles:
        raise MorpheCatalogError(
            "The Morphe catalog lists no apps and no bundles, so its format has probably changed."
        )
    for bundle in bundles:
        for package in bundle["packages"]:
            apps.setdefault(package, {"package": package, "name": package, "category": "", "icon": ""})
    return {"apps": apps, "bundles": bundles}


async def fetch_catalog(url: str | None = None) -> Catalog:
    target = url or settings.catalog_url

    @retry(
        stop=stop_after_attempt(FETCH_ATTEMPTS),
        wait=retry_conf.exponential_with_jitter(max=15.0),
        before_sleep=retry_conf.before_sleep("Morphe catalog request"),
        reraise=True,
    )
    async def _do() -> object:
        async with new_session(timeout=30) as client:
            res = await client.get(target, headers={"User-Agent": "python", "Accept": "application/json"})
            if res.status_code >= 400:
                raise RuntimeError(f"HTTP {res.status_code} from {target}")
            return res.json()

    try:
        data = await _do()
    except Exception as e:
        raise MorpheCatalogError(f"Could not load the Morphe catalog: {e}") from e
    return parse_catalog(data)
