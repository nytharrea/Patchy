# Troubleshooting

## `uv sync --locked` fails: lockfile missing or out of date

`uv.lock` does not match `pyproject.toml`. Run **Actions → CI → Run workflow** with **refresh_lock** ticked and merge the pull request it opens.

## CI fails on `ruff format --check` or `ruff check`

Run **Actions → CI → Run workflow** with **autofix** ticked, then merge the pull request. Any rule violation that cannot be fixed automatically is still reported by `check` on that pull request.

## `No pinned signature for <app>`

Expected the first time an app is built. See [Pinning original certificates](getting-started.md#5-pinning-original-certificates).

## `SIGNATURE MISMATCH`

The APK's certificate differs from the pin. Either the app changed its signing key (check the developer's announcement, then update the pin deliberately) or the file did not come from the developer. The build stops either way, on purpose.

## `pins/known.json is not valid JSON (line N, column M)`

The file was edited by hand and is broken, usually a trailing comma or a missing quote. Fix the reported position. Nothing is treated as unpinned and nothing is overwritten while the file is broken.

## `Cloudflare challenge could not be cleared`

APKMirror kept challenging every attempt and FlareSolverr could not clear it. The message names the page and the last HTTP status, and the page is saved under the run's `diagnostics-*` artifact. Re-run the affected build later; running fewer builds at once (`builds` input) helps.

## `Applying 0 patches`

No patch in the selected bundles is compatible with the downloaded version. Pin a compatible version with `force_version` in the build, or wait for the bundle to support the new release.

## Signing step: `apksigner sign failed`

The message ends with `apksigner`'s own output. The usual causes are a wrong `KEY_ALIAS`, a wrong `KEYSTORE_PASSWORD` or `KEY_PASSWORD`, or a `KEYSTORE_BASE64` value that is not a keystore. Affected apps are left out of the release and listed with this reason in the notification.

## `apksigner was not found`

The runner has no Android SDK build-tools. GitHub-hosted images include them; for other runners install the build-tools and set `ANDROID_HOME`, or set `APKSIGNER` to the binary.

## Release was created without MicroG or PotHelper

Companions are only uploaded when a build listed in their `for_builds` was published in the same run, and only if the companion repositories still ship an asset matching the configured `suffix`. Check `config/companions.yaml` and the `release` job log.

## Old releases were not removed

Only releases whose tag starts with `build-` are removed, and a failed deletion is logged without failing the run. Check the `release` job log for the exact API response.
