from curl_cffi.requests import AsyncSession

from .settings import settings

IMPERSONATE = "firefox"


def github_headers(base: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(base or {})
    token = settings.github_token.get_secret_value()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def new_session(
    *, timeout: float | None = 30, follow_redirects: bool = True, impersonate: str | None = IMPERSONATE, **kwargs
) -> AsyncSession:
    return AsyncSession(
        timeout=timeout,  # type: ignore[arg-type]
        allow_redirects=follow_redirects,
        impersonate=impersonate,
        **kwargs,
    )
