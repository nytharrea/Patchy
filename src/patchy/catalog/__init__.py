from . import loader
from .loader import CatalogError
from .models import BuildConfig, BundleSource, CliSource, Companion

__all__ = [
    "BUILDS",
    "BUNDLES",
    "CLI",
    "COMPANIONS",
    "BuildConfig",
    "BundleSource",
    "CatalogError",
    "CliSource",
    "Companion",
    "bundles_for",
    "get_release_naming",
]

CLI: CliSource = loader.load_cli()
BUNDLES: dict[str, BundleSource] = loader.load_bundles()
BUILDS: dict[str, BuildConfig] = loader.load_builds()
COMPANIONS: dict[str, Companion] = loader.load_companions()


def bundles_for(build_key: str) -> list[str]:
    return BUILDS[build_key]["bundles"]


def get_release_naming(build_key: str) -> tuple[str, str | None]:
    build = BUILDS[build_key]
    display_name = build["display_name"]

    siblings = [b for b in BUILDS.values() if b["display_name"] == display_name]
    if len(siblings) <= 1:
        return display_name, None

    def _owner(b: BuildConfig) -> str:
        return BUNDLES[b["bundles"][0]]["owner"]

    suffix = _owner(build)
    if sum(1 for b in siblings if _owner(b) == suffix) > 1:
        suffix = build["key"]

    return display_name, suffix
