# Apps

Each row is one **build**: a `key` under some app's `builds:` list in `config/apps/<slug>.yaml`. The key is what the `builds` input of the Release workflow and `patchy build --app` take. Certificate pins in `pins/` are keyed by the owning **app slug** instead, because every build of one app starts from the same original APK.

Several rows patch the same app from a different bundle (for example `tiktok` and `tiktok-hxreborn`). They are separate, independently downloaded and patched builds, not duplicates.

| Build key | App slug | Package | Source | Bundle(s) |
|---|---|---|---|---|
| `brave` | `brave` | `com.brave.browser` | APKMirror | 🦁 dh6k |
| `facebook` | `facebook` | `com.facebook.katana` | APKMirror | 📘 Hushfacebook |
| `fairemail` | `fairemail` | `eu.faircode.email` | APKMirror | 💎 Heval |
| `gboard` | `gboard` | `com.google.android.inputmethod.latin` | APKMirror | ⌨️ JasonWu Gboard |
| `google-photos` | `google-photos` | `com.google.android.apps.photos` | APKMirror | ⚡ Rushiranpise |
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

- `instagram-hushgram` sets `force_build: "385511871"`. HushGram is checked against exactly one Instagram build, which APKMirror lists as the arm64-v8a "480-640dpi" bundle of 449.0.0.52.84. Update this value when HushGram moves to a newer Instagram.

## Adding a new app

1. Create `config/apps/<slug>.yaml` with the app's `pkg`, `display_name`, `arch`, `icon`, an `apk_source` and at least one build. See [Configuration](configuration.md) for every field.
2. If the app uses a patch bundle that is not in `config/bundles.yaml` yet, add it there (`owner`, `repo`, `label`).
3. Run `patchy validate` to catch mistakes such as an unknown bundle key or `exclude` written as a string instead of a list. CI runs it too.
4. Run the Release workflow with `builds` set to the new key. It stops on purpose with a pending-certificate message the first time; follow [Pinning original certificates](getting-started.md#5-pinning-original-certificates) and run it again.

The CI matrix is generated from `config/apps/`, so there is no second list to keep in sync.
