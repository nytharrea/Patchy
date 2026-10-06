from tenacity import RetryCallState
from tenacity.wait import wait_base, wait_exponential, wait_incrementing, wait_random

from . import log


def incrementing(*, start: float, increment: float, max: float = 1_073_741_823, jitter: float = 0.0) -> wait_base:
    strategy: wait_base = wait_incrementing(start=start, increment=increment, max=max)
    return strategy + wait_random(0, jitter) if jitter else strategy


def exponential_with_jitter(*, multiplier: float = 1.0, max: float = 60.0, jitter: float = 0.3) -> wait_base:
    return wait_exponential(multiplier=multiplier, max=max) + wait_random(0, jitter)


def before_sleep(label: str):
    def _log(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        delay = retry_state.next_action.sleep if retry_state.next_action else 0.0
        log.notice(f"{label} (attempt {retry_state.attempt_number}): {exc} - retrying in {delay:.1f}s")

    return _log
