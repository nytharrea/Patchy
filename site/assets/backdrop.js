const SVG_NS = "http://www.w3.org/2000/svg";
const GRID = 22;
const DOT = 1.4;
const SEAM_INSET = 10;
const SEAM_WIDTH = 3;
const SEAM_DASH = [12, 10];
const WALL_MAX_DPR = 2;
const WALL_MAX_PIXELS = 6e6;
const ART_MAX_DPR = 3;
const ART_MAX_PIXELS = 1.2e7;

const root = document.documentElement;

const token = (name) => getComputedStyle(root).getPropertyValue(name).trim();

function withAlpha(color, alpha) {
  let match = /^#([\da-f]{3}|[\da-f]{6})$/i.exec(color);
  if (match) {
    let hex = match[1];
    if (hex.length === 3) hex = hex.replace(/./g, "$&$&");
    const value = parseInt(hex, 16);
    return `rgba(${value >> 16}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
  }
  match = /^rgba?\(([^)]+)\)/i.exec(color);
  if (match) {
    const [red, green, blue] = match[1].split(/[\s,/]+/).map(Number);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }
  return color;
}

function fitScale(width, height, maxRatio, maxPixels) {
  let scale = Math.min(window.devicePixelRatio || 1, maxRatio);
  const pixels = width * height * scale * scale;
  if (pixels > maxPixels) scale *= Math.sqrt(maxPixels / pixels);
  return scale;
}

function prepare(canvas, width, height, scale) {
  const pixelWidth = Math.max(1, Math.round(width * scale));
  const pixelHeight = Math.max(1, Math.round(height * scale));
  if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
  if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
  const ctx = canvas.getContext("2d", { alpha: false });
  ctx.setTransform(pixelWidth / width, 0, 0, pixelHeight / height, 0, 0);
  ctx.setLineDash([]);
  return ctx;
}

function dots(ctx, width, height, color) {
  ctx.beginPath();
  for (let y = GRID / 2; y < height; y += GRID) {
    for (let x = GRID / 2; x < width; x += GRID) {
      ctx.moveTo(x + DOT, y);
      ctx.arc(x, y, DOT, 0, Math.PI * 2);
    }
  }
  ctx.fillStyle = color;
  ctx.fill();
}

function glow(ctx, width, height, x, y, radius, color, end) {
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
  gradient.addColorStop(0, color);
  gradient.addColorStop(end, withAlpha(color, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
}

function ellipseGlow(ctx, width, height, x, y, radiusX, radiusY, color, end) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(radiusX, radiusY);
  const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
  gradient.addColorStop(0, color);
  gradient.addColorStop(end, withAlpha(color, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(-x / radiusX, -y / radiusY, width / radiusX, height / radiusY);
  ctx.restore();
}

function linear(ctx, width, height, degrees, from, to) {
  const angle = (degrees * Math.PI) / 180;
  const dx = Math.sin(angle);
  const dy = -Math.cos(angle);
  const length = Math.abs(width * dx) + Math.abs(height * dy);
  const gradient = ctx.createLinearGradient(
    width / 2 - (dx * length) / 2,
    height / 2 - (dy * length) / 2,
    width / 2 + (dx * length) / 2,
    height / 2 + (dy * length) / 2,
  );
  gradient.addColorStop(0, from);
  gradient.addColorStop(1, to);
  return gradient;
}

function roundedRect(ctx, x, y, width, height, radius) {
  const r = Math.max(0, Math.min(radius, width / 2, height / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function paintWall(canvas) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return false;
  const ctx = prepare(canvas, width, height, fitScale(width, height, WALL_MAX_DPR, WALL_MAX_PIXELS));
  const vmax = Math.max(width, height) / 100;
  ctx.fillStyle = token("--bg-base");
  ctx.fillRect(0, 0, width, height);
  glow(ctx, width, height, width * 0.52, height * 0.98, 70 * vmax, token("--bg-c"), 0.62);
  glow(ctx, width, height, width * 0.96, height * 0.16, 50 * vmax, token("--bg-b"), 0.62);
  glow(ctx, width, height, width * 0.12, height * 0.06, 60 * vmax, token("--bg-a"), 0.6);
  dots(ctx, width, height, token("--dot"));
  return true;
}

function stageRadius(stage) {
  return parseFloat(getComputedStyle(stage).borderTopLeftRadius) || 0;
}

function seamGeometry(width, height, radius) {
  const half = SEAM_INSET + SEAM_WIDTH / 2;
  return { x: half, y: half, width: width - half * 2, height: height - half * 2, radius: Math.max(0, radius - half) };
}

function paintArt(canvas, stage, art) {
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  if (!width || !height) return false;
  const ctx = prepare(canvas, width, height, fitScale(width, height, ART_MAX_DPR, ART_MAX_PIXELS));

  ctx.fillStyle = linear(ctx, width, height, 158, token("--patch-a"), token("--patch-b"));
  ctx.fillRect(0, 0, width, height);
  ellipseGlow(ctx, width, height, width * 0.18, 0, width * 1.2, height * 0.9, token("--patch-hi"), 0.6);
  dots(ctx, width, height, token("--patch-dot"));

  const seam = seamGeometry(width, height, stageRadius(stage));
  ctx.save();
  roundedRect(ctx, seam.x, seam.y, seam.width, seam.height, seam.radius);
  ctx.strokeStyle = token("--patch-seam");
  ctx.lineWidth = SEAM_WIDTH;
  ctx.lineCap = "round";
  ctx.setLineDash(SEAM_DASH);
  ctx.stroke();
  ctx.restore();

  const box = art.svg.getBoundingClientRect();
  const frame = stage.getBoundingClientRect();
  const view = art.svg.viewBox.baseVal;
  if (box.width && view && view.width) {
    const scale = box.width / view.width;
    ctx.save();
    ctx.translate(box.left - frame.left, box.top - frame.top);
    ctx.scale(scale, scale);
    ctx.fillStyle = token("--wm-fill");
    ctx.fill(art.fill);
    if (art.stitched) {
      ctx.strokeStyle = token("--wm-stitch");
      ctx.lineWidth = 12;
      ctx.lineCap = "round";
      ctx.setLineDash([30, 26]);
      ctx.stroke(art.stitch);
    }
    ctx.restore();
  }
  return true;
}

export function initSeam(stage) {
  if (!stage || stage.querySelector(".seam")) return;
  const svg = document.createElementNS(SVG_NS, "svg");
  const rect = document.createElementNS(SVG_NS, "rect");
  svg.setAttribute("class", "seam");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.append(rect);
  stage.prepend(svg);

  const place = () => {
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    if (!width || !height) return;
    const seam = seamGeometry(width, height, stageRadius(stage));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    rect.setAttribute("x", seam.x);
    rect.setAttribute("y", seam.y);
    rect.setAttribute("width", seam.width);
    rect.setAttribute("height", seam.height);
    rect.setAttribute("rx", seam.radius);
    rect.setAttribute("ry", seam.radius);
  };

  place();
  stage.classList.add("has-seam");
  if (typeof ResizeObserver === "function") new ResizeObserver(place).observe(stage);
}

function canvasFor(id, className) {
  const canvas = document.createElement("canvas");
  canvas.id = id;
  canvas.className = className;
  canvas.setAttribute("aria-hidden", "true");
  return canvas;
}

function whenSewn(stitch) {
  const running = typeof stitch.getAnimations === "function" ? stitch.getAnimations() : [];
  return Promise.all(running.map((animation) => animation.finished.catch(() => undefined)));
}

export function initBackdrops(glass, { scene, stage }) {
  const forced = new URLSearchParams(location.search).get("glass") === "scene";
  const live = glass.supportsBackdropSvg() && !forced;
  const webgl = glass.supportsWebGL();
  root.dataset.glass = live ? "live" : webgl ? "scene" : "frost";
  if (live || !webgl || !scene || !stage) return null;
  if (forced) {
    scene.setAttribute("force", "");
    stage.setAttribute("force", "");
  }

  const svg = stage.querySelector(".wordmark svg");
  const fill = svg && svg.querySelector(".wm-fill");
  const stitch = svg && svg.querySelector(".wm-stitch");
  if (!fill || !stitch) {
    root.dataset.glass = "frost";
    return null;
  }

  const wall = canvasFor("wall", "wall");
  const stageArt = canvasFor("stage-art", "stage-art");
  scene.prepend(wall);
  stage.append(stageArt);

  const art = {
    svg,
    fill: new Path2D(fill.getAttribute("d")),
    stitch: new Path2D(stitch.getAttribute("d")),
    stitched: false,
  };

  const drawWall = () => {
    if (paintWall(wall) && typeof scene.invalidate === "function") scene.invalidate();
  };
  const drawArt = () => {
    if (paintArt(stageArt, stage, art) && typeof stage.invalidate === "function") stage.invalidate();
  };
  const drawAll = () => {
    drawWall();
    drawArt();
  };

  drawAll();
  scene.setAttribute("backdrop", "#wall");
  stage.setAttribute("backdrop", "#stage-art");

  let timer = 0;
  const later = (task, delay) => {
    clearTimeout(timer);
    timer = setTimeout(task, delay);
  };

  if (typeof ResizeObserver === "function") {
    let wallSeen = false;
    new ResizeObserver(() => {
      if (!wallSeen) {
        wallSeen = true;
        return;
      }
      later(drawWall, 120);
    }).observe(wall);
    let artSeen = false;
    new ResizeObserver(() => {
      if (!artSeen) {
        artSeen = true;
        return;
      }
      requestAnimationFrame(drawArt);
    }).observe(stage);
  }

  new MutationObserver(() => requestAnimationFrame(drawAll)).observe(root, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });

  const watchRatio = () => {
    const query = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
    query.addEventListener(
      "change",
      () => {
        later(drawAll, 120);
        watchRatio();
      },
      { once: true },
    );
  };
  watchRatio();

  const ready = whenSewn(stitch).then(() => {
    art.stitched = true;
    drawArt();
  });

  return { ready, redraw: drawAll };
}
