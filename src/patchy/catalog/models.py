from typing import Literal, NotRequired, TypedDict


class ApkMirrorSource(TypedDict):
    type: Literal["apkmirror"]
    org: str
    slug: str
    release_slug: NotRequired[str]


class GithubAppSource(TypedDict):
    type: Literal["github"]
    owner: str
    repo: str
    asset_hint: NotRequired[str]
    tag_template: NotRequired[str]


ApkSource = ApkMirrorSource | GithubAppSource


class CliSource(TypedDict):
    owner: str
    repo: str


class BundleSource(TypedDict):
    owner: str
    repo: str
    label: str


class BuildConfig(TypedDict):
    key: str
    app_slug: str
    pkg: str
    display_name: str
    arch: str
    icon: str
    apk_source: ApkSource
    bundles: list[str]
    exclude: list[str]
    enable: list[str]
    options: dict[str, str | None]
    force_version: str | None
    force_build: str | None


class CompanionVariant(TypedDict):
    file: str
    suffix: str
    exclude: NotRequired[str]


class Companion(TypedDict):
    key: str
    owner: str
    repo: str
    for_builds: list[str]
    variants: list[CompanionVariant]
