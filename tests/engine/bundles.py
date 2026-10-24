import zipfile
from pathlib import Path


def write_bundle(directory: Path, name: str, patcher_version: str | None, *, newline: str = "\r\n") -> Path:
    lines = ["Manifest-Version: 1.0", "Name: Test Patches", "Version: 1.0.0"]
    if patcher_version is not None:
        lines.append(f"Patcher-Version: {patcher_version}")
    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", newline.join(lines) + newline + newline)
    return path
