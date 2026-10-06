import asyncio
import re
from collections.abc import Sequence
from pathlib import Path

from ..core import log
from ..core.process import clean_env, run_capture
from ..core.settings import settings

STREAM_LIMIT = 1024 * 1024
SAVED_PATTERN = re.compile(r"INFO:\s+Saved to\s+([^\r\n]+\.apk)", re.IGNORECASE)


class PatchTimeout(RuntimeError):
    pass


def build_patch_command(
    cli_jar: str | Path,
    bundles: Sequence[str | Path],
    apk: str | Path,
    exclude: list[str] | None = None,
    enable: list[str] | None = None,
    options: dict[str, str | None] | None = None,
    arch: str = "arm64-v8a",
) -> list[str]:
    cmd = ["java", "-jar", str(cli_jar), "patch"]

    for bundle in bundles:
        cmd += ["--patches", str(bundle)]

    if arch:
        cmd += ["--striplibs", arch]

    options_by_patch: dict[str, list[tuple[str, str | None]]] = {}
    for dotted_key, value in (options or {}).items():
        patch_name, sep, option_key = dotted_key.partition(".")
        if not sep:
            raise ValueError(f'Build options key {dotted_key!r} must be "Patch name.optionKey" (no "." found).')
        options_by_patch.setdefault(patch_name, []).append((option_key, value))

    for patch_name, patch_options in options_by_patch.items():
        for option_key, value in patch_options:
            cmd.append(f"-O{option_key}" if value is None else f'-O{option_key}="{value}"')
        cmd += ["--enable", patch_name]

    for name in exclude or []:
        cmd += ["--disable", name]

    for name in enable or []:
        cmd += ["--enable", name]

    cmd.append(str(apk))
    return cmd


async def _stream_lines(process: asyncio.subprocess.Process, silence_timeout: float) -> list[str]:
    assert process.stdout is not None
    lines: list[str] = []
    while True:
        try:
            raw = await asyncio.wait_for(process.stdout.readline(), silence_timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise PatchTimeout(
                f"Patch CLI timed out (no output for {silence_timeout:.0f}s) and was killed - likely hung."
            ) from None
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace")
        log.patch_line(line)
        lines.append(line)
    await process.wait()
    return lines


async def patch_apk(
    cli_jar: str | Path,
    bundles: Sequence[str | Path],
    apk: str | Path,
    exclude: list[str] | None = None,
    enable: list[str] | None = None,
    options: dict[str, str | None] | None = None,
    arch: str = "arm64-v8a",
) -> str:
    log.patch(f"Patching APK & stripping unused architectures ({arch} only)...")
    log.notice(
        "Patching without signing credentials: the patcher's own temporary signature is replaced "
        "with your key in the release job."
    )

    cmd = build_patch_command(cli_jar, bundles, apk, exclude, enable, options, arch)
    log.step(f"Executing command: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=clean_env(),
        limit=STREAM_LIMIT,
    )

    lines = await _stream_lines(process, settings.patch_timeout)
    output = "".join(lines)

    if "Applying 0 patches" in output:
        raise RuntimeError("Applying 0 patches. No compatible patch found or version not supported.")

    if process.returncode != 0:
        raise RuntimeError(f"Patch failed (exit {process.returncode}):\n{output}")

    match = SAVED_PATTERN.search(output)
    if not match:
        raise RuntimeError(f"Cannot find patched APK path in output:\n{output}")

    patched_apk = match.group(1).strip()

    if not Path(patched_apk).exists():
        raise RuntimeError(f"Patched APK does not exist:\n{patched_apk}")

    log.success("Patch done")
    log.saved(f"Output: {patched_apk}")

    return patched_apk


async def list_versions(cli_jar: str | Path, bundles: Sequence[str | Path], pkg: str) -> str | None:
    cmd = ["java", "-jar", str(cli_jar), "list-versions", "-f", pkg]
    for bundle in bundles:
        cmd += ["--patches", str(bundle)]
    cmd.append("--include-experimental")

    result = await run_capture(cmd, timeout=settings.download_timeout, stderr_to_stdout=False)
    if result.returncode != 0:
        tail = " | ".join(result.error.strip().splitlines()[-5:]) or "(no output)"
        log.warn(f"'list-versions' exited with code {result.returncode}, skipping CLI-reported versions: {tail}")
        return None
    return result.output
