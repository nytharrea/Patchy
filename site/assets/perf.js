import { FLAT, FULL, LITE } from "./glass.js";

const WINDOW = 120;
const SLOW_FRAME = 30;
const SLOW_SHARE = 0.3;
const SETTLE = 2500;
const IDLE = 220;

export function govern(kit) {
  if (navigator.webdriver) return;
  const asked = new URLSearchParams(location.search).get("glass-tier");
  if (asked) return;

  const started = performance.now();
  let scrolling = 0;
  let frame = 0;
  let last = 0;
  let samples = 0;
  let slow = 0;

  const step = (now) => {
    frame = 0;
    if (now > scrolling) {
      last = 0;
      return;
    }
    if (last && now - started > SETTLE && document.visibilityState === "visible") {
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

  window.addEventListener(
    "scroll",
    () => {
      scrolling = performance.now() + IDLE;
      if (!frame) frame = requestAnimationFrame(step);
    },
    { passive: true },
  );
}
