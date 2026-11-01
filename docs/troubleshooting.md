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

No patch in the selected bundles is compatible with the downloaded version. Patchy then steps down to the next version the bundles support (three at the most), and the build fails with this message only when every candidate failed, see [Stepping down to an older version](configuration.md#stepping-down-to-an-older-version). To patch a version the bundles do not list, set `force: true` for the build, see [Forced patching](configuration.md#forced-patching); to stay on one version, pin it with `force_version`; or wait for the bundle to support the new release. The `Executing command` line of the build log lists the bundle files that were passed to the patcher, and the tag of each bundle is in the plan job's log and in `bundles.json`.

## `Newer versions could not be used` in the release notes

Not an error. The release carries an older version of the app than the newest one the patch bundles support, because the newer one failed: it could not be downloaded, or the patcher could not patch it. The line names every version Patchy gave up with the stage (`download` or `patch`) and the reason, for example `20.2.1 (patch: Hide ads: Failed to match the fingerprint)`. The notification says `newer not usable`, and `status-<key>.json` keeps the same list under `attempts`. The next only-changed run builds the app again, because a newer bundle release may fix it. To stay on one version for good, pin it with `force_version`; to try the newer one anyway, see [Forced patching](configuration.md#forced-patching). See also [Stepping down to an older version](configuration.md#stepping-down-to-an-older-version).

## `Patched with --force, so the patches were not checked against this version`

The build has `force: true` and the version it patched is one the patch bundles do not list, so the patcher skipped its compatibility check. The APK is published, but test it before you rely on it. Remove `force: true` from the build to go back to the versions the bundles support. See [Forced patching](configuration.md#forced-patching).

## Warnings in the release notes

The build succeeded, but Patchy noticed something that may not be what you wanted. The release notes show the first three warnings of an app, the build log shows all of them, and `status-<key>.json` keeps them under `warnings`.

- `enable: "Name" is not a patch for <package> in <bundles> (did you mean "Other name"?)`: a name in `exclude`, `enable` or `options` is not a patch of the bundles for this app. The patcher ignores unknown names without a word, so the setting did nothing. Fix the name, see [Patch names are checked](configuration.md#patch-names-are-checked).
- `The downloaded APK is <package>, but this build is configured for <package>` or `The downloaded APK reports version X, but Y was requested`: the file that came from APKMirror or GitHub is not what the build asked for. Check `pkg`, the `apk_source` of the app and `force_version`. Patching went on, so the result is probably wrong.
- `The downloaded APK ships native libraries for ... but not for <arch>`: the original has no libraries for the architecture the patcher keeps, so the patched app may not start. Check `arch` and the variant APKMirror chose, see [How the APKMirror variant is chosen](configuration.md#how-the-apkmirror-variant-is-chosen).
- `The patched APK still holds native libraries for ...`, `The patched APK lost the <arch> native libraries of the original` or `The manifest of the patched APK could not be read`: the output differs from what `--striplibs` should leave. The APK is still published; install it and check that the app starts.

A patched APK without `classes.dex`, or one that is not a readable APK at all, is not a warning: the build fails with `The patched APK has no classes.dex, so it cannot be a working app`.

## `The patcher wrote no readable result file, so the applied patches are not listed`

Patchy asks the patcher for a result file (`--result-file`) to learn which patches were applied and which failed. When the file is missing or is not valid JSON, usually because the patcher crashed before it wrote it, the APK is still built and published. Its release notes then do not list the applied patches, and a failed build is explained by the patcher's output instead of the patch that failed.

## `No APKMirror release page found for version <version>`

APKMirror has no release page for that version. Patchy already tried the next versions the bundle supports (three at the most), so every one of them is missing, or the version is pinned with `force_version`. Check the app's page on APKMirror, run the build again once the upload is there, or pin another version.

## `None of the N arm64-v8a builds listed on APKMirror has a build code the patch bundle declares`

Patchy asked the patch bundle which build code it was written for and found no such build on the release page, so it fell back to the default variant, which often fails to patch. Common causes: APKMirror has not published that build yet (run the build again later), the bundle declares a build for another architecture than the app's `arch`, or the bundle and the listed release have drifted apart. The build log shows the declared codes and the variants that were considered; `force_build` can pin a different row.

## `The build pinned with force_build is not one the patch bundle declares`

The row selected by `force_build` has a build code the bundle does not declare for that version, so patching may fail. Remove the pin to let Patchy choose the declared build, or update the value. See [How the APKMirror variant is chosen](configuration.md#how-the-apkmirror-variant-is-chosen).

## `The patch rejected build code N and accepts ...`

The bundle checks the build code of the APK while patching, and the build Patchy downloaded is not one it was written for (`This build (version code N) isn't supported yet` or `version code N is not supported` in the patcher's output; bundles reword that message between releases, and Patchy recognises the usual wordings: not supported, isn't supported, unsupported, incompatible, not compatible). Patchy then fetches one of the accepted builds from APKMirror and patches again, so on its own this line is only a warning and adds one more download to the build. If the build still fails with `None of the N arm64-v8a builds listed on APKMirror for <version> has a build code the patch accepts`, APKMirror lists no accepted build yet: run the build again later, or pin another version with `force_version`. The release page is saved as `no-accepted-build-<app>-*.html` in the run's `diagnostics-*` artifact. See [How the APKMirror variant is chosen](configuration.md#how-the-apkmirror-variant-is-chosen).

## `The patch bundle lists <versions> as experimental, and building it failed`

Not an error by itself. The bundle supports the newest version only as an experimental one, and patching it (or finding its release on APKMirror) failed, so Patchy went on with the newest stable version, as the next line of the log says, and publishes that file when it succeeds. To stop trying the experimental version altogether, pin a version with `force_version`. If the stable version fails too, the build stops with the message of that second failure; see [How the version is chosen](configuration.md#how-the-version-is-chosen).

## `Failed to match the fingerprint`

A patch found nothing to change in the APK it was given, and the whole patching stopped. There are four usual reasons, and the log tells which one applies:

- The bundles of the build were built for different versions of Morphe Patcher, and the patcher applied the rules of the newest one to all of them. The output then has the line `Patches built for an older version of Morphe Patcher are applied with the behavior of Morphe Patcher 2.0.0 ...`. Patchy patches again by itself, see the next entry.
- The version is experimental: Patchy then falls back to a stable version by itself, see the entry above.
- The file is another compilation of the same release than the one the patch is written for, for example a plain APK where the bundle expects a split bundle (`.apkm`). The `VARIANT:` line shows `apk` or `bundle` for the chosen row. Set `apk_type` for the build, see the entry below.
- The app moved on and the bundle has not followed yet. Wait for a newer bundle release, or pin the version the bundle supports with `force_version`.

## `Patching failed while patch bundles built for different versions of Morphe Patcher were used together`

The patcher follows the newest bundle of a build: when one of them is built for Morphe Patcher 2.0.0 or later (the `morphe` bundle that adds `Disable Play Store updates` to the TikTok builds, for example), the fingerprints of every other bundle are matched by the new, stricter rules, and a bundle built for an older version can fail on an app it patches fine on its own. The first attempt, made with all bundles, failed, so Patchy read the version each bundle declares and patched the same APK a second time without the bundles built for the newer one. The line names every bundle with its version and the ones that were left out.

When the second attempt succeeds, the APK is published without the patches that only the left-out bundle provides, which for the TikTok builds is `Disable Play Store updates`. Nothing needs to be changed: once the bundle of the app is rebuilt for Morphe Patcher 2.0.0, the first attempt works again and the patch comes back. When the second attempt fails as well, the error below it is the real reason, usually one of the others in the entry above, and the build fails with it.

No second attempt is made, and the first failure stands, when all bundles were built for the same side of Morphe Patcher 2.0.0, when a bundle does not declare its version (the manifest of the `.mpp` file has no `Patcher-Version` line), or when the build has a single bundle. See [Bundles built for different versions of Morphe Patcher](configuration.md#bundles-built-for-different-versions-of-morphe-patcher).

## `apk_type is "bundle", but the build picked on APKMirror is a plain APK`

The build asks for one kind of APKMirror file with `apk_type`, and the release page has no row of that kind that fits the build's `arch` and `force_build`, or the build code the patch declares is only on a row of the other kind. The other kind was used and the patch may reject it. Check the release page on APKMirror: when the bundle is not listed yet, run the build again later; when the patch works with the plain APK after all, remove `apk_type` from the build.

## The installed app is named `@string/...`

The patched manifest stores the app name as plain text that looks like a resource reference (`@string/four_ones` for the 1.1.1.1 app), so Android shows that text as it is. Patchy repairs this after patching: the label of the application and of the launcher activities becomes the build's `display_name`, and the build log says `App name of <application> changed from '@string/four_ones' to '1.1.1.1'`. When a build still shows a wrong name, set `label` for it in its app file, see [App name](configuration.md#app-name). The warning `The app name of ... could not be checked` means the manifest could not be rewritten; the APK was then published as the patcher produced it, and the text after the colon tells why.

## `Nothing to build`

Not an error. A scheduled run, or a manual one with `only_changed` ticked, found the patcher, the patch bundles, the apps and the configuration unchanged since the last release, so it ended after the `plan` job and published nothing. To build anyway, start the **Release** workflow by hand with `only_changed` unticked. See [Only-changed runs](workflows.md#only-changed-runs).

## An app is in the release but was not rebuilt

The release notes say `Carried over from build-..., because this app was not rebuilt in this run`, and the notification lists the app under `carried over from the previous release`. Patchy copies the APK of every app a run did not produce from the previous release, so a release always holds all apps. Either nothing changed for the app, or the run built other apps only. When the note goes on with `The new build failed: <reason>`, the build of the app failed and its last good APK was kept: fix the reason and run the build again. Set the repository variable `CARRY_FORWARD` to `false` to publish only the apps a run built. See [Carried-over apps](workflows.md#carried-over-apps).

## Scheduled runs stopped

In a public repository GitHub switches scheduled workflows off after 60 days without repository activity. Open **Actions → Release** and enable the workflow again. Also check that `release.yml` still has its `schedule:` block and that the file is on the default branch.

## `Could not save patchy-state.json` or `patchy-state.json ... is not readable`

The state file is how an only-changed run knows what the last release was made from. When it cannot be uploaded, or the previous one cannot be read, nothing is lost except the comparison: the next only-changed run builds every selected app again and writes a new file. A release that predates this feature has none, so the first run after the update builds everything.

## The Morphe catalog cannot be loaded

The `discover.yml` workflow reads `https://morphe-patches.software/data/bundles.json`, a file that Patchy does not control. `Could not load the Morphe catalog: ...` means it could not be downloaded, because the site was down or answered with an error; run the workflow again later. `The Morphe catalog is not a JSON object` or `The Morphe catalog lists no apps and no bundles` means the file loaded but does not look like the catalog Patchy expects, so the site changed its format and `src/patchy/fetch/morphe.py` needs an update. Only the report is affected; builds never read the catalog.

## `Keystore file not found at .../morphe-data/morphe.keystore`

Morphe CLI 1.18.2-dev.1 and 1.18.2-dev.2 check for the patcher's own default keystore before signing and abort when it does not exist, which is always the case on a fresh runner. Patchy starts the patcher with `--unsigned` (the release job signs with your key), so current versions never reach that check. If you still see this message, the workflow is running an older copy of Patchy.

## `No signing credentials for <app>.apk`

The release job has no usable keystore, and the patcher's output is unsigned, so nothing can be published. Set the four `KEYSTORE_*` secrets, see [Getting started](getting-started.md).

## Signing step: `apksigner sign failed`

The message ends with `apksigner`'s own output. The usual causes are a wrong `KEY_ALIAS`, a wrong `KEYSTORE_PASSWORD` or `KEY_PASSWORD`, or a `KEYSTORE_BASE64` value that is not a keystore. Affected apps are left out of the release and listed with this reason in the notification.

## `apksigner was not found`

The runner has no Android SDK build-tools. GitHub-hosted images include them; for other runners install the build-tools and set `ANDROID_HOME`, or set `APKSIGNER` to the binary.

## An APK from the Artifacts list will not install

`apk-<key>` artifacts are unsigned on purpose, because signing happens only in the `release` job, where the keystore is available. The installer answers `INSTALL_PARSE_FAILED_NO_CERTIFICATES` or "Missing META-INF/MANIFEST.MF". Use the APKs of the release. When the `release` job failed after signing, the signed files are kept for two days in the `signed-apks` artifact of the same run.

## `Failed to create release: ... body is too long (maximum is 125000 characters)`

The release description, which contains the notes of every patch bundle that was used, was longer than GitHub accepts. Current versions of Patchy shorten the notes themselves, see [Release description](workflows.md#release-description), so this message means the workflow is running an older copy of Patchy. A run that failed with it is not repaired by re-running it, because a re-run uses the commit of the original run. Start a new run after updating the repository.

## Release was created without the patch bundle notes

GitHub refused the description even after it was shortened. The warning `GitHub rejected the release description` in the `release` job log contains GitHub's answer. The APKs are published normally, and the notes of each bundle are on its own releases page.

## Release was created without MicroG or PotHelper

Companions are only uploaded when a build listed in their `for_builds` was published in the same run, and only if the companion repositories still ship an asset matching the configured `suffix`. Check `config/companions.yaml` and the `release` job log.

## Uploads fail with a 5xx or a rate-limit answer

Too many assets were being uploaded at the same time. Set `UPLOAD_CONCURRENCY` to a lower number (6 was the previous default) in the `Create the release, carry over unchanged apps and clean up old releases` step's `env:`. A failed upload fails the run, so run the workflow again.

## Old releases were not removed

Only releases whose tag starts with `build-` are removed, and the newest `KEEP_RELEASES` of them (default `1`, which is the previous release) are kept on purpose, see [Release retention](workflows.md#release-retention). A failed deletion is logged without failing the run. Check the `release` job log for the exact API response.
