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
| `assets/backdrop.js` | Picks the glass engine (`data-glass`) and paints the wallpaper and the hero patch to canvases for browsers that cannot refract live content |
| `assets/glass.js` | Real glass surfaces for cards, panels and the status line: created near the viewport, removed far from it, three quality tiers |
| `assets/perf.js` | Frame-time governor that steps the glass tier down on phones that cannot keep up |
| `assets/world.js` | The scenery behind the glass: light arcs in turquoise and red, plus patches and stitched thread, laid out against the page, the card grid and the sections that hold glass |
| `assets/hero.js` | The draggable glass lens over the wordmark: drag, glide, light that follows the pointer or the tilt of the phone |
| `assets/boot.js` | Sets theme and language before first paint |
| `assets/vendor/` | `glassy-liquid` build and its license |
| `assets/fonts/` | Inter subsets and the OFL text |
| `THIRD_PARTY_NOTICES.txt` | Attribution for bundled third-party files |

## Customizing

| Change | Where |
|---|---|
| Text in either language | `assets/i18n.js` (Turkish text on the page itself lives in `index.html`) |
| Turquoise and red | `--turquoise` and `--flag-red` at the top of `assets/style.css`, then the `--bg-*`, `--patch-*`, `--world-*`, `--thread-*`, `--orb-*`, `--arc-*`, `--wm-stitch` and `--red-*` tokens in each theme block; `404.html`, `favicon.svg` and the two images carry the same colors |
| Surface colors | The tokens at the top of `assets/style.css`; the tint of each glass surface is `--glass-card-fill`, `--glass-panel-fill`, `--glass-pill-fill`, `--glass-bar-fill` or `--glass-field-fill` |
| Glass strength | `KINDS` in `assets/glass.js` sets the edge profile, bezel, refraction, blur, specular light and color fringing (dispersion) for cards, panels and the status line; the round and call to action buttons take `dispersion` and `specular` attributes in `index.html` |
| Where scenery appears | `ZONES` in `assets/world.js` lists the sections that get patches and thread; the light arcs run along the whole page |
| Light arcs | `--arc-a-*` (turquoise) and `--arc-b-*` (red) in each theme block set the colors, `--arc-dim` sets how much of the bright edge stays behind text, and `ARC_SPAN` in `assets/world.js` sets how often an arc appears |
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
| `scene` | Firefox, Safari | The page is a `glass-scene`. `assets/backdrop.js` paints the wallpaper and the hero patch (wordmark, thread, seam) to canvases and WebGL refracts those, so the lens and the controls bend the wallpaper and the hero art. Cards, panels and the status line use the library's frosted CSS engine over the live page, so the scenery and text behind them still show through |
| `frost` | Browsers without WebGL | Same layout with a plain frosted look |

Real refraction of live page content needs `backdrop-filter: url(#svg)`, which only Chromium supports. There, cards, panels and the status line are real glass surfaces made with `glass()` from the library: they bend the patches, seams, thread and dots behind them and carry a rim, a specular edge and a shadow. Everywhere else they use the library's frosted CSS engine (`engine: "css"`). Chips, variant pills and the buttons on cards are plain CSS with a gel highlight and no `backdrop-filter`. The chrome (header, tab bar, search, segmented control, menu, sheet, call to action buttons, lens) is glass in every browser.

The wallpaper canvas is capped at 2x pixel density and 6 megapixels, and is repainted on resize, theme change and zoom. The lens wakes the scene on every move, so its content never lags behind its position.

## Glass surfaces and quality tiers

`assets/glass.js` gives every `.card`, `.panel` and `.status` a glass surface and keeps the cost bounded on phones:

- A surface exists only while its element is within 70% of a screen height of the viewport. Elements that scroll far away lose it and get a new one on the way back. Cards rendered later by search, filters or sorting are picked up automatically.
- A host with a surface gets the `is-glass` class, which makes its own background and border transparent so the glass layers (`gl-fx`) do not sit on top of a second fill.
- Three tiers trade looks for speed. The tier shows as `data-glass-tier` on `<html>`.

| Tier | Cards, panels and status line |
|---|---|
| `full` | Refracting glass on Chromium, frosted glass elsewhere |
| `lite` | Frosted glass everywhere: one `backdrop-filter: blur`, no SVG refraction |
| `flat` | No surfaces, plain translucent CSS fills |

A visit starts in `full`, or in `lite` when the browser reports 2 GB of memory or 2 CPU cores or fewer. `assets/perf.js` times frames while the visitor scrolls (after the first 2.5 seconds) and steps one tier down when more than 30% of the last 120 frames took longer than 30 ms. The tier is remembered in `localStorage` (`patchy-glass-tier`) for 7 days. Visitors who ask for reduced transparency, more contrast or forced colors always get `flat`, and it switches live when the setting changes.

Two query parameters help with testing:

| Parameter | Effect |
|---|---|
| `?glass-tier=full`, `lite` or `flat` | Forces a tier, remembers it for 7 days and turns the governor off |
| `?glass=scene` | Makes Chromium take the Firefox and Safari path (`glass-scene` and WebGL), so that path can be checked without Firefox |

## Scenery behind the glass

Glass only shows what is behind it, and a lens only looks like a lens when there is something crisp to bend. `assets/world.js` fills the space behind the cards and panels with two kinds of scenery.

**Light arcs.** Large turquoise and red circles sit half off the left and right edges of the page, from the hero down to the footer, so their curved edges sweep across the content. Each arc has a wide body that runs from deep to bright and a thin hot edge on its outer side. The hot edge is what the glass bends most visibly, but it is bright, so it must never sit behind text. The script measures every heading, paragraph, toolbar, chip row and the inside of every card, panel and status line, and draws the hot edge (`.rim`) only in the gaps between them and along the edges of the glass, as short glints that taper along the curve. Behind text only a faint trace remains (`--arc-dim`), and the body colors are kept dark enough in the dark theme for text to keep its contrast. In the light theme the edge is white and text is dark, so the edge is drawn everywhere.

**Patches and thread.** In the sections that hold glass (the card grid, the companion list, the process steps and the verify and install columns) the script lays out turquoise and red patches (stitched fabric with a dashed seam and a dot grid) and two dashed threads that fade in and out at the zone edges. They give the glass small, high contrast details to bend. Patches and thread never sit behind headings or intro text, so reading text stays on the plain wallpaper. The soft orbs are a repeating CSS background across the whole page.

The layout is recomputed when the page width, the height of a zone or the position of a text block changes, and patch size follows the page width (0.9x to 1.5x). Everything lives in `.world`, which takes no pointer events.

The glass itself uses the library's `lip` edge profile on cards and panels: a flat middle with a steep rim, so the content stays readable and the bending happens at the edge, where the glints are.

## Phones

- Apps are one full width card per row below 720 px (`minmax(0, 1fr)`, so a long package name is cut with an ellipsis instead of widening the page) and fill 2 or 3 columns above.
- The wallpaper uses `100lvh`, so the browser bar sliding away does not resize it. Side gutters and the floating tab bar respect safe-area insets.
- Touch targets are 44 to 48 px on coarse pointers. Below 390 px the card buttons tighten, and below 350 px the English download label drops its icon, so the row fits at 320 px in both languages.
- The lens is moved with one finger. Its light follows the tilt of the phone where the browser allows it without a permission prompt.

## Accessibility

`prefers-reduced-motion` skips the stitching animation, the lens intro and glide, and the card transitions. `prefers-reduced-transparency` and `prefers-contrast: more` turn the card, panel and status glass off (the `flat` tier), use solid panel fills and halve the scenery, arcs included; `prefers-contrast: more` also raises text and edge contrast. Forced colors turn those surfaces off too and drop the scenery and the lens.
