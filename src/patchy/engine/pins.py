import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from .. import catalog
from ..core import log
from ..core import retry as retry_conf
from ..core.settings import settings

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PinsError(Exception):
    pass


class PushConflict(Exception):
    pass


def normalize_sha256(value: str) -> str:
    cleaned = value.strip().lower().replace(":", "")
    if not SHA256_PATTERN.match(cleaned):
        raise PinsError(f"{value!r} is not a SHA-256 fingerprint (64 hex characters, colons allowed).")
    return cleaned


def load_pins(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PinsError(
            f"{path} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}. "
            f"Fix the file; nothing was changed."
        ) from e
    except OSError as e:
        raise PinsError(f"Could not read {path}: {e}") from e

    if not isinstance(data, dict):
        raise PinsError(f"{path} must contain a JSON object mapping app slug to fingerprint.")

    for app, value in data.items():
        if not isinstance(app, str) or not isinstance(value, str) or not SHA256_PATTERN.match(value):
            raise PinsError(f"{path}: entry {app!r} is not a lowercase SHA-256 fingerprint.")
    return data


def save_pins(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def known_slugs() -> set[str]:
    return {build["app_slug"] for build in catalog.BUILDS.values()}


def require_known_app(app: str) -> None:
    slugs = known_slugs()
    if app not in slugs:
        raise PinsError(f"Unknown app '{app}'. Known apps: {', '.join(sorted(slugs))}")


def promote(app: str, expected_sha256: str | None = None) -> str:
    require_known_app(app)
    pending = load_pins(settings.pending_pins_path)
    known = load_pins(settings.known_pins_path)

    fingerprint = pending.get(app)
    if fingerprint is None:
        raise PinsError(f"There is no pending fingerprint for '{app}' in {settings.pending_pins_path}.")

    if expected_sha256 is not None and normalize_sha256(expected_sha256) != fingerprint:
        raise PinsError(
            f"The fingerprint you verified does not match the pending one for '{app}'.\n"
            f"   pending:  {fingerprint}\n   verified: {normalize_sha256(expected_sha256)}"
        )

    if known.get(app) == fingerprint:
        del pending[app]
        save_pins(settings.pending_pins_path, pending)
        return fingerprint

    known[app] = fingerprint
    del pending[app]
    save_pins(settings.known_pins_path, known)
    save_pins(settings.pending_pins_path, pending)
    return fingerprint


def collect_pending(candidates: dict[str, str]) -> dict[str, str]:
    slugs = known_slugs()
    accepted: dict[str, str] = {}
    for app, fingerprint in candidates.items():
        if app in slugs and isinstance(fingerprint, str) and SHA256_PATTERN.match(fingerprint):
            accepted[app] = fingerprint
        else:
            log.warn(f"Ignoring unusable pending pin record for {app!r}.")
    return accepted


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def commit_with_retry(files: list[Path], mutate: Callable[[], bool], message: str, branch: str = "main") -> bool:
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "github-actions[bot]@users.noreply.github.com")

    committed = False

    def _attempt() -> None:
        nonlocal committed
        git("fetch", "origin", branch)
        git("reset", "--hard", f"origin/{branch}")

        if not mutate():
            log.info("Nothing to commit, the repository is already up to date.")
            return

        git("add", *[str(f) for f in files])
        commit = git("commit", "-m", message)
        if commit.returncode != 0:
            log.info("No real change to commit.")
            return

        push = git("push", "origin", f"HEAD:{branch}")
        if push.returncode == 0:
            committed = True
            return

        raise PushConflict(push.stderr.strip() or "git push failed")

    for attempt in Retrying(
        stop=stop_after_attempt(6),
        wait=retry_conf.incrementing(start=2.0, increment=2.0, jitter=4.0),
        retry=retry_if_exception_type(PushConflict),
        before_sleep=retry_conf.before_sleep("Push conflict while committing pins"),
        reraise=True,
    ):
        with attempt:
            _attempt()

    return committed


def commit_pending(candidates: dict[str, str]) -> bool:
    accepted = collect_pending(candidates)
    if not accepted:
        log.info("No pending pin records to commit.")
        return False

    def _mutate() -> bool:
        known = load_pins(settings.known_pins_path)
        pending = load_pins(settings.pending_pins_path)
        changed = False
        for app, fingerprint in accepted.items():
            if known.get(app) == fingerprint:
                continue
            if pending.get(app) != fingerprint:
                pending[app] = fingerprint
                changed = True
        if changed:
            save_pins(settings.pending_pins_path, pending)
        return changed

    apps = ", ".join(sorted(accepted))
    return commit_with_retry(
        [settings.pending_pins_path], _mutate, f"chore: record pending pins for {apps} [skip ci]"
    )


def commit_promotion(app: str, expected_sha256: str | None = None) -> str:
    result: dict[str, str] = {}

    def _mutate() -> bool:
        result["sha256"] = promote(app, expected_sha256)
        return True

    commit_with_retry(
        [settings.known_pins_path, settings.pending_pins_path],
        _mutate,
        f"chore: pin signing certificate for {app} [skip ci]",
    )
    return result["sha256"]
