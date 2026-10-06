import shutil
from dataclasses import dataclass
from pathlib import Path

from ..core import log
from ..core.process import ProcessTimeout, clean_env, run_capture
from ..core.settings import settings
from ..core.toolchain import ToolchainError, resolve_apksigner, resolve_zipalign
from .verify import parse_cert_digests

KS_PASSWORD_VAR = "PATCHY_KS_PASSWORD"
KEY_PASSWORD_VAR = "PATCHY_KEY_PASSWORD"


class SigningError(Exception):
    pass


@dataclass(frozen=True)
class Credentials:
    keystore: Path
    alias: str
    ks_password: str
    key_password: str


def load_credentials() -> Credentials | None:
    ks_path = settings.ks_path
    ks_password = settings.ks_password.get_secret_value() if settings.ks_password else ""
    key_password = settings.key_password.get_secret_value() if settings.key_password else ""
    alias = settings.ks_alias or ""

    usable = ks_path is not None and ks_path.is_file() and ks_path.stat().st_size > 0
    if usable and ks_password and key_password and alias:
        assert ks_path is not None
        return Credentials(ks_path, alias, ks_password, key_password)
    return None


def build_sign_command(apksigner: Path, creds: Credentials, source: Path, dest: Path) -> list[str]:
    return [
        str(apksigner),
        "sign",
        "--ks",
        str(creds.keystore),
        "--ks-key-alias",
        creds.alias,
        "--ks-pass",
        f"env:{KS_PASSWORD_VAR}",
        "--key-pass",
        f"env:{KEY_PASSWORD_VAR}",
        "--v4-signing-enabled",
        "false",
        "--out",
        str(dest),
        str(source),
    ]


def _failure(prefix: str, output: str) -> SigningError:
    tail = " | ".join(output.strip().splitlines()[-4:]) or "(no output)"
    return SigningError(f"{prefix}: {tail}")


async def align_apk(source: Path, dest: Path) -> None:
    zipalign = resolve_zipalign()
    if zipalign is None:
        log.warn("zipalign not found; signing the patcher's output without re-aligning it.")
        shutil.copyfile(source, dest)
        return

    try:
        result = await run_capture(
            [str(zipalign), "-f", "-P", "16", "4", str(source), str(dest)], timeout=settings.tool_timeout
        )
        if result.returncode != 0:
            log.warn("zipalign rejected 16 KB page alignment (-P 16); retrying with 4 KB alignment (-p).")
            result = await run_capture(
                [str(zipalign), "-f", "-p", "4", str(source), str(dest)], timeout=settings.tool_timeout
            )
    except ProcessTimeout as e:
        raise SigningError(str(e)) from e
    if result.returncode != 0:
        raise _failure(f"zipalign failed for {source.name}", result.output)


async def verify_signed(apk: Path) -> str:
    try:
        apksigner = resolve_apksigner()
        result = await run_capture(
            [str(apksigner), "verify", "--print-certs", str(apk)], timeout=settings.tool_timeout
        )
    except (ToolchainError, ProcessTimeout) as e:
        raise SigningError(str(e)) from e

    if result.returncode != 0:
        raise _failure(f"apksigner verify failed for {apk.name}", result.output)

    digests = parse_cert_digests(result.output)
    if not digests:
        raise SigningError(f"apksigner verify printed no certificate for {apk.name}.")
    return digests[0]


async def sign_apk(source: Path, dest: Path, creds: Credentials | None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)

    if creds is None:
        log.warn(
            f"No signing credentials: {source.name} keeps the patcher's shared default test key. "
            f"Set the KEYSTORE_* secrets before relying on these builds."
        )
        shutil.copyfile(source, dest)
        return await verify_signed(dest)

    aligned = dest.with_name(dest.name + ".aligned")
    try:
        await align_apk(source, aligned)

        try:
            apksigner = resolve_apksigner()
            env = clean_env({KS_PASSWORD_VAR: creds.ks_password, KEY_PASSWORD_VAR: creds.key_password})
            result = await run_capture(
                build_sign_command(apksigner, creds, aligned, dest), timeout=settings.tool_timeout, env=env
            )
        except (ToolchainError, ProcessTimeout) as e:
            raise SigningError(str(e)) from e

        if result.returncode != 0:
            raise _failure(f"apksigner sign failed for {source.name}", result.output)
    finally:
        aligned.unlink(missing_ok=True)

    dest.with_name(dest.name + ".idsig").unlink(missing_ok=True)
    return await verify_signed(dest)
