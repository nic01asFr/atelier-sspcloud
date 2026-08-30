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

function badgeLabel(entry, upstreamKey, upstream, compte) {
  if (entry.enabled === false) return "désactivé";
  const raw = upstream?.[upstreamKey] || "";
  const n = entry.tools || compte || 0;
  if (raw === "connected" || entry.online) return `connecté · ${n} outils`;
  // Un serveur lancé par le client final ne se compte pas tout seul : son
  // nombre d'outils vient du sondage, comme dans le reste de l'application.
  if (raw === "stdio-local") return n ? `local · ${n} outils` : "local (CLI)";
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

function renderSidebarItem(entry, { kind, selectedId, upstream, actions, titre, sous, compte }) {
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
  name.textContent = titre || entry.name || entry.id;
  const badge = document.createElement("span");
  badge.className = badgeClass(entry, key, upstream);
  badge.textContent = badgeLabel(entry, key, upstream, compte);
  const titleRow = document.createElement("div");
  titleRow.className = "agent-card-title-row";
  titleRow.appendChild(dot);
  titleRow.appendChild(name);
  head.appendChild(titleRow);
  head.appendChild(badge);

  const meta = document.createElement("div");
  meta.className = "agent-card-meta";
  if (sous) {
    // Un service du socle se nomme par ce qu'il apporte ; son identité
    // technique reste lisible, mais au second plan.
    meta.textContent = sous;
  } else {
    const kindLabel =
      entry.runtime === "stdio" || entry.config?.command
        ? "stdio"
        : entry.transport || "http";
    meta.textContent = `${kindLabel} · ${entry.prefix || entry.id}`;
  }

  li.appendChild(head);
  li.appendChild(meta);
  return li;
}


/**
 * Une composition dans la liste latérale.
 *
 * C'est un outil, pas un service : elle se présente en ligne légère et
 * subordonnée, non en carte de même rang que wikichat ou le serveur de
 * fichiers.
 */
function renderCompositionItem(comp, selectedId, actions) {
  const li = document.createElement("li");
  li.className =
    "composition-item" + (selectedId === comp.id ? " composition-item-selected" : "");
  li.addEventListener("click", () => actions.selectComposition(comp.id));

  const dot = document.createElement("span");
  dot.className =
    "status-dot status-dot-" +
    (comp.status === "production" ? "ok" : comp.status === "tested" ? "pending" : "off");
  dot.title =
    comp.status === "production" ? "active" : comp.status === "tested" ? "testée" : "brouillon";

  const nom = document.createElement("span");
  nom.className = "composition-item-name";
  nom.textContent = comp.name;

  const meta = document.createElement("span");
  meta.className = "composition-item-meta";
  const n = comp.steps ?? 0;
  meta.textContent = comp.variant
    ? String(comp.source_tool || "").split("__").pop()
    : `${n} étape${n > 1 ? "s" : ""}`;

  li.appendChild(dot);
  li.appendChild(nom);
  li.appendChild(meta);
  return li;
}

/** Détail d'une composition : ce qu'elle reçoit, ce qu'elle enchaîne. */
function renderCompositionDetail(comp, state, actions) {
  const body = $("connectors-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = comp.name;
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    comp.description ||
    (comp.variant
      ? `Variante de ${comp.source_tool} aux paramètres figés.`
      : "Enchaînement d'outils enregistré.");
  head.appendChild(h);
  head.appendChild(lead);

  const actionsRow = document.createElement("div");
  actionsRow.className = "agent-head-actions";
  const lancer = document.createElement("button");
  lancer.type = "button";
  lancer.className = "primary btn-sm";
  lancer.textContent = "Lancer";
  lancer.addEventListener("click", () => actions.runComposition(comp));
  const bascule = document.createElement("button");
  bascule.type = "button";
  bascule.className = "ghost btn-sm";
  bascule.textContent = comp.status === "production" ? "Désactiver" : "Activer";
  bascule.addEventListener("click", () => actions.toggleComposition(comp));
  const del = document.createElement("button");
  del.type = "button";
  del.className = "ghost btn-sm agent-profile-del";
  del.textContent = "Supprimer";
  del.addEventListener("click", () => actions.deleteComposition(comp));
  actionsRow.appendChild(lancer);
  actionsRow.appendChild(bascule);
  actionsRow.appendChild(del);
  head.appendChild(actionsRow);
  body.appendChild(head);

  const def = comp.definition || comp;
  const entrees = Object.keys(def.input_schema?.properties || {});

  const infos = document.createElement("section");
  infos.className = "agent-section";
  infos.innerHTML = `<h3 class="connectors-sub">Ce qu'elle reçoit</h3>`;
  const ul = document.createElement("ul");
  ul.className = "agent-kv";
  const kv = (k, v) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="agent-kv-k">${k}</span><span class="agent-kv-v"></span>`;
    li.querySelector(".agent-kv-v").textContent = v;
    ul.appendChild(li);
  };
  kv("Entrées", entrees.length ? entrees.join(", ") : "aucune");
  kv("Appelable comme", comp.tool_name || "—");
  kv("État", comp.status || "—");
  infos.appendChild(ul);
  body.appendChild(infos);

  const etapes = document.createElement("section");
  etapes.className = "agent-section";
  etapes.innerHTML = `<h3 class="connectors-sub">Étapes</h3>`;
  const liste = document.createElement("ol");
  liste.className = "composition-steps";
  // Dans la liste, `steps` est un compte ; le détail seul porte le tableau.
  const pas = Array.isArray(def.steps) ? def.steps : [];
  for (const st of pas) {
    const li = document.createElement("li");
    const titre = document.createElement("strong");
    titre.textContent = st.label || st.step_id || st.type;
    const outil = document.createElement("span");
    outil.className = "composition-step-tool";
    outil.textContent = st.tool || st.type;
    li.appendChild(titre);
    li.appendChild(outil);
    const params = st.parameters || {};
    if (Object.keys(params).length) {
      const pre = document.createElement("pre");
      pre.className = "composition-step-params";
      pre.textContent = Object.entries(params)
        .map(([k, v]) => `${k} = ${typeof v === "string" ? v : JSON.stringify(v)}`)
        .join(String.fromCharCode(10));
      li.appendChild(pre);
    }
    liste.appendChild(li);
  }
  if (!pas.length) {
    const li = document.createElement("li");
    li.className = "mcp-empty";
    li.textContent = Array.isArray(def.steps) ? "Aucune étape." : "Lecture des étapes…";
    liste.appendChild(li);
  }
  etapes.appendChild(liste);
  body.appendChild(etapes);
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

/**
 * Fiche du service Compositions.
 *
 * Les autres services se contentent de dire ce qu'ils apportent : celui-ci
 * se gère. C'est ici qu'on voit ce qu'on a fabriqué, ce qui est réellement
 * appelable, et ce qui n'est encore qu'un brouillon.
 */
/**
 * Fiche « Accès aux outils ».
 *
 * Deux outils suffisent à se servir de tous les autres : c'est ce qui permet
 * de ne pas annoncer soixante-dix outils à un agent pour qu'il en emploie
 * deux. La fiche dit d'où vient ce qu'il trouvera.
 */
function renderFicheAcces(state) {
  const body = $("connectors-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const meta = (state.toolsByService || []).find((x) => x.key === "meta:acces");
  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "Accès aux outils";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Chercher un outil parmi tous ceux du pod, puis l’appeler. Un agent qui dispose de ces deux outils atteint tout le reste sans qu’on lui annonce chaque outil un par un.";
  head.appendChild(h);
  head.appendChild(lead);
  body.appendChild(head);

  const sec = document.createElement("section");
  sec.className = "agent-section";
  const h3 = document.createElement("h3");
  h3.className = "connectors-sub";
  h3.textContent = "Les deux outils";
  sec.appendChild(h3);
  const ul = document.createElement("ul");
  ul.className = "agent-queue";
  for (const t of meta?.tools || []) {
    const li = document.createElement("li");
    li.className = "agent-queue-item";
    const main = document.createElement("div");
    main.className = "agent-queue-main";
    const nom = document.createElement("strong");
    nom.textContent = t.label || t.short || t.name;
    const sub = document.createElement("span");
    sub.className = "agent-queue-sub";
    sub.textContent = t.description || "";
    main.appendChild(nom);
    if (sub.textContent) main.appendChild(sub);
    li.appendChild(main);
    ul.appendChild(li);
  }
  sec.appendChild(ul);
  body.appendChild(sec);

  const portee = document.createElement("section");
  portee.className = "agent-section";
  const h4 = document.createElement("h3");
  h4.className = "connectors-sub";
  h4.textContent = "Ce qu’ils atteignent";
  const p = document.createElement("p");
  p.className = "agent-section-hint";
  const total = (state.toolsByService || [])
    .filter((x) => String(x.key).startsWith("registry:"))
    .reduce((n, x) => n + (x.count || 0), 0);
  p.textContent = `Tous les connecteurs branchés à ce pod — ${total} outils aujourd’hui — sans avoir à les annoncer.`;
  portee.appendChild(h4);
  portee.appendChild(p);
  body.appendChild(portee);
}

function renderCompositionsService(state, actions) {
  const body = $("connectors-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const liste = state.compositions || [];
  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "Compositions";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Des outils fabriqués ici : un appel aux paramètres figés, ou un enchaînement d’étapes. Une fois active, une composition s’appelle comme n’importe quel outil.";
  head.appendChild(h);
  head.appendChild(lead);

  const actionsBar = document.createElement("div");
  actionsBar.className = "agent-head-actions";
  const neuf = document.createElement("button");
  neuf.type = "button";
  neuf.className = "primary btn-sm";
  neuf.textContent = "Nouvelle composition";
  neuf.addEventListener("click", () => actions.newComposition?.());
  actionsBar.appendChild(neuf);
  head.appendChild(actionsBar);
  body.appendChild(head);

  const rangs = [
    ["production", "Actives", "Appelables comme un outil."],
    ["tested", "Testées", "Validées, pas encore ouvertes à l’appel."],
    ["draft", "Brouillons", "Écrites, jamais exécutées."],
  ];
  let vide = true;
  for (const [statut, titre, sous] of rangs) {
    const dedans = liste.filter((c) => (c.status || "draft") === statut);
    if (!dedans.length) continue;
    vide = false;
    const sec = document.createElement("section");
    sec.className = "agent-section";
    const h3 = document.createElement("h3");
    h3.className = "connectors-sub";
    h3.textContent = titre;
    const p = document.createElement("p");
    p.className = "agent-section-hint";
    p.textContent = sous;
    sec.appendChild(h3);
    sec.appendChild(p);
    const ul = document.createElement("ul");
    ul.className = "agent-queue";
    for (const c of dedans) {
      const li = document.createElement("li");
      li.className = "agent-queue-item";
      li.addEventListener("click", () => actions.selectComposition(c.id));
      const main = document.createElement("div");
      main.className = "agent-queue-main";
      const nom = document.createElement("strong");
      nom.textContent = c.name || c.id;
      const sub = document.createElement("span");
      sub.className = "agent-queue-sub";
      const n = c.steps ?? 0;
      sub.textContent =
        c.description ||
        (c.variant
          ? `variante de ${String(c.source_tool || "").split("__").pop()}`
          : `${n} étape${n > 1 ? "s" : ""}`);
      main.appendChild(nom);
      main.appendChild(sub);
      li.appendChild(main);
      ul.appendChild(li);
    }
    sec.appendChild(ul);
    body.appendChild(sec);
  }

  if (vide) {
    const p = document.createElement("p");
    p.className = "connectors-lead";
    p.textContent =
      "Aucune composition. Figez les paramètres d’un outil pour en créer une, ou enchaînez plusieurs appels.";
    body.appendChild(p);
  }
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
  const famille = (state.toolsByService || []).find(
    (x) => String(x.key).split("#")[0] === key
  )?.group;
  const socle =
    famille === "Coordination et mémoire" || famille === "Accès aux fichiers";
  h.textContent = socle ? famille : entry.name || entry.id;
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent = socle
    ? famille === "Accès aux fichiers"
      ? "Ce que l’Atelier peut lire et écrire hors du dossier d’un projet."
      : "Ce qui relie les agents entre eux : messages, mémoire, suivi de projet."
    : entry.description ||
      `${kind === "org" ? "Service plateforme" : "Connecteur personnel"}`;
  head.appendChild(h);
  head.appendChild(lead);

  const compteOutils =
    entry.tools ||
    (state.toolsByService || [])
      .filter((x) => String(x.key).split("#")[0] === key)
      .reduce((n, x) => n + (x.count || 0), 0);
  const badge = document.createElement("span");
  badge.className = badgeClass(entry, key, upstream);
  badge.textContent = badgeLabel(entry, key, upstream, compteOutils);
  head.appendChild(badge);

  if ((kind === "registry" || entry.kind === "registry") && !socle) {
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
  // Un serveur lancé par le client ne se compte pas tout seul : le nombre
  // vient alors du sondage, comme partout ailleurs dans l'application.
  const compte =
    entry.tools ||
    (state.toolsByService || [])
      .filter((x) => String(x.key).split("#")[0] === key)
      .reduce((n, x) => n + (x.count || 0), 0);
  addKv("Outils", String(compte || 0));
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

  /**
   * Groupes de la liste latérale, dans la même taxonomie que la sélection
   * d'outils d'un agent : un service ne change pas de nature selon l'écran
   * où on le regarde.
   */
  const FAMILLES_SOCLE = ["Coordination et mémoire", "Accès aux fichiers"];

  /** Nombre d'outils d'un service, toutes familles confondues. */
  function compteDe(cle) {
    return (state.toolsByService || [])
      .filter((x) => String(x.key).split("#")[0] === cle)
      .reduce((n, x) => n + (x.count || 0), 0);
  }

  /** Groupe d'un service, tel que l'agrégation des outils le classe. */
  function groupeDe(cle, defaut) {
    const trouve = (state.toolsByService || []).find(
      (s) => String(s.key).split("#")[0] === cle
    );
    return trouve?.group || defaut;
  }

  /** Ce qu'un service du socle apporte, dit en clair sous son nom. */
  function sousTitreSysteme(groupe, entry) {
    if (groupe === "Accès aux fichiers") {
      const chemins = (entry.config?.args || []).filter(
        (a) => typeof a === "string" && a.startsWith("/") && !a.endsWith(".js")
      );
      return chemins.length ? `ouvre ${chemins[0]}` : "accès aux dossiers";
    }
    return "coordination, mémoire, agents";
  }

  /**
   * Compositions : un service au même rang que les autres.
   *
   * Ses outils ne viennent d'aucun serveur branché — ils sont fabriqués ici.
   * C'est ce qui lui vaut sa place dans la liste plutôt qu'un tiroir à part.
   */
  function renderServiceCompositions() {
    const li = document.createElement("li");
    const sel = state.selectedConnectorId === "atelier:compositions";
    li.className = "agent-card" + (sel ? " agent-card-selected" : "");
    li.addEventListener("click", () => actions.select("atelier", "compositions"));

    const liste = state.compositions || [];
    const actives = liste.filter((c) => c.status === "production").length;

    const head = document.createElement("div");
    head.className = "agent-card-head";
    const titleRow = document.createElement("div");
    titleRow.className = "agent-card-title-row";
    const dot = document.createElement("span");
    dot.className = "status-dot " + (actives ? "status-dot-ok" : "status-dot-off");
    const name = document.createElement("strong");
    name.className = "agent-card-name";
    name.textContent = "Compositions";
    titleRow.appendChild(dot);
    titleRow.appendChild(name);
    const badge = document.createElement("span");
    badge.className = actives ? "mcp-badge mcp-badge-ok" : "mcp-badge mcp-badge-warn";
    badge.textContent = actives
      ? `${actives} outil${actives > 1 ? "s" : ""} actif${actives > 1 ? "s" : ""}`
      : "aucun outil actif";
    head.appendChild(titleRow);
    head.appendChild(badge);

    const meta = document.createElement("div");
    meta.className = "agent-card-meta";
    meta.textContent = liste.length
      ? `${liste.length} fabriquée${liste.length > 1 ? "s" : ""} ici`
      : "outils fabriqués ici";

    li.appendChild(head);
    li.appendChild(meta);
    return li;
  }

  /**
   * La passerelle de l'Atelier, vue depuis la liste.
   *
   * Elle porte la recherche d'outils et l'appel — ce par quoi un agent
   * atteint tout le reste sans qu'on lui annonce chaque outil. Elle n'est pas
   * dans le pool : elle ne se branche pas, elle est la maison.
   */
  function renderServiceAcces() {
    const li = document.createElement("li");
    const sel = state.selectedConnectorId === "atelier:acces";
    li.className = "agent-card" + (sel ? " agent-card-selected" : "");
    li.addEventListener("click", () => actions.select("atelier", "acces"));

    const meta = (state.toolsByService || []).find((x) => x.key === "meta:acces");
    const head = document.createElement("div");
    head.className = "agent-card-head";
    const titleRow = document.createElement("div");
    titleRow.className = "agent-card-title-row";
    const dot = document.createElement("span");
    dot.className = "status-dot status-dot-ok";
    const name = document.createElement("strong");
    name.className = "agent-card-name";
    name.textContent = "Accès aux outils";
    titleRow.appendChild(dot);
    titleRow.appendChild(name);
    const badge = document.createElement("span");
    badge.className = "mcp-badge mcp-badge-ok";
    badge.textContent = `${meta?.count ?? 2} outils`;
    head.appendChild(titleRow);
    head.appendChild(badge);

    const sous = document.createElement("div");
    sous.className = "agent-card-meta";
    sous.textContent = "chercher un outil, l’appeler";

    li.appendChild(head);
    li.appendChild(sous);
    return li;
  }

  function renderGroupes() {
    const racine = $("connectors-groups");
    if (!racine) return;
    racine.innerHTML = "";

    const cat = state.mcpOverview?.catalog;
    const entrees = [
      ...(cat?.personal || []).map((e) => ({
        e,
        kind: "registry",
        groupe: groupeDe("registry:" + e.id, "Mes connecteurs"),
      })),
      ...(cat?.org || []).map((e) => ({
        e,
        kind: "org",
        groupe: groupeDe(e.id, "Plateforme"),
      })),
    ];

    const upstream = state.mcpOverview?.upstream || {};
    const bloc = (titre, remplir) => {
      const d = document.createElement("details");
      d.className = "conn-group";
      d.open = true;
      const sum = document.createElement("summary");
      sum.className = "connectors-sub";
      sum.textContent = titre;
      d.appendChild(sum);
      const ul = document.createElement("ul");
      ul.className = "mcp-list agent-list";
      remplir(ul);
      d.appendChild(ul);
      racine.appendChild(d);
    };

    // Le socle en premier : coordination, fichiers, compositions. On les
    // nomme par leur fonction — « wikichat » ne dit rien de ce qu'on y
    // trouve, et l'identité technique se lit dans la fiche.
    const systeme = entrees.filter((x) => FAMILLES_SOCLE.includes(x.groupe));
    bloc("Services de l’Atelier", (ul) => {
      for (const groupe of FAMILLES_SOCLE) {
        for (const { e, kind } of systeme.filter((x) => x.groupe === groupe)) {
          ul.appendChild(
            renderSidebarItem(e, {
              kind,
              selectedId: state.selectedConnectorId,
              upstream,
              actions,
              titre: groupe,
              sous: sousTitreSysteme(groupe, e),
              compte: compteDe(kind === "registry" ? "registry:" + e.id : e.id),
            })
          );
        }
      }
      ul.appendChild(renderServiceAcces());
      ul.appendChild(renderServiceCompositions());
    });

    for (const groupe of ["Mes connecteurs", "Plateforme"]) {
      const dedans = entrees.filter((x) => x.groupe === groupe);
      if (!dedans.length) {
        if (groupe !== "Mes connecteurs") continue;
        bloc(groupe, (ul) => {
          const li = document.createElement("li");
          li.className = "mcp-empty";
          li.textContent = "Aucun — branchez un service pour l’ajouter.";
          ul.appendChild(li);
        });
        continue;
      }
      bloc(groupe, (ul) => {
        for (const { e, kind } of dedans) {
          ul.appendChild(
            renderSidebarItem(e, {
              kind,
              selectedId: state.selectedConnectorId,
              upstream,
              actions,
              compte: compteDe(kind === "registry" ? "registry:" + e.id : e.id),
            })
          );
        }
      });
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
    renderGroupes();

    // Une composition sélectionnée prend le panneau : c'est aussi un objet
    // du pool, avec son détail et ses actions.
    if (state.selectedCompositionId) {
      const comp = (state.compositions || []).find(
        (c) => c.id === state.selectedCompositionId
      );
      if (comp) {
        renderCompositionDetail(state.compositionDetail || comp, state, actions);
        return;
      }
    }

    if (state.selectedConnectorId === "atelier:acces") {
      renderFicheAcces(state);
      return;
    }

    if (state.selectedConnectorId === "atelier:compositions") {
      renderCompositionsService(state, actions);
      return;
    }

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
