import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
ASSETS = SITE / "assets"
PAGES = ("index.html", "404.html")
BRAND_TURQUOISE = "#30d5c8"
BRAND_RED = "#e30a17"
ARC_TOKENS = ("--arc-dim", "--rim-opacity") + tuple(
    f"--arc-{tone}-{part}" for tone in "ab" for part in ("deep", "mid", "bright", "glow", "hot", "spec")
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _theme_block(stylesheet: str, theme: str) -> str:
    start = stylesheet.index(f':root[data-theme="{theme}"] {{')
    return stylesheet[start : stylesheet.index("\n}", start)]


def _media_block(stylesheet: str, query: str) -> str:
    start = stylesheet.index(f"@media ({query}) {{")
    return stylesheet[start : stylesheet.index("\n}", start)]


def _dictionary_keys(source: str, name: str) -> set[str]:
    start = source.index(f"const {name} = {{")
    end = source.index("\n};", start)
    return set(re.findall(r'^ {2}"?([\w.\-]+)"?:', source[start:end], re.MULTILINE))


def _policy(page: str) -> dict[str, str]:
    match = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', _read(SITE / page))
    assert match, f"{page} has no Content-Security-Policy"
    directives = {}
    for part in match.group(1).split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            directives[name] = value
    return directives


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def test_local_references_in_pages_resolve_to_files():
    for page in PAGES:
        for ref in re.findall(r'\b(?:href|src)="([^"]*)"', _read(SITE / page)):
            target = ref.replace("__SITE_URL__", "")
            if not target or target.startswith(("#", "http://", "https://", "data:", "mailto:")):
                continue
            relative = target.split("#")[0].split("?")[0].lstrip("/") or "index.html"
            assert (SITE / relative).is_file(), f"{page} points at missing {ref}"


def test_stylesheet_urls_resolve_to_files():
    for ref in re.findall(r'url\("?([^")]+)"?\)', _read(ASSETS / "style.css")):
        if ref.startswith(("data:", "#", "http")):
            continue
        assert (ASSETS / ref).is_file(), f"style.css points at missing {ref}"


def test_module_imports_resolve_to_files():
    for script in ASSETS.glob("*.js"):
        source = _read(script)
        for ref in re.findall(r'(?:from|import\()\s*"(\./[^"]+)"', source):
            assert (script.parent / ref).is_file(), f"{script.name} imports missing {ref}"


def test_pages_only_load_external_scripts():
    for page in PAGES:
        for attributes in re.findall(r"<script\b([^>]*)>", _read(SITE / page)):
            assert "src=" in attributes, f"{page} has an inline script"


def test_content_security_policy_forbids_inline_and_eval_scripts():
    for page in PAGES:
        policy = _policy(page)
        scripts = policy.get("script-src", policy.get("default-src", ""))
        assert "'unsafe-inline'" not in scripts
        assert "'unsafe-eval'" not in scripts


def test_site_url_placeholder_is_replaced_by_the_pages_workflow():
    workflow = _read(ROOT / ".github" / "workflows" / "pages.yml")

    assert "__SITE_URL__" in workflow
    for page in PAGES:
        assert "__SITE_URL__" in _read(SITE / page)


def test_dictionaries_cover_the_same_keys():
    source = _read(ASSETS / "i18n.js")

    assert _dictionary_keys(source, "tr") == _dictionary_keys(source, "en")


def test_every_translation_key_in_use_is_defined():
    known = _dictionary_keys(_read(ASSETS / "i18n.js"), "tr")
    html = _read(SITE / "index.html")
    scripts = "\n".join(_read(script) for script in ASSETS.glob("*.js") if script.name != "i18n.js")

    used = set(re.findall(r'data-i18n(?:-html)?="([\w.\-]+)"', html))
    for value in re.findall(r'data-i18n-attr="([^"]+)"', html):
        used |= {pair.split(":", 1)[1].strip() for pair in value.split(";") if ":" in pair}
    used |= set(re.findall(r'\bt\("([\w.\-]+)"', scripts))
    for key in re.findall(r'\bplural\("([\w.\-]+)"', scripts):
        used |= {f"{key}.one", f"{key}.other"}

    assert used
    assert not used - known, f"undefined translation keys: {sorted(used - known)}"


def test_vendored_library_ships_with_its_license_and_notice():
    notices = _read(SITE / "THIRD_PARTY_NOTICES.txt")

    assert (ASSETS / "vendor" / "glassy-liquid.min.js").is_file()
    assert (ASSETS / "vendor" / "LICENSE-glassy-liquid.txt").is_file()
    assert "glassy-liquid" in notices


def test_notice_names_the_commit_of_the_vendored_build():
    banner = _read(ASSETS / "vendor" / "glassy-liquid.min.js").splitlines()[0]
    short = re.search(r"\(([0-9a-f]{7,40})\)", banner)
    assert short, "vendored build has no commit in its banner"

    full = re.search(r"commit ([0-9a-f]{40})", _read(SITE / "THIRD_PARTY_NOTICES.txt"))

    assert full, "notice names no commit"
    assert full.group(1).startswith(short.group(1))


def test_glass_surfaces_and_world_are_wired_into_the_page():
    app = _read(ASSETS / "app.js")

    for module in ("glass.js", "perf.js", "world.js"):
        assert f'"./{module}"' in app, f"app.js does not load {module}"
    assert 'id="world"' in _read(SITE / "index.html")


def test_glass_surfaces_step_aside_for_accessibility_preferences():
    source = _read(ASSETS / "glass.js")

    for query in ("prefers-reduced-transparency: reduce", "prefers-contrast: more", "forced-colors: active"):
        assert query in source, f"glass.js ignores {query}"


def test_both_themes_define_every_light_arc_token():
    stylesheet = _read(ASSETS / "style.css")

    for theme in ("dark", "light"):
        block = _theme_block(stylesheet, theme)
        for token in ARC_TOKENS:
            assert f"{token}:" in block, f"{theme} theme has no {token}"


def test_world_draws_light_arcs_and_the_stylesheet_styles_them():
    script = _read(ASSETS / "world.js")
    stylesheet = _read(ASSETS / "style.css")

    for name in ('"arcs"', '"rims"', '"rim"', "arc arc-"):
        assert name in script, f"world.js never creates {name}"
    for selector in (".arcs,", ".rims {", ".rim {", ".arc {", ".arc-a {", ".arc-b {"):
        assert selector in stylesheet, f"style.css has no rule for {selector}"


def test_light_arcs_step_back_for_accessibility_preferences():
    stylesheet = _read(ASSETS / "style.css")

    for query in ("prefers-reduced-transparency: reduce", "prefers-contrast: more"):
        assert ".world" in _media_block(stylesheet, query), f"{query} leaves the scenery at full strength"
    hidden = _media_block(stylesheet, "forced-colors: active").split("display: none", 1)[0]
    assert ".world" in hidden


def test_palette_is_turquoise_and_turkish_red():
    stylesheet = _read(ASSETS / "style.css").lower()

    assert f"--turquoise: {BRAND_TURQUOISE}" in stylesheet
    assert f"--flag-red: {BRAND_RED}" in stylesheet
    assert BRAND_RED in _read(SITE / "favicon.svg").lower()
    assert BRAND_TURQUOISE in _read(SITE / "favicon.svg").lower()
    assert BRAND_RED in _read(SITE / "404.html").lower()


def test_share_image_and_touch_icon_have_their_expected_sizes():
    assert _png_size(ASSETS / "og.png") == (1200, 630)
    assert _png_size(SITE / "apple-touch-icon.png") == (180, 180)


def test_apps_grid_collapses_to_a_single_shrinkable_column_on_phones():
    stylesheet = _read(ASSETS / "style.css")
    block = re.search(r"@media \(max-width: 719px\) \{(.*?)\n\}", stylesheet, re.DOTALL)

    assert block, "phone breakpoint is missing"
    assert "grid-template-columns: minmax(0, 1fr)" in block.group(1)
