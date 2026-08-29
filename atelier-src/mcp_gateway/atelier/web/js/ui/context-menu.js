/** Menu contextuel flottant. */

import { $ } from "../core/dom.js";

export function hideContextMenu(state) {
  const el = $("context-menu");
  if (el) el.hidden = true;
  state.contextMenu = null;
}

export function showContextMenu(state, x, y, items) {
  const el = $("context-menu");
  el.innerHTML = "";
  for (const item of items) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = item.danger ? "ctx-danger" : "";
    btn.textContent = item.label;
    btn.disabled = item.disabled || false;
    btn.addEventListener("click", () => {
      hideContextMenu(state);
      item.action?.();
    });
    el.appendChild(btn);
  }
  el.hidden = false;
  const rect = el.getBoundingClientRect();
  const maxX = window.innerWidth - rect.width - 8;
  const maxY = window.innerHeight - rect.height - 8;
  el.style.left = `${Math.min(x, maxX)}px`;
  el.style.top = `${Math.min(y, maxY)}px`;
}

export function bindContextMenu(state) {
  document.addEventListener("click", (e) => {
    const menu = $("context-menu");
    if (menu && !menu.contains(e.target)) hideContextMenu(state);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hideContextMenu(state);
  });
}
