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
| `display_name` | yes | Name used in release asset file names and notes |
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
| `bundles` | yes | One or more keys from `config/bundles.yaml` |
| `display_name` | no | Overrides the app's name for this build |
| `exclude` | no | List of patch names passed as `--disable` |
| `enable` | no | List of patch names passed as `--enable` |
| `options` | no | Mapping of `"Patch name.optionKey"` to a value, passed as `-O` options |
| `force_version` | no | Skip version discovery and fetch exactly this version, even when its release page is missing. The bundle's build codes for it are still looked up |
| `force_build` | no | Only consider APKMirror rows whose text contains this value, such as a build code or a density. Rarely needed, see [How the APKMirror variant is chosen](#how-the-apkmirror-variant-is-chosen) |

When several builds of one app share a display name, the release file name gets a suffix taken from the first bundle's repository owner (or the build key when that is not unique).

### How the version is chosen

Patchy asks the patcher (`list-versions`) which versions the selected bundles support, ranks them by the number of patches that apply and then by version number, and downloads the first. A bundle can support a version before APKMirror lists it, or APKMirror can list it only as another kind of build (an F-Droid build, for example). When there is no release page for the chosen version, Patchy moves on to the next supported one, three at the most, and the log names the version it moved to. A version pinned with `force_version` is never replaced. When the bundles list no version at all, the newest release on APKMirror is used.

Some bundles list a version together with its release channel, for example `348.10 - Stable` for Discord. Patchy turns that text into the lowercase, dash-separated form APKMirror uses in release addresses (`discord-talk-play-hang-out-348-10-stable-release`) and writes it into the release file name without spaces (`Discord-348.10-Stable.apk`). `force_version` takes the text exactly as the patcher prints it.

### How the APKMirror variant is chosen

One APKMirror release often lists many variants of the same version: several CPU architectures, different minimum Android levels and screen densities, each with its own build code (Android's `versionCode`). A patch bundle is written against specific builds, so a wrong variant downloads fine and then fails to patch. Patchy applies the same rule as Morphe Manager:

1. The CLI's `list-versions` prints the build codes a bundle declares per architecture, for example `582.0.0.50.54 [versionCodes: ARM64_V8A=475417104, ARMEABI_V7A=475417036]`. Patchy reads them for the selected version, also when the version is pinned with `force_version`.
2. On the release page it keeps the rows that fit the app's `arch` (universal rows fit any architecture) and takes the row whose build code is the one declared for that `arch`. A code the bundle declares for another architecture, found on a row that fits the `arch`, is the second choice.
3. When the bundle declares no build code, the original rule applies: plain APKs before bundles, `nodpi` before `anydpi` before a specific density, and the first listed row wins. Instagram builds only consider bundle rows.
4. When the bundle declares codes but no row carries one of them, the original rule applies as well and the log carries a warning that names the declared codes.

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
