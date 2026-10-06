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
| `arch` | yes | Architecture kept by `--striplibs`, usually `arm64-v8a` |
| `icon` | yes | Icon URL shown in the release notes |
| `apk_source` | yes | Where the original APK comes from, see below |
| `builds` | yes | One or more builds of this app |

### `apk_source`

| Type | Fields | Notes |
|---|---|---|
| `apkmirror` | `org`, `slug`, optional `release_slug` | Scraped through the FlareSolverr sidecar. `release_slug` is needed only when release page URLs use a different word than the folder `slug` |
| `github` | `owner`, `repo`, optional `asset_hint`, `tag_template` | Downloaded straight from a GitHub release; no FlareSolverr involved |

### Build fields

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | Unique across all files. It is the CI matrix entry and appears in release file names |
| `bundles` | yes | One or more keys from `config/bundles.yaml` |
| `display_name` | no | Overrides the app's name for this build |
| `exclude` | no | List of patch names passed as `--disable` |
| `enable` | no | List of patch names passed as `--enable` |
| `options` | no | Mapping of `"Patch name.optionKey"` to a value, passed as `-O` options |
| `force_version` | no | Skip version discovery and fetch this version |
| `force_build` | no | Pick an APKMirror variant whose build text matches this value |

When several builds of one app share a display name, the release file name gets a suffix taken from the first bundle's repository owner (or the build key when that is not unique).

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
