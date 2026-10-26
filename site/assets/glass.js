const FULL = "full";
const LITE = "lite";
const FLAT = "flat";
const TIERS = [FULL, LITE, FLAT];
const TIER_KEY = "patchy-glass-tier";
const TIER_TTL = 7 * 24 * 60 * 60 * 1000;
const MARGIN = "70% 0px";

const KINDS = [
  { selector: ".card", token: "--glass-card-fill", bezel: 26, refraction: 26, blur: 4, frost: 12, specular: 1.15 },
  { selector: ".panel", token: "--glass-panel-fill", bezel: 28, refraction: 26, blur: 4, frost: 12, specular: 1.1 },
  { selector: ".status", token: "--glass-pill-fill", bezel: 18, refraction: 16, blur: 3, frost: 10, specular: 1.05 },
];

const BARS = [
  { selector: ".top", token: "--glass-bar-fill" },
  { selector: "#tabs", token: "--glass-bar-fill" },
  { selector: "#q", token: "--glass-field-fill" },
];

const SELECTOR = KINDS.map((kind) => kind.selector).join(",");

const QUIET = ["(prefers-reduced-transparency: reduce)", "(prefers-contrast: more)", "(forced-colors: active)"];

const root = document.documentElement;

function quiet() {
  return typeof matchMedia === "function" && QUIET.some((query) => matchMedia(query).matches);
}

function weakDevice() {
  const memory = navigator.deviceMemory;
  const cores = navigator.hardwareConcurrency;
  return (memory !== undefined && memory <= 2) || (cores !== undefined && cores <= 2);
}

function remember(tier) {
  try {
    localStorage.setItem(TIER_KEY, JSON.stringify({ tier, time: Date.now() }));
  } catch (error) {
    return;
  }
}

function readTier() {
  const asked = new URLSearchParams(location.search).get("glass-tier");
  if (TIERS.includes(asked)) {
    remember(asked);
    return asked;
  }
  try {
    const stored = JSON.parse(localStorage.getItem(TIER_KEY) || "null");
    if (stored && TIERS.includes(stored.tier) && Date.now() - stored.time < TIER_TTL) return stored.tier;
  } catch (error) {
    return weakDevice() ? LITE : FULL;
  }
  return weakDevice() ? LITE : FULL;
}

function kindOf(element) {
  return KINDS.find((kind) => element.matches(kind.selector)) || null;
}

function tokenValue(token) {
  return getComputedStyle(root).getPropertyValue(token).trim() || null;
}

export function createGlass(lib) {
  const hosts = new Map();
  let tier = quiet() ? FLAT : readTier();
  let observer = null;

  const refracts = () => tier === FULL && root.dataset.glass === "live";
  const engineFor = () => (refracts() ? "auto" : "css");
  const blurFor = (kind) => (refracts() ? kind.blur : kind.frost);

  const make = (element, kind) => {
    const height = element.offsetHeight;
    if (!height || !element.isConnected) return null;
    const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 24;
    const surface = lib.glass(element, {
      material: "regular",
      radius: radius >= height / 2 - 0.5 ? "capsule" : radius,
      bezel: kind.bezel,
      refraction: kind.refraction,
      blur: blurFor(kind),
      specular: kind.specular,
      fill: tokenValue(kind.token),
      engine: engineFor(),
    });
    element.classList.add("is-glass");
    return surface;
  };

  const drop = (element, record) => {
    if (record.surface) {
      record.surface.destroy();
      record.surface = null;
    }
    element.classList.remove("is-glass");
  };

  const onVisible = (entries) => {
    for (const entry of entries) {
      const record = hosts.get(entry.target);
      if (!record) continue;
      if (entry.isIntersecting) {
        if (!record.surface && tier !== FLAT) record.surface = make(entry.target, record.kind);
      } else if (record.surface) {
        drop(entry.target, record);
      }
    }
  };

  const near = (element) => {
    const rect = element.getBoundingClientRect();
    const margin = window.innerHeight * 0.7;
    return rect.bottom > -margin && rect.top < window.innerHeight + margin;
  };

  const add = (element) => {
    if (hosts.has(element)) return;
    const kind = kindOf(element);
    if (!kind) return;
    const record = { kind, surface: null };
    hosts.set(element, record);
    if (tier !== FLAT && near(element)) record.surface = make(element, kind);
    if (typeof IntersectionObserver === "function") {
      observer ??= new IntersectionObserver(onVisible, { rootMargin: MARGIN });
      observer.observe(element);
    } else {
      onVisible([{ target: element, isIntersecting: true }]);
    }
  };

  const remove = (element) => {
    const record = hosts.get(element);
    if (!record) return;
    if (observer) observer.unobserve(element);
    drop(element, record);
    hosts.delete(element);
  };

  const scan = (node) => {
    if (!(node instanceof Element)) return;
    if (node.matches(SELECTOR)) add(node);
    for (const child of node.querySelectorAll(SELECTOR)) add(child);
  };

  const sweep = (node) => {
    if (!(node instanceof Element)) return;
    if (hosts.has(node)) remove(node);
    for (const child of node.querySelectorAll(SELECTOR)) remove(child);
  };

  const mutations = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.removedNodes) sweep(node);
      for (const node of record.addedNodes) scan(node);
    }
  });

  const tune = () => {
    for (const bar of BARS) {
      const element = document.querySelector(bar.selector);
      const fill = tokenValue(bar.token);
      if (element && element.surface && fill) element.surface.set({ fill });
    }
  };

  const refill = () => {
    tune();
    for (const record of hosts.values()) {
      if (record.surface) record.surface.set({ fill: tokenValue(record.kind.token) });
    }
  };

  new MutationObserver(() => requestAnimationFrame(refill)).observe(root, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });

  root.dataset.glassTier = tier;

  const setTier = (next, persist = true) => {
    if (!TIERS.includes(next) || next === tier) return;
    tier = next;
    root.dataset.glassTier = next;
    if (persist) remember(next);
    for (const [element, record] of hosts) {
      if (next === FLAT) {
        drop(element, record);
      } else if (record.surface) {
        record.surface.set({ engine: engineFor(), blur: blurFor(record.kind) });
      } else if (observer) {
        observer.unobserve(element);
        observer.observe(element);
      }
    }
  };

  if (typeof matchMedia === "function") {
    for (const query of QUIET) {
      const list = matchMedia(query);
      if (typeof list.addEventListener === "function") {
        list.addEventListener("change", () => setTier(quiet() ? FLAT : readTier(), false));
      }
    }
  }

  return {
    track(scope = document) {
      tune();
      scan(scope instanceof Document ? scope.documentElement : scope);
    },
    watch(container) {
      if (container) mutations.observe(container, { childList: true, subtree: true });
    },
    setTier,
    tier: () => tier,
    count: () => Array.from(hosts.values()).filter((record) => record.surface).length,
  };
}

export { FULL, LITE, FLAT };
