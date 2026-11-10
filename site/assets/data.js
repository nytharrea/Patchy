const API = "https://api.github.com";
const CACHE_PREFIX = "patchy:v1:release:";
const FRESH_MS = 10 * 60 * 1000;
const STALE_MS = 7 * 24 * 60 * 60 * 1000;
const TIMEOUT_MS = 12000;

const dotted = (value) => value.replace(/ /g, ".");
const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function resolveRepo(catalog) {
  if (catalog && typeof catalog.repo === "string" && /^[\w.-]+\/[\w.-]+$/.test(catalog.repo)) return catalog.repo;
  const host = location.hostname.match(/^([a-z0-9-]+)\.github\.io$/i);
  const first = location.pathname.split("/").filter(Boolean)[0];
  if (host && first && !first.includes(".")) return `${host[1]}/${first}`;
  const meta = document.querySelector('meta[name="patchy-repo"]');
  return meta ? meta.content : null;
}

export function repoUrl(repo, path = "") {
  return `https://github.com/${repo}${path ? `/${path}` : ""}`;
}

export async function loadCatalog() {
  try {
    const response = await fetch("data/catalog.json", { cache: "no-cache" });
    if (!response.ok) return null;
    const data = await response.json();
    return data && Array.isArray(data.builds) && data.builds.length ? data : null;
  } catch (error) {
    return null;
  }
}

function readCache(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    return null;
  }
}

function writeCache(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    return;
  }
}

function slimRelease(json) {
  return {
    tag: String(json.tag_name || ""),
    name: String(json.name || json.tag_name || ""),
    published: json.published_at || json.created_at || null,
    url: String(json.html_url || ""),
    assets: (Array.isArray(json.assets) ? json.assets : []).map((asset) => ({
      name: String(asset.name || ""),
      size: Number(asset.size) || 0,
      url: String(asset.browser_download_url || ""),
      downloads: Number(asset.download_count) || 0,
      updated: asset.updated_at || null,
    })),
  };
}

export async function loadRelease(repo, { force = false } = {}) {
  const key = CACHE_PREFIX + repo;
  const cached = readCache(key);
  const now = Date.now();
  if (!force && cached && now - cached.time < FRESH_MS) {
    return { release: cached.release, source: "cache", time: cached.time };
  }
  try {
    const options = { headers: { Accept: "application/vnd.github+json" } };
    if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
      options.signal = AbortSignal.timeout(TIMEOUT_MS);
    }
    const response = await fetch(`${API}/repos/${repo}/releases/latest`, options);
    if (response.status === 404) return { release: null, source: "network", time: now };
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const release = slimRelease(await response.json());
    writeCache(key, { time: now, release });
    return { release, source: "network", time: now };
  } catch (error) {
    if (cached && now - cached.time < STALE_MS) {
      return { release: cached.release, source: "stale", time: cached.time };
    }
    throw error;
  }
}

function isCompanion(name, companions) {
  const lower = name.toLowerCase();
  return companions.some((companion) => lower.startsWith(String(companion.key).toLowerCase()));
}

export function matchBuilds(builds, assets, companions = []) {
  const candidates = builds
    .map((build) => ({ build, prefix: `${dotted(build.name)}-`, tag: build.tag }))
    .sort((a, b) => b.build.name.length - a.build.name.length);
  const matched = new Map();
  for (const asset of assets) {
    if (!/\.apk$/i.test(asset.name) || isCompanion(asset.name, companions)) continue;
    const base = asset.name.slice(0, -4);
    const lower = base.toLowerCase();
    for (const { build, prefix, tag } of candidates) {
      if (!lower.startsWith(prefix.toLowerCase())) continue;
      let version = base.slice(prefix.length);
      if (tag) {
        const suffix = `-${tag}`.toLowerCase();
        if (!version.toLowerCase().endsWith(suffix)) continue;
        version = version.slice(0, version.length - suffix.length);
      }
      if (!matched.has(build.key)) matched.set(build.key, { ...asset, version });
      break;
    }
  }
  return matched;
}

export function deriveBuilds(assets, companions = []) {
  const builds = [];
  for (const asset of assets) {
    if (!/\.apk$/i.test(asset.name) || isCompanion(asset.name, companions)) continue;
    const parts = asset.name.slice(0, -4).match(/^(.+?)-(\d.*)$/);
    const name = parts ? parts[1] : asset.name.slice(0, -4);
    const version = parts ? parts[2] : "";
    builds.push({
      key: asset.name,
      app: asset.name,
      title: name.replace(/\./g, " ").trim() || name,
      name,
      tag: null,
      variant: "",
      pkg: "",
      icon: "",
      arch: "",
      category: "other",
      source: null,
      bundles: [],
      asset: { ...asset, version },
    });
  }
  return builds;
}

export function groupApps(builds, matched) {
  const groups = new Map();
  for (const build of builds) {
    if (!groups.has(build.app)) {
      groups.set(build.app, {
        id: build.app,
        title: build.title,
        pkg: build.pkg,
        icon: build.icon,
        category: build.category,
        builds: [],
      });
    }
    groups.get(build.app).builds.push({ ...build, asset: build.asset || matched.get(build.key) || null });
  }
  return Array.from(groups.values());
}

export function companionAssets(companions, assets) {
  return companions.map((companion) => ({
    ...companion,
    items: companion.files.map((file) => {
      const plain = file.toLowerCase();
      const pre = file.replace(/\.apk$/i, "-PRERELEASE.apk").toLowerCase();
      const asset = assets.find((entry) => entry.name.toLowerCase() === plain || entry.name.toLowerCase() === pre);
      return { file, asset: asset || null, prerelease: Boolean(asset && asset.name.toLowerCase() === pre) };
    }),
  }));
}

export function obtainiumLink(build, repo) {
  const url = repoUrl(repo);
  const owner = repo.split("/")[0];
  if (!build.pkg) return `obtainium://add/${encodeURIComponent(url)}`;
  const prefix = escapeRegex(dotted(build.name));
  const filter = build.tag ? `^${prefix}-.+-${escapeRegex(build.tag)}\\.apk$` : `^${prefix}-\\d.*\\.apk$`;
  const settings = {
    includePrereleases: false,
    fallbackToOlderReleases: true,
    apkFilterRegEx: filter,
    autoApkFilterByArch: false,
    versionDetection: false,
    appName: build.title,
  };
  const app = {
    id: build.pkg,
    url,
    author: owner,
    name: build.title,
    preferredApkIndex: 0,
    additionalSettings: JSON.stringify(settings),
    allowIdChange: true,
  };
  return `obtainium://app/${encodeURIComponent(JSON.stringify(app))}`;
}

export function safeHttps(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch (error) {
    return "";
  }
}

export function formatSize(bytes, locale) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  const digits = mb >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(mb)} MB`;
}

export function formatCount(value, locale) {
  if (value < 10000) return new Intl.NumberFormat(locale).format(value);
  return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function formatDate(iso, locale) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(date);
}

export function formatAgo(iso, locale) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "always" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit);
  }
  return formatter.format(0, "second");
}
