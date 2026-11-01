import argparse
import asyncio
import os
import sys
from pathlib import Path

from .core import log

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_default(name: str, fallback: str = "") -> str:
    return os.environ.get(name, fallback)


def _env_flag(name: str) -> bool:
    return _env_default(name).strip().lower() in TRUE_VALUES


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from e
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def cmd_validate(args: argparse.Namespace) -> int:
    from .catalog.validate import ConfigError, validate_catalog

    try:
        validate_catalog()
    except ConfigError as e:
        log.error(f"Config validation failed:\n{e}")
        return 1
    log.success("Config is valid.")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from .catalog.plan import PlanError, make_plan, narrow, write_github_output
    from .catalog.validate import ConfigError, validate_catalog

    try:
        validate_catalog()
        plan = make_plan(args.builds)
    except (ConfigError, PlanError) as e:
        log.error(f"Planning failed:\n{e}")
        return 1

    if args.only_changed:
        from .publish.incremental import select_changed

        plan = narrow(plan, asyncio.run(select_changed(plan.matrix)))
        if not plan.has_builds:
            log.notice("Nothing changed since the last release, so no build runs.")
            log.step_summary(
                "## Nothing to build\n\n"
                "The patcher, the patch bundles, the apps and the configuration are unchanged since the last release."
            )

    log.info(f"Release tag for this run: {plan.tag}")
    log.info(f"Release name for this run: {plan.name}")
    log.info(f"Build matrix ({len(plan.matrix)} build(s)): {plan.matrix_json()}")
    write_github_output(plan)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from .catalog.plan import PlanError, select_builds
    from .fetch.bundles import fetch_all

    try:
        builds = select_builds(args.builds)
    except PlanError as e:
        log.error(str(e))
        return 1

    manifest = asyncio.run(fetch_all(builds))
    log.saved(f"Fetched the CLI and {len(manifest['bundles'])} patch bundle(s) for {len(builds)} build(s).")

    try:
        from .publish.incremental import record_fingerprints

        asyncio.run(record_fingerprints(manifest))
    except Exception as e:
        log.warn(f"Could not record what these builds are made from, so the next only-changed run builds all: {e}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from . import catalog
    from .core.settings import settings
    from .engine.build import run_builds
    from .fetch import apkmirror
    from .fetch.bundles import ManifestError, read_manifest, resolve_tools

    target = args.app or settings.target_app
    build_keys = list(catalog.BUILDS) if target == "all" else [target]
    unknown = [key for key in build_keys if key not in catalog.BUILDS]
    if unknown:
        log.error(f"Unknown build key(s): {', '.join(unknown)}")
        return 1

    async def _run() -> list[str]:
        try:
            tools = resolve_tools(read_manifest())
            return await run_builds(build_keys, tools)
        finally:
            await apkmirror.close_session()

    try:
        failed = asyncio.run(_run())
    except ManifestError as e:
        log.error(str(e))
        return 1

    if failed:
        log.error(f"Failed build(s): {', '.join(failed)}")
        return 1
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    from .publish.pipeline import run_sign

    asyncio.run(run_sign())
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from .publish.pipeline import run_publish

    asyncio.run(run_publish())
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    from .publish.telemetry import render_summary

    markdown = render_summary()
    if not markdown:
        log.warn("No build statuses were found, so there is nothing to summarize.")
        return 0
    if not log.step_summary(markdown):
        print(markdown)
    return 0


def cmd_pin(args: argparse.Namespace) -> int:
    from .engine import pins
    from .publish.assets import find_pending_pins

    try:
        if args.collect:
            directory = Path(args.collect)
            pins.commit_pending(find_pending_pins(directory))
            return 0

        if not args.app:
            log.error("Give an app slug to pin, or use --collect DIR to record pending fingerprints.")
            return 2

        fingerprint = pins.commit_promotion(args.app, args.sha256)
        log.success(f"Pinned {args.app}: {fingerprint}")
        return 0
    except pins.PinsError as e:
        log.error(str(e))
        return 1


def cmd_discover(args: argparse.Namespace) -> int:
    from .catalog.discover import build_report
    from .fetch.morphe import MorpheCatalogError, fetch_catalog

    try:
        morphe = asyncio.run(fetch_catalog())
    except MorpheCatalogError as e:
        log.error(str(e))
        return 1

    markdown = build_report(morphe, package=args.package, query=args.query, limit=args.limit)
    if log.step_summary(markdown):
        log.success("Wrote the Morphe catalog report to the job summary.")
    else:
        print(markdown)
    return 0


def cmd_toolchain(args: argparse.Namespace) -> int:
    from .core import toolchain

    try:
        tools = asyncio.run(toolchain.prepare(install_latest=not args.no_install))
    except toolchain.ToolchainError as e:
        log.error(str(e))
        return 1

    github_env = os.environ.get("GITHUB_ENV")
    for name, path in tools.items():
        log.info(f"{name}={path}")
        if github_env:
            with open(github_env, "a", encoding="utf-8") as f:
                f.write(f"{name}={path}\n")
    return 0


def _add_builds_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--builds", default=_env_default("BUILDS", "all"), help="build keys, comma-separated, or 'all'"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="patchy", description="Patchy - APK patching pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate config/ without touching the network")
    validate.set_defaults(func=cmd_validate)

    plan = commands.add_parser("plan", help="validate config and write the release plan")
    _add_builds_option(plan)
    plan.add_argument(
        "--only-changed",
        action="store_true",
        default=_env_flag("ONLY_CHANGED"),
        help="skip builds whose patcher, patch bundles, app and configuration match the last release",
    )
    plan.set_defaults(func=cmd_plan)

    fetch = commands.add_parser("fetch", help="download the patcher CLI and patch bundles")
    _add_builds_option(fetch)
    fetch.set_defaults(func=cmd_fetch)

    build = commands.add_parser("build", help="download, verify and patch one build (no signing credentials)")
    build.add_argument("--app", default="", help="build key; defaults to TARGET_APP, 'all' builds everything")
    build.set_defaults(func=cmd_build)

    sign = commands.add_parser("sign", help="zipalign and sign the patched APKs with apksigner")
    sign.set_defaults(func=cmd_sign)

    publish = commands.add_parser("publish", help="create the GitHub release, upload APKs and notify")
    publish.set_defaults(func=cmd_publish)

    summary = commands.add_parser("summary", help="write per-build download and patch times to the job summary")
    summary.set_defaults(func=cmd_summary)

    pin = commands.add_parser("pin", help="trust a pending certificate fingerprint, or record pending ones")
    pin.add_argument("app", nargs="?", help="app slug whose pending fingerprint should become trusted")
    pin.add_argument("--sha256", help="the fingerprint you verified; must equal the pending one")
    pin.add_argument("--collect", metavar="DIR", help="record pending fingerprints from build statuses in DIR")
    pin.set_defaults(func=cmd_pin)

    discover = commands.add_parser("discover", help="look up apps and patch bundles in the Morphe catalog")
    discover.add_argument(
        "--package",
        default=_env_default("DISCOVER_PACKAGE"),
        help="package name to look up: the bundles that patch it and ready-made config (wins over --query)",
    )
    discover.add_argument(
        "--query",
        default=_env_default("DISCOVER_QUERY"),
        help="search the catalog by app or package name",
    )
    discover.add_argument(
        "--limit",
        type=_positive_int,
        default=_env_default("DISCOVER_LIMIT") or "20",
        help="most rows to list in a table",
    )
    discover.set_defaults(func=cmd_discover)

    toolchain = commands.add_parser("toolchain", help="find (and install the latest) Android build-tools")
    toolchain.add_argument("--no-install", action="store_true", help="only use what is already installed")
    toolchain.set_defaults(func=cmd_toolchain)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
