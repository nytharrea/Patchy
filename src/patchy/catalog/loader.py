import re
from pathlib import Path

import yaml

from ..core.settings import settings
from .models import ApkSource, BuildConfig, BundleSource, CliSource, Companion, CompanionVariant

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CatalogError(Exception):
    pass


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise CatalogError(f"Config file not found: {path}") from e
    except yaml.YAMLError as e:
        raise CatalogError(f"Could not parse {path}: {e}") from e

    if not isinstance(data, dict):
        raise CatalogError(f"{path} should contain a YAML mapping at the top level.")
    return data


def load_cli() -> CliSource:
    raw = load_yaml(settings.bundles_path)
    try:
        entry = raw["cli"]
        return {"owner": entry["owner"], "repo": entry["repo"]}
    except (KeyError, TypeError) as e:
        raise CatalogError(f'{settings.bundles_path} needs a "cli" section with "owner" and "repo": {e}') from e


def load_bundles() -> dict[str, BundleSource]:
    raw = load_yaml(settings.bundles_path)
    section = raw.get("bundles")
    if not isinstance(section, dict) or not section:
        raise CatalogError(f'{settings.bundles_path} needs a non-empty "bundles" mapping.')

    bundles: dict[str, BundleSource] = {}
    for key, entry in section.items():
        try:
            bundles[key] = {
                "owner": entry["owner"],
                "repo": entry["repo"],
                "label": entry.get("label", key),
            }
        except (KeyError, TypeError, AttributeError) as e:
            raise CatalogError(f'Bundle "{key}" in {settings.bundles_path} is malformed: {e}') from e

    return bundles


def load_companions() -> dict[str, Companion]:
    path = settings.companions_path
    if not path.exists():
        return {}

    raw = load_yaml(path)
    companions: dict[str, Companion] = {}

    for key, entry in raw.items():
        try:
            variants: list[CompanionVariant] = []
            for variant in entry["variants"]:
                item: CompanionVariant = {"file": variant["file"], "suffix": variant["suffix"]}
                if variant.get("exclude"):
                    item["exclude"] = variant["exclude"]
                variants.append(item)
            companions[key] = {
                "key": key,
                "owner": entry["owner"],
                "repo": entry["repo"],
                "for_builds": list(entry.get("for_builds") or []),
                "variants": variants,
            }
        except (KeyError, TypeError, AttributeError) as e:
            raise CatalogError(f'Companion "{key}" in {path} is malformed: {e}') from e

    return companions


def app_files() -> list[Path]:
    directory = settings.apps_dir
    if not directory.is_dir():
        raise CatalogError(f"Apps directory not found: {directory}")
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise CatalogError(f"No app files (*.yaml) found in {directory}")
    return files


def load_builds() -> dict[str, BuildConfig]:
    builds: dict[str, BuildConfig] = {}

    for path in app_files():
        app_slug = path.stem
        if not SLUG_PATTERN.match(app_slug):
            raise CatalogError(f'App file name "{path.name}" must be a lowercase slug such as "youtube.yaml".')

        app = load_yaml(path)

        try:
            apk_source: ApkSource = app["apk_source"]

            src_type = apk_source.get("type")
            if src_type not in ("apkmirror", "github"):
                raise CatalogError(
                    f'{path.name} has apk_source.type {src_type!r} - must be "apkmirror" or "github".'
                )

            if not app.get("builds"):
                raise CatalogError(f"{path.name} has no builds.")

            for build in app["builds"]:
                key = build["key"]
                if key in builds:
                    raise CatalogError(
                        f'Build key "{key}" is used more than once (most recently in {path.name}) - build '
                        f"keys must be unique across all of config/apps, since they double as CI matrix jobs "
                        f"and release filenames."
                    )
                if not build.get("bundles"):
                    raise CatalogError(f'Build "{key}" ({path.name}) has no bundles.')

                builds[key] = {
                    "key": key,
                    "app_slug": app_slug,
                    "pkg": app["pkg"],
                    "display_name": build.get("display_name", app["display_name"]),
                    "arch": app["arch"],
                    "icon": app["icon"],
                    "apk_source": apk_source,
                    "bundles": list(build["bundles"]),
                    "exclude": list(build.get("exclude") or []),
                    "enable": list(build.get("enable") or []),
                    "options": dict(build.get("options") or {}),
                    "force_version": build.get("force_version"),
                    "force_build": build.get("force_build"),
                }
        except (KeyError, TypeError, AttributeError) as e:
            raise CatalogError(f"{path.name} is malformed: {e}") from e

    return builds
