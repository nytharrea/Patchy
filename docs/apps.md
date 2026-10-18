# Apps

Each row is one **build**: a `key` under some app's `builds:` list in `config/apps/<slug>.yaml`. The key is what the `builds` input of the Release workflow and `patchy build --app` take. Certificate pins in `pins/` are keyed by the owning **app slug** instead, because every build of one app starts from the same original APK.

Several rows patch the same app from a different bundle (for example `tiktok` and `tiktok-hxreborn`). They are separate, independently downloaded and patched builds, not duplicates.

| Build key | App slug | Package | Source | Bundle(s) |
|---|---|---|---|---|
| `brave` | `brave` | `com.brave.browser` | GitHub | 🌙 Kveld |
| `capcut` | `capcut` | `com.lemon.lvoverseas` | APKMirror | 🌌 Kveld Extra |
| `discord` | `discord` | `com.discord` | APKMirror | 🪐 Venus |
| `facebook` | `facebook` | `com.facebook.katana` | APKMirror | 📘 Hushfacebook |
| `fairemail` | `fairemail` | `eu.faircode.email` | APKMirror | 💎 Heval |
| `gboard` | `gboard` | `com.google.android.inputmethod.latin` | APKMirror | ⌨️ JasonWu Gboard |
| `google-photos` | `google-photos` | `com.google.android.apps.photos` | APKMirror | 📷 Akash-Sriram |
| `inshot` | `inshot` | `com.camerasideas.instashot` | APKMirror | 🎬 Hooman's Patches |
| `instagram` | `instagram` | `com.instagram.android` | APKMirror | ✖️ Piko |
| `instagram-hushgram` | `instagram` | `com.instagram.android` | APKMirror | 📸 HushGram |
| `inure-github` | `inure-github` | `app.simple.inure` | GitHub | ⚡ Rushiranpise |
| `inure-play` | `inure-play` | `app.simple.inure.play` | GitHub | ⚡ Rushiranpise |
| `messenger` | `messenger` | `com.facebook.orca` | APKMirror | 💬 HushMessenger |
| `notesnook` | `notesnook` | `com.streetwriters.notesnook` | APKMirror | 🔥 hxreborn |
| `proton-mail` | `proton-mail` | `ch.protonmail.android` | APKMirror | 🔥 hxreborn |
| `proton-pass` | `proton-pass` | `proton.android.pass` | APKMirror | ⚡ Rushiranpise, 🔥 hxreborn |
| `proton-vpn` | `proton-vpn` | `ch.protonvpn.android` | APKMirror | 🔥 hxreborn |
| `reddit` | `reddit` | `com.reddit.frontpage` | APKMirror | 🟢 Morphe |
| `reddit-adobo` | `reddit` | `com.reddit.frontpage` | APKMirror | 🥘 Adobo |
| `speedtest` | `speedtest` | `org.zwanoo.android.speedtest` | APKMirror | ⚡ Rushiranpise, 🟢 Morphe |
| `symfonium` | `symfonium` | `app.symfonik.music.player` | APKMirror | 🔥 hxreborn |
| `tiktok` | `tiktok` | `com.zhiliaoapp.musically` | APKMirror | 🎵 TikTok Patches, 🟢 Morphe |
| `tiktok-hxreborn` | `tiktok` | `com.zhiliaoapp.musically` | APKMirror | 🔥 hxreborn TikTok, 🟢 Morphe |
| `tiktok-bluedragon` | `tiktok` | `com.zhiliaoapp.musically` | APKMirror | 🔷 BlueIT Service, 🟢 Morphe |
| `tiktok-hushfeed` | `tiktok` | `com.zhiliaoapp.musically` | APKMirror | 🤫 Hushfeed, 🟢 Morphe |
| `tiktok-kveld` | `tiktok` | `com.zhiliaoapp.musically` | APKMirror | 🌙 Kveld, 🟢 Morphe |
| `tiktok-wake-old-hyphen` | `tiktok` | `com.zhiliaoapp.musically` | APKMirror | 🌀 Wake-Old-Hyphen, 🟢 Morphe |
| `twitter` | `twitter` | `com.twitter.android` | APKMirror | ✖️ Piko |
| `twitter-x` | `twitter` | `com.twitter.android` | APKMirror | 🆕 Piko NewX, 🟢 Morphe |
| `warp` | `warp` | `com.cloudflare.onedotonedotonedotone` | APKMirror | ⚡ Rushiranpise |
| `youtube-music` | `youtube-music` | `com.google.android.apps.youtube.music` | APKMirror | 🟢 Morphe |
| `youtube` | `youtube` | `com.google.android.youtube` | APKMirror | 🟢 Morphe |

"APKMirror" is scraped through the FlareSolverr sidecar that clears Cloudflare. "GitHub" is downloaded directly from a release asset, which is faster and needs no FlareSolverr.

## Notes

- `instagram-hushgram` sets `force_build: "385611438"`, the one Instagram build code HushGram declares. Patchy now reads declared build codes from the patch bundle by itself (see [Configuration](configuration.md#how-the-apkmirror-variant-is-chosen)), so this pin is only a safety net and can be removed.
- `discord` is patched with the Venus bundle, which targets exactly one release written as `348.10 - Stable`. APKMirror lists it as a single universal APK Bundle (`.apkm`), and Patchy follows the bundle's version, so a newer Venus release moves the build on by itself. Its release address uses the channel (`discord-talk-play-hang-out-348-10-stable-release`) and the file is named `Discord-348.10-Stable.apk`. The first run stops at the certificate pin, as for every new app.
- `warp` sets `label: "1.1.1.1"`. The patched app showed `@string/four_ones` as its name, because its manifest label was plain text instead of a resource reference. Patchy repairs such labels on its own; the explicit `label` makes the name independent of how the patcher left the attribute, see [App name](configuration.md#app-name).
- `brave` and `tiktok-kveld` use the same `kveld` bundle (`kveld9/kveld-morphe-patches`), which is downloaded once per run. The `dh6k` bundle stays in `config/bundles.yaml` unused.
- `brave` downloads Brave's own single-file build, `BraveMonoarm64.apk` from the `v<version>` release of `brave/brave-browser`, instead of APKMirror. The kveld patches are written for that file. APKMirror serves the Google Play split bundle, a different compilation of the same release, and its first patch (`Better Tab Closing`) stops with `Failed to match the fingerprint`. Both builds carry the same signing certificate, so the `brave` pin is the same for either source.
- `capcut` is patched with the Kveld Extra bundle (`kveld9/kveld-extra-morphe-patches`), which targets one CapCut release at a time. No version is pinned, so Patchy follows the bundle and a newer bundle release moves the build on by itself. APKMirror lists CapCut 19.8.0 twice with the same build code, as a 120-640dpi bundle and as a `nodpi` APK. The bundle declares no build codes, so the default rule takes the plain `nodpi` APK, which is the file the patches are written for. APKMirror's release address says `capcut-video-editor` instead of the folder name `capcut`, which is what `release_slug` is for. The original certificate is already in `pins/known.json` (the value APKMirror lists for the APK, which is also the one the patches' signature bypass expects), so the first run does not stop at the pin.

## Adding a new app

1. Create `config/apps/<slug>.yaml` with the app's `pkg`, `display_name`, `arch`, `icon`, an `apk_source` and at least one build. See [Configuration](configuration.md) for every field.
2. If the app uses a patch bundle that is not in `config/bundles.yaml` yet, add it there (`owner`, `repo`, `label`).
3. Run `patchy validate` to catch mistakes such as an unknown bundle key or `exclude` written as a string instead of a list. CI runs it too.
4. Run the Release workflow with `builds` set to the new key. It stops on purpose with a pending-certificate message the first time; follow [Pinning original certificates](getting-started.md#5-pinning-original-certificates) and run it again.

The CI matrix is generated from `config/apps/`, so there is no second list to keep in sync.
