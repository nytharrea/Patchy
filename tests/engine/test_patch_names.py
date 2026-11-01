from patchy.engine.patch_names import configured_names, unknown_names


def _build(**fields):
    return {"exclude": [], "enable": [], "options": {}, **fields}


def test_nothing_is_configured_for_a_plain_build():
    assert configured_names(_build()) == []


def test_missing_or_empty_fields_are_read_as_nothing_configured():
    assert configured_names(_build(exclude=None, enable=None, options=None)) == []
    assert configured_names({}) == []


def test_exclude_enable_and_option_patches_are_listed_in_that_order():
    build = _build(
        exclude=["Hide ads", "Spoof client"],
        enable=["Custom branding"],
        options={"Custom branding.App name": "YouTube", "Theme.color": "dark"},
    )

    assert configured_names(build) == [
        ("exclude", "Hide ads"),
        ("exclude", "Spoof client"),
        ("enable", "Custom branding"),
        ("options", "Custom branding"),
        ("options", "Theme"),
    ]


def test_an_option_key_is_split_at_its_first_dot():
    build = _build(options={"Custom branding.App icon.size": "big"})

    assert configured_names(build) == [("options", "Custom branding")]


def test_every_option_of_a_patch_is_listed_separately():
    build = _build(options={"Custom branding.App name": "a", "Custom branding.App icon": "b"})

    assert configured_names(build) == [("options", "Custom branding"), ("options", "Custom branding")]


def test_an_option_key_without_a_patch_name_is_skipped():
    assert configured_names(_build(options={".orphan": "x", "NoDot": "y"})) == [("options", "NoDot")]


def test_names_that_are_not_text_are_read_as_text():
    assert configured_names(_build(exclude=[123], enable=[4.5])) == [("exclude", "123"), ("enable", "4.5")]


def test_known_names_produce_no_problem():
    configured = [("exclude", "Hide ads"), ("enable", "Custom branding"), ("options", "Theme")]

    assert unknown_names(configured, ["Hide ads", "Custom branding", "Theme"], package="p", bundles=["b"]) == []


def test_names_are_matched_without_regard_to_case():
    configured = [("exclude", "hide ADS"), ("enable", "CUSTOM branding")]

    assert unknown_names(configured, ["Hide ads", "Custom Branding"], package="p", bundles=["b"]) == []


def test_an_unknown_name_is_reported_with_its_field_package_and_bundles():
    problems = unknown_names(
        [("exclude", "Hide adz")],
        ["Hide ads", "Other patch"],
        package="com.example.app",
        bundles=["morphe", "piko"],
    )

    assert problems == [
        'exclude: "Hide adz" is not a patch for com.example.app in morphe, piko (did you mean "Hide ads"?); '
        "the patcher ignores unknown names, so this setting has no effect."
    ]


def test_the_suggestion_keeps_the_spelling_of_the_known_name():
    problems = unknown_names([("enable", "custom brandin")], ["Custom branding"], package="p", bundles=["b"])

    assert len(problems) == 1
    assert '(did you mean "Custom branding"?)' in problems[0]


def test_no_suggestion_is_made_when_nothing_is_close():
    problems = unknown_names([("enable", "Zzzzzzzz")], ["Hide ads", "Custom branding"], package="p", bundles=["b"])

    assert len(problems) == 1
    assert "did you mean" not in problems[0]
    assert problems[0].startswith('enable: "Zzzzzzzz" is not a patch for p in b;')


def test_every_name_is_unknown_when_the_bundle_lists_no_patch():
    problems = unknown_names([("exclude", "A"), ("enable", "B")], [], package="p", bundles=["b"])

    assert len(problems) == 2
    assert all("did you mean" not in problem for problem in problems)


def test_the_same_name_in_the_same_field_is_reported_once():
    configured = [("exclude", "Nope"), ("exclude", "Nope"), ("exclude", "Nope")]

    assert len(unknown_names(configured, ["Hide ads"], package="p", bundles=["b"])) == 1


def test_the_same_name_in_two_fields_is_reported_for_each_field():
    problems = unknown_names([("exclude", "Nope"), ("enable", "Nope")], ["Hide ads"], package="p", bundles=["b"])

    assert [problem.split(":")[0] for problem in problems] == ["exclude", "enable"]


def test_problems_follow_the_order_of_the_configuration():
    configured = [("enable", "Second"), ("exclude", "First"), ("options", "Third")]

    problems = unknown_names(configured, ["Known"], package="p", bundles=["b"])

    assert [problem.split('"')[1] for problem in problems] == ["Second", "First", "Third"]


def test_any_iterable_can_be_given():
    problems = unknown_names(
        iter([("exclude", "Nope")]),
        (name for name in ["Hide ads"]),
        package="p",
        bundles=(key for key in ["a", "b"]),
    )

    assert len(problems) == 1
    assert "in a, b" in problems[0]
