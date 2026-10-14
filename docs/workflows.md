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
| `release` | `contents: write`, `id-token`, `attestations`, `artifact-metadata` | Downloads every `apk-*` artifact, runs `patchy sign`, attests the signed APKs, runs `patchy publish`, keeps the signed APKs as `signed-apks` if a step failed, then runs `patchy pin --collect` to record fingerprints that builds reported |
| `pin` | `contents: write` | Runs `patchy pin <app>` when the `pin` input is set |
| `cleanup` | `actions: write` | Deletes workflow runs older than 30 days, keeping at least five |

### Release speed

The release job is bounded by hashing and copying a few gigabytes and by upload bandwidth, so it is tuned rather than serialized:

- `patchy sign` signs up to `SIGN_CONCURRENCY` APKs at once (default 4, one per vCPU of a standard runner). Each APK goes through zipalign, `apksigner sign` and `apksigner verify`.
- `patchy publish` uploads up to `UPLOAD_CONCURRENCY` assets at once (default 10). GitHub serves a single upload at roughly 30 MB/s, so a larger pool finishes sooner until the runner's own bandwidth is reached. Lower it if uploads start failing with 5xx or rate-limit answers.
- Both stages start the largest file first, so the longest job never begins last and leaves the other slots idle at the end.
- MicroG and PotHelper are fetched and uploaded in the same pool as the APKs, ahead of them, instead of after the last APK.
- `apk-<key>` and `patchy-tools` are uploaded with `compression-level: 0`. APKs, jars and `.mpp` files are already compressed, so zipping them again only costs CPU time on both ends.
- Every `Signed and verified` line shows the size, the total time and the time of the `align`, `sign` and `verify` stages, every `Uploaded` line shows its duration and MB/s, and each stage ends with a summary line. Compare those numbers between runs before changing the settings.

### Artifacts

| Name | Contents | Kept |
|---|---|---|
| `patchy-tools` | Patcher jar and the `.mpp` bundles, one folder per bundle key | 1 day |
| `patchy-manifest` | `bundles.json`: file names, tags, notes and the planned builds | 1 day |
| `apk-<key>` | `<Name>-<version>.apk` (unsigned), `status-<key>.json` | 1 day |
| `signed-apks` | Every signed APK, uploaded only when a step of the `release` job fails | 2 days |
| `diagnostics-<key>-<run id>` | Saved HTML of Cloudflare and parse failures | 7 days |

The APKs in `apk-<key>` are unsigned on purpose: build jobs never see the keystore, only the `release` job does. Android refuses to install them (`INSTALL_PARSE_FAILED_NO_CERTIFICATES`, or "Missing META-INF/MANIFEST.MF" in the package installer). Install the APKs from the release. If the release was not created because the job failed after signing, download them from `signed-apks` instead; it is one zip with all signed APKs.

Release notes are taken from `bundles.json`, so they always describe the bundle versions that were actually used for the run.

### Release description

GitHub rejects a release description longer than 125,000 characters. `patchy publish` keeps it under 100,000:

- The list of patched apps is always complete.
- The notes of the patch bundles that were used share the remaining space evenly. A bundle whose notes fit is shown in full, a longer one is cut at a line break and ends with a link to its full notes on GitHub. A code block that the cut leaves open is closed.
- If GitHub refuses the description anyway, the release is created without bundle notes and the log says so. The APKs are published as usual.

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
