from collections.abc import Iterable
from difflib import get_close_matches

from ..catalog.models import BuildConfig

SUGGESTION_CUTOFF = 0.6


def configured_names(build: BuildConfig) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = [("exclude", str(name)) for name in build.get("exclude") or []]
    names += [("enable", str(name)) for name in build.get("enable") or []]
    for dotted_key in build.get("options") or {}:
        patch_name = str(dotted_key).partition(".")[0]
        if patch_name:
            names.append(("options", patch_name))
    return names


def unknown_names(
    configured: Iterable[tuple[str, str]], known: Iterable[str], *, package: str, bundles: Iterable[str]
) -> list[str]:
    by_lower = {name.lower(): name for name in known}
    where = ", ".join(bundles)
    problems: list[str] = []
    reported: set[tuple[str, str]] = set()

    for field, name in configured:
        if name.lower() in by_lower or (field, name) in reported:
            continue
        reported.add((field, name))
        close = get_close_matches(name.lower(), list(by_lower), n=1, cutoff=SUGGESTION_CUTOFF)
        hint = f' (did you mean "{by_lower[close[0]]}"?)' if close else ""
        problems.append(
            f'{field}: "{name}" is not a patch for {package} in {where}{hint}; '
            f"the patcher ignores unknown names, so this setting has no effect."
        )
    return problems
