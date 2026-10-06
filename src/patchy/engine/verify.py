import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from ..core import log
from ..core.process import ProcessTimeout, run_capture
from ..core.settings import settings
from ..core.toolchain import ToolchainError, resolve_apksigner
from .pins import PinsError, load_pins

DIGEST_PATTERN = re.compile(r"certificate SHA-256 digest:\s*([0-9a-fA-F]{64})")


class SignatureError(Exception):
    pass


class UnpinnedSignature(SignatureError):
    def __init__(self, app_name: str, fingerprint: str):
        self.app_name = app_name
        self.fingerprint = fingerprint
        super().__init__(
            f"No pinned signature for {app_name} - APK NOT patched/published.\n"
            f"   Certificate fingerprint seen: {fingerprint}\n"
            f"   It will be recorded in pins/pending.json. Verify it against the developer's official source "
            f"(Play Store listing, official website, etc.), then run the Release workflow with the "
            f"'pin' input set to {app_name} to trust it."
        )


def parse_cert_digests(output: str) -> list[str]:
    seen: list[str] = []
    for match in DIGEST_PATTERN.finditer(output):
        digest = match.group(1).lower()
        if digest not in seen:
            seen.append(digest)
    return seen


async def apk_certificate_fingerprints(apk_path: str) -> list[str]:
    try:
        apksigner = resolve_apksigner()
    except ToolchainError as e:
        raise SignatureError(str(e)) from e

    try:
        result = await run_capture(
            [str(apksigner), "verify", "--print-certs", apk_path], timeout=settings.tool_timeout
        )
    except ProcessTimeout as e:
        raise SignatureError(str(e)) from e

    if result.returncode != 0:
        tail = " | ".join(result.output.strip().splitlines()[:4]) or "(no output)"
        raise SignatureError(f"apksigner could not verify {Path(apk_path).name}: {tail}")

    digests = parse_cert_digests(result.output)
    if not digests:
        raise SignatureError(f"apksigner printed no signing certificate for {Path(apk_path).name}.")
    return digests


def _resolve_verifiable_apk(path: str) -> tuple[str, str | None]:
    if not zipfile.is_zipfile(path):
        if path.lower().endswith(".apk"):
            return path, None
        raise SignatureError(
            f"{Path(path).name} is neither a single .apk nor a ZIP-based bundle (.apkm/.xapk) - cannot verify."
        )

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()

        if "AndroidManifest.xml" in names:
            return path, None

        candidates = [n for n in names if n.split("/")[-1] == "base.apk"]
        if not candidates:
            candidates = [n for n in names if n.endswith(".apk")]
        if not candidates:
            raise SignatureError(f"No verifiable .apk found inside {Path(path).name}.")

        base_name = candidates[0]
        temp_dir = tempfile.mkdtemp(prefix="apkm_verify_")
        extracted_path = zf.extract(base_name, temp_dir)
        return extracted_path, temp_dir


async def verify_apk_signature(apk_path: str, app_name: str) -> None:
    if settings.skip_signature_verify:
        log.warn(f"SKIP_SIGNATURE_VERIFY=1: skipping signature verification for {app_name}.")
        return

    log.lock(f"Verifying signature: {app_name} ({Path(apk_path).name})")

    verifiable_path, temp_dir = _resolve_verifiable_apk(apk_path)
    try:
        if temp_dir:
            log.info(f"   Bundle detected, extracting and verifying base.apk: {Path(verifiable_path).name}")
        fingerprints = await apk_certificate_fingerprints(verifiable_path)
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    try:
        known = load_pins(settings.known_pins_path)
    except PinsError as e:
        raise SignatureError(str(e)) from e

    pinned = known.get(app_name)

    if pinned is None:
        raise UnpinnedSignature(app_name, fingerprints[0])

    if pinned not in fingerprints:
        raise SignatureError(
            f"SIGNATURE MISMATCH: expected certificate fingerprint for {app_name} is "
            f"{pinned}, but the downloaded APK's certificate is {fingerprints}. "
            f"This may indicate the APK came from an unexpected/untrusted source. "
            f"Stopping for safety."
        )

    log.success(f"Signature verified: {app_name} ({pinned})")
