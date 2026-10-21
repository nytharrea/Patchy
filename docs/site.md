# Site

`site/` is a static GitHub Pages site: a download page for the latest release with one-tap Obtainium links, plus short pages on how the pipeline works, how to verify an APK and how to install. There is no build step. The workflow copies the folder and adds one generated file.

The page ships in Turkish and English. It picks the language from the browser, remembers a manual choice and follows the system light or dark theme until the visitor picks one.

## Deploy

`.github/workflows/pages.yml` runs on every push to `main` that touches `site/`, `config/`, `src/patchy/catalog/`, the catalog script or the workflow itself, and on manual dispatch.

1. `configure-pages` resolves the public URL.
2. `uv sync --locked --no-dev` installs the project.
3. `site_catalog.py` writes `data/catalog.json` into a copy of `site/`.
4. `__SITE_URL__` in every `.html` file is replaced with the real URL.
5. The folder is uploaded and deployed.

Set it up once: **Settings → Pages → Build and deployment → Source: GitHub Actions**. When the `AUTOMERGE_TOKEN` secret exists, `configure-pages` turns Pages on by itself (`enablement: true`). With only the default token it cannot, so the setting has to be changed by hand the first time.

## Data

| Source | Produced | Holds |
|---|---|---|
| `data/catalog.json` | `.github/scripts/site_catalog.py`, at deploy | Repository, every build (key, app, title, file name, tag, variant, package, icon, architecture, category, APK source, bundles) and companions |
| `GET /repos/{repo}/releases/latest` | The visitor's browser | Asset names, sizes, download counts and dates |

The catalog comes from the same `patchy.catalog` module the release workflow uses, so file names on the page cannot drift from file names in the release. The browser matches assets to builds with a port of `match_asset` from `patchy.publish.assets`, and `tests/site` checks that every file name the catalog implies resolves back to its build through `match_asset`.

The release response is cached in `localStorage` for 10 minutes. If GitHub cannot be reached, a cached response up to 7 days old is shown with a notice. Unauthenticated GitHub API calls are limited per IP address, which the page reports as a retry notice instead of an empty list.

If `catalog.json` is missing, the page falls back to the asset names in the release and links Obtainium to the repository.

Icons are loaded by the visitor's browser from the `icon:` URL in each `config/apps/*.yaml`. When one fails to load, a letter badge replaces it.

## Obtainium links

Each card builds an `obtainium://app/<json>` link from the catalog: package name, repository URL, and an APK filter that matches only that build's file name (`^Name-\d.*\.apk$`, or `^Name-.+-<tag>\.apk$` for builds that share an app, such as the TikTok variants). Pre-releases are excluded and older releases are used as a fallback.

## Preview locally

```
mkdir -p build/site
cp -R site/. build/site/
uv run python .github/scripts/site_catalog.py
python3 -m http.server 8000 --directory build/site
```

Open `http://localhost:8000`. Outside GitHub Actions the repository comes from `<meta name="patchy-repo">` in `index.html`, so change it there when testing a fork.

## Files

| Path | Role |
|---|---|
| `index.html` | All content, in Turkish |
| `404.html` | Not found page |
| `assets/style.css` | Design tokens, layout, light and dark themes |
| `assets/i18n.js` | Turkish and English strings |
| `assets/app.js` | Cards, search, sort, filters, details sheet, navigation |
| `assets/data.js` | Catalog and release loading, asset matching, Obtainium links |
| `assets/hero.js` | The draggable glass lens over the wordmark |
| `assets/boot.js` | Sets theme and language before first paint |
| `assets/vendor/` | `glassy-liquid` build and its license |
| `assets/fonts/` | Inter subsets and the OFL text |
| `THIRD_PARTY_NOTICES.txt` | Attribution for bundled third-party files |

## Customizing

| Change | Where |
|---|---|
| Text in either language | `assets/i18n.js` (Turkish text on the page itself lives in `index.html`) |
| Accent and surface colors | The tokens at the top of `assets/style.css` |
| Category of a new app | `CATEGORIES` in `.github/scripts/site_catalog.py`; unlisted apps show up under `other` |
| Display name of a build | `TITLES` in the same script |

A new app in `config/apps/` appears on the site after the next deploy with no other change.

## Third-party files

The liquid glass controls come from [glassy-liquid](https://github.com/9und30/glassy-liquid) (MIT), built from the commit named in `THIRD_PARTY_NOTICES.txt`. Inter is under the SIL Open Font License. Both licenses ship next to the files.

Real backdrop refraction needs `backdrop-filter: url(#svg)`, which only Chromium-based browsers support. Other browsers get the same layout with a frosted glass look instead.

The page sets a Content Security Policy that allows scripts only from the site itself and API calls only to `api.github.com`.
