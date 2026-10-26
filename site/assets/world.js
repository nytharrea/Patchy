const SVG_NS = "http://www.w3.org/2000/svg";
const ZONES = [["#grid"], ["#companion-list"], [".steps"], ["#verify .split"], ["#install .split"]];
const PATCH_SPAN = 420;
const THREAD_STEP = 430;
const MIN_ZONE = 140;
const FADE = 0.12;
const QUANTUM = 24;

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

  const svg = svgNode("svg", { class: "thread", "aria-hidden": "true", focusable: "false" });
  const defs = svgNode("defs");
  const strokes = svgNode("g");
  svg.append(defs, strokes);
  world.append(svg);

  const patches = document.createElement("div");
  patches.className = "patches";
  world.append(patches);

  let signature = "";
  let timer = 0;

  const layout = () => {
    const width = Math.round(page.clientWidth);
    const height = Math.round(page.offsetHeight);
    if (!width || !height) return;
    const zones = measure(page);
    const next = `${width}|${zones.map((zone) => `${Math.round(zone.top / QUANTUM)}:${Math.round(zone.bottom / QUANTUM)}`).join(",")}`;
    if (next === signature) return;
    signature = next;

    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

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
