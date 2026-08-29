/** Vue Connecteurs — shell sidebar (Plateforme / Perso) + fiche service. */

import { $ } from "../core/dom.js";

function badgeClass(entry, upstreamKey, upstream) {
  if (entry.enabled === false) return "mcp-badge mcp-badge-off";
  const raw = upstream?.[upstreamKey] || "";
  if (raw === "connected" || entry.online) return "mcp-badge mcp-badge-ok";
  if (raw === "stdio-local") return "mcp-badge mcp-badge-stdio";
  if (raw.startsWith("error") || entry.error) return "mcp-badge mcp-badge-err";
  return "mcp-badge mcp-badge-warn";
}

function badgeLabel(entry, upstreamKey, upstream) {
  if (entry.enabled === false) return "désactivé";
  const raw = upstream?.[upstreamKey] || "";
  if (raw === "connected" || entry.online)
    return `connecté · ${entry.tools ?? 0} outils`;
  if (raw === "stdio-local") return "local (CLI)";
  if (raw.startsWith("error")) return raw.replace("error: ", "erreur · ");
  if (entry.error) return entry.error;
  return entry.state || "—";
}

function dotClass(entry, upstreamKey, upstream) {
  if (entry.enabled === false) return "status-dot status-dot-off";
  const raw = upstream?.[upstreamKey] || "";
  if (raw === "connected" || entry.online) return "status-dot status-dot-ok";
  if (raw === "stdio-local") return "status-dot status-dot-pending";
  if (raw.startsWith("error") || entry.error) return "status-dot status-dot-err";
  return "status-dot status-dot-warn";
}

function upstreamKeyFor(entry, kind) {
  return kind === "registry" || entry.kind === "registry"
    ? `registry:${entry.id}`
    : entry.id;
}

function isCompositionsService(entry) {
  const id = String(entry?.id || "").toLowerCase();
  const name = String(entry?.name || "").toLowerCase();
  return /compos/.test(id) || /compos/.test(name);
}

function renderSidebarItem(entry, { kind, selectedId, upstream, actions }) {
  const li = document.createElement("li");
  const key = upstreamKeyFor(entry, kind);
  const selKey = `${kind}:${entry.id}`;
  li.className =
    "agent-card" + (selectedId === selKey ? " agent-card-selected" : "");
  li.addEventListener("click", (e) => {
    if (e.target.closest("input,button")) return;
    actions.select(kind, entry.id);
  });

  const head = document.createElement("div");
  head.className = "agent-card-head";
  const dot = document.createElement("span");
  dot.className = dotClass(entry, key, upstream);
  const name = document.createElement("strong");
  name.className = "agent-card-name";
  name.textContent = entry.name || entry.id;
  const badge = document.createElement("span");
  badge.className = badgeClass(entry, key, upstream);
  badge.textContent = badgeLabel(entry, key, upstream);
  const titleRow = document.createElement("div");
  titleRow.className = "agent-card-title-row";
  titleRow.appendChild(dot);
  titleRow.appendChild(name);
  head.appendChild(titleRow);
  head.appendChild(badge);

  const meta = document.createElement("div");
  meta.className = "agent-card-meta";
  const kindLabel =
    entry.runtime === "stdio" || entry.config?.command
      ? "stdio"
      : entry.transport || "http";
  meta.textContent = `${kindLabel} · ${entry.prefix || entry.id}`;

  li.appendChild(head);
  li.appendChild(meta);
  return li;
}

function renderHome(state, actions) {
  const body = $("connectors-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "Vue d’ensemble";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Les services branchés à ce pod fournissent leurs outils aux sessions Code et aux agents. Choisissez un service dans la liste pour voir son détail.";
  const acts = document.createElement("div");
  acts.className = "agent-head-actions";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "primary btn-sm";
  add.textContent = "+ Ajouter un connecteur";
  add.addEventListener("click", () => actions.openNew());
  acts.appendChild(add);
  head.appendChild(h);
  head.appendChild(lead);
  head.appendChild(acts);
  body.appendChild(head);

  // Vue transverse : ce qui demande une action, pas un doublon de la liste.
  const upstream = state.mcpOverview?.upstream || {};
  const cat = state.mcpOverview?.catalog;
  const tous = [
    ...(cat?.org || []).map((e) => ({ entry: e, kind: "org" })),
    ...(cat?.personal || []).map((e) => ({ entry: e, kind: "registry" })),
  ];
  const asurveiller = tous.filter(({ entry, kind }) => {
    const cls = dotClass(entry, upstreamKeyFor(entry, kind), upstream);
    return cls.includes("status-dot-err") || cls.includes("status-dot-off");
  });

  const sec = document.createElement("section");
  sec.className = "agent-section";
  sec.innerHTML = `<h3 class="connectors-sub">À surveiller</h3>`;
  const ul = document.createElement("ul");
  ul.className = "agent-queue";
  if (!tous.length) {
    const li = document.createElement("li");
    li.className = "mcp-empty";
    li.textContent = "Aucun service branché — utilisez + pour en ajouter un.";
    ul.appendChild(li);
  } else if (!asurveiller.length) {
    const li = document.createElement("li");
    li.className = "mcp-empty";
    const n = tous.length;
    li.textContent = `Tout va bien — ${n} service${n > 1 ? "s" : ""} branché${n > 1 ? "s" : ""}, aucun en erreur.`;
    ul.appendChild(li);
  } else {
    for (const { entry, kind } of asurveiller) {
      const key = upstreamKeyFor(entry, kind);
      const li = document.createElement("li");
      li.className = "agent-queue-item";
      li.addEventListener("click", () => actions.select(kind, entry.id));
      const main = document.createElement("div");
      main.className = "agent-queue-main";
      const titre = document.createElement("strong");
      titre.textContent = entry.name || entry.id;
      const sub = document.createElement("span");
      sub.className = "agent-queue-sub";
      sub.textContent = badgeLabel(entry, key, upstream);
      main.appendChild(titre);
      main.appendChild(sub);
      const dot = document.createElement("span");
      dot.className = dotClass(entry, key, upstream);
      li.appendChild(dot);
      li.appendChild(main);
      ul.appendChild(li);
    }
  }
  sec.appendChild(ul);
  body.appendChild(sec);
}

/** Panel « nouveau » — pleine page, meme archetype que la creation d'agent. */
function renderNew(state, actions) {
  const body = $("connectors-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  head.innerHTML = `
    <h2 class="connectors-title">Nouveau connecteur</h2>
    <p class="connectors-lead">Collez la déclaration du service à brancher. Ses outils deviendront disponibles pour vos sessions et vos agents.</p>
  `;
  body.appendChild(head);

  const sec = document.createElement("section");
  sec.className = "agent-section";
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = "Déclaration du service (JSON)";
  const ta = document.createElement("textarea");
  ta.id = "mcp-import";
  ta.rows = 6;
  ta.placeholder = '{"mcpServers":{"nom":{"command":"…"}}}';
  ta.spellcheck = false;
  label.appendChild(span);
  label.appendChild(ta);
  sec.appendChild(label);

  const acts = document.createElement("div");
  acts.className = "agent-form-actions";
  const annuler = document.createElement("button");
  annuler.type = "button";
  annuler.className = "ghost btn-sm";
  annuler.textContent = "Annuler";
  annuler.addEventListener("click", () => actions.cancelNew());
  const valider = document.createElement("button");
  valider.type = "button";
  valider.id = "btn-mcp-import";
  valider.className = "primary btn-sm";
  valider.textContent = "Ajouter";
  valider.addEventListener("click", () => actions.importMcp());
  acts.appendChild(annuler);
  acts.appendChild(valider);
  sec.appendChild(acts);
  body.appendChild(sec);
}

function renderDetail(entry, kind, state, actions) {
  const body = $("connectors-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const upstream = state.mcpOverview?.upstream || {};
  const key = upstreamKeyFor(entry, kind);

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = entry.name || entry.id;
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent = entry.description || `${kind === "org" ? "Service plateforme" : "Connecteur personnel"}`;
  head.appendChild(h);
  head.appendChild(lead);

  const badge = document.createElement("span");
  badge.className = badgeClass(entry, key, upstream);
  badge.textContent = badgeLabel(entry, key, upstream);
  head.appendChild(badge);

  if (kind === "registry" || entry.kind === "registry") {
    const toolbar = document.createElement("div");
    toolbar.className = "agent-head-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "ghost btn-sm";
    toggle.textContent =
      entry.enabled === false ? "Activer" : "Désactiver";
    toggle.addEventListener("click", () =>
      actions.toggleMcp(entry.id, entry.enabled === false)
    );
    const del = document.createElement("button");
    del.type = "button";
    del.className = "ghost btn-sm agent-profile-del";
    del.textContent = "Supprimer";
    del.addEventListener("click", () => {
      if (confirm(`Supprimer le connecteur « ${entry.name || entry.id} » ?`)) {
        actions.deleteMcp(entry.id);
      }
    });
    toolbar.appendChild(toggle);
    toolbar.appendChild(del);
    head.appendChild(toolbar);
  }
  body.appendChild(head);

  const kvSec = document.createElement("section");
  kvSec.className = "agent-section";
  kvSec.innerHTML = `<h3 class="connectors-sub">Infos</h3>`;
  const ul = document.createElement("ul");
  ul.className = "agent-kv";
  const addKv = (k, v) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="agent-kv-k">${k}</span><span class="agent-kv-v"></span>`;
    li.querySelector(".agent-kv-v").textContent = v;
    ul.appendChild(li);
  };
  addKv("Identifiant", entry.id || "—");
  addKv(
    "Transport",
    entry.runtime === "stdio" || entry.config?.command
      ? "stdio"
      : entry.transport || "—"
  );
  addKv("Outils", String(entry.tools ?? 0));
  kvSec.appendChild(ul);
  body.appendChild(kvSec);

  const comps = state.mcpOverview?.compositions || [];
  const showComps = isCompositionsService(entry) && comps.length;
  if (showComps) {
    const toolsSec = document.createElement("section");
    toolsSec.className = "agent-section";
    toolsSec.innerHTML = `<h3 class="connectors-sub">Compositions</h3>`;
    const tUl = document.createElement("ul");
    tUl.className = "agent-queue";
    for (const c of comps) {
      const li = document.createElement("li");
      li.className = "agent-queue-item";
      const main = document.createElement("div");
      main.className = "agent-queue-main";
      const title = document.createElement("strong");
      title.textContent = c.name || c.id;
      const sub = document.createElement("span");
      sub.className = "agent-queue-sub";
      sub.textContent = c.description || c.status || "";
      main.appendChild(title);
      if (sub.textContent) main.appendChild(sub);
      li.appendChild(main);
      const st = document.createElement("span");
      st.className = "mcp-badge mcp-badge-muted";
      st.textContent = c.status || "composition";
      li.appendChild(st);
      tUl.appendChild(li);
    }
    toolsSec.appendChild(tUl);
    body.appendChild(toolsSec);
  }
}

/**
 * @param {object} ctx
 */
export function createConnectorsView(ctx) {
  const { state, actions } = ctx;

  function renderPoolSummary() {
    const el = $("mcp-pool-summary");
    if (!el) return;
    const ov = state.mcpOverview;
    if (!ov?.pool_summary) {
      el.textContent = "";
      return;
    }
    const s = ov.pool_summary;
    el.innerHTML = "";
    const parts = [
      ["connecté", "connectés", s.connected, "ok"],
      ["stdio", "stdio", s.stdio_local, "stdio"],
      ["erreur", "erreurs", s.error, "err"],
      ["désactivé", "désactivés", s.disabled, "off"],
    ];
    for (const [un, plusieurs, n, cls] of parts) {
      if (!n) continue;
      const span = document.createElement("span");
      span.className = `pool-chip pool-chip-${cls}`;
      span.textContent = `${n} ${n > 1 ? plusieurs : un}`;
      el.appendChild(span);
    }
  }

  function fillGroup(ulId, items, kind) {
    const ul = $(ulId);
    if (!ul) return;
    ul.innerHTML = "";
    if (!items?.length) {
      const li = document.createElement("li");
      li.className = "mcp-empty";
      li.textContent =
        kind === "org"
          ? "Aucun service plateforme sur ce pod."
          : "Aucun connecteur — utilisez + pour en ajouter un.";
      ul.appendChild(li);
      return;
    }
    const upstream = state.mcpOverview?.upstream || {};
    for (const entry of items) {
      ul.appendChild(
        renderSidebarItem(entry, {
          kind,
          selectedId: state.selectedConnectorId,
          upstream,
          actions,
        })
      );
    }
  }

  function findSelected() {
    const raw = state.selectedConnectorId || "";
    const [kind, ...rest] = raw.split(":");
    const id = rest.join(":");
    if (!kind || !id) return null;
    const cat = state.mcpOverview?.catalog;
    const list = kind === "org" ? cat?.org : cat?.personal;
    const entry = (list || []).find((e) => e.id === id);
    return entry ? { entry, kind } : null;
  }

  function renderMcp() {
    renderPoolSummary();
    const cat = state.mcpOverview?.catalog;
    fillGroup("mcp-org-list", cat?.org, "org");
    fillGroup("mcp-list", cat?.personal, "registry");

    const sel = findSelected();
    if (state.connectorPanel === "new") {
      renderNew(state, actions);
    } else if (!sel) {
      renderHome(state, actions);
    } else {
      renderDetail(sel.entry, sel.kind, state, actions);
    }
  }

  return { renderMcp };
}
