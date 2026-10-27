const SVG_NS = "http://www.w3.org/2000/svg";
const ZONES = [["#grid"], ["#companion-list"], [".steps"], ["#verify .split"], ["#install .split"]];
const TEXT = [
  ".hero .tagline",
  ".hero .lede",
  ".hero .fine",
  ".section-head",
  ".subhead > h3",
  ".subhead > p",
  ".toolbar",
  ".chips",
  ".count",
  ".note",
  ".linkrow",
  ".empty",
  ".notice",
  ".footer",
].join(",");
const GLASS = ".card, .panel, .status";
const PATCH_SPAN = 600;
const THREAD_STEP = 430;
const ARC_SPAN = 1250;
const MIN_ZONE = 140;
const FADE = 0.12;
const QUANTUM = 24;
const RIM = 22;
const FEATHER = 16;
const PAD = 8;
const MERGE = FEATHER * 2;
const CORE = 0.92;
const GLINT_ALONG = 44;
const GLINT_MIN = 28;

function random(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function svgNode(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function rectsOf(page, selector) {
  const origin = page.getBoundingClientRect().top;
  const list = [];
  for (const node of page.querySelectorAll(selector)) {
    const rect = node.getBoundingClientRect();
    if (rect.height > 0) list.push({ top: rect.top - origin, bottom: rect.bottom - origin });
  }
  return list;
}

function measure(page) {
  const origin = page.getBoundingClientRect().top;
  const zones = [];
  for (const group of ZONES) {
    let top = Infinity;
    let bottom = -Infinity;
    for (const selector of group) {
      const node = page.querySelector(selector);
      if (!node || node.hidden) continue;
      const rect = node.getBoundingClientRect();
      if (!rect.height) continue;
      top = Math.min(top, rect.top - origin);
      bottom = Math.max(bottom, rect.bottom - origin);
    }
    if (bottom - top >= MIN_ZONE) zones.push({ top, bottom });
  }
  return zones;
}

function heroOf(page) {
  const [rect] = rectsOf(page, ".hero");
  return rect || null;
}

function endOf(page, height) {
  const [rect] = rectsOf(page, ".footer");
  return rect ? rect.top : height;
}

function bandsOf(page) {
  const list = [];
  for (const rect of rectsOf(page, TEXT)) list.push([rect.top - PAD, rect.bottom + PAD]);
  for (const rect of rectsOf(page, GLASS)) {
    if (rect.bottom - rect.top > RIM * 3 + FEATHER * 2) list.push([rect.top + RIM + FEATHER, rect.bottom - RIM - FEATHER]);
    else list.push([rect.top - PAD, rect.bottom + PAD]);
  }
  list.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const band of list) {
    const last = merged[merged.length - 1];
    if (last && band[0] - last[1] < MERGE) last[1] = Math.max(last[1], band[1]);
    else merged.push([band[0], band[1]]);
  }
  return merged;
}

function gapsOf(bands, height) {
  const gaps = [];
  let cursor = 0;
  for (const [start, end] of bands) {
    if (start - cursor >= MERGE) gaps.push([cursor, start]);
    cursor = Math.max(cursor, end);
  }
  if (height - cursor >= MERGE) gaps.push([cursor, height]);
  return gaps;
}

function heroArcs(hero, width) {
  const span = hero.bottom - hero.top;
  const left = clamp(width * 1.55, 620, 1080);
  const right = clamp(width * 1.36, 560, 960);
  return [
    { cx: -left * 0.41, cy: hero.bottom + span * 0.07, r: left, tone: "a" },
    { cx: width + right * 0.51, cy: hero.top + span * 0.17, r: right, tone: "b" },
  ];
}

function streamArcs(top, bottom, width) {
  const next = random(6151);
  const count = Math.max(1, Math.round((bottom - top) / ARC_SPAN));
  const step = (bottom - top) / count;
  const base = clamp(width * 1.3, 520, 900);
  const list = [];
  for (let index = 0; index < count; index += 1) {
    const r = base * (0.85 + next() * 0.35);
    const reach = 0.38 + next() * 0.2;
    const left = (index + Math.floor(index / 2)) % 2 === 0;
    list.push({
      cx: left ? -r * reach : width + r * reach,
      cy: top + (index + 0.25 + next() * 0.5) * step,
      r,
      tone: index % 2 === 0 ? "a" : "b",
    });
  }
  return list;
}

function arcNode(arc) {
  const node = document.createElement("div");
  node.className = `arc arc-${arc.tone}`;
  node.style.cssText = `left:${(arc.cx - arc.r).toFixed(1)}px;top:${(arc.cy - arc.r).toFixed(1)}px;width:${(arc.r * 2).toFixed(1)}px;height:${(arc.r * 2).toFixed(1)}px`;
  return node;
}

function glintNode(arc, gap, width) {
  const rho = arc.r * CORE;
  const low = clamp((gap[0] - arc.cy) / rho, -1, 1);
  const high = clamp((gap[1] - arc.cy) / rho, -1, 1);
  const left = arc.cx < width / 2;
  const nearest = low <= 0 && high >= 0 ? 0 : Math.min(Math.abs(Math.asin(low)), Math.abs(Math.asin(high)));
  const reach = left ? arc.cx + rho * Math.cos(nearest) : arc.cx - rho * Math.cos(nearest);
  const half = arc.r * 0.05;
  if (left ? reach + half < 0 : reach - half > width) return null;
  const degrees = 180 / Math.PI;
  const start = left ? Math.asin(low) * degrees + 90 : 270 - Math.asin(high) * degrees;
  const end = left ? Math.asin(high) * degrees + 90 : 270 - Math.asin(low) * degrees;
  const span = end - start;
  if ((span / degrees) * rho < GLINT_MIN) return null;
  const feather = Math.min(span / 2, (GLINT_ALONG / rho) * degrees);
  const margin = Math.ceil(half) + 6;
  const top = gap[0] - margin;
  const height = gap[1] - gap[0] + margin * 2;
  const origin = `${arc.cx.toFixed(0)}px ${(arc.cy - top).toFixed(0)}px`;
  const along = `conic-gradient(from ${start.toFixed(2)}deg at ${origin}, transparent 0deg, #000 ${feather.toFixed(2)}deg, #000 ${(span - feather).toFixed(2)}deg, transparent ${span.toFixed(2)}deg, transparent 360deg)`;
  const across = `linear-gradient(to bottom, transparent ${margin}px, #000 ${margin + FEATHER}px, #000 ${height - margin - FEATHER}px, transparent ${height - margin}px)`;
  const mask = `${along}, ${across}`;
  const node = document.createElement("div");
  node.className = "rim";
  node.style.cssText = `top:${top.toFixed(0)}px;height:${height.toFixed(0)}px;background:radial-gradient(circle ${arc.r.toFixed(0)}px at ${origin}, var(--rim-${arc.tone}))`;
  node.style.maskImage = mask;
  node.style.webkitMaskImage = mask;
  node.style.maskComposite = "intersect";
  node.style.webkitMaskComposite = "source-in";
  return node;
}

function glintsFor(gaps, arcs, width) {
  const list = [];
  for (const gap of gaps) {
    for (const arc of arcs) {
      const node = glintNode(arc, gap, width);
      if (node) list.push(node);
    }
  }
  return list;
}

function patchesFor(zone, width, seed, counter) {
  const next = random(seed * 7919 + 13);
  const scale = clamp(width / 430, 0.9, 1.5);
  const height = zone.bottom - zone.top;
  const count = Math.max(1, Math.round(height / PATCH_SPAN));
  const list = [];
  for (let index = 0; index < count; index += 1) {
    const w = (230 + next() * 120) * scale;
    const h = (160 + next() * 90) * scale;
    const slot = (seed + index) % 3;
    let x;
    if (slot === 0) x = -w * (0.18 + next() * 0.3);
    else if (slot === 1) x = width - w * (0.62 + next() * 0.28);
    else x = width * (0.16 + next() * 0.34);
    const middle = zone.top + ((index + 0.3 + next() * 0.4) / count) * height;
    const low = zone.top + 28;
    const high = Math.max(low, zone.bottom - h - 28);
    list.push({
      x,
      y: clamp(middle - h / 2, low, high),
      w,
      h,
      rotate: (next() - 0.5) * 28,
      tone: (counter + index) % 3 === 1 ? "red" : "turquoise",
    });
  }
  return list;
}

function threadPath(zone, width, seed) {
  const next = random(seed * 104729 + 7);
  const points = [];
  let y = zone.top;
  while (y < zone.bottom) {
    points.push([width * (0.1 + next() * 0.8), y]);
    y += THREAD_STEP * (0.8 + next() * 0.5);
  }
  points.push([width * (0.1 + next() * 0.8), zone.bottom]);
  let d = `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let index = 1; index < points.length; index += 1) {
    const [x0, y0] = points[index - 1];
    const [x1, y1] = points[index];
    const mid = ((y0 + y1) / 2).toFixed(1);
    d += ` C${x0.toFixed(1)} ${mid} ${x1.toFixed(1)} ${mid} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  }
  return d;
}

function fadeGradient(id, tone, zone) {
  const gradient = svgNode("linearGradient", {
    id,
    class: `fade fade-${tone}`,
    gradientUnits: "userSpaceOnUse",
    x1: 0,
    y1: zone.top.toFixed(1),
    x2: 0,
    y2: zone.bottom.toFixed(1),
  });
  const stops = [
    [0, 0],
    [FADE, 1],
    [1 - FADE, 1],
    [1, 0],
  ];
  for (const [offset, opacity] of stops) {
    gradient.append(svgNode("stop", { offset, "stop-opacity": opacity }));
  }
  return gradient;
}

export function initWorld(world, page) {
  if (!world || !page) return;

  const arcs = document.createElement("div");
  arcs.className = "arcs";
  const rims = document.createElement("div");
  rims.className = "rims";

  const svg = svgNode("svg", { class: "thread", "aria-hidden": "true", focusable: "false" });
  const defs = svgNode("defs");
  const strokes = svgNode("g");
  svg.append(defs, strokes);

  const patches = document.createElement("div");
  patches.className = "patches";

  world.append(arcs, rims, svg, patches);

  let signature = "";
  let timer = 0;

  const layout = () => {
    const width = Math.round(page.clientWidth);
    const height = Math.round(page.offsetHeight);
    if (!width || !height) return;
    const zones = measure(page);
    const hero = heroOf(page);
    const end = endOf(page, height);
    const bands = bandsOf(page);
    const next = [
      width,
      Math.round(end / QUANTUM),
      hero ? Math.round(hero.bottom / QUANTUM) : 0,
      zones.map((zone) => `${Math.round(zone.top / QUANTUM)}:${Math.round(zone.bottom / QUANTUM)}`).join(","),
      bands.map((band) => `${Math.round(band[0] / 8)}:${Math.round(band[1] / 8)}`).join(","),
    ].join("|");
    if (next === signature) return;
    signature = next;

    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const lights = [];
    if (hero) lights.push(...heroArcs(hero, width));
    lights.push(...streamArcs(hero ? hero.bottom : 0, end, width));
    arcs.replaceChildren(...lights.map(arcNode));
    rims.replaceChildren(...glintsFor(gapsOf(bands, height), lights, width));

    const gradients = [];
    const paths = [];
    const nodes = [];
    let counter = 0;
    zones.forEach((zone, index) => {
      const seed = index + 1;
      for (const [tone, offset] of [["a", 0], ["b", 40]]) {
        const id = `thread-${tone}-${index}`;
        gradients.push(fadeGradient(id, tone, zone));
        paths.push(svgNode("path", { class: `thread-${tone}`, d: threadPath(zone, width, seed + offset), stroke: `url(#${id})` }));
      }
      for (const patch of patchesFor(zone, width, seed, counter)) {
        const node = document.createElement("div");
        node.className = `patch patch-${patch.tone}`;
        node.style.cssText = `left:${patch.x.toFixed(1)}px;top:${patch.y.toFixed(1)}px;width:${patch.w.toFixed(1)}px;height:${patch.h.toFixed(1)}px;transform:rotate(${patch.rotate.toFixed(1)}deg)`;
        nodes.push(node);
        counter += 1;
      }
    });
    defs.replaceChildren(...gradients);
    strokes.replaceChildren(...paths);
    patches.replaceChildren(...nodes);
  };

  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(layout, 120);
  };

  layout();
  if (typeof ResizeObserver === "function") new ResizeObserver(later).observe(page);
  else window.addEventListener("resize", later, { passive: true });
}
