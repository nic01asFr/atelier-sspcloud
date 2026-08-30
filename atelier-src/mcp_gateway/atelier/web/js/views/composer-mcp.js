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
  const { state, onToggle, onManage, onAdvanced } = ctx;
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
    // Le badge signale un écart voulu, pas le socle : il compte ce qui se règle.
    const reglables = connectors.filter((c) => !c.system);
    const activeCount = reglables.filter((c) => c.active).length;
    if (badge) {
      if (reglables.length && activeCount < reglables.length) {
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

    // Ce qui se règle ici, ce sont les services qu'on a branchés soi-même.
    // La coordination et l'accès aux fichiers ne sont pas de cet ordre : un
    // agent en dispose du seul fait de tourner dans un projet, au même titre
    // que de ses outils intégrés. Les faire cocher reviendrait à demander à
    // l'utilisateur de reconfirmer le socle à chaque fil.
    const acquis = connectors.filter((c) => c.system);
    const choisis = connectors.filter((c) => !c.system);

    if (acquis.length) {
      const p = document.createElement("p");
      p.className = "composer-mcp-acquis";
      const noms = acquis.map((c) => {
        if (c.group === "Accès aux fichiers" && (c.scope || []).length) {
          return `fichiers (${c.scope[0]})`;
        }
        if (c.group === "Accès aux outils") return "accès aux outils";
        return c.group.toLowerCase();
      });
      p.textContent = `Acquis : outils intégrés, ${noms.join(", ")}.`;
      p.title =
        "Le socle d'un agent : son dossier de travail et les services que " +
        "l'Atelier lui fournit. Il se règle dans Connecteurs, pas par fil.";
      pop.appendChild(p);

      // Un service du socle désactivé est un état qu'on ne devinerait pas
      // sans l'afficher : on le montre, et on laisse le rallumer.
      for (const c of acquis.filter((x) => !x.active)) {
        const alerte = document.createElement("p");
        alerte.className = "composer-mcp-coupe";
        const txt = document.createElement("span");
        txt.textContent = `${c.name} est coupé sur ce fil.`;
        const rallume = document.createElement("button");
        rallume.type = "button";
        rallume.className = "linklike";
        rallume.textContent = "Rétablir";
        rallume.disabled = state.mcpOverlayBusy;
        rallume.addEventListener("click", () => onToggle(c.id, true));
        alerte.appendChild(txt);
        alerte.appendChild(rallume);
        pop.appendChild(alerte);
      }
    }

    if (!choisis.length) {
      const empty = document.createElement("p");
      empty.className = "composer-mcp-empty";
      empty.textContent = connectors.length
        ? "Aucun service personnalisé sur ce fil — branche-en un dans Connecteurs."
        : "Aucun connecteur lié — configure le binding projet ou l’onglet Connecteurs.";
      pop.appendChild(empty);
    } else {
      const titre = document.createElement("p");
      titre.className = "composer-mcp-group";
      titre.textContent = "Services connectés";
      pop.appendChild(titre);

      const infosDe = (id) => {
        const parts = (state.toolsByService || []).filter(
          (x) => String(x.key).split("#")[0] === "registry:" + id
        );
        if (!parts.length) return null;
        return { count: parts.reduce((n, p) => n + (p.count || 0), 0) };
      };

      const ul = document.createElement("ul");
      ul.className = "composer-mcp-list";
      for (const c of choisis) {
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
        label.appendChild(cb);
        label.appendChild(name);
        li.appendChild(label);

        const infos = infosDe(c.id);
        if (infos?.count) {
          const n = document.createElement("span");
          n.className = "composer-mcp-count";
          n.textContent = `${infos.count} outils`;
          li.appendChild(n);
        }

        const badgeEl = document.createElement("span");
        badgeEl.className = healthBadgeClass(c.health);
        badgeEl.textContent = healthLabel(c.health);
        li.appendChild(badgeEl);
        ul.appendChild(li);
      }
      pop.appendChild(ul);
    }

    const foot = document.createElement("div");
    foot.className = "composer-mcp-foot";
    if (state.slug) {
      const avance = document.createElement("button");
      avance.type = "button";
      avance.className = "linklike";
      avance.textContent = "Configuration avancée";
      avance.title =
        "Choisir les services ouverts à ce projet, pour toutes ses conversations.";
      avance.addEventListener("click", (e) => {
        e.preventDefault();
        onAdvanced?.();
      });
      foot.appendChild(avance);
    }
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
