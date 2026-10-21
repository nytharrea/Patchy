import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from patchy import catalog
from patchy.catalog import loader

DEFAULT_OUTPUT = "build/site/data/catalog.json"
DEFAULT_CATEGORY = "other"
CATEGORIES = {
    "brave": "tools",
    "capcut": "media",
    "discord": "social",
    "facebook": "social",
    "fairemail": "tools",
    "gboard": "tools",
    "google-photos": "media",
    "inshot": "media",
    "instagram": "social",
    "inure-github": "tools",
    "inure-play": "tools",
    "messenger": "social",
    "notesnook": "tools",
    "proton-mail": "privacy",
    "proton-pass": "privacy",
    "proton-vpn": "privacy",
    "reddit": "social",
    "speedtest": "tools",
    "symfonium": "media",
    "tiktok": "social",
    "twitter": "social",
    "warp": "privacy",
    "youtube": "media",
    "youtube-music": "media",
}
TITLES = {
    "inure-github": "Inure (GitHub)",
    "inure-play": "Inure (Play Store)",
    "youtube-music": "YouTube Music",
}
LEADING_SYMBOLS = re.compile(r"^[\W_]+")


def _clean_label(label: str) -> str:
    return LEADING_SYMBOLS.sub("", label).strip() or label


def _app_titles() -> dict[str, str]:
    titles = {path.stem: str(loader.load_yaml(path)["display_name"]) for path in loader.app_files()}
    titles.update(TITLES)
    return titles


def _bundle(key: str) -> dict[str, str]:
    bundle = catalog.BUNDLES[key]
    return {
        "key": key,
        "label": _clean_label(bundle["label"]),
        "url": f"https://github.com/{bundle['owner']}/{bundle['repo']}",
    }


def _source(source: dict) -> dict[str, str]:
    if source["type"] == "github":
        return {"type": "github", "url": f"https://github.com/{source['owner']}/{source['repo']}"}
    return {"type": "apkmirror", "url": f"https://www.apkmirror.com/apk/{source['org']}/{source['slug']}/"}


def _build(key: str, titles: dict[str, str]) -> dict:
    build = catalog.BUILDS[key]
    name, tag = catalog.get_release_naming(key)
    return {
        "key": key,
        "app": build["app_slug"],
        "title": titles.get(build["app_slug"], build["display_name"]),
        "name": name,
        "tag": tag,
        "variant": _clean_label(catalog.BUNDLES[build["bundles"][0]]["label"]),
        "pkg": build["pkg"],
        "icon": build["icon"],
        "arch": build["arch"],
        "category": CATEGORIES.get(build["app_slug"], DEFAULT_CATEGORY),
        "source": _source(build["apk_source"]),
        "bundles": [_bundle(bundle) for bundle in build["bundles"]],
    }


def _companion(key: str) -> dict:
    companion = catalog.COMPANIONS[key]
    return {
        "key": key,
        "url": f"https://github.com/{companion['owner']}/{companion['repo']}",
        "for": companion["for_builds"],
        "files": [variant["file"].replace(" ", ".") for variant in companion["variants"]],
    }


def build_payload() -> dict:
    titles = _app_titles()
    return {
        "repo": os.environ.get("GITHUB_REPOSITORY") or None,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builds": [_build(key, titles) for key in catalog.BUILDS],
        "companions": [_companion(key) for key in catalog.COMPANIONS],
    }


def main(output: str = DEFAULT_OUTPUT) -> None:
    payload = build_payload()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path} ({len(payload['builds'])} builds, {len(payload['companions'])} companions)")


if __name__ == "__main__":
    main(*sys.argv[1:2])
