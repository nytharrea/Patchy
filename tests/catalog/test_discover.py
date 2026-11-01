import re

import pytest
import yaml

from patchy.catalog import discover
from patchy.fetch.morphe import parse_catalog


def _bundle(name, repo, packages, source="github", patches=None):
    return {"name": name, "repo": repo, "source": source, "targetApps": packages, "patches": patches or []}


def _catalog():
    return parse_catalog(
        {
            "store": {
                "com.google.android.youtube": {
                    "name": "YouTube",
                    "category": "Video",
                    "iconUrl": "https://x/yt.png",
                },
                "com.example.newapp": {"name": "New App", "category": "Social", "iconUrl": "https://x/new.png"},
                "com.example.lab": {"name": "Lab App", "category": "Tools"},
                "com.example.orphan": {"name": "Orphan", "category": "Tools"},
            },
            "compatibilities": [["com.google.android.youtube"], ["com.example.newapp"]],
            "bundles": [
                _bundle(
                    "Morphe",
                    "MorpheApp/morphe-patches",
                    ["com.google.android.youtube"],
                    patches=[
                        {"name": "Hide ads", "compatiblePackagesKey": 0},
                        {"name": "Layout", "compatiblePackagesKey": 0},
                        {"name": "Misc", "compatiblePackagesKey": 1},
                    ],
                ),
                _bundle("Piko", "crimera/piko", ["com.google.android.youtube"]),
                _bundle("Fancy", "fancy/newapp-patches", ["com.example.newapp"]),
                _bundle("Lab", "lab/lab-patches", ["com.example.lab"], source="gitlab"),
                _bundle("Third", "third/newapp", ["com.example.newapp"]),
            ],
        }
    )


BUNDLES = {
    "morphe": {"owner": "MorpheApp", "repo": "morphe-patches", "label": "Morphe"},
    "piko": {"owner": "crimera", "repo": "piko", "label": "Piko"},
    "local": {"owner": "me", "repo": "private-patches", "label": "Local"},
}


def _build(key, pkg, bundles, name, slug=None):
    return {"key": key, "app_slug": slug or key, "pkg": pkg, "display_name": name, "bundles": bundles}


BUILDS = {"youtube": _build("youtube", "com.google.android.youtube", ["morphe"], "YouTube")}


def _blocks(report):
    return re.findall(r"```yaml\n(.*?)\n```", report, re.DOTALL)


def _row(report, first_cell):
    return next(line for line in report.splitlines() if line.startswith(f"| {first_cell} |"))


def test_a_package_patchy_builds_shows_its_builds_and_which_bundle_it_uses():
    report = discover.package_report(_catalog(), "com.google.android.youtube", BUILDS, BUNDLES)

    assert "## Morphe catalog: `com.google.android.youtube`" in report
    assert "**YouTube** · Video · 2 bundle(s) patch it" in report
    assert "Patchy builds it as `youtube`." in report
    assert _row(report, "Morphe") == (
        "| Morphe | [MorpheApp/morphe-patches](https://github.com/MorpheApp/morphe-patches) "
        "| 2 for this app, 3 in total | ✅ `morphe` · used for this app |"
    )
    assert _row(report, "Piko") == "| Piko | [crimera/piko](https://github.com/crimera/piko) | – | ✅ `piko` |"
    assert "Add the missing bundles" not in report
    assert "Add the app" not in report
    assert report.endswith("\n") and not report.endswith("\n\n")


def test_a_package_patchy_does_not_build_gets_ready_made_config():
    report = discover.package_report(_catalog(), "com.example.newapp", BUILDS, BUNDLES)

    assert "Patchy does not build it yet." in report
    assert _row(report, "Morphe").endswith("| 1 for this app, 3 in total | ✅ `morphe` |")
    assert _row(report, "Fancy").endswith("| – | ➕ not configured |")
    assert _row(report, "Third").endswith("| – | ➕ not configured |")

    bundles_block, app_block = _blocks(report)
    assert yaml.safe_load("bundles:\n" + bundles_block) == {
        "bundles": {
            "fancy": {"owner": "fancy", "repo": "newapp-patches", "label": "Fancy"},
            "third": {"owner": "third", "repo": "newapp", "label": "Third"},
        }
    }
    assert yaml.safe_load(app_block) == {
        "pkg": "com.example.newapp",
        "display_name": "New App",
        "arch": "arm64-v8a",
        "icon": "https://x/new.png",
        "apk_source": {"type": "apkmirror", "org": "FILL-IN", "slug": "FILL-IN"},
        "builds": [{"key": "new-app", "bundles": ["morphe"]}],
    }
    assert "Save this as `config/apps/new-app.yaml`:" in report
    assert "Replace every `FILL-IN` value" in report
    assert "The other GitHub bundles in the table can be added as extra builds" in report


def test_the_new_app_uses_a_new_bundle_when_none_of_the_configured_ones_patches_it():
    bundles = {"piko": BUNDLES["piko"]}

    report = discover.package_report(_catalog(), "com.example.newapp", {}, bundles)

    bundles_block, app_block = _blocks(report)
    assert set(yaml.safe_load("bundles:\n" + bundles_block)["bundles"]) == {"morpheapp", "fancy", "third"}
    assert yaml.safe_load(app_block)["builds"] == [{"key": "new-app", "bundles": ["morpheapp"]}]


def test_suggested_names_never_clash_with_what_exists():
    bundles = {**BUNDLES, "fancy": {"owner": "other", "repo": "other", "label": "Other"}}
    builds = {"new-app": _build("new-app", "com.other.app", ["morphe"], "Other", slug="other")}

    report = discover.package_report(_catalog(), "com.example.newapp", builds, bundles)

    bundles_block, app_block = _blocks(report)
    assert "fancy" not in yaml.safe_load("bundles:\n" + bundles_block)["bundles"]
    assert "newapp-patches" in yaml.safe_load("bundles:\n" + bundles_block)["bundles"]
    assert yaml.safe_load(app_block)["builds"][0]["key"] == "newapp"
    assert "config/apps/newapp.yaml" in report


@pytest.mark.parametrize(
    ("candidates", "taken", "expected"),
    [
        (["a", "b"], set(), "a"),
        (["a", "b"], {"a"}, "b"),
        (["", "b"], set(), "b"),
        (["a", "b"], {"a", "b"}, "b-2"),
        (["a", "b"], {"a", "b", "b-2"}, "b-3"),
        (["", ""], set(), "item"),
        (["", ""], {"item"}, "item-2"),
    ],
)
def test_a_free_key_is_the_first_unused_candidate_or_a_numbered_one(candidates, taken, expected):
    assert discover._free_key(candidates, taken) == expected


def test_a_package_only_hosted_outside_github_cannot_be_built():
    report = discover.package_report(_catalog(), "com.example.lab", BUILDS, BUNDLES)

    assert _row(report, "Lab") == (
        "| Lab | [lab/lab-patches](https://gitlab.com/lab/lab-patches) | – | ⛔ GitLab bundles are not supported |"
    )
    assert "Every bundle that patches it is hosted outside GitHub" in report
    assert "Add the missing bundles" not in report
    assert _blocks(report) == []


def test_a_package_no_bundle_patches_says_so():
    report = discover.package_report(_catalog(), "com.example.orphan", BUILDS, BUNDLES)

    assert "0 bundle(s) patch it" in report
    assert "Patchy does not build it yet." in report
    assert "No bundle in the catalog patches this app." in report
    assert "| Bundle |" not in report


def test_the_lookup_ignores_case_and_surrounding_space():
    report = discover.package_report(_catalog(), "  COM.Google.Android.YouTube ", BUILDS, BUNDLES)

    assert "## Morphe catalog: `com.google.android.youtube`" in report


def test_an_unknown_package_suggests_close_matches_or_a_search():
    close = discover.package_report(_catalog(), "com.example", BUILDS, BUNDLES)
    far = discover.package_report(_catalog(), "nothing.here", BUILDS, BUNDLES)

    assert "No app with that package name is in the catalog." in close
    assert "Close matches: `com.example.lab`, `com.example.newapp`, `com.example.orphan`" in close
    assert "Close matches" not in far
    assert "Search by app name instead" in far


def test_text_from_the_catalog_cannot_break_the_tables_or_the_config():
    nasty = parse_catalog(
        {
            "store": {
                "com.evil.app": {
                    "name": "Evil | `x` *y*\nline <b>2</b>",
                    "category": "Cat | egory",
                    "iconUrl": 'https://x/"i".png',
                }
            },
            "bundles": [_bundle('Qu"ote ```break``` it', "a b/c d", ["com.evil.app"])],
        }
    )

    report = discover.package_report(nasty, "com.evil.app", {}, {})
    search = discover.search_report(nasty, "evil", 5, {})

    for text in (report, search):
        pipes = {len(re.findall(r"(?<!\\)\|", line)) for line in text.splitlines() if line.startswith("|")}
        assert len(pipes) == 1
        assert "<b>" not in re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    assert "\\<b\\>2\\</b\\>" in report
    assert "[a b/c d]" not in report
    assert report.count("```") == 2 * len(_blocks(report))
    bundles_block, app_block = _blocks(report)
    assert yaml.safe_load("bundles:\n" + bundles_block)["bundles"]["a-b"] == {
        "owner": "a b",
        "repo": "c d",
        "label": 'Qu"ote break it',
    }
    app = yaml.safe_load(app_block)
    assert app["display_name"] == "Evil | x *y* line <b>2</b>"
    assert app["icon"] == 'https://x/"i".png'


def test_a_repository_with_unsafe_characters_is_not_linked():
    nasty = parse_catalog({"bundles": [_bundle("Odd", "a b/c)d", ["com.odd.app"])]})

    report = discover.package_report(nasty, "com.odd.app", {}, {})

    assert "](" not in report
    assert "| a b/c)d |" in report


def test_a_search_matches_names_and_packages_and_shows_what_patchy_builds():
    report = discover.search_report(_catalog(), "new", 20, BUILDS)

    assert "## Morphe catalog search: `new`" in report
    assert _row(report, "`com.example.newapp`") == "| `com.example.newapp` | New App | Social | 3 | – |"
    assert "Showing 1 of 1 match(es)." in report

    tube = discover.search_report(_catalog(), "TUBE", 20, BUILDS)
    assert (
        _row(tube, "`com.google.android.youtube`")
        == "| `com.google.android.youtube` | YouTube | Video | 2 | ✅ `youtube` |"
    )


def test_a_search_with_several_words_needs_every_word():
    assert "`com.example.newapp`" in discover.search_report(_catalog(), "new app", 20, BUILDS)
    assert "No app in the catalog matches that text." in discover.search_report(
        _catalog(), "new youtube", 20, BUILDS
    )


def test_search_results_start_with_names_that_begin_with_the_text_then_the_most_supported():
    catalog = parse_catalog(
        {
            "store": {
                "com.a.mytube": {"name": "My Tube"},
                "com.b.tubey": {"name": "Tubey"},
                "com.c.superyoutube": {"name": "Super Tube"},
                "com.d.tubemate": {"name": "Tubemate"},
            },
            "bundles": [
                _bundle("One", "o/one", ["com.a.mytube", "com.c.superyoutube"]),
                _bundle("Two", "t/two", ["com.c.superyoutube"]),
            ],
        }
    )

    report = discover.search_report(catalog, "tube", 20, {})

    packages = [line.split("|")[1].strip() for line in report.splitlines() if line.startswith("| `")]
    assert packages == ["`com.d.tubemate`", "`com.b.tubey`", "`com.c.superyoutube`", "`com.a.mytube`"]


def test_a_search_lists_no_more_rows_than_the_limit_and_says_how_many_there_are():
    report = discover.search_report(_catalog(), "com.example", 2, BUILDS)

    assert len([line for line in report.splitlines() if line.startswith("| `")]) == 2
    assert "Showing 2 of 3 match(es)." in report


def test_a_search_without_a_match_says_so():
    report = discover.search_report(_catalog(), "zzz", 20, BUILDS)

    assert "No app in the catalog matches that text." in report
    assert "| Package |" not in report


def test_the_overview_compares_the_catalog_with_what_patchy_has():
    report = discover.overview_report(_catalog(), 20, BUILDS, BUNDLES)

    assert "The catalog lists 4 app(s) and 5 bundle(s), 4 of them on GitHub." in report
    assert "- **YouTube** — uses `morphe`. Also patched by: ✅ `piko`" in report
    assert "### Configured bundles the catalog does not list" in report
    assert "- `local` — me/private-patches" in report
    assert "- `morphe`" not in report
    assert "### Apps Patchy does not build yet" in report
    assert _row(report, "`com.example.newapp`") == "| `com.example.newapp` | New App | Social | 3 |"
    assert "com.example.lab" not in report
    assert "com.example.orphan" not in report
    assert "Showing 1 of 1." in report


def test_the_overview_notes_an_app_the_catalog_does_not_know():
    builds = {**BUILDS, "gboard": _build("gboard", "com.google.android.inputmethod.latin", ["morphe"], "Gboard")}

    report = discover.overview_report(_catalog(), 20, builds, BUNDLES)

    assert "- **Gboard** — uses `morphe`. Not listed in the catalog." in report


def test_the_overview_lists_patchys_apps_by_name_and_every_bundle_an_app_uses():
    builds = {
        "b": _build("b", "com.b.app", ["morphe", "piko"], "beta"),
        "a": _build("a", "com.a.app", ["morphe"], "Alpha"),
        "a2": _build("a2", "com.a.app", ["piko", "morphe"], "Alpha"),
    }

    report = discover.overview_report(_catalog(), 20, builds, BUNDLES)

    lines = [line for line in report.splitlines() if line.startswith("- **")]
    assert lines == [
        "- **Alpha** — uses `morphe`, `piko`. Not listed in the catalog.",
        "- **beta** — uses `morphe`, `piko`. Not listed in the catalog.",
    ]


def test_the_overview_shortens_a_long_list_of_other_bundles():
    others = [_bundle(f"B{i}", f"o{i}/r{i}", ["com.google.android.youtube"]) for i in range(7)]
    catalog = parse_catalog({"store": {"com.google.android.youtube": {"name": "YouTube"}}, "bundles": others})
    bundles = {"morphe": {"owner": "o0", "repo": "r0", "label": "x"}}

    report = discover.overview_report(catalog, 20, BUILDS, bundles)

    assert "Also patched by: ➕ o1/r1, ➕ o2/r2, ➕ o3/r3, ➕ o4/r4 (+2 more)" in report


def test_the_overview_skips_sections_with_nothing_to_say():
    catalog = parse_catalog(
        {
            "store": {"com.google.android.youtube": {"name": "YouTube"}},
            "bundles": [_bundle("Morphe", "MorpheApp/morphe-patches", ["com.google.android.youtube"])],
        }
    )

    report = discover.overview_report(catalog, 20, BUILDS, {"morphe": BUNDLES["morphe"]})

    assert "- **YouTube** — uses `morphe`." in report
    assert "does not list" not in report
    assert "does not build yet" not in report


def test_the_overview_matches_bundles_by_repository_without_regard_to_case():
    bundles = {"mine": {"owner": "morpheapp", "repo": "MORPHE-PATCHES", "label": "x"}}
    builds = {"youtube": _build("youtube", "com.google.android.youtube", ["mine"], "YouTube")}

    report = discover.overview_report(_catalog(), 20, builds, bundles)

    assert "- **YouTube** — uses `mine`. Also patched by: ➕ crimera/piko" in report
    assert "does not list" not in report


def test_the_overview_ranks_new_apps_by_how_many_bundles_patch_them_and_obeys_the_limit():
    store = {f"com.new.app{i}": {"name": f"App {i}"} for i in range(5)}
    bundles = [_bundle(f"B{i}", f"o{i}/r{i}", [f"com.new.app{j}" for j in range(5) if j >= i]) for i in range(5)]
    catalog = parse_catalog({"store": store, "bundles": bundles})

    report = discover.overview_report(catalog, 2, {}, {})

    rows = [line for line in report.splitlines() if line.startswith("| `")]
    assert [row.split("|")[1].strip() for row in rows] == ["`com.new.app4`", "`com.new.app3`"]
    assert "Showing 2 of 5." in report


def test_the_report_depends_on_what_was_asked_for():
    catalog = _catalog()

    assert "## Morphe catalog: `com.example.newapp`" in discover.build_report(
        catalog, package="com.example.newapp", query="youtube", builds=BUILDS, bundles=BUNDLES
    )
    assert "## Morphe catalog search: `youtube`" in discover.build_report(
        catalog, query="youtube", builds=BUILDS, bundles=BUNDLES
    )
    assert "## Morphe catalog overview" in discover.build_report(
        catalog, package=" ", query="  ", builds=BUILDS, bundles=BUNDLES
    )


def test_the_limit_is_kept_between_one_and_the_maximum():
    store = {f"com.many.app{i}": {"name": f"Many {i}"} for i in range(discover.MAX_LIMIT + 20)}
    catalog = parse_catalog({"store": store})

    zero = discover.build_report(catalog, query="many", limit=0, builds={}, bundles={})
    huge = discover.build_report(catalog, query="many", limit=100_000, builds={}, bundles={})

    assert f"Showing 1 of {discover.MAX_LIMIT + 20} match(es)." in zero
    assert f"Showing {discover.MAX_LIMIT} of {discover.MAX_LIMIT + 20} match(es)." in huge


def test_patchys_own_config_is_used_unless_other_config_is_given():
    report = discover.build_report(_catalog(), package="com.google.android.youtube")

    assert "Patchy builds it as `youtube`." in report
