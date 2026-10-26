const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const easeOut = (x) => 1 - Math.pow(1 - x, 3);

const HOME_ANGLE = -135;
const ANGLE_STEP = 6;
const EDGE = 8;
const REST = { x: 0.34, y: 0.5 };
const START_X = 0.94;

async function surfaceOf(lens) {
  for (let frame = 0; frame < 40; frame += 1) {
    if (lens.surface) return lens.surface;
    await new Promise((resolve) => requestAnimationFrame(resolve));
  }
  return null;
}

function tuneMaterials(glass) {
  const clear = glass && glass.materials && glass.materials.clear;
  if (!clear) return;
  for (const appearance of ["dark", "light"]) {
    if (clear[appearance]) Object.assign(clear[appearance], { lift: 0, roll: 0, fill: "rgba(0,0,0,0)" });
  }
}

function tiltAngle(event) {
  const side = clamp(event.gamma || 0, -45, 45) / 45;
  const front = clamp((event.beta || 0) - 50, -45, 45) / 45;
  return (Math.atan2(-0.7 + front * 0.9, -0.7 + side * 0.9) * 180) / Math.PI;
}

export async function initLens(stage, glass, scenes) {
  const lens = stage.querySelector(".lens");
  if (!lens) return;
  await customElements.whenDefined("glass-surface");
  tuneMaterials(glass);
  const surface = await surfaceOf(lens);
  if (!surface) return;
  const tune = () => {
    const height = lens.offsetHeight;
    if (!height) return;
    surface.set({
      zoom: 1.12,
      fill: "rgba(0,0,0,0)",
      dispersion: 0.2,
      blur: document.documentElement.dataset.glass === "live" ? 0.6 : 0,
      bezel: clamp(Math.round(height * 0.2), 11, 16),
      refraction: clamp(Math.round(height * 0.12), 6, 9),
    });
  };
  tune();

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const sceneMode = document.documentElement.dataset.glass === "scene";

  const ratio = { x: REST.x, y: REST.y };
  const pos = { x: 0, y: 0 };
  let motion = 0;
  let drag = null;

  const range = () => ({
    minX: EDGE,
    maxX: Math.max(EDGE, stage.clientWidth - lens.offsetWidth - EDGE),
    minY: EDGE,
    maxY: Math.max(EDGE, stage.clientHeight - lens.offsetHeight - EDGE),
  });

  const place = (x, y) => {
    const box = range();
    pos.x = clamp(x, box.minX, box.maxX);
    pos.y = clamp(y, box.minY, box.maxY);
    lens.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0)`;
    if (typeof stage.poke === "function") stage.poke();
  };

  const placeRatio = (rx, ry) => {
    const box = range();
    place(box.minX + (box.maxX - box.minX) * rx, box.minY + (box.maxY - box.minY) * ry);
  };

  const remember = () => {
    const box = range();
    ratio.x = (pos.x - box.minX) / (box.maxX - box.minX || 1);
    ratio.y = (pos.y - box.minY) / (box.maxY - box.minY || 1);
  };

  const stop = () => {
    if (motion) cancelAnimationFrame(motion);
    motion = 0;
  };

  const glide = (vx, vy) => {
    if (reduced || Math.hypot(vx, vy) < 0.05) {
      remember();
      return;
    }
    let last = performance.now();
    const tick = (now) => {
      const dt = Math.min(now - last, 40);
      last = now;
      const box = range();
      let x = pos.x + vx * dt;
      let y = pos.y + vy * dt;
      if (x < box.minX || x > box.maxX) vx = -vx * 0.4;
      if (y < box.minY || y > box.maxY) vy = -vy * 0.4;
      const decay = Math.exp(-dt / 240);
      vx *= decay;
      vy *= decay;
      place(x, y);
      if (Math.hypot(vx, vy) > 0.02) {
        motion = requestAnimationFrame(tick);
      } else {
        motion = 0;
        remember();
      }
    };
    motion = requestAnimationFrame(tick);
  };

  placeRatio(START_X, ratio.y);

  const arrive = (delay) => {
    if (reduced) {
      placeRatio(REST.x, REST.y);
      surface.setOpacity(1);
      lens.style.pointerEvents = "";
      return;
    }
    const began = performance.now() + delay;
    const tick = (now) => {
      const progress = clamp((now - began) / 1500, 0, 1);
      placeRatio(START_X + (REST.x - START_X) * easeOut(progress), ratio.y);
      if (sceneMode) surface.setOpacity(clamp(progress * 4, 0, 1));
      if (progress < 1) {
        motion = requestAnimationFrame(tick);
      } else {
        motion = 0;
        remember();
        lens.style.pointerEvents = "";
      }
    };
    motion = requestAnimationFrame(tick);
  };

  if (sceneMode) {
    surface.setOpacity(0);
    lens.style.pointerEvents = "none";
    Promise.resolve(scenes && scenes.ready).then(() => arrive(120));
  } else {
    arrive(900);
  }

  lens.addEventListener("pointerdown", (event) => {
    if (event.button > 0 || drag) return;
    stop();
    lens.setPointerCapture(event.pointerId);
    lens.classList.add("is-dragging");
    drag = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      ox: pos.x,
      oy: pos.y,
      trail: [{ t: event.timeStamp, x: pos.x, y: pos.y }],
    };
  });

  lens.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    place(drag.ox + event.clientX - drag.x, drag.oy + event.clientY - drag.y);
    drag.trail.push({ t: event.timeStamp, x: pos.x, y: pos.y });
    while (drag.trail.length > 2 && event.timeStamp - drag.trail[0].t > 90) drag.trail.shift();
  });

  const release = (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    if (lens.hasPointerCapture(event.pointerId)) lens.releasePointerCapture(event.pointerId);
    lens.classList.remove("is-dragging");
    const first = drag.trail[0];
    const last = drag.trail[drag.trail.length - 1];
    const span = last.t - first.t;
    const fresh = event.timeStamp - last.t < 80;
    const vx = span > 0 && fresh ? (last.x - first.x) / span : 0;
    const vy = span > 0 && fresh ? (last.y - first.y) / span : 0;
    drag = null;
    remember();
    if (event.type === "pointerup") glide(clamp(vx, -3, 3), clamp(vy, -3, 3));
  };

  lens.addEventListener("pointerup", release);
  lens.addEventListener("pointercancel", release);

  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => {
      tune();
      if (drag || motion) return;
      placeRatio(ratio.x, ratio.y);
    }).observe(stage);
  }

  if (reduced) return;

  const light = { target: HOME_ANGLE, current: HOME_ANGLE, applied: HOME_ANGLE, frame: 0, stamp: 0 };

  const relight = (now) => {
    light.frame = 0;
    const diff = ((light.target - light.current + 540) % 360) - 180;
    light.current = ((light.current + diff * 0.22 + 540) % 360) - 180;
    const snapped = Math.round(light.current / ANGLE_STEP) * ANGLE_STEP;
    if (snapped !== light.applied && now - light.stamp > 70) {
      light.applied = snapped;
      light.stamp = now;
      surface.set({ lightAngle: snapped });
    }
    if (Math.abs(diff) > 0.6 || snapped !== light.applied) light.frame = requestAnimationFrame(relight);
  };

  const aim = (angle) => {
    light.target = angle;
    if (!light.frame) light.frame = requestAnimationFrame(relight);
  };

  const follow = (event) => {
    const box = lens.getBoundingClientRect();
    const dx = event.clientX - (box.left + box.width / 2);
    const dy = event.clientY - (box.top + box.height / 2);
    if (Math.abs(dx) + Math.abs(dy) < 4) return;
    aim((Math.atan2(dy, dx) * 180) / Math.PI);
  };

  const tilt = (event) => {
    if (event.gamma === null || event.gamma === undefined) return;
    aim(tiltAngle(event));
  };

  const motionSensor =
    coarse && "DeviceOrientationEvent" in window && typeof window.DeviceOrientationEvent.requestPermission !== "function";

  const listen = (on) => {
    const method = on ? "addEventListener" : "removeEventListener";
    window[method]("pointermove", follow, { passive: true });
    if (motionSensor) window[method]("deviceorientation", tilt, { passive: true });
  };

  if (typeof IntersectionObserver === "function") {
    new IntersectionObserver((entries) => listen(entries.some((entry) => entry.isIntersecting))).observe(stage);
  } else {
    listen(true);
  }
}
