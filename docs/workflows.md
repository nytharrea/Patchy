# Workflows

## `release.yml`

Triggered by hand (`workflow_dispatch`). To run on a schedule, add a `schedule:` trigger under `on:`.

| Input | Default | Meaning |
|---|---|---|
| `builds` | `all` | Comma-separated build keys to patch |
| `pin` | empty | App slug to trust. When set, only the `pin` job runs |
| `pin_sha256` | empty | Fingerprint you verified, which must equal the pending one |

Only one run is active at a time (`concurrency: patchy-release`), because the release job deletes older releases.

### Jobs

| Job | Permissions | What it does |
|---|---|---|
| `plan` | `contents: read` | Installs dependencies from `uv.lock`, runs `patchy plan` (validates config, writes `tag`, `name`, `matrix`) and `patchy fetch` (downloads the CLI and the bundles the selected builds need, writes `bundles.json`). Uploads `patchy-tools` and `patchy-manifest` |
| `build` | `contents: read` | One runner per build, with a FlareSolverr service container. Runs `patchy build --app <key>` and uploads `apk-<key>` (unsigned APK and `status-<key>.json`) and diagnostics |
| `release` | `contents: write`, `id-token`, `attestations`, `artifact-metadata` | Downloads every `apk-*` artifact, runs `patchy sign`, attests the signed APKs, runs `patchy publish`, then `patchy pin --collect` to record fingerprints that builds reported |
| `pin` | `contents: write` | Runs `patchy pin <app>` when the `pin` input is set |
| `cleanup` | `actions: write` | Deletes workflow runs older than 30 days, keeping at least five |

### Artifacts

| Name | Contents | Kept |
|---|---|---|
| `patchy-tools` | Patcher jar and `.mpp` bundles | 1 day |
| `patchy-manifest` | `bundles.json`: file names, tags, notes and the planned builds | 1 day |
| `apk-<key>` | `<Name>-<version>.apk`, `status-<key>.json` | 1 day |
| `diagnostics-<key>-<run id>` | Saved HTML of Cloudflare and parse failures | 7 days |

Release notes are taken from `bundles.json`, so they always describe the bundle versions that were actually used for the run.

### Release cleanup

After a successful upload the job deletes older releases whose tag starts with `build-`. Releases you created by hand with other tags are kept. Failed deletions are logged and do not fail the run.

## `ci.yml`

| Job | Trigger | What it does |
|---|---|---|
| `check` | push to `main`, pull requests, manual | `uv sync --locked`, then `patchy validate`, `ruff check`, `ruff format --check`, `mypy`, `pytest` |
| `lock` | manual, `refresh_lock` ticked | `uv lock --upgrade`, then opens a pull request with the new `uv.lock` |
| `autofix` | manual, `autofix` ticked | `ruff check --fix` and `ruff format`, then opens a pull request with the changes |
| `automerge` | Dependabot pull requests | Squash-merges once `check` is green, when `AUTOMERGE_TOKEN` is set |

`lock` and `autofix` use `AUTOMERGE_TOKEN` when it exists, so the pull request they open triggers `check`. Without it they fall back to `GITHUB_TOKEN`, which requires **Allow GitHub Actions to create and approve pull requests** in the repository settings and does not trigger `check` on the new pull request.

## Dependabot

`.github/dependabot.yml` updates GitHub Actions daily and Python dependencies (`uv` ecosystem, which edits `pyproject.toml` and `uv.lock`) weekly, both with a three-day cooldown and one grouped pull request.
