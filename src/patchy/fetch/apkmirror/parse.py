import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin

import lxml.html

from ...core import log

DEFAULT_ARCH = "arm64-v8a"

_UNIVERSAL_ARCHS = ("universal", "evrensel", "noarch")
_ARCH_TOKEN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_BUILD_CODE_TOKEN = re.compile(r"(?<!\w)(?<!\d\.)(?<!\d,)(\d{3,})(?!\w)(?!\.\d)(?!,\d)")

PickBasis = Literal["target-build", "declared-build", "default"]

_TARGET_BUILD = 0
_DECLARED_BUILD = 1
_NO_BUILD_MATCH = 2

_BASIS_BY_TIER: dict[int, PickBasis] = {
    _TARGET_BUILD: "target-build",
    _DECLARED_BUILD: "declared-build",
    _NO_BUILD_MATCH: "default",
}


@dataclass(frozen=True)
class Variant:
    href: str
    build_codes: frozenset[int]
    arch: str
    min_android: str
    dpi: str
    is_bundle: bool
    row_text: str

    @property
    def build_code(self) -> int | None:
        return max(self.build_codes) if self.build_codes else None

    def describe(self, code: int | None = None) -> str:
        code = self.build_code if code is None else code
        return ", ".join(
            [
                f"build {code}" if code is not None else "build code not listed",
                self.arch or "no arch listed",
                self.min_android or "no minimum Android listed",
                self.dpi or "no dpi listed",
                "bundle" if self.is_bundle else "apk",
            ]
        )


@dataclass(frozen=True)
class Pick:
    variant: Variant
    basis: PickBasis
    matched_code: int | None
    listed: int
    eligible: int


def parse(html: str) -> lxml.html.HtmlElement | None:
    if not html:
        return None
    try:
        return lxml.html.fromstring(html)
    except Exception:
        return None


def abs_url(base: str, href: str | None) -> str | None:
    return urljoin(base, href) if href else None


def page_text(tree: lxml.html.HtmlElement | None, limit: int) -> str:
    if tree is None:
        return ""
    title = tree.findtext(".//title") or ""
    body = tree.find(".//body")
    body_text = " ".join(body.itertext())[:limit] if body is not None else ""
    return f"{title} {body_text}".lower()


def is_404_html(tree: lxml.html.HtmlElement | None) -> bool:
    content = page_text(tree, 300)
    if "404" not in content:
        return False
    return "whoops" in content or "could not be found" in content or "not be found" in content


def classes(el) -> list[str]:
    return list(getattr(el, "classes", None) or [])


def cell_text(cell) -> str:
    return (cell.text_content() or "").strip() if cell is not None else ""


def closest(el, tags: set[str]):
    node = el
    while node is not None:
        if node.tag in tags:
            return node
        node = node.getparent()
    return None


def variant_rows(tree: lxml.html.HtmlElement | None) -> list:
    if tree is None:
        return []
    rows = []
    for el in tree.iter():
        if "table-row" not in classes(el):
            continue
        ancestor = el.getparent()
        while ancestor is not None:
            if "variants-table" in classes(ancestor):
                rows.append(el)
                break
            ancestor = ancestor.getparent()
    return rows


def row_count(tree: lxml.html.HtmlElement | None) -> int:
    return len(variant_rows(tree))


def has_download_button(tree: lxml.html.HtmlElement | None) -> bool:
    if tree is None:
        return False
    return any("downloadButton" in classes(a) for a in tree.iter("a"))


def arch_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _cell_build_codes(cell) -> frozenset[int]:
    codes: set[int] = set()
    for fragment in cell.xpath(".//text()"):
        codes.update(int(token) for token in _BUILD_CODE_TOKEN.findall(str(fragment)))
    return frozenset(codes)


def _is_bundle_cell(cell) -> bool:
    for el in cell.iter():
        if "apkm-badge" not in classes(el):
            continue
        badge = cell_text(el).upper()
        if "BUNDLE" in badge or "PAKET" in badge:
            return True
    return False


def _variant_from_row(row) -> Variant | None:
    cells = [c for c in row.iterchildren() if "table-cell" in classes(c)]
    if len(cells) < 4:
        return None

    link = next((a for a in cells[0].iter("a") if "accent_color" in classes(a)), None)
    href = link.get("href") if link is not None else None
    if not href:
        return None

    return Variant(
        href=href,
        build_codes=_cell_build_codes(cells[0]),
        arch=cell_text(cells[1]).lower(),
        min_android=cell_text(cells[2]),
        dpi=cell_text(cells[3]).lower(),
        is_bundle=_is_bundle_cell(cells[0]),
        row_text=" ".join(cell_text(c) for c in cells),
    )


def parse_variants(tree: lxml.html.HtmlElement | None) -> list[Variant]:
    variants = (_variant_from_row(row) for row in variant_rows(tree))
    return [variant for variant in variants if variant is not None]


def _arch_allowed(arch_text: str, target_key: str) -> bool:
    text = arch_text.strip().lower()
    if not text:
        return True
    if any(word in text for word in _UNIVERSAL_ARCHS):
        return True
    return target_key in {arch_key(token) for token in _ARCH_TOKEN.findall(text)}


def _default_slot(variant: Variant) -> int:
    if variant.dpi == "" or "nodpi" in variant.dpi:
        slot = 0
    elif "anydpi" in variant.dpi:
        slot = 1
    else:
        slot = 2
    return slot + 3 if variant.is_bundle else slot


def _match_declared_build(
    variant: Variant, target_code: int | None, declared_codes: frozenset[int]
) -> tuple[int, int | None]:
    if target_code is not None and target_code in variant.build_codes:
        return _TARGET_BUILD, target_code
    shared = variant.build_codes & declared_codes
    if shared:
        return _DECLARED_BUILD, min(shared)
    return _NO_BUILD_MATCH, None


def select_variant(
    tree: lxml.html.HtmlElement | None,
    force_build: str | None,
    app_slug: str,
    *,
    arch: str = DEFAULT_ARCH,
    build_codes: Mapping[str, int] | None = None,
) -> Pick | None:
    variants = parse_variants(tree)
    target_key = arch_key(arch)
    declared = {arch_key(name): code for name, code in (build_codes or {}).items()}
    target_code = declared.get(target_key)
    declared_codes = frozenset(declared.values())
    pin = str(force_build) if force_build else ""

    best: tuple[tuple[int, int, int], Variant, int | None] | None = None
    eligible = 0

    for index, variant in enumerate(variants):
        if pin and pin not in variant.row_text:
            continue
        if app_slug == "instagram" and not variant.is_bundle:
            continue
        if not _arch_allowed(variant.arch, target_key):
            continue

        eligible += 1
        tier, matched = _match_declared_build(variant, target_code, declared_codes)
        rank = (tier, _default_slot(variant), index)
        if best is None or rank < best[0]:
            best = (rank, variant, matched)

    if best is None:
        return None

    (tier, _, _), variant, matched = best
    return Pick(
        variant=variant,
        basis=_BASIS_BY_TIER[tier],
        matched_code=matched,
        listed=len(variants),
        eligible=eligible,
    )


def extract_variant_url(
    tree: lxml.html.HtmlElement | None,
    force_build: str | None,
    app_slug: str,
    arch: str = DEFAULT_ARCH,
    build_codes: Mapping[str, int] | None = None,
) -> str | None:
    pick = select_variant(tree, force_build, app_slug, arch=arch, build_codes=build_codes)
    return pick.variant.href if pick is not None else None


def dump_variant_rows_for_debug(tree: lxml.html.HtmlElement | None) -> None:
    all_rows = [el for el in (tree.iter() if tree is not None else []) if "table-row" in classes(el)]
    scoped_rows = variant_rows(tree)

    log.info(
        f"Debug: page has {len(all_rows)} .table-row elements "
        f"({len(scoped_rows)} of them inside the real .variants-table), is404: {is_404_html(tree)}"
    )
    for i, row in enumerate(scoped_rows[:20]):
        cells = [c for c in row.iterchildren() if "table-cell" in classes(c)]
        name = cell_text(cells[0])[:60] if len(cells) > 0 else None
        arch = cell_text(cells[1]) if len(cells) > 1 else None
        android = cell_text(cells[2]) if len(cells) > 2 else None
        dpi = cell_text(cells[3]) if len(cells) > 3 else None
        codes = sorted(_cell_build_codes(cells[0])) if cells else []
        log.info(
            f"   [{i}] cells={len(cells)} name={name!r} arch={arch!r} android={android!r} dpi={dpi!r} codes={codes}"
        )


def find_listing_link(tree: lxml.html.HtmlElement, base_url: str, slug_part: str) -> str | None:
    for a in tree.iter("a"):
        href = a.get("href")
        if href and "-release/" in href and slug_part in href and "#" not in href:
            return abs_url(base_url, href)
    return None


def version_from_href(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"-(\d[\d]*(?:-\d+)+)-release", href)
    if not match:
        return None
    return match.group(1).replace("-", ".")


def listing_candidates(tree: lxml.html.HtmlElement, base_url: str) -> list[tuple[str, str]]:
    results = []
    for a in tree.iter("a"):
        href = a.get("href")
        if not href or "-release/" not in href:
            continue
        row = closest(a, {"div", "li", "tr"})
        if row is None:
            row = a.getparent() if a.getparent() is not None else a
        abs_href = abs_url(base_url, href)
        if abs_href:
            results.append((abs_href, row.text_content() or ""))
        if len(results) >= 60:
            break
    return results
