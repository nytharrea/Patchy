# Development

## Setup

Dependencies are declared only in `pyproject.toml`. `uv.lock` pins the exact tree, with hashes.

```bash
uv sync --locked            # runtime and dev dependencies
uv sync --locked --no-dev   # what the workflows use for build and release jobs
```

Python 3.12 is required (`.python-version`). Everything runs through `uv run`:

```bash
uv run patchy validate
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

To change a dependency, edit its range in `pyproject.toml` and run `uv lock` (or start the `lock` job of `ci.yml` from the Actions tab if you cannot run uv yourself).

## Layout

```
src/patchy/
├─ cli.py              argparse entry point (`patchy ...`)
├─ catalog/            loading and validating config/, release plan
│  ├─ models.py        TypedDicts for builds, bundles, companions
│  ├─ loader.py        reads config/apps/*.yaml, bundles.yaml, companions.yaml
│  ├─ validate.py      cross-checks the loaded config
│  └─ plan.py          release tag, name and build matrix
├─ fetch/
│  ├─ apkmirror/       client.py (orchestration), parse.py (HTML), challenge.py (Cloudflare handling)
│  ├─ github.py        GitHub release downloads and GitHub-hosted apps
│  └─ bundles.py       patcher CLI, patch bundles, companions, bundles.json manifest
├─ engine/
│  ├─ build.py         one build: version, download, verify, patch, status file
│  ├─ patcher.py       async patcher CLI wrapper with a per-line watchdog
│  ├─ verify.py        apksigner-based certificate check against the pins
│  ├─ pins.py          reading, promoting and committing pins
│  ├─ signer.py        zipalign, apksigner sign and verify
│  └─ versions.py      parsing `list-versions` output, APKMirror version slugs
├─ publish/
│  ├─ pipeline.py      `sign` and `publish` orchestration
│  ├─ release.py       GitHub Releases REST wrapper
│  ├─ assets.py        file name matching, status files, release body
│  └─ notify.py        Discord, Telegram and Apprise notifications
└─ core/               settings, paths, log, retry, http, process, toolchain, flaresolverr
```

`tests/` mirrors this tree. All generated files (downloads, patched and signed APKs, manifests, diagnostics) live under `build/`, which `PATCHY_BUILD_DIR` can relocate.

## CLI

| Command | Purpose |
|---|---|
| `patchy validate` | Validate `config/` without network access |
| `patchy plan [--builds KEYS]` | Validate and write `tag`, `name`, `matrix` to `$GITHUB_OUTPUT` |
| `patchy fetch [--builds KEYS]` | Download the patcher CLI and the needed bundles, write `build/manifest/bundles.json` |
| `patchy build [--app KEY]` | Download, verify and patch one build (`all` runs every build); writes `build/out/` |
| `patchy sign` | Zipalign and sign everything in `build/artifacts/` into `build/signed/` |
| `patchy publish` | Create the release from `build/signed/`, upload, clean up, notify |
| `patchy pin APP [--sha256 HEX]` | Promote a pending fingerprint to `pins/known.json` and commit |
| `patchy pin --collect DIR` | Record fingerprints reported by build status files into `pins/pending.json` |
| `patchy toolchain [--no-install]` | Find (and install the newest) Android build-tools; exports `APKSIGNER` and `ZIPALIGN` to `$GITHUB_ENV` |

`--builds` also reads the `BUILDS` environment variable.

## Environment reference

Matched case-insensitively by `core/settings.py`.

| Variable | Used for |
|---|---|
| `GITHUB_TOKEN`, `GITHUB_REPOSITORY` | GitHub API calls and release creation |
| `TARGET_APP` | Default for `patchy build --app` |
| `KS_PATH`, `KS_PASSWORD`, `KS_ALIAS`, `KEY_PASSWORD` | Signing key, read only by `patchy sign` |
| `APKSIGNER`, `ZIPALIGN` | Override the tool paths |
| `ANDROID_HOME`, `ANDROID_SDK_ROOT` | Where to look for build-tools and `sdkmanager` |
| `FLARESOLVERR_URL`, `FLARESOLVERR_TIMEOUT` | FlareSolverr endpoint (default `http://localhost:8191/v1`) and per-page timeout |
| `DOWNLOAD_TIMEOUT`, `PATCH_TIMEOUT`, `TOOL_TIMEOUT` | Seconds for downloads, silence limit of the patcher, and `apksigner`/`zipalign`/`sdkmanager` runs |
| `SKIP_SIGNATURE_VERIFY` | Skip the original certificate check (local use only) |
| `KNOWN_PINS_PATH`, `PENDING_PINS_PATH` | Override `pins/known.json` and `pins/pending.json` |
| `APPS_DIR`, `BUNDLES_PATH`, `COMPANIONS_PATH` | Override the config locations |
| `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `APPRISE_URLS` | Notifications |
| `RELEASE_TAG`, `RELEASE_NAME` | Set from the plan job's outputs; required by `patchy publish` |
| `UPLOAD_CONCURRENCY` | Parallel asset uploads (default 6) |
| `PATCHY_BUILD_DIR` | Relocate `build/` |
| `NO_COLOR`, `GITHUB_ACTIONS` | Console colors and GitHub annotation output |

## Tests and style

`pytest` runs without network access: HTTP sessions, subprocesses and the patcher are replaced by fakes. Style is enforced by `ruff` (line length 115, rule sets `E`, `F`, `I`, `UP`, `B`, `SIM`) and `mypy`. The code base carries no comments or docstrings.
