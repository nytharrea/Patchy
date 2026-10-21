const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const easeOut = (x) => 1 - Math.pow(1 - x, 3);

export async function initLens(stage, glass) {
  const lens = stage.querySelector(".lens");
  if (!lens) return;
  await customElements.whenDefined("glass-surface");

  const clear = glass && glass.materials && glass.materials.clear;
  if (clear) {
    for (const appearance of ["dark", "light"]) {
      if (clear[appearance]) Object.assign(clear[appearance], { lift: 0, roll: 0, fill: "rgba(0,0,0,0)" });
    }
  }
  requestAnimationFrame(() => {
    if (lens.surface) lens.surface.set({ zoom: 1.12, fill: "rgba(0,0,0,0)" });
  });

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const rest = { x: 0.34, y: 0.5 };
  const ratio = { x: rest.x, y: rest.y };
  let size = lens.offsetWidth;
  let frame = 0;

  const range = () => ({
    minX: -size * 0.18,
    maxX: stage.clientWidth - size * 0.82,
    minY: -size * 0.2,
    maxY: stage.clientHeight - size * 0.8,
  });

  const place = (x, y) => {
    const box = range();
    const px = clamp(x, box.minX, box.maxX);
    const py = clamp(y, box.minY, box.maxY);
    lens.style.transform = `translate3d(${px}px, ${py}px, 0)`;
    return { x: px, y: py };
  };

  const placeRatio = (rx, ry) => {
    const box = range();
    return place(box.minX + (box.maxX - box.minX) * rx, box.minY + (box.maxY - box.minY) * ry);
  };

  const remember = (pos) => {
    const box = range();
    ratio.x = (pos.x - box.minX) / (box.maxX - box.minX || 1);
    ratio.y = (pos.y - box.minY) / (box.maxY - box.minY || 1);
  };

  let current = placeRatio(ratio.x, ratio.y);

  const cancelIntro = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  };

  if (!reduced) {
    const from = 0.94;
    const began = performance.now() + 900;
    current = placeRatio(from, ratio.y);
    const tick = (now) => {
      const progress = clamp((now - began) / 1500, 0, 1);
      current = placeRatio(from + (rest.x - from) * easeOut(progress), ratio.y);
      remember(current);
      frame = progress < 1 ? requestAnimationFrame(tick) : 0;
    };
    frame = requestAnimationFrame(tick);
  }

  lens.addEventListener("pointerdown", (event) => {
    if (event.button > 0) return;
    cancelIntro();
    lens.setPointerCapture(event.pointerId);
    lens.classList.add("is-dragging");
    const startX = event.clientX;
    const startY = event.clientY;
    const originX = current.x;
    const originY = current.y;

    const move = (moveEvent) => {
      current = place(originX + moveEvent.clientX - startX, originY + moveEvent.clientY - startY);
    };

    const stop = (stopEvent) => {
      if (lens.hasPointerCapture(stopEvent.pointerId)) lens.releasePointerCapture(stopEvent.pointerId);
      lens.classList.remove("is-dragging");
      lens.removeEventListener("pointermove", move);
      lens.removeEventListener("pointerup", stop);
      lens.removeEventListener("pointercancel", stop);
      remember(current);
    };

    lens.addEventListener("pointermove", move);
    lens.addEventListener("pointerup", stop);
    lens.addEventListener("pointercancel", stop);
  });

  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => {
      size = lens.offsetWidth;
      current = placeRatio(ratio.x, ratio.y);
    }).observe(stage);
  }
}
