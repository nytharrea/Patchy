import { applyTranslations, getLang, has, onLangChange, plural, setLang, t } from "./i18n.js";
import {
  companionAssets,
  deriveBuilds,
  formatAgo,
  formatCount,
  formatDate,
  formatSize,
  groupApps,
  loadCatalog,
  loadRelease,
  matchBuilds,
  obtainiumLink,
  repoUrl,
  resolveRepo,
  safeHttps,
} from "./data.js";
import { initLens } from "./hero.js";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const ICONS = {
  download:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v10.5"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/></svg>',
  more: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5.5" cy="12" r="1.9"/><circle cx="12" cy="12" r="1.9"/><circle cx="18.5" cy="12" r="1.9"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8.5" y="8.5" width="11" height="11" rx="3"/><path d="M15.5 8.5V7a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3v5.5a3 3 0 0 0 3 3h1.5"/></svg>',
};

const CATEGORY_ORDER = ["all", "social", "media", "tools", "privacy", "other"];

const state = {
  repo: null,
  catalog: null,
  release: null,
  source: "network",
  phase: "loading",
  apps: [],
  companions: [],
  query: "",
  category: "all",
  sort: "name",
  pick: new Map(),
  sheet: null,
};

function icon(name) {
  const template = document.createElement("template");
  template.innerHTML = ICONS[name];
  return template.content.firstElementChild.cloneNode(true);
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const fold = (value) =>
  String(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "");

function releasesHref() {
  return state.repo ? repoUrl(state.repo, "releases") : "#";
}

function selectedBuild(app) {
  const key = state.pick.get(app.id);
  return app.builds.find((build) => build.key === key) || app.builds.find((build) => build.asset) || app.builds[0];
}

function computeApps() {
  const assets = state.release ? state.release.assets : [];
  const catalog = state.catalog;
  const companions = catalog && Array.isArray(catalog.companions) ? catalog.companions : [];
  if (catalog) {
    state.apps = groupApps(catalog.builds, matchBuilds(catalog.builds, assets, companions));
  } else {
    state.apps = groupApps(deriveBuilds(assets, companions), new Map());
  }
  state.companions = companionAssets(companions, assets);
}

function visibleApps() {
  const query = fold(state.query.trim());
  const collator = new Intl.Collator(getLang());
  const available = (app) => app.builds.some((build) => build.asset);
  const sizeOf = (app) => (selectedBuild(app).asset ? selectedBuild(app).asset.size : 0);
  const downloadsOf = (app) => (selectedBuild(app).asset ? selectedBuild(app).asset.downloads : 0);

  const list = state.apps.filter((app) => {
    if (state.category !== "all" && app.category !== state.category) return false;
    if (!query) return true;
    const words = [app.title, app.pkg];
    for (const build of app.builds) {
      words.push(build.name, build.variant, build.asset ? build.asset.version : "");
      for (const bundle of build.bundles) words.push(bundle.label);
    }
    return fold(words.join(" ")).includes(query);
  });

  list.sort((a, b) => {
    if (available(a) !== available(b)) return available(a) ? -1 : 1;
    if (state.sort === "size") return sizeOf(b) - sizeOf(a) || collator.compare(a.title, b.title);
    if (state.sort === "downloads") return downloadsOf(b) - downloadsOf(a) || collator.compare(a.title, b.title);
    return collator.compare(a.title, b.title);
  });
  return list;
}

function iconNode(app) {
  const holder = el("span", { class: "icon", "aria-hidden": "true" });
  const letter = () => holder.replaceChildren(el("span", { text: (app.title.trim()[0] || "?").toUpperCase() }));
  const src = safeHttps(app.icon);
  if (!src) {
    letter();
    return holder;
  }
  const image = el("img", {
    src,
    alt: "",
    width: "32",
    height: "32",
    loading: "lazy",
    decoding: "async",
    referrerpolicy: "no-referrer",
  });
  image.addEventListener("error", letter, { once: true });
  holder.append(image);
  return holder;
}

function variantRow(app, current) {
  const row = el("div", { class: "variants", role: "group", "aria-label": t("card.variant") });
  for (const build of app.builds) {
    row.append(
      el("button", {
        type: "button",
        class: "variant",
        "aria-pressed": String(build.key === current.key),
        "data-missing": build.asset ? null : "true",
        text: build.variant || build.name,
        onclick: () => {
          state.pick.set(app.id, build.key);
          replaceCard(app);
        },
      }),
    );
  }
  return row;
}

function actionRow(app, build) {
  const asset = build.asset;
  const row = el("div", { class: "actions" });
  const download = asset ? safeHttps(asset.url) : "";
  if (download) {
    row.append(el("a", { class: "btn btn-prime", href: download, rel: "noopener" }, icon("download"), t("card.download")));
    if (state.repo) {
      row.append(el("a", { class: "btn", href: obtainiumLink(build, state.repo), rel: "noopener" }, t("card.obtainium")));
    }
  } else {
    row.append(el("span", { class: "btn btn-prime", "aria-disabled": "true", text: t("card.missing") }));
  }
  row.append(
    el(
      "button",
      {
        type: "button",
        class: "btn btn-icon btn-details",
        "aria-label": t("card.details"),
        title: t("card.details"),
        onclick: () => openSheet(app, build),
      },
      icon("more"),
    ),
  );
  return row;
}

function renderCard(app) {
  const build = selectedBuild(app);
  const asset = build.asset;
  const locale = getLang();
  const card = el("article", { class: "card", "data-app": app.id, "data-missing": asset ? null : "true" });

  card.append(
    el(
      "div",
      { class: "card-head" },
      iconNode(app),
      el(
        "div",
        { class: "titles" },
        el("h3", { text: app.title }),
        app.pkg ? el("p", { class: "pkg", text: app.pkg, title: app.pkg }) : null,
      ),
      asset && asset.version ? el("span", { class: "ver", text: asset.version, title: asset.version }) : null,
    ),
  );

  if (app.builds.length > 1) card.append(variantRow(app, build));

  const meta = el("div", { class: "meta" });
  if (asset) {
    if (asset.size) meta.append(el("span", { text: formatSize(asset.size, locale) }));
    if (asset.downloads > 0) {
      meta.append(el("span", { text: t("card.downloads", { n: formatCount(asset.downloads, locale) }) }));
    }
  }
  if (build.source) meta.append(el("span", { text: t(`source.${build.source.type}`) }));
  if (meta.childElementCount) card.append(meta);

  card.append(actionRow(app, build));
  return card;
}

function replaceCard(app) {
  const old = $(`.card[data-app="${CSS.escape(app.id)}"]`);
  if (!old) return;
  const fresh = renderCard(app);
  old.replaceWith(fresh);
  const pressed = $('.variant[aria-pressed="true"]', fresh);
  if (pressed) pressed.focus();
}

function renderChips() {
  const holder = $("#chips");
  holder.replaceChildren();
  const present = new Set(state.apps.map((app) => app.category));
  const keys = CATEGORY_ORDER.filter((key) => key === "all" || present.has(key));
  holder.hidden = state.phase === "error" || state.phase === "none" || keys.length <= 2;
  if (holder.hidden) {
    state.category = "all";
    return;
  }
  if (!keys.includes(state.category)) state.category = "all";
  for (const key of keys) {
    holder.append(
      el("button", {
        type: "button",
        class: "chip",
        "aria-pressed": String(state.category === key),
        text: t(`cat.${key}`),
        onclick: () => {
          state.category = key;
          renderChips();
          renderGrid();
        },
      }),
    );
  }
}

function renderGrid() {
  const grid = $("#grid");
  const empty = $("#empty");
  const notice = $("#notice");
  const count = $("#count");
  grid.replaceChildren();
  empty.hidden = true;
  notice.hidden = true;
  count.textContent = "";
  grid.setAttribute("aria-busy", String(state.phase === "loading"));
  $(".toolbar").hidden = state.phase === "error" || state.phase === "none";

  if (state.phase === "loading") {
    for (let index = 0; index < 6; index += 1) grid.append(el("div", { class: "skeleton", "aria-hidden": "true" }));
    return;
  }

  if (state.phase === "error" || state.phase === "none") {
    notice.replaceChildren(
      el("p", { text: t(state.phase === "error" ? "apps.error" : "apps.noRelease") }),
      el(
        "div",
        { class: "linkrow" },
        state.phase === "error"
          ? el("button", { type: "button", class: "btn", text: t("status.retry"), onclick: () => load({ force: true }) })
          : null,
        state.repo ? el("a", { href: releasesHref(), target: "_blank", rel: "noopener", text: t("status.open") }) : null,
      ),
    );
    notice.hidden = false;
    return;
  }

  const list = visibleApps();
  count.textContent = plural("apps.count", list.length);
  if (!list.length) {
    empty.hidden = false;
    return;
  }
  for (const app of list) grid.append(renderCard(app));
}

function renderStatus() {
  const box = $("#status");
  const dot = el("span", { class: "dot", "aria-hidden": "true" });
  box.replaceChildren();

  if (state.phase === "loading") {
    box.dataset.state = "loading";
    box.append(dot, el("span", { text: t("status.loading") }));
    return;
  }
  if (state.phase === "error") {
    box.dataset.state = "error";
    box.append(
      dot,
      el("span", { text: t("status.error") }),
      el("button", { type: "button", text: t("status.retry"), onclick: () => load({ force: true }) }),
    );
    return;
  }
  if (state.phase === "none") {
    box.dataset.state = "error";
    box.append(dot, el("span", { text: t("status.none") }));
    return;
  }

  const locale = getLang();
  const count = state.apps.reduce((total, app) => total + app.builds.filter((build) => build.asset).length, 0);
  const ago = formatAgo(state.release.published, locale);
  box.dataset.state = state.source === "stale" ? "stale" : "ok";
  const parts = [
    dot,
    el(
      "span",
      {},
      el("strong", { text: t("status.latest") }),
      ` ${formatDate(state.release.published, locale)}`,
      ago ? ` (${ago})` : "",
    ),
    el("span", { text: plural("status.apks", count) }),
    state.source === "stale" ? el("span", { text: t("status.stale") }) : null,
    el("a", {
      href: safeHttps(state.release.url) || releasesHref(),
      target: "_blank",
      rel: "noopener",
      text: t("status.open"),
    }),
  ];
  box.append(...parts.filter(Boolean));
}

function renderCompanions() {
  const section = $("#companions");
  const holder = $("#companion-list");
  holder.replaceChildren();
  section.hidden = state.phase !== "ready" || state.companions.length === 0;
  if (section.hidden) return;
  const locale = getLang();

  for (const companion of state.companions) {
    const key = companion.key;
    const title = has(`comp.${key}.title`) ? t(`comp.${key}.title`) : key;
    const actions = el("div", { class: "actions" });
    let size = 0;
    let preview = false;

    companion.items.forEach((item, index) => {
      const labelKey = `comp.${key}.file${index}`;
      const label = has(labelKey) ? t(labelKey) : item.file;
      const href = item.asset ? safeHttps(item.asset.url) : "";
      if (item.asset) size = Math.max(size, item.asset.size);
      if (item.prerelease) preview = true;
      if (href) {
        actions.append(
          el("a", { class: index === 0 ? "btn btn-prime" : "btn", href, rel: "noopener" }, icon("download"), label),
        );
      } else {
        actions.append(el("span", { class: "btn", "aria-disabled": "true", text: `${label}: ${t("comp.missing")}` }));
      }
    });

    const meta = el("div", { class: "meta" });
    if (size) meta.append(el("span", { text: formatSize(size, locale) }));
    meta.append(el("span", { text: "arm64-v8a" }));
    if (preview) meta.append(el("span", { text: t("comp.prerelease") }));
    meta.append(el("a", { href: safeHttps(companion.url), target: "_blank", rel: "noopener", text: t("comp.repo") }));

    holder.append(
      el(
        "article",
        { class: "panel companion" },
        el("h4", { text: title }),
        has(`comp.${key}.body`) ? el("p", { text: t(`comp.${key}.body`) }) : null,
        has(`comp.${key}.hint`) ? el("p", { class: "fine-print", text: t(`comp.${key}.hint`) }) : null,
        meta,
        actions,
      ),
    );
  }
}

function renderAll() {
  renderStatus();
  renderChips();
  renderGrid();
  renderCompanions();
  if (state.sheet) {
    const app = state.apps.find((entry) => entry.id === state.sheet.app);
    const build = app && app.builds.find((entry) => entry.key === state.sheet.key);
    if (app && build) fillSheet(app, build);
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    const area = el("textarea", { class: "sr-only", readonly: "", "aria-hidden": "true" });
    area.value = text;
    document.body.append(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (failure) {
      ok = false;
    }
    area.remove();
    return ok;
  }
}

function flashCopied(button) {
  const label = $("[data-copy-label]", button);
  const original = label ? label.textContent : "";
  button.dataset.done = "true";
  if (label) label.textContent = t("copied");
  setTimeout(() => {
    delete button.dataset.done;
    if (label) label.textContent = original && label.dataset.i18n ? t(label.dataset.i18n) : original;
  }, 1600);
}

function copyButton(text, compact = false) {
  const button = el(
    "button",
    { type: "button", class: compact ? "copy mini-copy" : "copy", "aria-label": t("copy") },
    icon("copy"),
    el("span", { "data-copy-label": "", "data-i18n": "copy", text: t("copy") }),
  );
  button.addEventListener("click", async () => {
    if (await copyText(text)) flashCopied(button);
  });
  return button;
}

function detailRow(label, ...content) {
  return el("div", {}, el("dt", { text: label }), el("dd", {}, ...content));
}

function fillSheet(app, build) {
  const body = $("#sheet-body");
  const asset = build.asset;
  const locale = getLang();
  const downloadUrl = asset ? safeHttps(asset.url) : "";
  const list = el("dl");
  const rows = [];

  if (app.pkg) rows.push(detailRow(t("d.package"), el("span", { class: "mono", text: app.pkg }), copyButton(app.pkg, true)));
  if (asset && asset.version) rows.push(detailRow(t("d.version"), asset.version));
  if (asset) rows.push(detailRow(t("d.file"), el("span", { class: "mono", text: asset.name })));
  if (asset && asset.size) rows.push(detailRow(t("d.size"), formatSize(asset.size, locale)));
  if (asset && asset.downloads > 0) rows.push(detailRow(t("d.downloads"), formatCount(asset.downloads, locale)));
  if (asset && asset.updated) rows.push(detailRow(t("d.updated"), formatDate(asset.updated, locale)));
  if (build.arch) rows.push(detailRow(t("d.arch"), build.arch));
  if (build.source && safeHttps(build.source.url)) {
    rows.push(
      detailRow(
        t("d.source"),
        el("a", { href: safeHttps(build.source.url), target: "_blank", rel: "noopener", text: t(`source.${build.source.type}`) }),
      ),
    );
  }
  if (build.bundles.length) {
    rows.push(
      detailRow(
        t("d.bundles"),
        el(
          "ul",
          {},
          build.bundles.map((bundle) =>
            el(
              "li",
              {},
              el("a", { href: safeHttps(bundle.url), target: "_blank", rel: "noopener", text: bundle.label }),
            ),
          ),
        ),
      ),
    );
  }
  list.append(...rows);

  const actions = el("div", { class: "sheet-actions" });
  if (downloadUrl) {
    actions.append(el("a", { class: "btn btn-prime", href: downloadUrl, rel: "noopener" }, icon("download"), t("card.download")));
    if (state.repo) actions.append(el("a", { class: "btn", href: obtainiumLink(build, state.repo), rel: "noopener", text: t("card.obtainium") }));
  }
  if (state.release && safeHttps(state.release.url)) {
    actions.append(el("a", { class: "btn", href: safeHttps(state.release.url), target: "_blank", rel: "noopener", text: t("d.release") }));
  }

  body.replaceChildren(el("div", { class: "sheet-head" }, iconNode(app), el("h3", { text: app.title })), list, actions);
}

function openSheet(app, build) {
  const sheet = $("#sheet");
  state.sheet = { app: app.id, key: build.key };
  fillSheet(app, build);
  if (typeof sheet.show === "function") sheet.show();
}

function initSheet() {
  const sheet = $("#sheet");
  sheet.addEventListener("toggle", (event) => {
    if (event.detail && event.detail.open === false) state.sheet = null;
  });
}

function applyRepoLinks() {
  if (!state.repo) return;
  for (const node of $$("[data-repo-path]")) node.setAttribute("href", repoUrl(state.repo, node.dataset.repoPath));
  for (const node of $$("[data-owner]")) node.textContent = state.repo.split("/")[0];
}

function applyTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  const meta = $('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", mode === "dark" ? "#04151c" : "#e6f6f4");
}

function storedTheme() {
  try {
    const value = localStorage.getItem("patchy-theme");
    return value === "light" || value === "dark" ? value : null;
  } catch (error) {
    return null;
  }
}

function initTheme() {
  $("#theme").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem("patchy-theme", next);
    } catch (error) {
      return;
    }
  });
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  query.addEventListener("change", (event) => {
    if (!storedTheme()) applyTheme(event.matches ? "dark" : "light");
  });
}

function syncLangControl() {
  $("#lang").setAttribute("value", getLang());
}

function initLang() {
  syncLangControl();
  $("#lang").addEventListener("change", (event) => {
    if (event.detail && event.detail.value) setLang(event.detail.value);
  });
  onLangChange(() => {
    syncLangControl();
    renderAll();
  });
}

function initToolbar() {
  $("#q").addEventListener("input", (event) => {
    state.query = event.target.value || "";
    renderGrid();
  });
  $("#sort").addEventListener("select", (event) => {
    if (event.detail && event.detail.value) {
      state.sort = event.detail.value;
      renderGrid();
    }
  });
}

function initCopy() {
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const source = $(button.dataset.copy);
    if (source && (await copyText(source.textContent.trim()))) flashCopied(button);
  });
}

function initNav() {
  const bar = $("#tabs");
  const ids = ["apps", "process", "verify", "install"];
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const visible = new Map();
  let lock = 0;

  let moved = 0;

  const follow = () => {
    const found = ids.find((id) => visible.get(id));
    const first = document.getElementById(ids[0]);
    const current = found || (first && first.getBoundingClientRect().top > 0 ? ids[0] : ids[ids.length - 1]);
    if (bar.getAttribute("value") !== current) bar.setAttribute("value", current);
  };

  const go = (id) => {
    const target = document.getElementById(id);
    if (!target || performance.now() - moved < 150) return;
    moved = performance.now();
    lock = moved + 1000;
    target.scrollIntoView({ behavior: reduced.matches ? "auto" : "smooth", block: "start" });
    setTimeout(follow, 1050);
  };

  bar.addEventListener("change", (event) => {
    if (event.detail) go(event.detail.value);
  });

  bar.addEventListener("click", (event) => {
    const tab = event.target.closest("glass-tab");
    if (tab) go(tab.getAttribute("value"));
  });

  if (typeof IntersectionObserver !== "function") return;
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) visible.set(entry.target.id, entry.isIntersecting);
      if (performance.now() >= lock) follow();
    },
    { rootMargin: "-40% 0px -55% 0px" },
  );
  for (const id of ids) {
    const node = document.getElementById(id);
    if (node) observer.observe(node);
  }
}

async function load({ force = false } = {}) {
  state.phase = "loading";
  renderStatus();
  renderGrid();
  renderCompanions();
  if (!state.repo) {
    state.phase = "error";
  } else {
    try {
      const result = await loadRelease(state.repo, { force });
      state.release = result.release;
      state.source = result.source;
      state.phase = result.release ? "ready" : "none";
    } catch (error) {
      state.release = null;
      state.phase = "error";
    }
  }
  computeApps();
  renderAll();
}

async function loadGlass() {
  try {
    const glass = await import("./vendor/glassy-liquid.min.js");
    await initLens($(".stage"), glass);
  } catch (error) {
    document.documentElement.classList.add("no-glass");
  }
}

async function boot() {
  applyTranslations();
  initTheme();
  initLang();
  initToolbar();
  initCopy();
  initNav();
  initSheet();
  loadGlass();

  state.catalog = await loadCatalog();
  state.repo = resolveRepo(state.catalog);
  applyRepoLinks();
  await load();
}

boot();
