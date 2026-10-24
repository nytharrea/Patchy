# Site

`site/` is a static GitHub Pages site: a download page for the latest release with one-tap Obtainium links, plus short pages on how the pipeline works, how to verify an APK and how to install. There is no build step. The workflow copies the folder and adds one generated file.

The page ships in Turkish and English. It picks the language from the browser, remembers a manual choice and follows the system light or dark theme until the visitor picks one.

The palette is Turkuaz (Türk mavisi, `#30d5c8`) and Türk kırmızısı (`#e30a17`): turquoise carries the surfaces, glow and download buttons, red carries the thread, the main call to action and the warnings.

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
| `favicon.svg`, `apple-touch-icon.png` | Tab and home screen icons |
| `assets/og.png` | Link preview image (1200 x 630) |
| `assets/style.css` | Design tokens, layout, light and dark themes |
| `assets/i18n.js` | Turkish and English strings |
| `assets/app.js` | Cards, search, sort, filters, details sheet, navigation |
| `assets/data.js` | Catalog and release loading, asset matching, Obtainium links |
| `assets/backdrop.js` | Paints the wallpaper and the hero patch to canvases for browsers that cannot refract live content |
| `assets/hero.js` | The draggable glass lens over the wordmark: drag, glide, light that follows the pointer or the tilt of the phone |
| `assets/boot.js` | Sets theme and language before first paint |
| `assets/vendor/` | `glassy-liquid` build and its license |
| `assets/fonts/` | Inter subsets and the OFL text |
| `THIRD_PARTY_NOTICES.txt` | Attribution for bundled third-party files |

## Customizing

| Change | Where |
|---|---|
| Text in either language | `assets/i18n.js` (Turkish text on the page itself lives in `index.html`) |
| Turquoise and red | `--turquoise` and `--flag-red` at the top of `assets/style.css`, then the `--bg-*`, `--patch-*`, `--wm-stitch` and `--red-*` tokens in each theme block; `404.html`, `favicon.svg` and the two images carry the same colors |
| Surface colors | The tokens at the top of `assets/style.css` |
| Lens size and strength | `--lens-w` and `--lens-h` on `.stage` in `assets/style.css`; `tune()` in `assets/hero.js` derives bezel, refraction and dispersion from the lens height |
| Category of a new app | `CATEGORIES` in `.github/scripts/site_catalog.py`; unlisted apps show up under `other` |
| Display name of a build | `TITLES` in the same script |

A new app in `config/apps/` appears on the site after the next deploy with no other change.

## Third-party files

The liquid glass controls come from [glassy-liquid](https://github.com/9und30/glassy-liquid) (MIT), built from the commit named in `THIRD_PARTY_NOTICES.txt`. Inter is under the SIL Open Font License. Both licenses ship next to the files.

The page sets a Content Security Policy that allows scripts only from the site itself and API calls only to `api.github.com`.

## Glass in different browsers

Glass is drawn one of three ways. The choice is made at run time and shows as `data-glass` on `<html>` and as `data-glass-engine` on each glass element.

| `data-glass` | Browsers | How it is drawn |
|---|---|---|
| `live` | Chromium (Chrome, Edge, Brave, Opera, Samsung Internet) | `backdrop-filter: url(#svg)` refracts whatever is really behind the glass, page content included |
| `scene` | Firefox, Safari | The page is a `glass-scene`. `assets/backdrop.js` paints the wallpaper and the hero patch (wordmark, thread, seam) to canvases and WebGL refracts those, so the lens and the controls bend the wallpaper and the hero art. Cards and text behind a control are covered by its frosted fill instead of refracted |
| `frost` | Browsers without WebGL | Same layout with a plain frosted look |

Real refraction of live page content needs `backdrop-filter: url(#svg)`, which only Chromium supports. Cards, panels, chips and the status line are plain translucent CSS without `backdrop-filter`, and only the chrome (header, tab bar, search, segmented control, menu, sheet, call to action buttons, lens) is glass, which keeps scrolling smooth on phones.

The wallpaper canvas is capped at 2x pixel density and 6 megapixels, and is repainted on resize, theme change and zoom. The lens wakes the scene on every move, so its content never lags behind its position.

## Phones

- Apps are one full width card per row below 720 px (`minmax(0, 1fr)`, so a long package name is cut with an ellipsis instead of widening the page) and fill 2 or 3 columns above.
- The wallpaper uses `100lvh`, so the browser bar sliding away does not resize it. Side gutters and the floating tab bar respect safe-area insets.
- Touch targets are 44 to 48 px on coarse pointers. Below 390 px the card buttons tighten, and below 350 px the English download label drops its icon, so the row fits at 320 px in both languages.
- The lens is moved with one finger. Its light follows the tilt of the phone where the browser allows it without a permission prompt.

## Accessibility

`prefers-reduced-motion` skips the stitching animation and the lens intro and glide. `prefers-reduced-transparency` swaps glass for solid fills, `prefers-contrast: more` raises text and edge contrast, and forced colors drop the decoration and the lens.
