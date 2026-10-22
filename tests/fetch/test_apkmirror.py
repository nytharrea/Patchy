import pytest

from patchy.core.flaresolverr import Cleared
from patchy.fetch.apkmirror import ChallengeError, challenge, client
from patchy.fetch.apkmirror.parse import (
    arch_key,
    closest,
    extract_variant_url,
    is_404_html,
    listing_candidates,
    parse,
    parse_variants,
    select_variant,
    variant_rows,
    version_from_href,
)


def _row(name, arch, dpi, href, badge=None):
    badge_html = f'<span class="apkm-badge">{badge}</span>' if badge else ""
    return f"""
    <div class="table-row">
      <div class="table-cell">{badge_html}<a class="accent_color" href="{href}">{name}</a></div>
      <div class="table-cell">{arch}</div>
      <div class="table-cell">type</div>
      <div class="table-cell">{dpi}</div>
    </div>
    """


def test_extract_variant_url_prefers_non_bundle_nodpi():
    html = f"""<html><body><div class="variants-table">
        {_row("Foo 1.0 arm64-v8a", "arm64-v8a", "nodpi", "/normal-nodpi")}
        {_row("Foo 1.0 x86", "x86", "nodpi", "/wrong-arch")}
        {_row("Foo 1.0 Bundle", "arm64-v8a + armeabi-v7a", "nodpi", "/bundle-nodpi", badge="APK Bundle")}
    </div></body></html>"""
    assert extract_variant_url(parse(html), None, "youtube") == "/normal-nodpi"


def test_extract_variant_url_falls_back_to_anydpi_then_specific():
    html = f"""<html><body><div class="variants-table">
        {_row("Foo 1.0", "universal", "160-640dpi", "/specific-dpi")}
        {_row("Foo 1.0", "universal", "anydpi", "/anydpi")}
    </div></body></html>"""
    assert extract_variant_url(parse(html), None, "youtube") == "/anydpi"


def test_extract_variant_url_instagram_skips_non_bundle_rows():
    html = f"""<html><body><div class="variants-table">
        {_row("Instagram 1.0 arm64-v8a", "arm64-v8a", "nodpi", "/should-be-skipped")}
        {_row("Instagram 1.0 Bundle", "arm64-v8a + armeabi-v7a", "nodpi", "/insta-bundle", badge="APK Bundle")}
    </div></body></html>"""
    assert extract_variant_url(parse(html), None, "instagram") == "/insta-bundle"


def test_extract_variant_url_instagram_with_no_bundle_row_returns_none():
    html = f"""<html><body><div class="variants-table">
        {_row("Instagram 1.0 arm64-v8a", "arm64-v8a", "nodpi", "/no-bundle-here")}
    </div></body></html>"""
    assert extract_variant_url(parse(html), None, "instagram") is None


def test_extract_variant_url_respects_force_build():
    html = f"""<html><body><div class="variants-table">
        {_row("Foo build1234 arm64-v8a", "arm64-v8a", "nodpi", "/build1234")}
        {_row("Foo build5678 arm64-v8a", "arm64-v8a", "nodpi", "/build5678")}
    </div></body></html>"""
    assert extract_variant_url(parse(html), "build5678", "youtube") == "/build5678"


def test_extract_variant_url_force_build_matches_dpi_and_version_cells():
    html = f"""<html><body><div class="variants-table">
        {_row("Foo 1.0 475019269", "arm64-v8a", "480dpi", "/android9", badge="BUNDLE")}
        {_row("Foo 1.0 475019344", "arm64-v8a", "240-640dpi", "/android11", badge="BUNDLE")}
    </div></body></html>"""
    assert extract_variant_url(parse(html), "240-640dpi", "facebook") == "/android11"
    assert extract_variant_url(parse(html), "475019344", "facebook") == "/android11"
    assert extract_variant_url(parse(html), "999", "facebook") is None


FACEBOOK_RELEASE = "/apk/facebook-2/facebook/facebook-582-0-0-50-54-release/"

FACEBOOK_582_ROWS = [
    (2, "", 475417029, "October 8, 2026", "arm64-v8a", "Android 9.0+", "480-640dpi", "5"),
    (1, "", 475417031, "October 8, 2026", "arm64-v8a", "Android 11+", "480dpi", "7"),
    (1, "NEW", 475417032, "October 10, 2026", "x86", "Android 8.0+", "480dpi", "17"),
    (1, "NEW", 475417034, "October 10, 2026", "armeabi-v7a", "Android 8.0+", "480dpi", "16"),
    (1, "", 475417036, "October 8, 2026", "armeabi-v7a", "Android 11+", "320dpi", "11"),
    (1, "", 475417037, "October 8, 2026", "arm64-v8a", "Android 11+", "213-480dpi", "12"),
    (1, "", 475417038, "October 8, 2026", "x86", "Android 8.0+", "480dpi", "10"),
    (1, "", 475417040, "October 8, 2026", "armeabi-v7a", "Android 8.0+", "480dpi", "4"),
    (1, "NEW", 475417041, "October 10, 2026", "arm64-v8a", "Android 9.0+", "480dpi", "15"),
    (11, "", 475417043, "October 8, 2026", "arm64-v8a", "Android 11+", "480dpi", "9"),
    (1, "", 475417102, "October 8, 2026", "arm64-v8a", "Android 9.0+", "480dpi", "3"),
    (2, "", 475417104, "October 8, 2026", "arm64-v8a", "Android 11+", "320-640dpi", "13"),
    (1, "", 475417105, "October 8, 2026", "x86", "Android 8.0+", "480dpi", ""),
    (1, "", 475417126, "October 8, 2026", "armeabi-v7a", "Android 8.0+", "480dpi", "6"),
    (2, "", 475417127, "October 8, 2026", "arm64-v8a", "Android 9.0+", "480-640dpi", "2"),
    (1, "", 475417129, "October 8, 2026", "arm64-v8a", "Android 11+", "480-640dpi", "8"),
    (1, "", 475417131, "October 8, 2026", "x86_64", "Android 9.0+", "480dpi", "14"),
]

HUSHFACEBOOK_CODES = {"ARM64_V8A": 475417104, "ARMEABI_V7A": 475417036}


def _facebook_variant_href(number):
    suffix = f"-{number}" if number else ""
    return f"{FACEBOOK_RELEASE}facebook-582-0-0-50-54{suffix}-android-apk-download/"


def _facebook_row(badge_count, flag, code, date, arch, android, dpi, number):
    href = _facebook_variant_href(number)
    new_badge = '<span class="apkm-badge success">NEW</span>' if flag else ""
    return f"""
    <div class="table-row headerFont">
      <div class="table-cell rowheight addseparator expand pad dowrap">
        <span class="apkm-badge">BUNDLE</span><span class="apkm-badge">{badge_count}</span>
        <a class="accent_color" href="{href}">582.0.0.50.54</a>{new_badge}
        <div><span>S</span> <span>8a3c</span></div>
        <div>{code}</div>
        <div>{date}</div>
        <a href="{href}#comments">Comments</a>
      </div>
      <div class="table-cell rowheight addseparator expand pad dowrap">{arch}</div>
      <div class="table-cell rowheight addseparator expand pad">{android}</div>
      <div class="table-cell rowheight addseparator expand pad dowrap">{dpi}</div>
    </div>
    """


def _facebook_html(rows=None):
    body = "".join(_facebook_row(*row) for row in (FACEBOOK_582_ROWS if rows is None else rows))
    return f'<html><body><div class="variants-table">{body}</div></body></html>'


def _split(code, arch, dpi, href, android="Android 11+", badge="BUNDLE"):
    return f"""
    <div class="table-row">
      <div class="table-cell"><span class="apkm-badge">{badge}</span><a class="accent_color" href="{href}">1.0</a>
        <div>{code}</div></div>
      <div class="table-cell">{arch}</div>
      <div class="table-cell">{android}</div>
      <div class="table-cell">{dpi}</div>
    </div>
    """


def test_parse_variants_reads_every_column_of_the_real_facebook_table():
    variants = parse_variants(parse(_facebook_html()))

    assert len(variants) == 17
    declared = variants[11]
    assert declared.href == _facebook_variant_href("13")
    assert declared.build_code == 475417104
    assert declared.arch == "arm64-v8a"
    assert declared.min_android == "Android 11+"
    assert declared.dpi == "320-640dpi"
    assert declared.is_bundle is True


def test_parse_variants_does_not_mistake_badge_counts_or_the_dotted_version_for_a_build_code():
    variants = parse_variants(parse(_facebook_html([FACEBOOK_582_ROWS[11]])))

    assert 2 not in variants[0].build_codes
    assert 582 not in variants[0].build_codes
    assert 475417104 in variants[0].build_codes


def test_parse_variants_finds_a_build_code_that_shares_a_text_node_with_other_words():
    html = """<html><body><div class="variants-table">
        <div class="table-row">
          <div class="table-cell"><a class="accent_color" href="/a">Foo 1.0</a> Build 123456789 uploaded today</div>
          <div class="table-cell">arm64-v8a</div>
          <div class="table-cell">Android 8.0+</div>
          <div class="table-cell">nodpi</div>
        </div>
    </div></body></html>"""

    assert parse_variants(parse(html))[0].build_codes == frozenset({123456789})


def test_parse_variants_skips_rows_without_a_link_or_with_too_few_cells():
    html = """<html><body><div class="variants-table">
        <div class="table-row"><div class="table-cell">header</div></div>
        <div class="table-row">
          <div class="table-cell">no link</div><div class="table-cell">a</div>
          <div class="table-cell">b</div><div class="table-cell">c</div>
        </div>
        <div class="table-row">
          <div class="table-cell"><a class="accent_color">no href</a></div><div class="table-cell">a</div>
          <div class="table-cell">b</div><div class="table-cell">c</div>
        </div>
    </div></body></html>"""

    assert parse_variants(parse(html)) == []


def test_select_variant_picks_the_row_with_the_build_code_the_bundle_declares():
    pick = select_variant(parse(_facebook_html()), None, "facebook", build_codes=HUSHFACEBOOK_CODES)

    assert pick is not None
    assert pick.variant.href == _facebook_variant_href("13")
    assert pick.basis == "target-build"
    assert pick.matched_code == 475417104
    assert pick.listed == 17
    assert pick.eligible == 9


def test_select_variant_without_declared_codes_keeps_the_old_pick_that_failed_in_ci():
    pick = select_variant(parse(_facebook_html()), None, "facebook")

    assert pick is not None
    assert pick.variant.href == _facebook_variant_href("5")
    assert pick.basis == "default"
    assert pick.matched_code is None


def test_select_variant_follows_the_target_arch_of_the_build():
    pick = select_variant(
        parse(_facebook_html()), None, "facebook", arch="armeabi-v7a", build_codes=HUSHFACEBOOK_CODES
    )

    assert pick is not None
    assert pick.variant.href == _facebook_variant_href("11")
    assert pick.matched_code == 475417036


def test_select_variant_falls_back_to_the_default_pick_when_no_listed_build_is_declared():
    pick = select_variant(parse(_facebook_html()), None, "facebook", build_codes={"ARM64_V8A": 111111111})

    assert pick is not None
    assert pick.variant.href == _facebook_variant_href("5")
    assert pick.basis == "default"
    assert pick.matched_code is None


def test_select_variant_never_leaves_the_target_arch_even_for_a_declared_code():
    pick = select_variant(parse(_facebook_html()), None, "facebook", build_codes={"ARM64_V8A": 475417032})

    assert pick is not None
    assert pick.variant.arch == "arm64-v8a"
    assert pick.basis == "default"


def test_select_variant_ignores_a_declared_code_that_only_exists_for_another_arch_row():
    pick = select_variant(parse(_facebook_html()), None, "facebook", build_codes={"ARMEABI_V7A": 475417036})

    assert pick is not None
    assert pick.variant.arch == "arm64-v8a"
    assert pick.basis == "default"


def test_select_variant_accepts_a_code_declared_for_another_arch_on_a_multi_arch_row():
    html = f"""<html><body><div class="variants-table">
        {_split(555555, "arm64-v8a", "nodpi", "/arm64-only")}
        {_split(777777, "arm64-v8a + armeabi-v7a", "nodpi", "/both")}
    </div></body></html>"""
    codes = {"ARM64_V8A": 999999, "ARMEABI_V7A": 777777}

    pick = select_variant(parse(html), None, "foo", build_codes=codes)

    assert pick is not None
    assert pick.variant.href == "/both"
    assert pick.basis == "declared-build"
    assert pick.matched_code == 777777


def test_select_variant_prefers_the_target_arch_code_over_another_archs_code():
    html = f"""<html><body><div class="variants-table">
        {_split(777777, "arm64-v8a + armeabi-v7a", "nodpi", "/both")}
        {_split(555555, "arm64-v8a", "nodpi", "/arm64-only")}
    </div></body></html>"""
    codes = {"ARM64_V8A": 555555, "ARMEABI_V7A": 777777}

    pick = select_variant(parse(html), None, "foo", build_codes=codes)

    assert pick is not None
    assert pick.variant.href == "/arm64-only"
    assert pick.basis == "target-build"


def test_select_variant_lets_force_build_narrow_the_rows_before_the_declared_code_decides():
    pick = select_variant(
        parse(_facebook_html()), "Android 9.0+", "facebook", build_codes={"ARM64_V8A": 475417104}
    )

    assert pick is not None
    assert pick.variant.min_android == "Android 9.0+"
    assert pick.variant.href == _facebook_variant_href("5")
    assert pick.basis == "default"


def test_select_variant_uses_the_declared_code_among_the_rows_a_force_build_keeps():
    pick = select_variant(parse(_facebook_html()), "Android 11+", "facebook", build_codes={"ARM64_V8A": 475417104})

    assert pick is not None
    assert pick.variant.href == _facebook_variant_href("13")
    assert pick.basis == "target-build"


def test_select_variant_returns_none_when_no_row_fits_the_arch():
    html = f"""<html><body><div class="variants-table">
        {_split(1000001, "x86", "nodpi", "/x86")}
        {_split(1000002, "x86_64", "nodpi", "/x86_64")}
    </div></body></html>"""

    assert select_variant(parse(html), None, "foo") is None
    assert select_variant(parse(html), None, "foo", arch="x86_64") is not None


def test_select_variant_keeps_the_default_dpi_order_between_rows_with_the_same_build_code():
    html = f"""<html><body><div class="variants-table">
        {_split(424242, "arm64-v8a", "480dpi", "/specific", badge="APK")}
        {_split(424242, "arm64-v8a", "nodpi", "/nodpi", badge="APK")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "foo", build_codes={"ARM64_V8A": 424242})

    assert pick is not None
    assert pick.variant.href == "/nodpi"


def test_select_variant_accepts_the_arch_spellings_apkmirror_uses():
    html = f"""<html><body><div class="variants-table">
        {_split(1, "armeabi-v7a", "nodpi", "/v7")}
        {_split(2, "x86_64", "nodpi", "/x86_64")}
        {_split(3, "arm64-v8a (64-bit)", "nodpi", "/annotated")}
        {_split(4, "armeabi-v7a arm64-v8a x86", "nodpi", "/spaced")}
    </div></body></html>"""

    assert extract_variant_url(parse(html), None, "foo") == "/annotated"
    assert extract_variant_url(parse(html), None, "foo", arch="x86_64") == "/x86_64"
    assert extract_variant_url(parse(html), None, "foo", arch="x86") == "/spaced"
    assert extract_variant_url(parse(html), None, "foo", arch="ARMEABI_V7A") == "/v7"


@pytest.mark.parametrize("arch", ["universal", "noarch", "evrensel", "Universal", ""])
def test_select_variant_treats_universal_rows_as_fitting_any_arch(arch):
    html = f"""<html><body><div class="variants-table">
        {_split(1, arch, "nodpi", "/any")}
    </div></body></html>"""

    assert extract_variant_url(parse(html), None, "foo", arch="armeabi-v7a") == "/any"


def test_extract_variant_url_forwards_the_arch_and_the_declared_build_codes():
    tree = parse(_facebook_html())

    positional = extract_variant_url(tree, None, "facebook", "arm64-v8a", HUSHFACEBOOK_CODES)
    keyword = extract_variant_url(tree, None, "facebook", arch="armeabi-v7a", build_codes=HUSHFACEBOOK_CODES)

    assert positional == _facebook_variant_href("13")
    assert keyword == _facebook_variant_href("11")


def test_extract_variant_url_instagram_still_requires_a_bundle_when_a_code_is_declared():
    html = f"""<html><body><div class="variants-table">
        {_split(385611438, "arm64-v8a", "nodpi", "/plain-apk", badge="APK")}
        {_split(385611439, "arm64-v8a", "nodpi", "/bundle")}
    </div></body></html>"""

    assert extract_variant_url(parse(html), None, "instagram", build_codes={"ARM64_V8A": 385611438}) == "/bundle"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ARM64_V8A", "arm64v8a"),
        ("arm64-v8a", "arm64v8a"),
        ("ARMEABI_V7A", "armeabiv7a"),
        ("X86_64", "x8664"),
        ("x86_64", "x8664"),
        ("x86", "x86"),
    ],
)
def test_arch_key_makes_cli_names_and_apkmirror_names_comparable(raw, expected):
    assert arch_key(raw) == expected


def test_arch_key_keeps_x86_and_x86_64_apart():
    assert arch_key("x86") != arch_key("X86_64")


def test_variant_describe_lists_what_a_person_needs_to_judge_the_pick():
    pick = select_variant(parse(_facebook_html()), None, "facebook", build_codes=HUSHFACEBOOK_CODES)

    assert pick is not None
    assert pick.variant.describe() == "build 475417104, arm64-v8a, Android 11+, 320-640dpi, bundle"
    assert pick.variant.describe(1500) == "build 1500, arm64-v8a, Android 11+, 320-640dpi, bundle"


def test_variant_rows_ignores_rows_outside_variants_table():
    html = """<html><body>
        <div class="table-row">not scoped, should be ignored</div>
        <div class="variants-table"><div class="table-row">scoped</div></div>
    </body></html>"""
    rows = variant_rows(parse(html))
    assert len(rows) == 1
    assert rows[0].text_content().strip() == "scoped"


def test_is_404_html_detects_apkmirror_not_found_page():
    html = "<html><head><title>404 - Whoops! That page can&#8217;t be found.</title></head><body></body></html>"
    assert is_404_html(parse(html)) is True


def test_is_404_html_false_for_normal_page():
    html = "<html><head><title>YouTube 19.35.36</title></head><body>Download options</body></html>"
    assert is_404_html(parse(html)) is False


def test_looks_like_challenge_detects_cloudflare_interstitial():
    html = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
    assert challenge.looks_like_challenge(html) is True


def test_looks_like_challenge_false_for_normal_page():
    assert challenge.looks_like_challenge("<html><body>Normal content</body></html>") is False


def test_version_from_href_extracts_dotted_version():
    href = "/apk/google-inc/youtube/youtube-19-35-36-release/"
    assert version_from_href(href) == "19.35.36"


def test_version_from_href_returns_none_without_match():
    assert version_from_href("/apk/google-inc/youtube/") is None


def test_listing_candidates_resolves_relative_hrefs():
    html = """<html><body>
        <div><a href="/apk/google-inc/youtube/youtube-19-35-36-release/">YouTube 19.35.36</a></div>
    </body></html>"""
    candidates = listing_candidates(parse(html), "https://www.apkmirror.com/apk/google-inc/youtube/")
    assert candidates == [
        ("https://www.apkmirror.com/apk/google-inc/youtube/youtube-19-35-36-release/", "YouTube 19.35.36")
    ]


async def test_get_latest_listing_picks_the_highest_version_not_the_first_candidate(monkeypatch):
    html = """<html><body>
        <div><a href="/apk/instagram/instagram/instagram-1-1-1-release/instagram-1-1-1-android-apk-download/">Instagram 1.1.1</a></div>
        <div><a href="/apk/instagram/instagram/instagram-439-0-0-37-89-release/instagram-439-0-0-37-89-android-apk-download/">Instagram 439.0.0.37.89</a></div>
    </body></html>"""

    async def fake_fetch(url, label, **kwargs):
        return Cleared(url=url, status=200, html=html, user_agent="", cookies=[])

    monkeypatch.setattr(client, "_fetch", fake_fetch)

    result = await client.get_latest_listing("instagram", {"org": "instagram", "slug": "instagram"})

    assert result["version"] == "439.0.0.37.89"


async def test_get_latest_listing_ignores_a_different_apps_release_link(monkeypatch):
    html = """<html><body>
        <div><a href="/apk/some-dev/similar-app/similar-app-99-0-release/">Similar App 99.0</a></div>
        <div><a href="/apk/acme-inc/acme-app/acme-app-1-2-3-release/">Acme App 1.2.3</a></div>
    </body></html>"""

    async def fake_fetch(url, label, **kwargs):
        return Cleared(url=url, status=200, html=html, user_agent="", cookies=[])

    monkeypatch.setattr(client, "_fetch", fake_fetch)

    result = await client.get_latest_listing("acme-app", {"org": "acme-inc", "slug": "acme-app"})

    assert result["version"] == "1.2.3"


async def test_get_latest_listing_falls_back_to_any_candidate_when_none_match_the_app(monkeypatch):
    html = """<html><body>
        <div><a href="/apk/some-dev/other-app-a/other-app-a-1-0-release/">Other App A 1.0</a></div>
        <div><a href="/apk/some-dev/other-app-b/other-app-b-2-0-release/">Other App B 2.0</a></div>
    </body></html>"""

    async def fake_fetch(url, label, **kwargs):
        return Cleared(url=url, status=200, html=html, user_agent="", cookies=[])

    monkeypatch.setattr(client, "_fetch", fake_fetch)

    result = await client.get_latest_listing("acme-app", {"org": "acme-inc", "slug": "acme-app"})

    assert result is not None
    assert result["version"] == "2.0"


def test_closest_walks_up_to_matching_ancestor():
    html = '<html><body><tr><td><a href="#">link</a></td></tr></body></html>'
    a = parse(html).find(".//a")
    assert closest(a, {"div", "li", "tr"}).tag == "tr"


def test_closest_returns_none_when_no_ancestor_matches():
    html = '<html><body><span><a href="#">link</a></span></body></html>'
    a = parse(html).find(".//a")
    assert closest(a, {"div", "li", "tr"}) is None


CHALLENGE_HTML = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"


async def _no_cooldown():
    return None


def _patch_challenge_environment(monkeypatch, tmp_path, fake_get):
    monkeypatch.setattr(client.flaresolverr, "get", fake_get)
    monkeypatch.setattr(client, "register_challenge", lambda: 0.0)
    monkeypatch.setattr(client, "apply_global_cooldown", _no_cooldown)
    monkeypatch.setattr(client.paths, "build_dir", lambda: tmp_path)


async def test_fetch_raises_challenge_error_when_cloudflare_never_clears(monkeypatch, tmp_path):
    calls = []

    async def fake_get(url):
        calls.append(url)
        return Cleared(url=url, status=200, html=CHALLENGE_HTML, user_agent="", cookies=[])

    _patch_challenge_environment(monkeypatch, tmp_path, fake_get)

    with pytest.raises(ChallengeError, match="Cloudflare challenge could not be cleared"):
        await client._fetch("https://www.apkmirror.com/apk/x/", label="unit-test")

    assert len(calls) == 4


async def test_fetch_saves_the_challenge_page_for_diagnosis(monkeypatch, tmp_path):
    async def fake_get(url):
        return Cleared(url=url, status=403, html=CHALLENGE_HTML, user_agent="", cookies=[])

    _patch_challenge_environment(monkeypatch, tmp_path, fake_get)

    with pytest.raises(ChallengeError, match="HTTP 403"):
        await client._fetch("https://www.apkmirror.com/apk/x/", label="unit-test")

    saved = list((tmp_path / "diagnostics").glob("cloudflare-unit-test-*.html"))
    assert len(saved) == 1


async def test_fetch_returns_a_404_page_without_treating_it_as_a_challenge(monkeypatch, tmp_path):
    async def fake_get(url):
        return Cleared(url=url, status=404, html="<html>missing</html>", user_agent="", cookies=[])

    _patch_challenge_environment(monkeypatch, tmp_path, fake_get)

    cleared = await client._fetch("https://www.apkmirror.com/apk/x/", label="unit-test")
    assert cleared.status == 404


async def test_fetch_recovers_when_the_challenge_clears_on_a_later_attempt(monkeypatch, tmp_path):
    responses = [CHALLENGE_HTML, "<html><body>Real content</body></html>"]

    async def fake_get(url):
        return Cleared(url=url, status=200, html=responses.pop(0), user_agent="", cookies=[])

    _patch_challenge_environment(monkeypatch, tmp_path, fake_get)

    cleared = await client._fetch("https://www.apkmirror.com/apk/x/", label="unit-test")
    assert "Real content" in cleared.html


async def test_page_exists_lets_a_challenge_error_through(monkeypatch):
    async def fake_fetch(url, label, **kwargs):
        raise ChallengeError("walled")

    monkeypatch.setattr(client, "_fetch", fake_fetch)

    with pytest.raises(ChallengeError):
        await client._page_exists("https://www.apkmirror.com/apk/x/")


async def test_page_exists_is_false_for_other_errors(monkeypatch):
    async def fake_fetch(url, label, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(client, "_fetch", fake_fetch)

    assert await client._page_exists("https://www.apkmirror.com/apk/x/") is False


async def test_resolve_list_url_surfaces_the_challenge_instead_of_pretending_the_page_is_missing(monkeypatch):
    async def fake_fetch(url, label, **kwargs):
        raise ChallengeError("walled")

    monkeypatch.setattr(client, "_fetch", fake_fetch)

    with pytest.raises(ChallengeError):
        await client._resolve_list_url({"org": "acme-inc", "slug": "acme-app"}, "1.2.3")


async def test_resolve_list_url_raises_release_not_found_when_apkmirror_has_no_page_for_the_version(
    monkeypatch, tmp_path
):
    async def fake_fetch(url, label, **kwargs):
        return Cleared(
            url=url, status=200, html="<html><body>nothing here</body></html>", user_agent="", cookies=[]
        )

    monkeypatch.setattr(client, "_fetch", fake_fetch)
    monkeypatch.setattr(client.paths, "diagnostics_dir", lambda: tmp_path / "diagnostics")

    with pytest.raises(client.ReleaseNotFound, match="No APKMirror release page found for version 1.2338"):
        await client._resolve_list_url({"org": "acme-inc", "slug": "acme-app"}, "1.2338")


async def test_resolve_list_url_does_not_report_an_exhausted_budget_as_a_missing_release(monkeypatch):
    monkeypatch.setattr(client, "RESOLVE_BUDGET_SECONDS", -1.0)

    with pytest.raises(RuntimeError, match="Giving up") as exc_info:
        await client._resolve_list_url({"org": "acme-inc", "slug": "acme-app"}, "1.2338")

    assert not isinstance(exc_info.value, client.ReleaseNotFound)


FACEBOOK_SITE = {"org": "facebook-2", "slug": "facebook"}
FACEBOOK_LIST_URL = f"https://www.apkmirror.com{FACEBOOK_RELEASE}"


async def _download_facebook(monkeypatch, tmp_path, page=None, **kwargs):
    fetched = []
    warnings = []

    async def fake_resolve_list_url(site, version):
        return FACEBOOK_LIST_URL, False

    async def fake_fetch(url, label, **fetch_kwargs):
        fetched.append((label, url))
        list_page = _facebook_html() if page is None else page
        html = list_page if label == "list-page" else "<html><body>variant page</body></html>"
        return Cleared(url=url, status=200, html=html, user_agent="", cookies=[])

    async def fake_resolve_download_url(variant_url, variant_cleared):
        return "https://www.apkmirror.com/file", variant_cleared

    async def fake_download_file(url, cleared, out_dir, fallback_name):
        path = out_dir / "facebook.apkm"
        path.write_bytes(b"x" * 2048)
        return path

    monkeypatch.setattr(client, "_resolve_list_url", fake_resolve_list_url)
    monkeypatch.setattr(client, "_fetch", fake_fetch)
    monkeypatch.setattr(client, "_resolve_download_url", fake_resolve_download_url)
    monkeypatch.setattr(client.flaresolverr, "download_file", fake_download_file)
    monkeypatch.setattr(client.paths, "downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(client.paths, "diagnostics_dir", lambda: tmp_path / "diagnostics")
    monkeypatch.setattr(client.log, "warn", warnings.append)

    await client.download_apk("582.0.0.50.54", "facebook", FACEBOOK_SITE, **kwargs)
    return fetched, warnings


def _variant_page_fetched(fetched):
    return [url for label, url in fetched if label == "variant-page"]


async def test_download_apk_opens_the_variant_page_of_the_build_the_bundle_declares(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(
        monkeypatch, tmp_path, arch="arm64-v8a", build_codes=HUSHFACEBOOK_CODES
    )

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('13')}"]
    assert warnings == []
    assert not (tmp_path / "diagnostics").exists()


async def test_download_apk_without_declared_codes_still_takes_the_default_variant(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(monkeypatch, tmp_path)

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('5')}"]
    assert warnings == []


async def test_download_apk_warns_when_none_of_the_declared_builds_is_listed(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(monkeypatch, tmp_path, build_codes={"ARM64_V8A": 111111111})

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('5')}"]
    assert len(warnings) == 1
    assert "ARM64_V8A=111111111" in warnings[0]
    assert "arm64-v8a" in warnings[0]
    assert len(list((tmp_path / "diagnostics").glob("no-declared-build-facebook-*.html"))) == 1


async def test_download_apk_follows_the_arch_it_is_given(monkeypatch, tmp_path):
    fetched, _ = await _download_facebook(
        monkeypatch, tmp_path, arch="armeabi-v7a", build_codes=HUSHFACEBOOK_CODES
    )

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('11')}"]


async def test_download_apk_force_build_still_overrides_the_declared_build(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(
        monkeypatch, tmp_path, force_build="475417102", build_codes=HUSHFACEBOOK_CODES
    )

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('3')}"]
    assert len(warnings) == 1
    assert "force_build" in warnings[0]
    assert not (tmp_path / "diagnostics").exists()


async def test_download_apk_opens_the_bundle_page_when_the_build_asks_for_a_bundle(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(
        monkeypatch, tmp_path, _plain_and_bundle_html(), file_type="bundle"
    )

    assert _variant_page_fetched(fetched) == ["https://www.apkmirror.com/bundle"]
    assert warnings == []


async def test_download_apk_opens_the_plain_apk_page_when_the_build_does_not_ask_for_a_type(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(monkeypatch, tmp_path, _plain_and_bundle_html())

    assert _variant_page_fetched(fetched) == ["https://www.apkmirror.com/plain"]
    assert warnings == []


async def test_download_apk_warns_when_the_picked_build_is_not_of_the_asked_type(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(
        monkeypatch, tmp_path, build_codes=HUSHFACEBOOK_CODES, file_type="apk"
    )

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('13')}"]
    assert len(warnings) == 1
    assert 'apk_type is "apk"' in warnings[0]
    assert "a bundle" in warnings[0]


async def test_download_apk_does_not_warn_when_the_picked_build_is_of_the_asked_type(monkeypatch, tmp_path):
    _, warnings = await _download_facebook(
        monkeypatch, tmp_path, build_codes=HUSHFACEBOOK_CODES, file_type="bundle"
    )

    assert warnings == []


DISCORD_SITE = {"org": "discord", "slug": "discord-chat-for-gamers", "release_slug": "discord-talk-play-hang-out"}
DISCORD_VERSION = "348.10 - Stable"
DISCORD_CODES = {"ARM64_V8A": 348010, "ARMEABI_V7A": 348010, "X86_64": 348010, "X86": 348010}
DISCORD_FOLDER = "/apk/discord/discord-chat-for-gamers/"
DISCORD_RELEASE = f"{DISCORD_FOLDER}discord-talk-play-hang-out-348-10-stable-release/"
DISCORD_VARIANT = f"{DISCORD_RELEASE}discord-talk-play-hang-out-348-10-stable-android-apk-download/"
DISCORD_RELEASE_URL = f"https://www.apkmirror.com{DISCORD_RELEASE}"
DISCORD_VARIANT_URL = f"https://www.apkmirror.com{DISCORD_VARIANT}"
DISCORD_LISTING_URL = f"https://www.apkmirror.com{DISCORD_FOLDER}"


def _discord_table():
    return f"""<html><body><div class="table topmargin variants-table">
        <div class="table-row headerFont">
          <div class="table-cell rowheight addseparator expand variant-min-width pad">Variant</div>
          <div class="table-cell rowheight addseparator expand pad">Architecture</div>
          <div class="table-cell rowheight addseparator expand pad">Minimum Version</div>
          <div class="table-cell rowheight addseparator expand pad">Screen DPI</div>
        </div>
        <div class="table-row headerFont">
          <div class="table-cell rowheight addseparator expand pad dowrap-break-all">
            <a class="accent_color" href="{DISCORD_VARIANT}">
              <svg class="icon tag-icon"><use xlink:href="#apkm-icon-tag"></use></svg>
              348.10 - Stable</a>
            <span class="apkm-badge success" data-apkm-tooltip="APK bundle with base APK and 32 splits">BUNDLE</span>
            <span class="apkm-badge success" data-apkm-tooltip="32 splits">32 S</span>
            <span class="bubble p-static inlineBlock"><a href="{DISCORD_VARIANT}#disqus_thread"></a></span>
            <br><span class="colorLightBlack">348010</span>
            <br><span class="colorLightBlack wrapText"><span class="dateyear_utc">October 6, 2026 GMT+0300</span></span>
          </div>
          <div class="table-cell rowheight addseparator expand pad dowrap">universal</div>
          <div class="table-cell rowheight addseparator expand pad dowrap">Android 7.0+</div>
          <div class="table-cell rowheight addseparator expand pad dowrap">120-640dpi</div>
        </div>
    </div></body></html>"""


def _discord_listing():
    releases = [
        ("350-3-alpha", "350.3 - Alpha"),
        ("349-8-beta", "349.8 - Beta"),
        ("348-10-beta", "348.10 - Beta"),
        ("348-10-stable", "348.10 - Stable"),
        ("347-12-stable", "347.12 - Stable"),
    ]
    rows = "".join(
        f'<div class="appRow"><a class="fontBlack" href="{DISCORD_FOLDER}discord-talk-play-hang-out-{slug}-release/">'
        f"Talk, Play, Hang Out {title}</a></div>"
        for slug, title in releases
    )
    return f"<html><body>{rows}</body></html>"


def _serve_pages(monkeypatch, pages):
    requested = []

    async def fake_fetch(url, label, **kwargs):
        requested.append((label, url))
        found = url in pages
        html = pages[url] if found else "<html><body>404 Whoops! The page could not be found</body></html>"
        return Cleared(url=url, status=200 if found else 404, html=html, user_agent="", cookies=[])

    monkeypatch.setattr(client, "_fetch", fake_fetch)
    return requested


def test_parse_variants_reads_the_universal_bundle_row_of_a_discord_release():
    variants = parse_variants(parse(_discord_table()))

    assert len(variants) == 1
    variant = variants[0]
    assert variant.href == DISCORD_VARIANT
    assert variant.arch == "universal"
    assert variant.min_android == "Android 7.0+"
    assert variant.dpi == "120-640dpi"
    assert variant.is_bundle is True
    assert 348010 in variant.build_codes


def test_select_variant_takes_the_universal_discord_bundle_by_the_build_code_the_patches_declare():
    pick = select_variant(parse(_discord_table()), None, "discord", build_codes=DISCORD_CODES)

    assert pick is not None
    assert pick.variant.href == DISCORD_VARIANT
    assert pick.basis == "target-build"
    assert pick.matched_code == 348010


async def test_resolve_list_url_builds_the_discord_release_slug_from_a_version_with_a_channel(monkeypatch):
    requested = _serve_pages(monkeypatch, {DISCORD_RELEASE_URL: _discord_table()})

    assert await client._resolve_list_url(DISCORD_SITE, DISCORD_VERSION) == (DISCORD_RELEASE_URL, False)
    assert requested == [("direct-try", DISCORD_RELEASE_URL)]


async def test_resolve_list_url_falls_back_to_the_single_discord_variant_page(monkeypatch):
    variant_page = (
        '<html><body><a class="downloadButton" href="/download/?key=1">Download APK Bundle</a></body></html>'
    )
    _serve_pages(monkeypatch, {DISCORD_VARIANT_URL: variant_page})

    assert await client._resolve_list_url(DISCORD_SITE, DISCORD_VERSION) == (DISCORD_VARIANT_URL, True)


async def test_resolve_list_url_finds_the_discord_release_in_the_app_listing(monkeypatch):
    _serve_pages(monkeypatch, {DISCORD_LISTING_URL: _discord_listing()})

    assert await client._resolve_list_url(DISCORD_SITE, DISCORD_VERSION) == (DISCORD_RELEASE_URL, False)


async def test_download_apk_opens_the_variant_page_of_the_discord_bundle(monkeypatch, tmp_path):
    requested = _serve_pages(
        monkeypatch,
        {
            DISCORD_RELEASE_URL: _discord_table(),
            DISCORD_VARIANT_URL: "<html><body>variant page</body></html>",
        },
    )
    downloads = []

    async def fake_resolve_download_url(variant_url, variant_cleared):
        return "https://www.apkmirror.com/file", variant_cleared

    async def fake_download_file(url, cleared, out_dir, fallback_name):
        downloads.append((url, fallback_name))
        path = out_dir / "discord.apkm"
        path.write_bytes(b"x" * 2048)
        return path

    monkeypatch.setattr(client, "_resolve_download_url", fake_resolve_download_url)
    monkeypatch.setattr(client.flaresolverr, "download_file", fake_download_file)
    monkeypatch.setattr(client.paths, "downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(client.paths, "diagnostics_dir", lambda: tmp_path / "diagnostics")

    path = await client.download_apk(
        DISCORD_VERSION, "discord", DISCORD_SITE, arch="arm64-v8a", build_codes=DISCORD_CODES
    )

    assert path == str(tmp_path / "discord.apkm")
    assert [url for label, url in requested if label == "variant-page"] == [DISCORD_VARIANT_URL]
    assert downloads == [("https://www.apkmirror.com/file", "discord.apk")]
    assert not (tmp_path / "diagnostics").exists()


MESSENGER_ACCEPTED = frozenset({346611351, 346611369, 346611423, 346611438, 346611439, 346611440})


def _messenger_html():
    return f"""<html><body><div class="variants-table">
        {_split(346611418, "arm64-v8a", "nodpi", "/unsupported", android="Android 9.0+", badge="APK")}
        {_split(346611351, "arm64-v8a", "213-240dpi", "/dpi", android="Android 9.0+", badge="APK")}
        {_split(346611369, "arm64-v8a", "nodpi", "/base", android="Android 9.0+", badge="APK")}
        {_split(346611423, "armeabi-v7a", "nodpi", "/v7a", android="Android 9.0+", badge="APK")}
    </div></body></html>"""


def test_select_variant_takes_the_first_nodpi_apk_when_nothing_tells_which_build_the_patch_wants():
    pick = select_variant(parse(_messenger_html()), None, "messenger")

    assert pick is not None
    assert pick.variant.href == "/unsupported"
    assert pick.basis == "default"


def test_select_variant_picks_a_row_with_a_build_code_the_patch_accepts():
    pick = select_variant(parse(_messenger_html()), None, "messenger", accepted_codes=MESSENGER_ACCEPTED)

    assert pick is not None
    assert pick.variant.href == "/base"
    assert pick.basis == "accepted-build"
    assert pick.matched_code == 346611369


def test_select_variant_prefers_an_accepted_code_over_the_one_the_bundle_declares():
    pick = select_variant(
        parse(_messenger_html()),
        None,
        "messenger",
        build_codes={"ARM64_V8A": 346611418},
        accepted_codes=MESSENGER_ACCEPTED,
    )

    assert pick is not None
    assert pick.variant.href == "/base"
    assert pick.basis == "accepted-build"


def test_select_variant_never_leaves_the_target_arch_for_an_accepted_code():
    html = f"""<html><body><div class="variants-table">
        {_split(346611418, "arm64-v8a", "nodpi", "/unsupported", badge="APK")}
        {_split(346611423, "armeabi-v7a", "nodpi", "/v7a", badge="APK")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "messenger", accepted_codes=MESSENGER_ACCEPTED)

    assert pick is not None
    assert pick.variant.href == "/unsupported"
    assert pick.basis == "default"


def test_select_variant_lets_force_build_narrow_the_rows_before_an_accepted_code_decides():
    pick = select_variant(parse(_messenger_html()), "213-240dpi", "messenger", accepted_codes=MESSENGER_ACCEPTED)

    assert pick is not None
    assert pick.variant.href == "/dpi"
    assert pick.basis == "accepted-build"
    assert pick.matched_code == 346611351


def test_select_variant_treats_empty_accepted_codes_like_none():
    html = _messenger_html()

    assert select_variant(parse(html), None, "messenger", accepted_codes=[]) == select_variant(
        parse(html), None, "messenger"
    )


def _plain_and_bundle_html(*, plain_code=5001, bundle_code=5001, plain_dpi="nodpi", bundle_dpi="nodpi"):
    return f"""<html><body><div class="variants-table">
        {_split(plain_code, "arm64-v8a", plain_dpi, "/plain", badge="APK")}
        {_split(bundle_code, "arm64-v8a", bundle_dpi, "/bundle", badge="BUNDLE")}
    </div></body></html>"""


def test_select_variant_prefers_a_plain_apk_over_a_bundle_when_the_build_does_not_say():
    pick = select_variant(parse(_plain_and_bundle_html()), None, "proton-vpn")

    assert pick is not None
    assert pick.variant.href == "/plain"
    assert pick.file_type_matched is True


def test_select_variant_takes_the_bundle_when_the_build_asks_for_a_bundle():
    pick = select_variant(parse(_plain_and_bundle_html()), None, "proton-vpn", file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/bundle"
    assert pick.file_type_matched is True


def test_select_variant_takes_the_plain_apk_when_the_build_asks_for_a_plain_apk():
    html = f"""<html><body><div class="variants-table">
        {_split(5001, "arm64-v8a", "nodpi", "/bundle", badge="BUNDLE")}
        {_split(5001, "arm64-v8a", "nodpi", "/plain", badge="APK")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "foo", file_type="apk")

    assert pick is not None
    assert pick.variant.href == "/plain"
    assert pick.file_type_matched is True


def test_select_variant_takes_the_bundle_over_a_better_dpi_slot_when_the_build_asks_for_a_bundle():
    html = _plain_and_bundle_html(bundle_dpi="240-640dpi")

    pick = select_variant(parse(html), None, "proton-vpn", file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/bundle"


def test_select_variant_keeps_the_dpi_order_among_the_rows_of_the_asked_type():
    html = f"""<html><body><div class="variants-table">
        {_split(5001, "arm64-v8a", "240-640dpi", "/bundle-dpi", badge="BUNDLE")}
        {_split(5001, "arm64-v8a", "nodpi", "/bundle-nodpi", badge="BUNDLE")}
        {_split(5001, "arm64-v8a", "nodpi", "/plain", badge="APK")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "proton-vpn", file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/bundle-nodpi"


def test_select_variant_lets_the_build_code_decide_before_the_asked_type():
    html = _plain_and_bundle_html(plain_code=6002, bundle_code=5001)

    pick = select_variant(parse(html), None, "foo", build_codes={"ARM64_V8A": 6002}, file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/plain"
    assert pick.basis == "target-build"
    assert pick.file_type_matched is False


def test_select_variant_takes_the_bundle_that_has_the_build_code_the_patch_declares():
    html = f"""<html><body><div class="variants-table">
        {_split(5001, "arm64-v8a", "nodpi", "/bundle-old", badge="BUNDLE")}
        {_split(5002, "arm64-v8a", "nodpi", "/bundle-new", badge="BUNDLE")}
        {_split(5002, "arm64-v8a", "nodpi", "/plain-new", badge="APK")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "foo", build_codes={"ARM64_V8A": 5002}, file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/bundle-new"
    assert pick.basis == "target-build"
    assert pick.file_type_matched is True


def test_select_variant_keeps_the_asked_type_among_the_builds_the_patch_accepts():
    pick = select_variant(parse(_plain_and_bundle_html()), None, "foo", accepted_codes={5001}, file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/bundle"
    assert pick.basis == "accepted-build"


def test_select_variant_says_when_no_listed_build_is_of_the_asked_type():
    html = f"""<html><body><div class="variants-table">
        {_split(5001, "arm64-v8a", "nodpi", "/plain-only", badge="APK")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "proton-vpn", file_type="bundle")

    assert pick is not None
    assert pick.variant.href == "/plain-only"
    assert pick.file_type_matched is False


def test_select_variant_still_applies_the_arch_and_the_force_build_pin_with_an_asked_type():
    html = f"""<html><body><div class="variants-table">
        {_split(5001, "x86", "nodpi", "/bundle-x86", badge="BUNDLE")}
        {_split(5001, "arm64-v8a", "240-640dpi", "/bundle-240", badge="BUNDLE")}
        {_split(5001, "arm64-v8a", "480dpi", "/bundle-480", badge="BUNDLE")}
        {_split(5001, "arm64-v8a", "nodpi", "/plain", badge="APK")}
    </div></body></html>"""

    assert select_variant(parse(html), None, "foo", file_type="bundle").variant.href == "/bundle-240"
    assert select_variant(parse(html), "480dpi", "foo", file_type="bundle").variant.href == "/bundle-480"


def test_select_variant_never_picks_a_non_bundle_row_for_instagram_whatever_the_asked_type():
    html = f"""<html><body><div class="variants-table">
        {_split(5001, "arm64-v8a", "nodpi", "/plain", badge="APK")}
        {_split(5001, "arm64-v8a", "nodpi", "/bundle", badge="BUNDLE")}
    </div></body></html>"""

    pick = select_variant(parse(html), None, "instagram", file_type="apk")

    assert pick is not None
    assert pick.variant.href == "/bundle"
    assert pick.file_type_matched is False


async def test_download_apk_opens_the_variant_page_of_a_build_the_patch_accepts(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(monkeypatch, tmp_path, accepted_codes={475417127})

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('2')}"]
    assert warnings == []
    assert not (tmp_path / "diagnostics").exists()


async def test_download_apk_prefers_an_accepted_build_over_a_declared_one(monkeypatch, tmp_path):
    fetched, warnings = await _download_facebook(
        monkeypatch, tmp_path, build_codes=HUSHFACEBOOK_CODES, accepted_codes={475417127}
    )

    assert _variant_page_fetched(fetched) == [f"https://www.apkmirror.com{_facebook_variant_href('2')}"]
    assert warnings == []


async def test_download_apk_says_which_build_code_the_patch_accepted(monkeypatch, tmp_path):
    lines = []
    monkeypatch.setattr(client.log, "info", lines.append)

    await _download_facebook(monkeypatch, tmp_path, accepted_codes={475417127})

    assert any("build 475417127" in line and "a build code the patch accepts" in line for line in lines)


async def test_download_apk_gives_up_when_no_listed_build_is_one_the_patch_accepts(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="has a build code the patch accepts") as exc_info:
        await _download_facebook(monkeypatch, tmp_path, accepted_codes={222222222, 111111111})

    assert "111111111, 222222222" in str(exc_info.value)
    assert not (tmp_path / "facebook.apkm").exists()
    assert len(list((tmp_path / "diagnostics").glob("no-accepted-build-facebook-*.html"))) == 1


async def test_download_apk_cannot_choose_another_build_of_a_single_variant_release(monkeypatch, tmp_path):
    async def fake_resolve_list_url(site, version):
        return FACEBOOK_LIST_URL, True

    monkeypatch.setattr(client, "_resolve_list_url", fake_resolve_list_url)
    monkeypatch.setattr(client.paths, "downloads_dir", lambda: tmp_path)

    with pytest.raises(RuntimeError, match="only one build of 582.0.0.50.54"):
        await client.download_apk("582.0.0.50.54", "facebook", FACEBOOK_SITE, accepted_codes={475417127})
