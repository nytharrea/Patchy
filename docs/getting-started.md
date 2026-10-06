# Getting started

## 1. Repository settings

**Settings → Actions → General**

- **Workflow permissions:** choose "Read and write permissions".
- **Allow GitHub Actions to create and approve pull requests:** tick it. The lock-file and autofix jobs open pull requests. If you would rather not enable this, create a personal access token with `repo` scope and store it as the `AUTOMERGE_TOKEN` secret; those jobs use it when present.

## 2. Secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required | Purpose |
|---|---|---|
| `KEYSTORE_BASE64` | For your own signing key | Your Android keystore (`.jks` or `.keystore`), base64-encoded |
| `KEYSTORE_PASSWORD` | With the above | The keystore password |
| `KEY_ALIAS` | With the above | The alias you chose when creating the key |
| `KEY_PASSWORD` | With the above | The key entry password (often the same as the keystore password) |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook for the run summary |
| `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` | No | Telegram notification, used together |
| `APPRISE_URLS` | No | Any other [Apprise](https://github.com/caronc/apprise#supported-notifications) target, separated by spaces, commas or newlines |
| `AUTOMERGE_TOKEN` | No | Personal access token used to auto-merge Dependabot pull requests and to open pull requests that trigger CI |

`GITHUB_TOKEN` is provided by GitHub Actions automatically.

Create a keystore once and keep it safe:

```bash
keytool -genkeypair -v -keystore release.keystore -alias <your-alias> -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 release.keystore
```

Paste the single line of output into `KEYSTORE_BASE64`.

Without the four `KEYSTORE_*` secrets the release job logs a warning and publishes the APKs with the patcher's shared default test key. That is fine for a quick trial, but every fork doing the same ends up with the same key, so set your own before relying on the builds.

## 3. Create `uv.lock`

Dependencies are declared only in `pyproject.toml`; `uv.lock` pins the exact tree. The lock file is created by CI:

1. **Actions → CI → Run workflow**, tick **refresh_lock**.
2. Open the pull request it creates and merge it.

From then on Dependabot (`uv` ecosystem) keeps the lock current. You can run the same job again at any time.

## 4. First release

**Actions → Release → Run workflow.**

| Input | Meaning |
|---|---|
| `builds` | Comma-separated build keys such as `youtube,gboard`, or `all` (default) |
| `pin` | An app slug to trust, see below. When set, nothing is built |
| `pin_sha256` | Optional: the fingerprint you verified, which must equal the pending one |

## 5. Pinning original certificates

Before patching, Patchy checks that the downloaded APK is signed by the certificate recorded for that app in `pins/known.json`. The first time an app runs there is no entry yet, so that build stops on purpose, and the release job records the fingerprint it saw in `pins/pending.json`.

1. Compare the fingerprint in the failed build's message (or in `pins/pending.json`) with an official source for the app: its Play Store listing, the developer's website, a trusted signature database.
2. **Actions → Release → Run workflow**, set **pin** to the app slug (for example `youtube`) and, optionally, **pin_sha256** to the fingerprint you verified. The job moves the value from `pins/pending.json` to `pins/known.json` and commits it.
3. Run the release again.

The same flow is available from a terminal as `patchy pin <app> [--sha256 HEX]`.

`pins/known.json` is validated strictly. If it is ever malformed, every command reports the file, line and column instead of treating the app as unpinned.
