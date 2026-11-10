import { FLAT, FULL, LITE } from "./glass.js";

const WINDOW = 120;
const SLOW_FRAME = 30;
const SLOW_SHARE = 0.3;
const SETTLE = 2500;
const IDLE = 220;

function detectWebViewOrSoftwareGpu() {
  const ua = navigator.userAgent || "";
  if (/;\s*wv\)|FBAN|FBAV|Instagram|Line\//i.test(ua)) return true;
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) return true;
    const debug = gl.getExtension("WEBGL_debug_renderer_info");
    if (debug) {
      const renderer = String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) || "");
      if (/SwiftShader|llvmpipe|Software|Basic Render/i.test(renderer)) return true;
    }
  } catch (error) {
    return true;
  }
  return false;
}

export function govern(kit) {
  if (navigator.webdriver) return;
  const asked = new URLSearchParams(location.search).get("glass-tier");
  if (asked) return;

  if (detectWebViewOrSoftwareGpu() && kit.tier() === FULL) {
    kit.setTier(LITE, false);
  }

  const started = performance.now();
  let scrolling = 0;
  let frame = 0;
  let last = 0;
  let samples = 0;
  let slow = 0;

  const stopLoop = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    last = 0;
  };

  const step = (now) => {
    frame = 0;
    if (document.visibilityState !== "visible" || now > scrolling) {
      last = 0;
      return;
    }
    if (last && now - started > SETTLE) {
      samples += 1;
      if (now - last > SLOW_FRAME) slow += 1;
      if (samples >= WINDOW) {
        if (slow / samples > SLOW_SHARE) degrade();
        samples = 0;
        slow = 0;
      }
    }
    last = now;
    frame = requestAnimationFrame(step);
  };

  const degrade = () => {
    const tier = kit.tier();
    if (tier === FULL) kit.setTier(LITE);
    else if (tier === LITE) kit.setTier(FLAT);
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") stopLoop();
  });

  window.addEventListener(
    "scroll",
    () => {
      if (document.visibilityState !== "visible") return;
      scrolling = performance.now() + IDLE;
      if (!frame) frame = requestAnimationFrame(step);
    },
    { passive: true },
  );
}
