import asyncio
import re
import time
from pathlib import Path
from typing import NotRequired, TypedDict

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt

from ...core import flaresolverr, log, paths
from ...core.flaresolverr import Cleared, FlareSolverrError
from ...engine.versions import to_apkmirror_version
from .challenge import (
    BudgetExceeded,
    ChallengeCooldownWait,
    ChallengeError,
    ChallengePresent,
    apply_global_cooldown,
    challenge_hits,
    looks_like_challenge,
    register_challenge,
)
from .parse import (
    abs_url,
    classes,
    dump_variant_rows_for_debug,
    extract_variant_url,
    find_listing_link,
    has_download_button,
    is_404_html,
    listing_candidates,
    parse,
    row_count,
    version_from_href,
)


class ApkMirrorSite(TypedDict):
    org: str
    slug: str
    release_slug: NotRequired[str]


RESOLVE_BUDGET_SECONDS = 300.0


async def close_session() -> None:
    await flaresolverr.close_session()


async def _save_diagnostic_html(html: str, label: str) -> None:
    try:
        diagnostics_dir = paths.diagnostics_dir()
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        path = diagnostics_dir / f"{label}-{int(time.time())}.html"
        path.write_text(html or "", encoding="utf-8", errors="replace")
        log.info(f"Diagnostic HTML saved: {path}")
    except Exception as e:
        log.warn(f"Could not save diagnostic HTML: {e}")


async def _fetch(url: str, label: str, deadline: float | None = None, challenge_retries: int = 3) -> Cleared:
    await apply_global_cooldown()
    cleared: Cleared | None = None

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(challenge_retries + 1) | BudgetExceeded(deadline),
            wait=ChallengeCooldownWait(),
            retry=retry_if_exception_type(ChallengePresent),
            before_sleep=lambda rs: log.notice(
                f"Cloudflare challenge detected ({label}), cooling down "
                f"{(rs.next_action.sleep if rs.next_action else 0):.0f}s before retrying "
                f"(challenge #{challenge_hits()} this run)..."
            ),
            reraise=True,
        ):
            with attempt:
                log.browser(f"Requesting via FlareSolverr ({label}): {url}")
                try:
                    cleared = await flaresolverr.get(url)
                except FlareSolverrError as e:
                    raise RuntimeError(f"FlareSolverr could not fetch {url}: {e}") from e
                if cleared.status == 404:
                    return cleared
                if cleared.status >= 400 or looks_like_challenge(cleared.html):
                    raise ChallengePresent(register_challenge())
    except ChallengePresent:
        if cleared is not None:
            await _save_diagnostic_html(cleared.html, f"cloudflare-{label}")
        status = f"HTTP {cleared.status}" if cleared is not None else "no response"
        raise ChallengeError(
            f"Cloudflare challenge could not be cleared for {label} ({url}, last result: {status}) "
            f"after {challenge_hits()} challenge(s) this run."
        ) from None

    if cleared is None:
        raise RuntimeError(f"Could not fetch {url} ({label})")
    return cleared


async def _page_exists(url: str, deadline: float | None = None) -> bool:
    try:
        cleared = await _fetch(url, label="direct-try", deadline=deadline)
        tree = parse(cleared.html)
        return not is_404_html(tree) and row_count(tree) > 0
    except ChallengeError:
        raise
    except Exception:
        return False


async def _resolve_list_url(site: ApkMirrorSite, version: str) -> tuple[str, bool]:
    version_slug = to_apkmirror_version(version)
    name_part = site.get("release_slug") or site["slug"]
    folder_url = f"https://www.apkmirror.com/apk/{site['org']}/{site['slug']}"
    deadline = time.monotonic() + RESOLVE_BUDGET_SECONDS

    release_slugs = [
        f"{name_part}-{version_slug}-release",
        f"{name_part}-{version_slug}-release-0-release",
        f"{name_part}-{version_slug}-beta-0-release",
        f"{name_part}-{version_slug}-beta-1-release",
    ]

    for slug in release_slugs:
        if time.monotonic() > deadline:
            break

        candidate = f"{folder_url}/{slug}/"
        log.search(f"TRY: {candidate}")
        if await _page_exists(candidate, deadline=deadline):
            return candidate, False

        if time.monotonic() > deadline:
            break

        direct_variant = f"{candidate}{name_part}-{version_slug}-android-apk-download/"
        log.search(f"TRY (single-variant direct): {direct_variant}")
        try:
            cleared = await _fetch(direct_variant, label="direct-variant-try", deadline=deadline)
            tree = parse(cleared.html)
            if not is_404_html(tree) and has_download_button(tree):
                return direct_variant, True
        except ChallengeError:
            raise
        except Exception:
            pass

    if time.monotonic() > deadline:
        raise RuntimeError(
            f"Giving up on {site['slug']} v{version}: APKMirror kept challenge-walling every "
            f"attempt (exceeded {RESOLVE_BUDGET_SECONDS:.0f}s resolve budget)"
        )

    log.search("No direct match, scanning app listing page...")
    listing_url = f"{folder_url}/"
    slug_part = f"-{version_slug}-"
    last_cleared: Cleared | None = None

    for _attempt in range(2):
        if time.monotonic() > deadline:
            break
        last_cleared = await _fetch(listing_url, label="listing-scan", deadline=deadline)
        tree = parse(last_cleared.html)
        found_url = find_listing_link(tree, listing_url, slug_part) if tree is not None else None
        if found_url:
            return found_url, False

    if last_cleared is not None:
        await _save_diagnostic_html(last_cleared.html, f"no-match-{site['slug']}")
    raise RuntimeError(f"No APKMirror release page found for version {version}")


async def _resolve_download_url(variant_url: str, variant_cleared: Cleared) -> tuple[str, Cleared]:
    tree = parse(variant_cleared.html)
    buttons = tree.iter("a") if tree is not None else []
    button = next((a for a in buttons if "downloadButton" in classes(a)), None)
    if button is None or not button.get("href"):
        raise ChallengePresent(register_challenge())

    confirm_url = abs_url(variant_url, button.get("href"))
    if confirm_url is None:
        raise RuntimeError(f"Could not resolve download button URL on {variant_url}")
    confirm_cleared = await _fetch(confirm_url, label="confirm-page")
    confirm_tree = parse(confirm_cleared.html)

    link = confirm_tree.get_element_by_id("download-link", None) if confirm_tree is not None else None
    file_url = abs_url(confirm_url, link.get("href")) if link is not None else None
    if file_url:
        return file_url, confirm_cleared

    return confirm_url, confirm_cleared


async def download_apk(version: str, app_slug: str, site: ApkMirrorSite, force_build: str | None = None) -> str:
    out_dir = paths.downloads_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    list_url, is_final = await _resolve_list_url(site, version)
    log.info(f"LIST: {list_url}")

    if is_final:
        variant_url = list_url
        log.info(f"VARIANT: {variant_url} (single-variant release)")
    else:
        listing_base = f"https://www.apkmirror.com/apk/{site['org']}/{site['slug']}/"
        variant_url = None
        for attempt in range(4):
            cleared = await _fetch(list_url, label="list-page")
            tree = parse(cleared.html)
            found = extract_variant_url(tree, force_build, app_slug) if tree is not None else None
            variant_url = abs_url(listing_base, found) if found else None
            if variant_url:
                break
            log.notice(f"No matching row found on page, retrying ({attempt + 1}/4)...")
            dump_variant_rows_for_debug(tree)
            if attempt < 3:
                await asyncio.sleep(2.0 * (attempt + 1))

        if not variant_url:
            await _save_diagnostic_html(cleared.html, f"no-variant-{app_slug}")
            raise RuntimeError("No matching variant found on APKMirror")
        log.info(f"VARIANT: {variant_url}")

    if variant_url is None:
        raise RuntimeError(f"Could not resolve a variant URL for {app_slug}")

    final_path: Path | None = None
    last_error: Exception | None = None
    last_variant_cleared: Cleared | None = None

    try:
        async for retry_attempt in AsyncRetrying(
            stop=stop_after_attempt(4),
            wait=ChallengeCooldownWait(),
            retry=retry_if_exception_type((ChallengePresent, ChallengeError)),
            before_sleep=lambda rs: log.notice(
                f"Download attempt had no effect, cooling down "
                f"{(rs.next_action.sleep if rs.next_action else 0):.0f}s before retrying "
                f"(attempt #{challenge_hits()} this run)..."
            ),
            reraise=True,
        ):
            with retry_attempt:
                variant_cleared = await _fetch(variant_url, label="variant-page")
                last_variant_cleared = variant_cleared
                file_url, cleared_for_cookies = await _resolve_download_url(variant_url, variant_cleared)

                log.download(f"Downloading: {file_url}")
                try:
                    candidate_path = await flaresolverr.download_file(
                        file_url, cleared_for_cookies, out_dir, f"{app_slug}.apk"
                    )
                except FlareSolverrError as e:
                    last_error = e
                    raise ChallengePresent(register_challenge()) from e

                size = candidate_path.stat().st_size if candidate_path.exists() else 0
                if size < 1024:
                    candidate_path.unlink(missing_ok=True)
                    last_error = RuntimeError(f"Downloaded file too small ({size} bytes)")
                    raise ChallengePresent(register_challenge())

                final_path = candidate_path
    except (ChallengePresent, ChallengeError) as e:
        if isinstance(e, ChallengeError):
            last_error = e

    if final_path is None:
        if last_variant_cleared is not None:
            await _save_diagnostic_html(last_variant_cleared.html, f"no-download-{app_slug}")
        raise last_error or RuntimeError("Download did not start / file not detected.")

    log.success(f"DONE: {final_path} ({final_path.stat().st_size / 1024 / 1024:.2f} MB)")
    return str(final_path)


def _version_sort_key(version: str) -> tuple[int, ...]:
    core = version.split("-")[0]
    try:
        return tuple(int(p) for p in core.split("."))
    except ValueError:
        return (0,)


async def get_latest_listing(app_slug: str, site: ApkMirrorSite) -> dict | None:
    listing_url = f"https://www.apkmirror.com/apk/{site['org']}/{site['slug']}/"
    log.info(f"LISTING: {listing_url}")

    cleared: Cleared | None = None
    candidates: list[tuple[str, str]] = []
    for attempt in range(4):
        cleared = await _fetch(listing_url, label="app-listing")
        tree = parse(cleared.html)
        candidates = listing_candidates(tree, listing_url) if tree is not None else []
        if candidates:
            break
        log.notice(f"No link found on listing page, retrying ({attempt + 1}/4)...")
        if attempt < 3:
            await asyncio.sleep(2.0 * (attempt + 1))

    if not candidates:
        if cleared is not None:
            await _save_diagnostic_html(cleared.html, f"no-listing-{app_slug}")
        return None

    same_app_path = f"/apk/{site['org']}/{site['slug']}/"
    same_app = _best_versioned_candidate(candidates, same_app_path)
    best = same_app if same_app is not None else _best_versioned_candidate(candidates, None)

    if best is None:
        if cleared is not None:
            await _save_diagnostic_html(cleared.html, f"no-version-{app_slug}")
        return None

    _, version, href = best
    return {"version": version, "href": href}


def _best_versioned_candidate(
    candidates: list[tuple[str, str]], require_path: str | None
) -> tuple[tuple[int, ...], str, str] | None:
    best: tuple[tuple[int, ...], str, str] | None = None
    for href, text in candidates:
        if require_path is not None and require_path not in href:
            continue
        version = version_from_href(href)
        if not version:
            match = re.search(r"\d+(?:\.\d+)+", text)
            version = match.group(0) if match else None
        if not version:
            continue
        core = _version_sort_key(version)
        if best is None or core > best[0]:
            best = (core, version, href)
    return best
