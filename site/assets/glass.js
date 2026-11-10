const FULL = "full";
const LITE = "lite";
const FLAT = "flat";
const TIERS = [FULL, LITE, FLAT];
const TIER_KEY = "patchy-glass-tier";
const CUSTOM_KEY = "patchy-glass-custom";
const TIER_TTL = 7 * 24 * 60 * 60 * 1000;
const MARGIN = "70% 0px";

const DEFAULT_CUSTOM = {
  blurScale: 1,
  refractionScale: 1,
  dispersion: 0.38,
  specular: 1.75,
};

const KINDS = [
  { selector: ".card", token: "--glass-card-fill", profile: "lip", bezel: 24, refraction: 44, blur: 2, frost: 12, specular: 1.75, dispersion: 0.38 },
  { selector: ".panel", token: "--glass-panel-fill", profile: "lip", bezel: 24, refraction: 44, blur: 2, frost: 12, specular: 1.7, dispersion: 0.32 },
  { selector: ".status", token: "--glass-pill-fill", profile: "squircle", bezel: 18, refraction: 26, blur: 2, frost: 10, specular: 1.6, dispersion: 0.45 },
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

function isRestrictedWebView() {
  const ua = navigator.userAgent || "";
  if (/;\s*wv\)|Version\/\d+\.\d+\s+Chrome\/\d+/i.test(ua)) return true;
  if (typeof CSS === "undefined" || typeof CSS.supports !== "function") return true;
  return !CSS.supports("backdrop-filter", "blur(4px)") && !CSS.supports("-webkit-backdrop-filter", "blur(4px)");
}

function weakDevice() {
  if (isRestrictedWebView()) return true;
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

function readCustom() {
  try {
    const raw = JSON.parse(localStorage.getItem(CUSTOM_KEY) || "null");
    if (!raw || typeof raw !== "object") return { ...DEFAULT_CUSTOM };
    return {
      blurScale: Number.isFinite(raw.blurScale) ? Math.min(2.5, Math.max(0, raw.blurScale)) : DEFAULT_CUSTOM.blurScale,
      refractionScale: Number.isFinite(raw.refractionScale) ? Math.min(2, Math.max(0, raw.refractionScale)) : DEFAULT_CUSTOM.refractionScale,
      dispersion: Number.isFinite(raw.dispersion) ? Math.min(1, Math.max(0, raw.dispersion)) : DEFAULT_CUSTOM.dispersion,
      specular: Number.isFinite(raw.specular) ? Math.min(3, Math.max(0, raw.specular)) : DEFAULT_CUSTOM.specular,
    };
  } catch (error) {
    return { ...DEFAULT_CUSTOM };
  }
}

function saveCustom(custom) {
  try {
    localStorage.setItem(CUSTOM_KEY, JSON.stringify(custom));
  } catch (error) {
    return;
  }
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
  let custom = readCustom();
  let observer = null;

  const refracts = () => tier === FULL && root.dataset.glass === "live";
  const engineFor = () => (refracts() ? "auto" : "css");
  const blurFor = (kind) => Math.round((refracts() ? kind.blur : kind.frost) * custom.blurScale * 10) / 10;
  const refractionFor = (kind) => Math.round(kind.refraction * custom.refractionScale);
  const dispersionFor = (kind) => (refracts() ? Number((kind.dispersion * (custom.dispersion / DEFAULT_CUSTOM.dispersion)).toFixed(2)) : 0);
  const specularFor = (kind) => Number((kind.specular * (custom.specular / DEFAULT_CUSTOM.specular)).toFixed(2));

  const syncCssVars = () => {
    root.style.setProperty("--glass-custom-blur", `${Math.round(12 * custom.blurScale)}px`);
    root.style.setProperty("--glass-custom-specular", String(custom.specular));
    root.style.setProperty("--glass-custom-dispersion", String(custom.dispersion));
  };
  syncCssVars();

  const make = (element, kind) => {
    const height = element.offsetHeight;
    if (!height || !element.isConnected) return null;
    const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 24;
    const surface = lib.glass(element, {
      material: "regular",
      radius: radius >= height / 2 - 0.5 ? "capsule" : radius,
      profile: kind.profile,
      bezel: kind.bezel,
      refraction: refractionFor(kind),
      blur: blurFor(kind),
      specular: specularFor(kind),
      dispersion: dispersionFor(kind),
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
      record.visible = entry.isIntersecting;
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
    const isNear = near(element);
    const record = { kind, surface: null, visible: isNear };
    hosts.set(element, record);
    if (tier !== FLAT && isNear) record.surface = make(element, kind);
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

  const applySurfaceSettings = () => {
    syncCssVars();
    for (const [element, record] of hosts) {
      if (tier === FLAT) {
        drop(element, record);
      } else if (record.surface) {
        record.surface.set({
          engine: engineFor(),
          blur: blurFor(record.kind),
          refraction: refractionFor(record.kind),
          dispersion: dispersionFor(record.kind),
          specular: specularFor(record.kind),
          fill: tokenValue(record.kind.token),
        });
      } else if (observer) {
        observer.unobserve(element);
        observer.observe(element);
      }
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
    applySurfaceSettings();
  };

  const configure = (patch = {}, persist = true) => {
    if (patch.reset) {
      custom = { ...DEFAULT_CUSTOM };
    } else {
      custom = {
        blurScale: patch.blurScale !== undefined ? Number(patch.blurScale) : custom.blurScale,
        refractionScale: patch.refractionScale !== undefined ? Number(patch.refractionScale) : custom.refractionScale,
        dispersion: patch.dispersion !== undefined ? Number(patch.dispersion) : custom.dispersion,
        specular: patch.specular !== undefined ? Number(patch.specular) : custom.specular,
      };
    }
    if (persist) saveCustom(custom);
    applySurfaceSettings();
    return { ...custom, tier };
  };

  const reducedMotion = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reducedMotion) {
    let rafId = 0;
    let pointerX = window.innerWidth * 0.5;
    let pointerY = window.innerHeight * 0.3;
    let gyroAngle = null;

    const updateReflections = () => {
      rafId = 0;
      if (document.visibilityState === "hidden" || tier === FLAT) return;
      root.style.setProperty("--pointer-x", `${((pointerX / Math.max(1, window.innerWidth)) * 100).toFixed(1)}%`);
      root.style.setProperty("--pointer-y", `${((pointerY / Math.max(1, window.innerHeight)) * 100).toFixed(1)}%`);

      for (const [element, record] of hosts) {
        if (!record.visible || !record.surface) continue;
        const rect = element.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const angle =
          gyroAngle !== null
            ? gyroAngle
            : Math.round(((Math.atan2(pointerY - cy, pointerX - cx) * 180) / Math.PI) / 6) * 6;
        record.surface.set({ lightAngle: angle });
        const localX = pointerX - rect.left;
        const localY = pointerY - rect.top;
        const dist = Math.hypot(pointerX - cx, pointerY - cy);
        const maxDist = Math.max(rect.width, rect.height) * 1.35;
        if (dist < maxDist && typeof record.surface.setGlow === "function") {
          const strength = Math.max(0, (1 - dist / maxDist) * 0.42 * (custom.specular / DEFAULT_CUSTOM.specular));
          record.surface.setGlow(localX, localY, strength, Math.max(rect.width, rect.height) * 0.75);
        } else if (typeof record.surface.setGlow === "function") {
          record.surface.setGlow(localX, localY, 0, 120);
        }
      }
    };

    window.addEventListener(
      "pointermove",
      (event) => {
        if (document.visibilityState === "hidden") return;
        pointerX = event.clientX;
        pointerY = event.clientY;
        gyroAngle = null;
        if (!rafId) rafId = requestAnimationFrame(updateReflections);
      },
      { passive: true },
    );

    if ("DeviceOrientationEvent" in window && typeof window.DeviceOrientationEvent.requestPermission !== "function") {
      window.addEventListener(
        "deviceorientation",
        (event) => {
          if (document.visibilityState === "hidden" || event.gamma === null) return;
          const side = Math.min(45, Math.max(-45, event.gamma || 0)) / 45;
          const front = Math.min(45, Math.max(-45, (event.beta || 0) - 45)) / 45;
          gyroAngle = Math.round(((Math.atan2(-0.65 + front * 0.85, -0.65 + side * 0.85) * 180) / Math.PI) / 8) * 8;
          pointerX = (0.5 + side * 0.38) * window.innerWidth;
          pointerY = (0.4 + front * 0.38) * window.innerHeight;
          if (!rafId) rafId = requestAnimationFrame(updateReflections);
        },
        { passive: true },
      );
    }
  }

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
    configure,
    getSettings: () => ({ ...custom, tier }),
    count: () => Array.from(hosts.values()).filter((record) => record.surface).length,
  };
}

export { FULL, LITE, FLAT, DEFAULT_CUSTOM };
