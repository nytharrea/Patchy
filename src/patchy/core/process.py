import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass

SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "JAVA_HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
    "LOGNAME",
    "SYSTEMROOT",
)


class ProcessTimeout(Exception):
    pass


@dataclass(frozen=True)
class Completed:
    returncode: int
    output: str
    error: str = ""


def clean_env(extra: Mapping[str, str] | None = None, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    env = {key: source[key] for key in SAFE_ENV_KEYS if key in source}
    env.update(extra or {})
    return env


async def run_capture(
    cmd: list[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
    stderr_to_stdout: bool = True,
) -> Completed:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT if stderr_to_stdout else asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else clean_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ProcessTimeout(f"{cmd[0]} did not finish within {timeout:.0f}s and was killed.") from None
    return Completed(
        process.returncode or 0,
        (stdout or b"").decode("utf-8", errors="replace"),
        (stderr or b"").decode("utf-8", errors="replace"),
    )
