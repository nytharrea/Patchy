# Patchy

A GitHub Actions pipeline that downloads Android APKs, patches them (ReVanced-style, through the `morphe-desktop` CLI), signs them with your own release key using the latest `apksigner`, and publishes everything together as a single GitHub Release. It runs entirely on GitHub-hosted runners, so no local machine is needed.

Patchy is an independent project. It is not affiliated with the Morphe or ReVanced projects; it downloads and runs their published tools.

## How it works

`release.yml` runs as four jobs:

1. **plan** validates `config/`, computes the release tag, name and build matrix, and downloads the patcher CLI plus every patch bundle once for the whole run.
2. **build** runs one runner per build, in parallel. Each runner downloads the original APK (APKMirror through a FlareSolverr sidecar, or a GitHub release), checks its signing certificate against `pins/known.json`, and patches it. This job runs third-party patch code, so it holds no signing key and only a read-only token.
3. **release** downloads every built APK, zipaligns and signs it with the newest `apksigner`, verifies the result, attests build provenance, creates one GitHub Release with release notes, uploads the APKs (plus MicroG and PotHelper when YouTube or YT Music was built), removes older Patchy releases, and sends a notification.
4. **cleanup** deletes old workflow runs.

A separate `ci.yml` runs `ruff`, `mypy` and `pytest` on every push and pull request, and also hosts two maintenance jobs you can start by hand: one that regenerates `uv.lock`, and one that fixes lint and formatting.

## Quick start

1. Push this repository to your own GitHub account.
2. Follow [Getting started](docs/getting-started.md): permissions, signing secrets, the first `uv.lock`, and the first release.
3. Edit `config/apps/<app>.yaml` to change what gets built. See [Configuration](docs/configuration.md).

## Documentation

| Page | What it covers |
|---|---|
| [Getting started](docs/getting-started.md) | Repository settings, secrets, first lock file, first run, pinning certificates |
| [Configuration](docs/configuration.md) | `config/apps/*.yaml`, `config/bundles.yaml`, `config/companions.yaml` |
| [Apps](docs/apps.md) | Every build that ships today and how to add a new app |
| [Signing](docs/signing.md) | Key isolation, `apksigner`, certificate pins, verifying a downloaded APK |
| [Workflows](docs/workflows.md) | Jobs, inputs and artifacts of `release.yml` and `ci.yml` |
| [Development](docs/development.md) | Project layout, `uv`, tests, CLI and environment reference |
| [Troubleshooting](docs/troubleshooting.md) | Common failures and what to do about them |

## Layout

```
patchy/
├─ config/        apps/, bundles.yaml, companions.yaml
├─ src/patchy/    cli.py, catalog/, fetch/, engine/, publish/, core/
├─ tests/         mirrors src/patchy
├─ pins/          known.json, pending.json
├─ site/          static site files
├─ docs/
├─ build/         all generated files (ignored by git)
└─ .github/workflows/   ci.yml, release.yml
```

## License

[GPL-3.0](LICENSE). Forks and modified versions stay under the same license.
