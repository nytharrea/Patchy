from typing import get_args

from ..core.settings import settings
from ..engine.label import MAX_LABEL_LENGTH
from . import BUILDS, BUNDLES, COMPANIONS
from .models import ApkType

APK_TYPES = get_args(ApkType)


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

        label = build.get("label")
        if label is not None and not (isinstance(label, str) and label.strip() and len(label) <= MAX_LABEL_LENGTH):
            problems.append(
                f'Build "{key}".label should be a text of 1 to {MAX_LABEL_LENGTH} characters, got {label!r} '
                f"(it becomes the app name shown by Android, see the App name section of docs/configuration.md)."
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

        apk_type = build.get("apk_type")
        if apk_type is not None:
            if apk_type not in APK_TYPES:
                problems.append(
                    f'Build "{key}".apk_type should be "apk" or "bundle", got {apk_type!r} '
                    f"(see the APK type section of docs/configuration.md)."
                )
            elif source.get("type") != "apkmirror":
                problems.append(
                    f'Build "{key}".apk_type only applies to APKMirror sources, but its apk_source is type '
                    f'"{source.get("type")}", where it would be ignored.'
                )

    for key, companion in COMPANIONS.items():
        for build_key in companion["for_builds"]:
            if build_key not in BUILDS:
                problems.append(f'Companion "{key}" is meant for build "{build_key}", which does not exist.')
        if not companion["variants"]:
            problems.append(f'Companion "{key}" has no variants.')

    if problems:
        header = f"Found {len(problems)} problem(s) in the config:"
        raise ConfigError("\n".join([header] + [f"  - {p}" for p in problems]))
