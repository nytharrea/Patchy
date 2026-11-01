# Workflows

## `release.yml`

Runs on a schedule (every six hours, `cron: "23 */6 * * *"`, UTC) and by hand (`workflow_dispatch`). A scheduled run builds only what changed since the last release and ends after the `plan` job when nothing did, see [Only-changed runs](#only-changed-runs). A manual run builds every selected build unless `only_changed` is ticked.

| Input | Default | Meaning |
|---|---|---|
| `builds` | `all` | Comma-separated build keys to patch |
| `only_changed` | off | Skip the builds whose patcher, patch bundles, app and configuration are unchanged since the last release. Scheduled runs always behave this way |
| `pin` | empty | App slug to trust. When set, only the `pin` job runs |
| `pin_sha256` | empty | Fingerprint you verified, which must equal the pending one |

Only one run is active at a time (`concurrency: patchy-release`), because the release job carries APKs over from the previous release and deletes older ones.

To change how often it runs, edit the `cron` line under `on.schedule` in `.github/workflows/release.yml`; GitHub reads the times as UTC and may start a scheduled run a few minutes late. To stop scheduled runs, delete the whole `schedule:` block. In a public repository GitHub switches scheduled workflows off after 60 days without repository activity; open the **Actions** tab and enable the workflow again when that happens.

### Jobs

| Job | Permissions | What it does |
|---|---|---|
| `plan` | `contents: read` | Installs dependencies from `uv.lock`, runs `patchy plan` (validates config, writes `tag`, `name`, `matrix`, `builds` and `has_builds`; with `only_changed`, and on a schedule, it drops the builds that did not change) and `patchy fetch` (downloads the CLI and the bundles the selected builds need, writes `bundles.json` with what each build is made from). Uploads `patchy-tools` and `patchy-manifest`. When no build is left, `fetch`, the uploads and the `build` and `release` jobs are skipped |
| `build` | `contents: read` | One runner per build, with a FlareSolverr service container. Runs `patchy build --app <key>` and uploads `apk-<key>` (unsigned APK and `status-<key>.json`, which carries the stage timings and the [build report](#build-report)) and diagnostics |
| `release` | `contents: write`, `id-token`, `attestations`, `artifact-metadata` | Downloads every `apk-*` artifact, runs `patchy sign`, attests the signed APKs, runs `patchy publish` (creates the release, uploads the signed APKs, the [carried-over](#carried-over-apps) ones and `patchy-state.json`, deletes old releases, notifies), writes the build telemetry table to the job summary (`patchy summary`), keeps the signed APKs as `signed-apks` if a step failed, then runs `patchy pin --collect` to record fingerprints that builds reported |
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

### Build telemetry

Every build job times its stages with `log.timed` (`core/log.py`) and stores the seconds in its `status-<key>.json` under `timings`:

| Stage | What it covers |
|---|---|
| `select` | Asking the patch bundles which app versions they support |
| `download` | Finding and downloading the original APK (APKMirror or GitHub), including retries and Cloudflare handling |
| `verify` | Checking the original certificate against `pins/known.json` |
| `patch` | Running the patcher |
| `total` | The whole build, from the first stage to the status file |

A build that fails reports the stages it reached. The same measurements appear in the build log as `⏱️ download took 41.3 s`.

At the end of the `release` job, `patchy summary` merges the status files of all builds with the list of planned builds and appends one table to the job summary (`$GITHUB_STEP_SUMMARY`), so the run's page shows it without opening a log:

| App | Version | Status | Download | Patch | Total |
|---|---|---|--:|--:|--:|
| `youtube` | 20.1.2 | ✅ ok | 1m 12s | 48.3 s | 2m 09s |
| `gboard` | – | ❌ failed | 3.0 s | – | 3.5 s |

Under the table the summary names the slowest download and the slowest patch, and lists every failure with the first line of its reason. A build that uploaded no status file at all (cancelled or crashed job) is listed as `no status`. The step runs even when an earlier step failed and never fails the run itself. Outside GitHub Actions, where `GITHUB_STEP_SUMMARY` is not set, `patchy summary` prints the table to the console.

Times are measured inside each build job, so they leave out runner setup, the FlareSolverr start and the wait for a free runner.

### Build report

Besides the timings, every `status-<key>.json` records what happened in the build. The release notes, the notification and the job summary are written from it.

| Field | Meaning |
|---|---|
| `ok`, `error` | Whether the build produced an APK, and the reason when it did not |
| `version`, `file` | The version that was patched and the name of the APK |
| `attempts` | Versions that were tried and given up, each with its `stage` (`download` or `patch`) and `reason`, see [Stepping down to an older version](configuration.md#stepping-down-to-an-older-version) |
| `patches` | The patches that were `applied` and the ones that `failed` with their error, read from the patcher's result file (`--result-file`) |
| `warnings` | Problems that did not stop the build: a patch name that does not exist, a download that does not match the build, a patched APK that looks wrong |
| `forced` | `true` when the patcher ran with `--force`, see [Forced patching](configuration.md#forced-patching) |
| `apk` | Package name, version name, version code and native-library architectures of the patched APK |
| `timings` | The stage timings above |

In the release notes every app lists the versions that could not be used, a notice when `--force` was used and its first three warnings, and a collapsed section names the patches that were applied (the first 80). A build that failed is reported with the patch that broke it, taken from the result file, and with the versions it tried.

### Artifacts

| Name | Contents | Kept |
|---|---|---|
| `patchy-tools` | Patcher jar and the `.mpp` bundles, one folder per bundle key | 1 day |
| `patchy-manifest` | `bundles.json`: file names, tags, notes, the planned builds and what each build is made from | 1 day |
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

### Only-changed runs

With `only_changed` ticked, and on every scheduled run, `patchy plan` decides before anything is downloaded which of the selected builds need a new APK. It compares a fingerprint of each build with the one stored in the `patchy-state.json` asset of the previous release. The fingerprint is made of:

- the build's configuration, which is everything in its YAML except `icon`
- the newest release of the patcher CLI (tag and file name)
- the newest release of every patch bundle the build uses (tag and file name)
- for a `github` source, the newest release of the app's repository

A build runs when its fingerprint differs, and also when:

- there is no previous release, or it carries no `patchy-state.json` (releases made before this feature do not), so the first run builds everything
- the app was not part of the previous release
- its inputs cannot be compared: a release lookup failed, or the build has `force: true` and an APKMirror source, see [Forced patching](configuration.md#forced-patching)
- the previous build had to step down to an older version, so the newer one is tried again

The `plan` log says for every build whether it runs and why. The listing on APKMirror is not part of the fingerprint: the version that gets patched is chosen from what the bundles support, so it changes when a bundle does. To build everything anyway, run the workflow by hand with `only_changed` off.

`patchy fetch` records the fingerprint of what it really downloaded, and `patchy publish` stores it. A bundle release that appears while a run is in progress is therefore not skipped later: the next run sees that its fingerprint differs.

When no build is left, the run ends after `plan`. The job summary says **Nothing to build**, no release is created and no old release is deleted.

`patchy-state.json` is uploaded to every release next to the APKs. For every app of that release it lists the version, the file name, the fingerprint and a `retry` flag. The site only reads `.apk` assets, so it does not see this file. When the file cannot be uploaded or read, nothing is lost except the comparison: the next only-changed run builds every selected app again and writes a new one.

### Carried-over apps

A release should hold every app, however many of them a run built. After the new release is created, `patchy publish` looks up the previous Patchy release and copies the APK of every app this run did not produce into the new release, together with the companions of those apps. That covers:

- apps that were skipped because nothing changed, or because the `builds` input named other apps
- apps whose build failed: their last good APK stays in the release, the release notes say `Carried over from build-..., because this app was not rebuilt in this run. The new build failed: <reason>`, and the notification says `previous build kept`

Carried-over APKs are downloaded and uploaded again as they are, without being patched or signed a second time, so the site shows the date of the new release for them and their download counter starts at zero. Their entry in `patchy-state.json` keeps the fingerprint it had: an app that failed is built again by the next only-changed run, while an app that was skipped stays skipped until something changes. An app that is no longer in `config/apps/` is not carried over.

Set the repository variable `CARRY_FORWARD` to `false` to publish only the apps a run built, as older versions of Patchy did. When the previous release cannot be found, or one of its assets cannot be downloaded, the log says so and that app is left out.

### Release retention

After a successful upload the job deletes older releases, and their tags, whose tag starts with `build-`, except the newest `KEEP_RELEASES` of them. The default is `1`: the previous release stays, so you can install from it when a new build misbehaves. Set the repository variable `KEEP_RELEASES` (Settings → Secrets and variables → Actions → Variables) to `0` to keep none, or to a larger number to keep more. Releases you created by hand with other tags are kept. Failed deletions are logged and do not fail the run.

## `discover.yml`

Triggered by hand. Reads the Morphe patch catalog (`https://morphe-patches.software/data/bundles.json`) and writes a report to the job summary, so you can see on a phone which patch bundles cover an app and what to add to `config/`, without opening any JSON. It only reads: no app is downloaded and no file changes.

| Input | Default | Meaning |
|---|---|---|
| `package` | empty | Android package name, for example `com.reddit.frontpage`. Reports the bundles that patch the app, whether each one is already in `config/bundles.yaml`, and whether Patchy builds the app |
| `query` | empty | Searches app names and package names instead. Ignored when `package` is set |
| `limit` | `20` | Most rows shown in a table |

With both inputs empty the report is an overview: the apps Patchy builds with their bundles, the configured bundles the catalog does not list, and the apps that bundles patch but Patchy does not build yet.

For an app Patchy does not build yet, the report ends with YAML you can paste: the missing entries for `config/bundles.yaml`, and a `config/apps/<slug>.yaml` file in which `FILL-IN` marks the APKMirror `org` and `slug` and the icon, which you still have to supply. Only bundles hosted on GitHub are offered, because Patchy downloads bundles from GitHub releases; bundles on other sites are listed as not supported.

The catalog is a third-party file that Patchy reads defensively. When it cannot be loaded or no longer looks like a catalog, the run fails with a message that says so, see [Troubleshooting](troubleshooting.md#the-morphe-catalog-cannot-be-loaded). Builds never read the catalog.

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
