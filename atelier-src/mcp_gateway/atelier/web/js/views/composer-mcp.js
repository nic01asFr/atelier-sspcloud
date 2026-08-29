/** Popover connecteurs conversation (composer +). */

import { $ } from "../core/dom.js";

function healthBadgeClass(health) {
  if (health === "connected") return "mcp-badge mcp-badge-ok";
  if (health === "stdio-local") return "mcp-badge mcp-badge-stdio";
  if (health?.startsWith("error")) return "mcp-badge mcp-badge-err";
  return "mcp-badge mcp-badge-warn";
}

function healthLabel(health) {
  if (health === "connected") return "connecté";
  if (health === "stdio-local") return "stdio";
  if (health?.startsWith("error")) return health.replace("error: ", "erreur");
  return health || "—";
}

/**
 * @param {object} ctx
 * @param {ReturnType<import("../state.js").createState>} ctx.state
 * @param {(id: string, active: boolean) => Promise<void>} ctx.onToggle
 * @param {() => void} ctx.onManage
 */
export function createComposerMcpView(ctx) {
  const { state, onToggle, onManage } = ctx;
  let open = false;

  function setOpen(value) {
    open = value;
    const btn = $("btn-composer-mcp");
    const pop = $("composer-mcp-popover");
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (pop) pop.hidden = !open;
  }

  function close() {
    setOpen(false);
  }

  function renderPopover() {
    const pop = $("composer-mcp-popover");
    const btn = $("btn-composer-mcp");
    const badge = $("composer-mcp-badge");
    if (!pop || !btn) return;

    const sessionReady =
      state.view === "code" && !!state.token && !!state.sessionId;
    btn.disabled = !sessionReady || state.busy;

    const connectors = state.sessionMcp?.connectors || [];
    const activeCount = connectors.filter((c) => c.active).length;
    if (badge) {
      if (connectors.length && activeCount < connectors.length) {
        badge.textContent = String(activeCount);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    }

    if (!open || !sessionReady) {
      pop.hidden = true;
      return;
    }

    pop.hidden = false;
    pop.innerHTML = "";

    const head = document.createElement("div");
    head.className = "composer-mcp-head";
    head.textContent = "Connecteurs — ce fil";
    pop.appendChild(head);

    const data = state.sessionMcp;

    if (!connectors.length) {
      const empty = document.createElement("p");
      empty.className = "composer-mcp-empty";
      empty.textContent =
        "Aucun connecteur lié — configure le binding projet ou l’onglet Connecteurs.";
      pop.appendChild(empty);
    } else {
      const ul = document.createElement("ul");
      ul.className = "composer-mcp-list";
      for (const c of connectors) {
        const li = document.createElement("li");
        li.className = "composer-mcp-item";
        if (!c.active) li.classList.add("composer-mcp-item-off");
        const label = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !!c.active;
        cb.disabled = state.mcpOverlayBusy;
        cb.addEventListener("change", () => {
          onToggle(c.id, cb.checked);
        });
        const name = document.createElement("span");
        name.className = "composer-mcp-name";
        name.textContent = c.name || c.id;
        const badgeEl = document.createElement("span");
        badgeEl.className = healthBadgeClass(c.health);
        badgeEl.textContent = healthLabel(c.health);
        label.appendChild(cb);
        label.appendChild(name);
        li.appendChild(label);
        li.appendChild(badgeEl);
        ul.appendChild(li);
      }
      pop.appendChild(ul);
    }

    const foot = document.createElement("div");
    foot.className = "composer-mcp-foot";
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = "Gérer dans Connecteurs";
    link.addEventListener("click", (e) => {
      e.preventDefault();
      onManage();
    });
    foot.appendChild(link);
    pop.appendChild(foot);
  }

  function renderComposerMcp() {
    renderPopover();
  }

  return { renderComposerMcp, setOpen, close, isOpen: () => open };
}
