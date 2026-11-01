import json
import re
from collections.abc import Iterable, Mapping, Sequence

from ..fetch.morphe import GITHUB, Catalog, CatalogApp, CatalogBundle
from . import BUILDS, BUNDLES
from .models import BuildConfig, BundleSource

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
CELL_LIMIT = 70
ALTERNATIVES_SHOWN = 4
BUILD_KEYS_SHOWN = 3
SUGGESTIONS_SHOWN = 5
FILL_IN = "FILL-IN"
DEFAULT_ARCH = "arm64-v8a"
EMPTY = "–"
MARKDOWN_SPECIALS = re.compile(r"([\\`*_\[\]|<>&~])")
SAFE_PART = re.compile(r"^[A-Za-z0-9._-]+$")
FORGES = {"github": ("GitHub", "https://github.com/"), "gitlab": ("GitLab", "https://gitlab.com/")}


def _text(value: str, limit: int = CELL_LIMIT) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1].rstrip() + "…"
    return MARKDOWN_SPECIALS.sub(r"\\\1", collapsed)


def _code(value: str) -> str:
    return "`" + " ".join(value.replace("`", "'").split()) + "`"


def _codes(values: Iterable[str], shown: int | None = None) -> str:
    items = list(dict.fromkeys(values))
    visible = items if shown is None else items[:shown]
    text = ", ".join(_code(item) for item in visible)
    hidden = len(items) - len(visible)
    return f"{text} (+{hidden} more)" if hidden > 0 else text


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _yaml(value: str) -> str:
    return json.dumps(" ".join(value.replace("`", "").split()), ensure_ascii=False)


def _fenced(lines: Iterable[str]) -> list[str]:
    return ["```yaml", *lines, "```"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _title(package: str) -> str:
    last = package.rsplit(".", 1)[-1]
    return re.sub(r"[_-]+", " ", last).strip().title() or package


def _free_key(candidates: Sequence[str], taken: set[str]) -> str:
    for candidate in candidates:
        if candidate and candidate not in taken:
            return candidate
    base = next((candidate for candidate in reversed(candidates) if candidate), "item")
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


def _repo_id(owner: str, repo: str) -> str:
    return f"{owner}/{repo}".lower()


def _bundle_id(bundle: CatalogBundle) -> str:
    return _repo_id(bundle["owner"], bundle["repo"])


def _usable(bundle: CatalogBundle) -> bool:
    return bundle["source"] == GITHUB


def _forge_name(bundle: CatalogBundle) -> str:
    known = FORGES.get(bundle["source"])
    return known[0] if known else bundle["source"].capitalize() or "Unknown"


def _repo_cell(bundle: CatalogBundle) -> str:
    slug = f"{bundle['owner']}/{bundle['repo']}"
    forge = FORGES.get(bundle["source"])
    if forge is not None and SAFE_PART.match(bundle["owner"]) and SAFE_PART.match(bundle["repo"]):
        return f"[{_text(slug)}]({forge[1]}{slug})"
    return _text(slug)


def _configured(bundles: Mapping[str, BundleSource]) -> dict[str, str]:
    return {_repo_id(source["owner"], source["repo"]): key for key, source in bundles.items()}


def _supporters(morphe: Catalog) -> dict[str, list[CatalogBundle]]:
    found: dict[str, list[CatalogBundle]] = {}
    for bundle in morphe["bundles"]:
        for package in bundle["packages"]:
            found.setdefault(package, []).append(bundle)
    return found


def _usable_count(supporters: Mapping[str, list[CatalogBundle]], package: str) -> int:
    return sum(1 for bundle in supporters.get(package, []) if _usable(bundle))


def _builds_by_package(builds: Mapping[str, BuildConfig]) -> dict[str, list[BuildConfig]]:
    grouped: dict[str, list[BuildConfig]] = {}
    for build in builds.values():
        grouped.setdefault(build["pkg"], []).append(build)
    return grouped


def _patchy_cell(package_builds: Sequence[BuildConfig] | None) -> str:
    if not package_builds:
        return EMPTY
    return "✅ " + _codes((build["key"] for build in package_builds), BUILD_KEYS_SHOWN)


def _patches_cell(bundle: CatalogBundle, package: str) -> str:
    total = bundle["patch_count"]
    if total == 0:
        return EMPTY
    mine = bundle["targeted"].get(package, 0)
    return f"{mine} for this app, {total} in total" if mine else f"{total} in total"


def _status_cell(bundle: CatalogBundle, configured: Mapping[str, str], used: set[str]) -> str:
    if not _usable(bundle):
        return f"⛔ {_forge_name(bundle)} bundles are not supported"
    key = configured.get(_bundle_id(bundle))
    if key is None:
        return "➕ not configured"
    return f"✅ {_code(key)}" + (" · used for this app" if key in used else "")


def _resolve(morphe: Catalog, wanted: str) -> str | None:
    lowered = wanted.strip().lower()
    return next((package for package in morphe["apps"] if package.lower() == lowered), None)


def _close_matches(morphe: Catalog, wanted: str) -> list[str]:
    lowered = wanted.strip().lower()
    close = (package for package in morphe["apps"] if lowered in package.lower() or package.lower() in lowered)
    return sorted(close)[:SUGGESTIONS_SHOWN]


def _app_line(app: CatalogApp, bundle_count: int) -> str:
    parts = []
    if app["name"] != app["package"]:
        parts.append(f"**{_text(app['name'])}**")
    if app["category"]:
        parts.append(_text(app["category"]))
    parts.append(f"{bundle_count} bundle(s) patch it")
    return " · ".join(parts)


def _bundle_snippet(bundle: CatalogBundle, key: str) -> list[str]:
    return [
        f"  {_yaml(key)}:",
        f"    owner: {_yaml(bundle['owner'])}",
        f"    repo: {_yaml(bundle['repo'])}",
        f"    label: {_yaml(bundle['name'])}",
    ]


def _new_bundle_keys(missing: Sequence[CatalogBundle], taken: set[str]) -> dict[str, str]:
    keys: dict[str, str] = {}
    used = set(taken)
    for bundle in missing:
        owner, repo = _slug(bundle["owner"]), _slug(bundle["repo"])
        key = _free_key([owner, repo, f"{owner}-{repo}"], used)
        used.add(key)
        keys[_bundle_id(bundle)] = key
    return keys


def _app_section(
    app: CatalogApp,
    supporting: Sequence[CatalogBundle],
    configured: Mapping[str, str],
    new_keys: Mapping[str, str],
    builds: Mapping[str, BuildConfig],
) -> list[str]:
    usable = [bundle for bundle in supporting if _usable(bundle)]
    lines = ["", "### Add the app", ""]
    if not usable:
        lines.append("Every bundle that patches it is hosted outside GitHub, which Patchy cannot download from.")
        return lines
    chosen = next((bundle for bundle in usable if _bundle_id(bundle) in configured), usable[0])
    bundle_key = configured.get(_bundle_id(chosen)) or new_keys[_bundle_id(chosen)]
    package = app["package"]
    taken = set(builds) | {build["app_slug"] for build in builds.values()}
    slug = _free_key([_slug(app["name"]), _slug(package.rsplit(".", 1)[-1]), _slug(package)], taken)
    display_name = app["name"] if app["name"] != package else _title(package)
    snippet = [
        f"pkg: {_yaml(package)}",
        f"display_name: {_yaml(display_name)}",
        f"arch: {_yaml(DEFAULT_ARCH)}",
        f"icon: {_yaml(app['icon'] or FILL_IN)}",
        "apk_source:",
        "  type: apkmirror",
        f"  org: {_yaml(FILL_IN)}",
        f"  slug: {_yaml(FILL_IN)}",
        "builds:",
        f"  - key: {_yaml(slug)}",
        f"    bundles: [{_yaml(bundle_key)}]",
    ]
    lines += [f"Save this as `config/apps/{slug}.yaml`:", "", *_fenced(snippet), ""]
    advice = (
        f"Replace every {_code(FILL_IN)} value: `org` and `slug` are the two names in the app's APKMirror address "
        "(`apkmirror.com/apk/<org>/<slug>/`), and `icon` is any image address."
    )
    if len(usable) > 1:
        advice += " The other GitHub bundles in the table can be added as extra builds of the same app."
    lines.append(advice)
    return lines


def _unknown_package(morphe: Catalog, wanted: str) -> str:
    lines = [f"## Morphe catalog: {_code(wanted)}", "", "No app with that package name is in the catalog."]
    close = _close_matches(morphe, wanted)
    if close:
        lines += ["", f"Close matches: {_codes(close)}"]
    else:
        lines += ["", "Search by app name instead to find the package name."]
    return "\n".join(lines) + "\n"


def package_report(
    morphe: Catalog,
    package: str,
    builds: Mapping[str, BuildConfig] = BUILDS,
    bundles: Mapping[str, BundleSource] = BUNDLES,
) -> str:
    resolved = _resolve(morphe, package)
    if resolved is None:
        return _unknown_package(morphe, package)
    app = morphe["apps"][resolved]
    supporting = _supporters(morphe).get(resolved, [])
    configured = _configured(bundles)
    mine = _builds_by_package(builds).get(resolved, [])
    used = {key for build in mine for key in build["bundles"]}

    lines = [f"## Morphe catalog: {_code(resolved)}", "", _app_line(app, len(supporting)), ""]
    lines.append(
        f"Patchy builds it as {_codes(build['key'] for build in mine)}."
        if mine
        else "Patchy does not build it yet."
    )
    if not supporting:
        lines += ["", "No bundle in the catalog patches this app."]
        return "\n".join(lines) + "\n"

    lines += ["", "### Bundles that patch it", ""]
    rows = [
        [
            _text(bundle["name"]),
            _repo_cell(bundle),
            _patches_cell(bundle, resolved),
            _status_cell(bundle, configured, used),
        ]
        for bundle in supporting
    ]
    lines += _table(["Bundle", "Repository", "Patches", "In Patchy"], rows)

    missing = [bundle for bundle in supporting if _usable(bundle) and _bundle_id(bundle) not in configured]
    new_keys = _new_bundle_keys(missing, set(bundles))
    if missing:
        snippet = [line for bundle in missing for line in _bundle_snippet(bundle, new_keys[_bundle_id(bundle)])]
        lines += ["", "### Add the missing bundles", "", "Add this under `bundles:` in `config/bundles.yaml`:", ""]
        lines += _fenced(snippet)
    if not mine:
        lines += _app_section(app, supporting, configured, new_keys, builds)
    return "\n".join(lines) + "\n"


def _matches(app: CatalogApp, tokens: Sequence[str]) -> bool:
    haystack = f"{app['package']} {app['name']}".lower()
    return all(token in haystack for token in tokens)


def _rank(app: CatalogApp, query: str, usable: int) -> tuple[int, int, str, str]:
    starts = app["name"].lower().startswith(query) or app["package"].lower().startswith(query)
    return (0 if starts else 1, -usable, app["name"].lower(), app["package"])


def search_report(
    morphe: Catalog,
    query: str,
    limit: int = DEFAULT_LIMIT,
    builds: Mapping[str, BuildConfig] = BUILDS,
) -> str:
    wanted = " ".join(query.lower().split())
    supporters = _supporters(morphe)
    found = [app for app in morphe["apps"].values() if _matches(app, wanted.split())]
    found.sort(key=lambda app: _rank(app, wanted, _usable_count(supporters, app["package"])))

    lines = [f"## Morphe catalog search: {_code(query)}", ""]
    if not found:
        lines.append("No app in the catalog matches that text.")
        return "\n".join(lines) + "\n"

    grouped = _builds_by_package(builds)
    rows = [
        [
            _code(app["package"]),
            _text(app["name"]),
            _text(app["category"]) or EMPTY,
            str(_usable_count(supporters, app["package"])),
            _patchy_cell(grouped.get(app["package"])),
        ]
        for app in found[:limit]
    ]
    lines += _table(["Package", "App", "Category", "Bundles", "In Patchy"], rows)
    lines += [
        "",
        f"Showing {len(rows)} of {len(found)} match(es). Look one up by its package name for the details.",
    ]
    return "\n".join(lines) + "\n"


def _alternatives(candidates: Sequence[CatalogBundle], configured: Mapping[str, str]) -> str:
    shown = []
    for bundle in candidates[:ALTERNATIVES_SHOWN]:
        key = configured.get(_bundle_id(bundle))
        if key is not None:
            shown.append(f"✅ {_code(key)}")
        else:
            shown.append(f"➕ {_text(bundle['owner'] + '/' + bundle['repo'])}")
    hidden = len(candidates) - len(shown)
    return ", ".join(shown) + (f" (+{hidden} more)" if hidden > 0 else "")


def _used_bundles(package_builds: Sequence[BuildConfig]) -> list[str]:
    return list(dict.fromkeys(key for build in package_builds for key in build["bundles"]))


def _patchy_lines(
    morphe: Catalog,
    grouped: Mapping[str, list[BuildConfig]],
    supporters: Mapping[str, list[CatalogBundle]],
    configured: Mapping[str, str],
    bundles: Mapping[str, BundleSource],
) -> list[str]:
    lines = ["### Apps Patchy builds", ""]
    for package, package_builds in sorted(grouped.items(), key=lambda item: item[1][0]["display_name"].lower()):
        in_use = _used_bundles(package_builds)
        line = f"- **{_text(package_builds[0]['display_name'])}** — uses {_codes(in_use)}"
        if package not in morphe["apps"]:
            lines.append(f"{line}. Not listed in the catalog.")
            continue
        in_use_ids = {_repo_id(bundles[key]["owner"], bundles[key]["repo"]) for key in in_use if key in bundles}
        others = [
            bundle
            for bundle in supporters.get(package, [])
            if _usable(bundle) and _bundle_id(bundle) not in in_use_ids
        ]
        lines.append(f"{line}. Also patched by: {_alternatives(others, configured)}" if others else f"{line}.")
    return lines


def _unlisted_lines(morphe: Catalog, bundles: Mapping[str, BundleSource]) -> list[str]:
    listed = {_bundle_id(bundle) for bundle in morphe["bundles"] if _usable(bundle)}
    unlisted = [
        f"- {_code(key)} — {_text(source['owner'] + '/' + source['repo'])}"
        for key, source in bundles.items()
        if _repo_id(source["owner"], source["repo"]) not in listed
    ]
    if not unlisted:
        return []
    return ["", "### Configured bundles the catalog does not list", "", *unlisted]


def _new_app_lines(
    morphe: Catalog,
    grouped: Mapping[str, list[BuildConfig]],
    supporters: Mapping[str, list[CatalogBundle]],
    limit: int,
) -> list[str]:
    candidates = [
        app
        for package, app in morphe["apps"].items()
        if package not in grouped and _usable_count(supporters, package) > 0
    ]
    candidates.sort(
        key=lambda app: (-_usable_count(supporters, app["package"]), app["name"].lower(), app["package"])
    )
    if not candidates:
        return []
    rows = [
        [
            _code(app["package"]),
            _text(app["name"]),
            _text(app["category"]) or EMPTY,
            str(_usable_count(supporters, app["package"])),
        ]
        for app in candidates[:limit]
    ]
    lines = ["", "### Apps Patchy does not build yet", ""]
    lines += _table(["Package", "App", "Category", "Bundles"], rows)
    lines += [
        "",
        f"Showing {len(rows)} of {len(candidates)}. Look one up by its package name to get ready-made config.",
    ]
    return lines


def overview_report(
    morphe: Catalog,
    limit: int = DEFAULT_LIMIT,
    builds: Mapping[str, BuildConfig] = BUILDS,
    bundles: Mapping[str, BundleSource] = BUNDLES,
) -> str:
    supporters = _supporters(morphe)
    grouped = _builds_by_package(builds)
    configured = _configured(bundles)
    on_github = sum(1 for bundle in morphe["bundles"] if _usable(bundle))
    lines = [
        "## Morphe catalog overview",
        "",
        f"The catalog lists {len(morphe['apps'])} app(s) and {len(morphe['bundles'])} bundle(s), {on_github} of them on GitHub.",
        "",
    ]
    lines += _patchy_lines(morphe, grouped, supporters, configured, bundles)
    lines += _unlisted_lines(morphe, bundles)
    lines += _new_app_lines(morphe, grouped, supporters, limit)
    return "\n".join(lines) + "\n"


def build_report(
    morphe: Catalog,
    *,
    package: str = "",
    query: str = "",
    limit: int = DEFAULT_LIMIT,
    builds: Mapping[str, BuildConfig] | None = None,
    bundles: Mapping[str, BundleSource] | None = None,
) -> str:
    known_builds = BUILDS if builds is None else builds
    known_bundles = BUNDLES if bundles is None else bundles
    shown = max(1, min(limit, MAX_LIMIT))
    if package.strip():
        return package_report(morphe, package, known_builds, known_bundles)
    if query.strip():
        return search_report(morphe, query, shown, known_builds)
    return overview_report(morphe, shown, known_builds, known_bundles)
