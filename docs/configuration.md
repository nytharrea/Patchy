# Configuration

Everything Patchy builds is described by YAML files in `config/`. Nothing else needs to change when you add or remove an app: the build matrix is generated from these files at the start of every run.

```
config/
├─ apps/            one file per app, named <app-slug>.yaml
├─ bundles.yaml     the patcher CLI and every patch bundle repository
└─ companions.yaml  extra APKs published next to certain builds
```

Run `patchy validate` (or `uv run patchy validate`) to check the configuration without touching the network. CI does this on every push.

## `config/apps/<slug>.yaml`

The file name is the app slug. It is also the key used in `pins/known.json`.

```yaml
pkg: "com.reddit.frontpage"
display_name: "Reddit"
arch: "arm64-v8a"
icon: "https://cdn.simpleicons.org/reddit/FF4500"
apk_source:
  type: apkmirror
  org: "reddit-inc"
  slug: "reddit"
builds:
  - key: "reddit"
    bundles: ["morphe"]
    enable: ["Clone app", "Change installer source"]
  - key: "reddit-adobo"
    bundles: ["adobo"]
    enable: ["Change package name"]
    display_name: "Reddit-Adobo"
```

### App fields

| Field | Required | Meaning |
|---|---|---|
| `pkg` | yes | Android package name, passed to the CLI's `list-versions` |
| `display_name` | yes | Name used in release asset file names and notes. It is also the name Patchy puts on an app whose patched manifest lost its real name, see [App name](#app-name) |
| `label` | no | Name the installed app shows, written into the patched APK whatever the patcher produced, see [App name](#app-name) |
| `apk_type` | no | Kind of APKMirror file to prefer, `apk` or `bundle`. Every build of the app inherits it, see [How the APKMirror variant is chosen](#how-the-apkmirror-variant-is-chosen) |
| `arch` | yes | Architecture kept by `--striplibs` and looked for on APKMirror, usually `arm64-v8a` |
| `icon` | yes | Icon URL shown in the release notes |
| `apk_source` | yes | Where the original APK comes from, see below |
| `builds` | yes | One or more builds of this app |

### `apk_source`

| Type | Fields | Notes |
|---|---|---|
| `apkmirror` | `org`, `slug`, optional `release_slug` | Scraped through the FlareSolverr sidecar. `release_slug` is needed only when release page URLs use a different word than the folder `slug` |
| `github` | `owner`, `repo`, optional `asset_hint`, `tag_template` | Downloaded straight from a GitHub release; no FlareSolverr involved |

For `github`, `tag_template` turns the version the patch bundle supports into the release tag: `{version}` is replaced, and the default is `{version}` itself, so `v{version}` gives `v1.97.56` for version `1.97.56`. `asset_hint` is a part of the asset file name, matched without regard to case, that picks one `.apk` or `.apkm` file among the several a release may carry; with no match the `arm64` file, or else the first file, is taken. When the tag does not exist the latest release is used. The download is retried up to five times, a partial file is resumed, and the size is checked against the one GitHub reports.

### Build fields

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | Unique across all files. It is the CI matrix entry and appears in release file names |
| `bundles` | yes | One or more keys from `config/bundles.yaml`. List the bundle that carries the patches of the app first, see [Bundles built for different versions of Morphe Patcher](#bundles-built-for-different-versions-of-morphe-patcher) |
| `display_name` | no | Overrides the app's name for this build |
| `label` | no | Overrides the app's `label` for this build; `label: null` removes it |
| `apk_type` | no | Overrides the app's `apk_type` for this build; `apk_type: null` removes it. Only valid for `apkmirror` sources |
| `exclude` | no | List of patch names passed as `--disable` |
| `enable` | no | List of patch names passed as `--enable` |
| `options` | no | Mapping of `"Patch name.optionKey"` to a value, passed as `-O` options |
| `force_version` | no | Skip version discovery and fetch exactly this version, even when its release page is missing. The bundle's build codes for it are still looked up |
| `force_build` | no | Only consider APKMirror rows whose text contains this value, such as a build code or a density. Rarely needed, see [How the APKMirror variant is chosen](#how-the-apkmirror-variant-is-chosen) |
| `force` | no | `true` passes `--force` to the patcher, so it patches a version the patch bundles do not list. Read from the build only, never inherited from the app, see [Forced patching](#forced-patching) |

When several builds of one app share a display name, the release file name gets a suffix taken from the first bundle's repository owner (or the build key when that is not unique).

### Patch names are checked

`exclude`, `enable` and the part of an `options` key before the dot must name patches of the build's bundles. The patcher ignores a name it does not know, so a typo changes nothing and no error shows it. Before it downloads the app, Patchy asks the patcher for the patches of the build's package (`list-patches --filter-package-name`) and warns about every name that is not among them, with the closest real name when there is one:

`enable: "Clon app" is not a patch for com.reddit.frontpage in morphe (did you mean "Clone app"?); the patcher ignores unknown names, so this setting has no effect.`

The comparison ignores case, as the patcher does. The build goes on, and the warning appears in the release notes, the job log and `status-<key>.json`. When the list of patches cannot be read, the check is skipped and the log says so.

### App name

Android takes the name of an app from the `android:label` attribute of its `AndroidManifest.xml`. Normally that attribute is a reference to a string resource, which the system resolves when it shows the name. When the patched manifest holds the plain text of such a reference instead (`@string/four_ones`, for example), nothing resolves it, and the installer, the launcher and the app list show that text as the name of the app.

After patching, Patchy checks the label of the `<application>` element and of every launcher activity:

- A label that is the text of a resource reference is replaced by the build's `display_name`.
- A label that is a real resource reference, or ordinary text, is left alone.
- With `label` set, the build's name is written into all of those places whatever they contain. Use it when an app shows a wrong name although nothing looks broken, or when the app should carry another name than the original. Leave it out for builds whose patch bundle sets the name itself (a branding option, for example), or the patched name is overwritten. The name no longer follows the language of the device, because a fixed text cannot be translated.

Only `AndroidManifest.xml` is rewritten. The new name is appended to the manifest's string pool and the label attributes point to it. Every other file of the APK keeps its content, and the result is checked (same files, sizes and checksums, a readable zip, a second pass that finds nothing left to repair) before it replaces the patcher's copy. The patcher's own output is not touched. Zipalign and signing happen afterwards in the release job, as for every APK.

The build log shows what was done, for example `App name of <application> changed from '@string/four_ones' to '1.1.1.1'`, or `App name needs no repair`. When the manifest cannot be rewritten (an unexpected format, or `label` set for an APK that has no `android:label` to replace), the log carries a warning and the APK is published as the patcher produced it; the build does not fail.

### How the version is chosen

Patchy asks the patcher (`list-versions`) which versions the selected bundles support, ranks them by the number of patches that apply and then by version number, and downloads the first. A bundle can support a version before APKMirror lists it, or APKMirror can list it only as another kind of build (an F-Droid build, for example). When there is no release page for the chosen version, Patchy moves on to the next supported one, three at the most, and the log names the version it moved to. A version pinned with `force_version` is never replaced. A version that downloads but cannot be patched is replaced the same way, see [Stepping down to an older version](#stepping-down-to-an-older-version). When the bundles list no version at all, the newest release on APKMirror is used.

The list includes experimental versions, the ones a bundle supports but marks as not fully tested (`list-versions --include-experimental`). This is on for every app and is not a setting: the patcher accepts such a version when it is asked to patch, so the newest version a bundle can patch at all is the one that gets built. A newer experimental version can still fail, because a patch finds nothing to match in it or because APKMirror has no release for it yet. When the build then stops while patching, or none of the versions Patchy tried has a release page, Patchy asks `list-versions` once more without experimental versions and builds the newest stable version it has not tried yet. The log says `The patch bundle lists <versions> as experimental, and building it failed. Falling back to <version>, the newest stable version it supports.` The fallback happens at most once per build, never replaces a version pinned with `force_version`, and does not happen when the version that failed was a stable one.

Some bundles list a version together with its release channel, for example `348.10 - Stable` for Discord. Patchy turns that text into the lowercase, dash-separated form APKMirror uses in release addresses (`discord-talk-play-hang-out-348-10-stable-release`) and writes it into the release file name without spaces (`Discord-348.10-Stable.apk`). `force_version` takes the text exactly as the patcher prints it.

### Stepping down to an older version

The versions Patchy ranked are candidates in order, three at the most for an APKMirror source and one for a `github` source. When patching a version fails for good, which is after the retries described in this page (a second attempt with fewer bundles, and a build code the patcher accepts), the build goes on with the next candidate instead of ending. The next version is downloaded, checked against the pinned certificate and patched. A version that cannot be downloaded is skipped in the same way.

Every version that was given up is recorded with the stage it failed at (`download` or `patch`) and the reason. The release notes of the app say `Newer versions could not be used: 20.2.1 (patch: ...)`, the notification adds `newer not usable`, and `status-<key>.json` keeps the list under `attempts`. The log line is `Stepping down to <version>, the next version the patch bundle supports.` When the candidates are used up, the fallback to a stable version described above still applies, and then the build fails with the reason of the last attempt. A version pinned with `force_version` has no other candidate, so it never steps down.

An app that had to step down is built again by the next only-changed run, because a newer bundle release may fix the newer version, see [Only-changed runs](workflows.md#only-changed-runs).

### Forced patching

By default the patcher refuses an app version that none of the selected patches lists as compatible, and the build ends with `Applying 0 patches`. `force: true` on a build passes `--force` to the patcher, which then applies the patches without checking the version against them. It is meant for a version that is newer than what the bundle lists but changed so little that the patches still match. When they do not, the patch fails like in any other build.

```yaml
builds:
  - key: "youtube"
    bundles: ["morphe"]
    force: true
```

How the version is chosen with `force: true`:

- Without `force_version`, Patchy looks up the newest version first: the newest release on APKMirror, or the latest release of a `github` source, for which only that release is tried. `--force` is passed only when the bundles do not list that version; a version they do list is patched normally. The versions the bundles support follow as candidates and are never forced, so a build that cannot patch the newest version steps down to a listed one.
- With `force_version`, that version is patched with `--force`.
- When the newest version cannot be determined, the build runs without `--force` and the log says so.

A forced build is marked in `status-<key>.json` (`forced`), in the release notes (`Patched with --force, so the patches were not checked against this version.`) and in the notification. The setting is read from the build only and never inherited from the app, so forcing one build cannot change another. Because the result depends on a version that no bundle has declared, an APKMirror build with `force: true` is built on every only-changed run, see [Only-changed runs](workflows.md#only-changed-runs).

### How the APKMirror variant is chosen

One APKMirror release often lists many variants of the same version: several CPU architectures, different minimum Android levels and screen densities, each with its own build code (Android's `versionCode`). A patch bundle is written against specific builds, so a wrong variant downloads fine and then fails to patch. Patchy applies the same rule as Morphe Manager:

1. The CLI's `list-versions` prints the build codes a bundle declares per architecture, for example `582.0.0.50.54 [versionCodes: ARM64_V8A=475417104, ARMEABI_V7A=475417036]`. Patchy reads them for the selected version, also when the version is pinned with `force_version`.
2. On the release page it keeps the rows that fit the app's `arch` (universal rows fit any architecture) and takes the row whose build code is the one declared for that `arch`. A code the bundle declares for another architecture, found on a row that fits the `arch`, is the second choice.
3. When the bundle declares no build code, the original rule applies: plain APKs before bundles, `nodpi` before `anydpi` before a specific density, and the first listed row wins. Instagram builds only consider bundle rows.
4. When the bundle declares codes but no row carries one of them, the original rule applies as well and the log carries a warning that names the declared codes.
5. Some bundles, HushMessenger for one, list a version without build codes and check the build only while patching. When the patcher stops because it does not support the build (`This Messenger build (version code N) isn't supported yet`, or `version code N is not supported`, the wording changes from one bundle release to the next) and names the build codes it accepts, Patchy fetches the same version again, takes the row that carries one of those codes (the `VARIANT:` line then says `a build code the patch accepts`) and patches a second time. This happens once per build, only for APKMirror sources, and `force_build` still narrows the rows first. When APKMirror lists none of the accepted builds, the build fails with a message that names them.

`apk_type` settles the choice between rows that are equally good by build code. `bundle` takes APK Bundle rows (`.apkm`) before plain APKs, `apk` takes plain APKs before bundles, and the density order of rule 3 applies among the rows of the preferred kind. It is a preference and not a filter: a row with a better build code (rules 2 and 5) still wins, and when no row of the preferred kind fits, the other kind is used and the log warns `apk_type is "bundle", but the build picked on APKMirror is a plain APK, so the patch may reject it`. Set it for a bundle that is written for one kind of file. A bundle states that kind as `apkFileType` (`APK`, `APK_REQUIRED`, `APKM` or `XAPK_REQUIRED`), but the patcher's command line does not print it, so Patchy cannot read it by itself. The Proton VPN patches ask for an XAPK, for example, and `proton-vpn` sets `apk_type: "bundle"` for that reason.

The `VARIANT:` line of the build log is followed by the chosen row's build code, architecture, minimum Android, density and the reason it was chosen.

`force_build` comes first: only rows whose text contains the value are considered, and the declared build code then chooses among those. If the pinned row is not a declared build, the log warns that patching may fail. Because the bundle's own build code is used automatically, `force_build` is rarely needed.

## `config/bundles.yaml`

```yaml
cli:
  owner: MorpheApp
  repo: morphe-desktop

bundles:
  morphe:
    owner: MorpheApp
    repo: morphe-patches
    label: "🟢 Morphe"
```

`cli` is the patcher jar. Each entry under `bundles` is a repository whose newest release (prereleases included) ships a `.mpp` patch bundle. `label` appears in the release notes.

Every bundle is stored in its own folder, `build/tools/bundles/<key>/`, so two repositories that publish a file with the same name (a fork that mirrors upstream's version number, for example `patches-1.47.0.mpp`) never overwrite each other.

### Bundles built for different versions of Morphe Patcher

A patch bundle declares the version of Morphe Patcher it was built for in its manifest (`Patcher-Version`). A build with several bundles gives all of them to one run of the patcher, and the patcher follows the newest one. From Morphe Patcher 2.0.0 on, the strings of a fingerprint must equal a string of the method instead of only being contained in one, and the instruction filters of a fingerprint are retried differently. A bundle built for an older version is applied with these rules too, so a patch that finds its code when its bundle runs alone can stop finding it. The patcher warns about this in its output (`Patches built for an older version of Morphe Patcher are applied with the behavior of Morphe Patcher 2.0.0 ... and may not work as intended`), and the patching usually ends with `Failed to match the fingerprint` or `expected one candidate, found 0`.

Nothing has to be configured for this. A build is patched with all of its bundles first, which keeps every patch a helper bundle adds, such as `Disable Play Store updates` from `morphe`. When that fails, Patchy reads the `Patcher-Version` of the bundle files. If they were built for both sides of Morphe Patcher 2.0.0, it patches the same APK once more, without downloading anything again, with only the bundles built for the same side as the first bundle of the build. `enable`, `exclude` and `options` are passed again as they were, and the patcher ignores an `enable` name that none of the remaining bundles has. The log says `Patching failed while patch bundles built for different versions of Morphe Patcher were used together (...)` and names the bundles that were left out, and the run page shows it as a warning. The patches that only those bundles provide are missing from that APK. For the TikTok builds, which add `morphe` only for `Disable Play Store updates`, that is the one patch.

The second attempt is not made when all bundles were built for the same side of 2.0.0, when a bundle declares no version or cannot be read, for a build with a single bundle, when the patcher rejected the build code of the APK (Patchy then fetches another build, see [How the APKMirror variant is chosen](#how-the-apkmirror-variant-is-chosen)) and when no patch fitted the version (`Applying 0 patches`). The first bundle of a build is never left out, so list the bundle that carries the patches of the app first and the helper bundles after it. As soon as the bundle of the app is rebuilt for Morphe Patcher 2.0.0, the first attempt succeeds again on its own. If the second attempt fails too, the build fails with its error.

## `config/companions.yaml`

```yaml
microg:
  owner: MorpheApp
  repo: MicroG-RE
  for_builds: ["youtube", "youtube-music"]
  variants:
    - file: "MicroG.apk"
      suffix: "-arm64-v8a.apk"
      exclude: "noicon"
```

A companion is uploaded to the release whenever any build listed in `for_builds` was published. Each variant picks the release asset ending with `suffix` (and not containing `exclude`, case-insensitively) and uploads it under the name `file`. Companions are third-party APKs published as they are; Patchy does not re-sign them.

## Repository variables

Two optional repository variables (Settings → Secrets and variables → Actions → Variables) change what `patchy publish` does after a run. Without them the defaults apply.

| Variable | Default | Meaning |
|---|---|---|
| `KEEP_RELEASES` | `1` | How many older Patchy releases are kept next to the new one, see [Release retention](workflows.md#release-retention) |
| `CARRY_FORWARD` | `true` | `false` publishes only the apps a run built instead of copying the others from the previous release, see [Carried-over apps](workflows.md#carried-over-apps) |
