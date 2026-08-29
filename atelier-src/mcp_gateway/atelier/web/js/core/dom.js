/** Helpers DOM minimalistes — pas d'état applicatif. */

export const $ = (id) => document.getElementById(id);

export function showBanner(msg) {
  const el = $("banner");
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}
