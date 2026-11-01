import io
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .label import MANIFEST_ENTRY, LabelError, manifest_info
from .versions import to_apkmirror_version

DEX_ENTRY = "classes.dex"
LIBRARY_DIRECTORY = "lib"
BASE_APK_NAME = "base.apk"
UNPARSEABLE = (LabelError, struct.error, IndexError, UnicodeError)


class SanityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApkFacts:
    package: str | None
    version_name: str | None
    version_code: int | None
    abis: frozenset[str]
    has_dex: bool
    manifest_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "version_name": self.version_name,
            "version_code": self.version_code,
            "abis": sorted(self.abis),
        }


def _inner_apk_name(names: list[str]) -> str | None:
    candidates = [name for name in names if name.split("/")[-1] == BASE_APK_NAME]
    if not candidates:
        candidates = [name for name in names if name.endswith(".apk")]
    return candidates[0] if candidates else None


def _facts(archive: zipfile.ZipFile) -> ApkFacts:
    names = archive.namelist()
    abis = frozenset(
        parts[1]
        for name in names
        if len(parts := name.split("/")) >= 3 and parts[0] == LIBRARY_DIRECTORY and parts[-1]
    )
    has_dex = DEX_ENTRY in names
    try:
        info = manifest_info(archive.read(MANIFEST_ENTRY))
    except UNPARSEABLE as e:
        return ApkFacts(None, None, None, abis, has_dex, str(e))
    return ApkFacts(info.package, info.version_name, info.version_code, abis, has_dex)


def inspect_apk(path: str | Path) -> ApkFacts:
    target = Path(path)
    try:
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            if MANIFEST_ENTRY in names:
                return _facts(archive)
            inner_name = _inner_apk_name(names)
            if inner_name is None:
                raise SanityError(f"{target.name} holds no {MANIFEST_ENTRY} and no inner .apk")
            with zipfile.ZipFile(io.BytesIO(archive.read(inner_name))) as inner:
                if MANIFEST_ENTRY not in inner.namelist():
                    raise SanityError(f"{inner_name} inside {target.name} holds no {MANIFEST_ENTRY}")
                return _facts(inner)
    except (OSError, zipfile.BadZipFile) as e:
        raise SanityError(f"{target.name} is not a readable APK: {e}") from e


def inspect_quietly(path: str | Path) -> ApkFacts | None:
    try:
        return inspect_apk(path)
    except SanityError:
        return None


def _tokens(version: str) -> list[str]:
    return to_apkmirror_version(version).split("-")


def same_version(requested: str, actual: str) -> bool:
    left, right = _tokens(requested), _tokens(actual)
    shorter = min(len(left), len(right))
    return left[:shorter] == right[:shorter]


def input_problems(original: ApkFacts | None, *, package: str, version: str, arch: str) -> list[str]:
    if original is None or original.manifest_error:
        return []

    problems: list[str] = []
    if original.package and original.package != package:
        problems.append(f"The downloaded APK is {original.package}, but this build is configured for {package}.")
    if (
        original.version_name
        and version
        and version != "latest"
        and not same_version(version, original.version_name)
    ):
        problems.append(
            f"The downloaded APK reports version {original.version_name}, but {version} was requested."
        )
    if arch and original.abis and arch not in original.abis:
        libraries = ", ".join(sorted(original.abis))
        problems.append(
            f"The downloaded APK ships native libraries for {libraries} but not for {arch}, "
            f"the only architecture the patcher keeps."
        )
    return problems


def output_problems(patched: ApkFacts, *, arch: str, original: ApkFacts | None = None) -> list[str]:
    if not patched.has_dex:
        raise SanityError(f"The patched APK has no {DEX_ENTRY}, so it cannot be a working app.")

    problems: list[str] = []
    if patched.manifest_error:
        problems.append(f"The manifest of the patched APK could not be read: {patched.manifest_error}")
    if arch and patched.abis:
        extra = sorted(patched.abis - {arch})
        if extra:
            problems.append(f"The patched APK still holds native libraries for {', '.join(extra)}.")
    if arch and original is not None and arch in original.abis and arch not in patched.abis:
        problems.append(f"The patched APK lost the {arch} native libraries of the original.")
    return problems
