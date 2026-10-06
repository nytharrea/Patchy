import os
from pathlib import Path

BUILD_DIR_ENV = "PATCHY_BUILD_DIR"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    return repo_root() / "config"


def apps_dir() -> Path:
    return config_dir() / "apps"


def bundles_file() -> Path:
    return config_dir() / "bundles.yaml"


def companions_file() -> Path:
    return config_dir() / "companions.yaml"


def pins_dir() -> Path:
    return repo_root() / "pins"


def known_pins_file() -> Path:
    return pins_dir() / "known.json"


def pending_pins_file() -> Path:
    return pins_dir() / "pending.json"


def build_dir() -> Path:
    override = os.environ.get(BUILD_DIR_ENV)
    return Path(override).resolve() if override else repo_root() / "build"


def tools_dir() -> Path:
    return build_dir() / "tools"


def manifest_file() -> Path:
    return build_dir() / "manifest" / "bundles.json"


def companions_dir() -> Path:
    return build_dir() / "companions"


def downloads_dir() -> Path:
    return build_dir() / "downloads"


def out_dir() -> Path:
    return build_dir() / "out"


def artifacts_dir() -> Path:
    return build_dir() / "artifacts"


def signed_dir() -> Path:
    return build_dir() / "signed"


def diagnostics_dir() -> Path:
    return build_dir() / "diagnostics"
