from ..core.settings import settings
from . import BUILDS, BUNDLES, COMPANIONS


class ConfigError(Exception):
    pass


def validate_catalog() -> None:
    problems: list[str] = []

    for key, build in BUILDS.items():
        bundles = build.get("bundles") or []

        if not bundles:
            problems.append(f'Build "{key}" has no bundles.')

        for name in bundles:
            if name not in BUNDLES:
                problems.append(
                    f'Build "{key}" references bundle "{name}", which is not in {settings.bundles_path}.'
                )

        for field in ("exclude", "enable"):
            value = build.get(field)
            if value is not None and not isinstance(value, list):
                problems.append(
                    f'Build "{key}".{field} should be a list, got {type(value).__name__} '
                    f"(a bare string would get patch_apk() to pass one --disable/--enable flag per "
                    f"character instead of one per patch name)."
                )

        options = build.get("options")
        if options is not None:
            if not isinstance(options, dict):
                problems.append(f'Build "{key}".options should be a mapping, got {type(options).__name__}.')
            else:
                for dotted_key in options:
                    if not isinstance(dotted_key, str) or "." not in dotted_key:
                        problems.append(
                            f'Build "{key}".options key {dotted_key!r} should be "Patch name.optionKey" '
                            f'(e.g. "Custom branding.App name") - patch_apk() needs both parts to build the '
                            f"-O flag."
                        )

        source = build.get("apk_source") or {}
        required_fields = {"apkmirror": ("org", "slug"), "github": ("owner", "repo")}.get(source.get("type"), ())
        for field in required_fields:
            if not source.get(field):
                problems.append(f'Build "{key}".apk_source is type "{source.get("type")}" but has no "{field}".')

    for key, companion in COMPANIONS.items():
        for build_key in companion["for_builds"]:
            if build_key not in BUILDS:
                problems.append(f'Companion "{key}" is meant for build "{build_key}", which does not exist.')
        if not companion["variants"]:
            problems.append(f'Companion "{key}" has no variants.')

    if problems:
        header = f"Found {len(problems)} problem(s) in the config:"
        raise ConfigError("\n".join([header] + [f"  - {p}" for p in problems]))
