import asyncio
import time

from tenacity.stop import stop_base
from tenacity.wait import wait_base

from ...core import log
from .parse import page_text, parse

_CHALLENGE_MARKERS = [
    "just a moment",
    "checking your browser",
    "attention required! | cloudflare",
    "verify you are human",
    "cf-browser-verification",
    "cf_chl_",
    "ddos protection by cloudflare",
    "performing security verification",
    "verifies you are not a bot",
]

_challenge_hits = 0
_cooldown_until = 0.0


def challenge_hits() -> int:
    return _challenge_hits


def looks_like_challenge(html: str) -> bool:
    if not html:
        return False
    content = page_text(parse(html), 500) or html[:1000].lower()
    return any(marker in content for marker in _CHALLENGE_MARKERS)


async def apply_global_cooldown() -> None:
    now = time.monotonic()
    if now < _cooldown_until:
        remaining = _cooldown_until - now
        log.wait(f"Global cooldown active, waiting {remaining:.0f}s...")
        await asyncio.sleep(remaining)


class ChallengeError(RuntimeError):
    pass


class ChallengePresent(Exception):
    def __init__(self, cooldown: float):
        super().__init__("Cloudflare challenge page detected")
        self.cooldown = cooldown


def register_challenge() -> float:
    global _challenge_hits, _cooldown_until
    _challenge_hits += 1
    cooldown = min(15.0 * (2 ** (_challenge_hits - 1)), 120.0)
    _cooldown_until = time.monotonic() + cooldown
    return cooldown


class ChallengeCooldownWait(wait_base):
    def __call__(self, retry_state) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        return exc.cooldown if isinstance(exc, ChallengePresent) else 0.0


class BudgetExceeded(stop_base):
    def __init__(self, deadline: float | None):
        self.deadline = deadline

    def __call__(self, retry_state) -> bool:
        if self.deadline is None or retry_state.outcome is None:
            return False
        exc = retry_state.outcome.exception()
        cooldown = exc.cooldown if isinstance(exc, ChallengePresent) else 0.0
        return time.monotonic() + cooldown >= self.deadline
