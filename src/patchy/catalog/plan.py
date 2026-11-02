import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import BUILDS

TAG_PREFIX = "build-"


class PlanError(Exception):
    pass


@dataclass(frozen=True)
class Plan:
    tag: str
    name: str
    matrix: list[str]

    def matrix_json(self) -> str:
        return json.dumps(self.matrix)


def select_builds(selection: str | None) -> list[str]:
    raw = (selection or "").strip()
    if not raw or raw.lower() == "all":
        return list(BUILDS)

    wanted: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        key = part.strip()
        if key and key not in wanted:
            wanted.append(key)

    unknown = [key for key in wanted if key not in BUILDS]
    if unknown:
        raise PlanError(f"Unknown build key(s): {', '.join(unknown)}. Known keys: {', '.join(BUILDS)}")

    return [key for key in BUILDS if key in wanted]


def make_plan(selection: str | None = None, now: datetime | None = None) -> Plan:
    moment = now or datetime.now(UTC)
    return Plan(
        tag=f"{TAG_PREFIX}{moment.strftime('%Y-%m-%dT%H-%M-%S')}",
        name=f"Patched APKs - {moment.day} {moment.strftime('%B %Y')}",
        matrix=select_builds(selection),
    )


def write_github_output(plan: Plan, destination: str | None = None) -> bool:
    target = destination or os.environ.get("GITHUB_OUTPUT")
    if not target:
        return False
    with Path(target).open("a", encoding="utf-8") as f:
        f.write(f"tag={plan.tag}\n")
        f.write(f"name={plan.name}\n")
        f.write(f"matrix={plan.matrix_json()}\n")
    return True
