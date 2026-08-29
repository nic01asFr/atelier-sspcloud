/** Textarea auto-height — grandit avec le contenu jusqu'à maxHeight, puis scroll interne. */

const bindings = new WeakMap();

/**
 * @param {HTMLTextAreaElement | null} el
 * @param {{ maxHeight?: number, onSync?: () => void }} [options]
 */
export function bindAutoGrowTextarea(el, options = {}) {
  if (!el) return { sync: () => {}, reset: () => {}, destroy: () => {} };

  const maxHeight = options.maxHeight ?? 160;
  const minHeight = el.offsetHeight || 44;

  function sync() {
    el.style.height = "auto";
    const scroll = el.scrollHeight;
    const height = Math.min(Math.max(scroll, minHeight), maxHeight);
    el.style.height = `${height}px`;
    el.style.overflowY = scroll > maxHeight ? "auto" : "hidden";
    options.onSync?.();
  }

  function reset() {
    el.value = "";
    sync();
  }

  const onInput = () => sync();
  const onResize = () => sync();

  el.addEventListener("input", onInput);
  window.addEventListener("resize", onResize);
  requestAnimationFrame(sync);

  const api = { sync, reset, destroy: () => {
    el.removeEventListener("input", onInput);
    window.removeEventListener("resize", onResize);
    bindings.delete(el);
  } };
  bindings.set(el, api);
  return api;
}

/** @param {HTMLTextAreaElement | null} el */
export function syncAutoGrowTextarea(el) {
  const b = bindings.get(el);
  if (b) b.sync();
}
