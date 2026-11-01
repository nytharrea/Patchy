import re
from collections.abc import Collection, Mapping

import apprise

from ..core import log
from ..core.settings import settings
from . import details

_BODY_LIMIT = 2000


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n... (truncated)"


def _build_apprise() -> apprise.Apprise:
    apobj = apprise.Apprise()

    discord_url = settings.discord_webhook_url.get_secret_value()
    if discord_url:
        apobj.add(discord_url)

    bot_token = settings.telegram_bot_token.get_secret_value()
    chat_id = settings.telegram_chat_id
    if bot_token and chat_id:
        apobj.add(f"tgram://{bot_token}/{chat_id}")

    for url in re.split(r"[\s,]+", settings.apprise_urls.get_secret_value().strip()):
        if url:
            apobj.add(url)

    return apobj


async def notify(text: str) -> None:
    apobj = _build_apprise()
    if not len(apobj):
        return

    try:
        results = await apobj.async_notify(body=_truncate(text, _BODY_LIMIT))
        if not results:
            log.warn("One or more notification targets failed to send (apprise reported failure).")
    except Exception as e:
        log.warn(f"Notification error: {e}")


def _format_failed_line(
    key: str,
    failure_reasons: dict[str, str] | None,
    statuses: Mapping[str, Mapping[str, object]] | None = None,
    kept: Collection[str | None] = (),
) -> str:
    reason = (failure_reasons or {}).get(key)
    line = f"  • {key}" if not reason else f"  • {key} — {_truncate(reason, 100)}"
    tried = details.tried_versions((statuses or {}).get(key))
    if tried:
        line += f" (tried {', '.join(tried)})"
    if key in kept:
        line += " — previous build kept"
    return line


def _summary_line(apk: dict, status: Mapping[str, object] | None) -> str:
    line = f"  • {apk['display_name']} — {apk['version']}"
    extras: list[str] = []
    applied = details.applied_patches(status)
    if applied:
        extras.append(f"{len(applied)} patch(es)")
    tried = details.tried_versions(status)
    if tried:
        extras.append(f"newer not usable: {', '.join(tried)}")
    if details.is_forced(status):
        extras.append("forced")
    warnings = details.warning_texts(status)
    if warnings:
        extras.append(f"{len(warnings)} warning(s)")
    return f"{line} ({'; '.join(extras)})" if extras else line


def format_summary(
    release_name: str,
    release_url: str,
    matched: list[dict],
    failed_keys: list[str],
    failure_reasons: dict[str, str] | None = None,
    statuses: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    built = [apk for apk in matched if not apk.get("carried")]
    carried = [apk for apk in matched if apk.get("carried")]

    lines = [f"✅ {release_name}", "", f"{len(built)} app(s) patched:"]
    lines += [_summary_line(apk, (statuses or {}).get(apk.get("build_key", ""))) for apk in built]

    if carried:
        lines += ["", f"↩️ {len(carried)} app(s) carried over from the previous release:"]
        lines += [f"  • {apk['display_name']} — {apk['version']}" for apk in carried]

    if failed_keys:
        kept = {apk.get("build_key") for apk in carried}
        lines += ["", f"⚠️ {len(failed_keys)} app(s) failed or produced no APK:"]
        lines += [_format_failed_line(key, failure_reasons, statuses, kept) for key in failed_keys]

    lines += ["", release_url]
    return "\n".join(lines)


def format_all_failed(
    release_name: str,
    failed_keys: list[str],
    failure_reasons: dict[str, str] | None = None,
    statuses: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    lines = [f"❌ {release_name} — no apps were patched successfully this run."]
    if failed_keys:
        lines += ["", f"{len(failed_keys)} app(s) failed or produced no APK:"]
        lines += [_format_failed_line(key, failure_reasons, statuses) for key in failed_keys]
    lines += ["", "Check the Actions run log for details."]
    return "\n".join(lines)
