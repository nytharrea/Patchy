import re
import shutil
from pathlib import Path

from . import log
from .process import ProcessTimeout, run_capture
from .settings import settings

STABLE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
BUILD_TOOLS_PATH = re.compile(r"^build-tools;(\d+\.\d+\.\d+)$")


class ToolchainError(Exception):
    pass


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def sdk_root() -> Path | None:
    for candidate in (settings.android_sdk_root, settings.android_home):
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def installed_versions(root: Path) -> list[str]:
    directory = root / "build-tools"
    if not directory.is_dir():
        return []
    names = [entry.name for entry in directory.iterdir() if entry.is_dir() and STABLE_VERSION.match(entry.name)]
    return sorted(names, key=version_key)


def resolve_tool(name: str, override: Path | None = None) -> Path:
    if override is not None:
        if override.is_file():
            return override
        raise ToolchainError(f"{name} was configured as {override}, but that file does not exist.")

    root = sdk_root()
    if root is not None:
        for version in reversed(installed_versions(root)):
            candidate = root / "build-tools" / version / name
            if candidate.is_file():
                return candidate

    found = shutil.which(name)
    if found:
        return Path(found)

    raise ToolchainError(
        f"{name} was not found. Install the Android SDK build-tools or set {name.upper()} to its path."
    )


def resolve_apksigner() -> Path:
    return resolve_tool("apksigner", settings.apksigner)


def resolve_zipalign() -> Path | None:
    try:
        return resolve_tool("zipalign", settings.zipalign)
    except ToolchainError:
        return None


def latest_build_tools(listing: str) -> str | None:
    versions: list[str] = []
    for line in listing.splitlines():
        match = BUILD_TOOLS_PATH.match(line.split("|", 1)[0].strip())
        if match:
            versions.append(match.group(1))
    return max(versions, key=version_key) if versions else None


def find_sdkmanager(root: Path) -> Path | None:
    candidates = sorted((root / "cmdline-tools").glob("*/bin/sdkmanager"), reverse=True)
    latest = root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if latest.is_file():
        return latest
    if candidates:
        return candidates[0]
    found = shutil.which("sdkmanager")
    return Path(found) if found else None


async def install_latest_build_tools() -> str | None:
    root = sdk_root()
    if root is None:
        log.warn("No Android SDK found (ANDROID_HOME / ANDROID_SDK_ROOT unset); using apksigner from PATH.")
        return None

    sdkmanager = find_sdkmanager(root)
    if sdkmanager is None:
        log.warn("sdkmanager not found; using the newest build-tools already installed.")
        return None

    try:
        listing = await run_capture(
            [str(sdkmanager), f"--sdk_root={root}", "--list"], timeout=settings.tool_timeout
        )
    except (ProcessTimeout, OSError) as e:
        log.warn(f"Could not list available build-tools: {e}")
        return None

    latest = latest_build_tools(listing.output)
    if latest is None:
        log.warn("sdkmanager listed no stable build-tools; using the newest installed.")
        return None

    if latest in installed_versions(root):
        log.info(f"Android build-tools {latest} is already installed.")
        return latest

    log.step(f"Installing Android build-tools {latest}...")
    try:
        result = await run_capture(
            [str(sdkmanager), f"--sdk_root={root}", "--install", f"build-tools;{latest}"],
            timeout=settings.tool_timeout * 3,
        )
    except (ProcessTimeout, OSError) as e:
        log.warn(f"Could not install build-tools {latest}: {e}")
        return None

    if result.returncode != 0:
        tail = " | ".join(result.output.strip().splitlines()[-3:]) or "(no output)"
        log.warn(f"sdkmanager failed to install build-tools {latest}: {tail}")
        return None

    log.success(f"Installed Android build-tools {latest}.")
    return latest


async def prepare(install_latest: bool = True) -> dict[str, Path]:
    if install_latest:
        await install_latest_build_tools()

    tools = {"APKSIGNER": resolve_apksigner()}
    zipalign = resolve_zipalign()
    if zipalign is not None:
        tools["ZIPALIGN"] = zipalign
    return tools
