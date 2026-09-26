/** Vue Agent — accueil / création pleine page / détail onglets. */

import { $, rendreActivable } from "../core/dom.js";
import { showContextMenu } from "../ui/context-menu.js";
import { renderToolPicker } from "../ui/tool-picker.js";
import { carteGardien, ficheGardien, listeAutomates } from "./gardiens.js";

const FREQ_PRESETS = [
  { value: "0 8 * * *", label: "Chaque jour à 8h" },
  { value: "0 9 * * 1-5", label: "En semaine à 9h" },
  { value: "0 */6 * * *", label: "Toutes les 6 heures" },
  { value: "0 8 * * 1", label: "Chaque lundi à 8h" },
  { value: "0 17 * * 5", label: "Chaque vendredi à 17h" },
  { value: "__custom__", label: "Personnaliser…" },
];

function agentTone(agent, daemon) {
  const pend = pendingCount(agent);
  if (pend > 0) return "pending";
  if (daemon?.paused) return "warn";
  if (!agent.enabled) return "off";
  if (agent.base === "actif") return "busy";
  return "ok";
}

function agentStatus(agent, daemon) {
  const tone = agentTone(agent, daemon);
  const labels = {
    pending: "À valider",
    warn: "En pause",
    off: "Désactivé",
    busy: "En cours",
    ok: "En veille",
  };
  return { label: labels[tone] || "—", tone };
}

function pendingCount(agent) {
  const q = agent.queue || [];
  return q.filter((a) => (a.status || "pending") === "pending").length;
}

function cronHuman(cron) {
  const p = String(cron || "").trim().split(/\s+/);
  if (p.length !== 5) return "";
  const [mi, h, , , dow] = p;
  const pad = (n) => String(n).padStart(2, "0");
  if (String(h).startsWith("*/")) {
    return `Toutes les ${h.slice(2)} h`;
  }
  if (h === "*") return `Chaque heure à ${pad(mi === "*" ? 0 : mi)} min`;
  const time = `à ${pad(h)}:${pad(mi === "*" ? 0 : mi)}`;
  if (dow === "1-5") return `En semaine ${time}`;
  if (dow === "0" || dow === "7") return `Le dimanche ${time}`;
  if (dow !== "*") return `Selon planning ${time}`;
  return `Tous les jours ${time}`;
}

function statusDot(tone, title) {
  const el = document.createElement("span");
  el.className = `status-dot status-dot-${tone || "off"}`;
  el.title = title || "";
  el.setAttribute("aria-label", title || "état");
  return el;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderAgentCard(agent, selected, daemon, actions, panel, state) {
  const li = document.createElement("li");
  const onDetail = panel === "detail" && agent.id === selected;
  li.className = "agent-card" + (onDetail ? " agent-card-selected" : "");
  rendreActivable(li, () => actions.select(agent.id));
  li.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    showContextMenu(state, e.clientX, e.clientY, [
      { label: "Lancer maintenant", action: () => actions.fire(agent.id) },
      { label: "Modifier l’agent", action: () => actions.openEdit(agent) },
      {
        label: agent.enabled ? "Désactiver" : "Activer",
        action: () => actions.toggle(agent.id),
      },
      {
        label: "Supprimer l’agent",
        danger: true,
        action: () => {
          if (confirm(`Supprimer l'agent « ${agent.name || agent.id} » ?`)) {
            actions.remove(agent.id);
          }
        },
      },
    ]);
  });

  const head = document.createElement("div");
  head.className = "agent-card-head";
  const left = document.createElement("div");
  left.className = "agent-card-title-row";
  const st = agentStatus(agent, daemon);
  left.appendChild(statusDot(st.tone, st.label));
  const name = document.createElement("strong");
  name.className = "agent-card-name";
  name.textContent = agent.name || agent.id;
  left.appendChild(name);
  head.appendChild(left);

  const desc = document.createElement("p");
  desc.className = "agent-card-desc";
  desc.textContent = agent.desc || "Agent planifié";

  const meta = document.createElement("div");
  meta.className = "agent-card-meta";
  const cron = document.createElement("span");
  cron.textContent = cronHuman(agent.cron) || agent.cron || "—";
  meta.appendChild(cron);
  const pend = pendingCount(agent);
  if (pend > 0) {
    const badge = document.createElement("span");
    badge.className = "agent-pending-badge";
    badge.textContent = `${pend} à valider`;
    meta.appendChild(badge);
  }

  li.appendChild(head);
  li.appendChild(desc);
  li.appendChild(meta);
  return li;
}

function renderQueueItem(agentId, item, actions, { showAgent } = {}) {
  const li = document.createElement("li");
  li.className = "agent-queue-item";
  const main = document.createElement("div");
  main.className = "agent-queue-main";
  const title = document.createElement("strong");
  title.textContent = item.title || item.id;
  const sub = document.createElement("span");
  sub.className = "agent-queue-sub";
  const bits = [];
  if (showAgent && item._agentName) bits.push(item._agentName);
  if (item.sub) bits.push(item.sub);
  sub.textContent = bits.join(" · ");
  main.appendChild(title);
  if (sub.textContent) main.appendChild(sub);

  const status = item.status || "pending";
  if (status === "pending") {
    const btns = document.createElement("div");
    btns.className = "agent-queue-actions";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "primary btn-sm";
    ok.textContent = "Accepter";
    ok.addEventListener("click", (e) => {
      e.stopPropagation();
      actions.decide(agentId, item.id, "approve");
    });
    const no = document.createElement("button");
    no.type = "button";
    no.className = "ghost btn-sm";
    no.textContent = "Refuser";
    no.addEventListener("click", (e) => {
      e.stopPropagation();
      actions.decide(agentId, item.id, "reject");
    });
    btns.appendChild(ok);
    btns.appendChild(no);
    li.appendChild(main);
    li.appendChild(btns);
  } else {
    const st = document.createElement("span");
    st.className = "mcp-badge mcp-badge-muted";
    st.textContent = status;
    li.appendChild(main);
    li.appendChild(st);
  }
  return li;
}

function kv(label, value) {
  const li = document.createElement("li");
  const k = document.createElement("span");
  k.className = "agent-kv-k";
  k.textContent = label;
  const v = document.createElement("span");
  v.className = "agent-kv-v";
  v.textContent = value;
  li.appendChild(k);
  li.appendChild(v);
  return li;
}

function renderDaemonBar(daemon, actions, into) {
  const wrap = document.createElement("div");
  wrap.className = "agent-daemon-bar";
  const paused = !!daemon?.paused;
  const inner = document.createElement("div");
  inner.className = "agent-daemon-bar-inner";
  const info = document.createElement("div");
  info.className = "agent-daemon-info";
  const tone = paused ? "warn" : "ok";
  info.appendChild(statusDot(tone, paused ? "En pause" : "Actif"));
  const text = document.createElement("span");
  text.innerHTML = `<strong>Planificateur</strong> · ${daemon?.armed ?? 0}/${daemon?.total ?? 0} actifs · prochain : ${escapeHtml(daemon?.wake || "—")}${daemon?.wake_agent ? ` (${escapeHtml(daemon.wake_agent)})` : ""}`;
  info.appendChild(text);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = paused ? "primary btn-sm" : "ghost btn-sm";
  btn.textContent = paused ? "Reprendre" : "Mettre en pause";
  btn.addEventListener("click", () => actions.setDaemonPaused(!paused));
  inner.appendChild(info);
  inner.appendChild(btn);
  wrap.appendChild(inner);
  into.appendChild(wrap);
}

/**
 * Mécanismes de la plateforme — ce qui agit sans être un agent.
 *
 * Le réveil sur mention n'exécute aucune mission : il écoute les messages et
 * relance un agent hors ligne quand on le nomme. Le ranger parmi les agents
 * laissait croire à un travail planifié ; sa vraie nature est celle d'un
 * réglage, à côté du planificateur.
 */
function renderMecanismes(ov, actions, into) {
  const liste = ov?.system_agents || [];
  if (!liste.length) return;

  const LIBELLES = {
    "evt-wake-any": {
      titre: "Réveil sur mention",
      texte:
        "Relance un agent hors ligne quand un message le nomme en attendant une réponse.",
    },
  };

  for (const m of liste) {
    const infos = LIBELLES[m.id] || { titre: m.name || m.id, texte: m.description || "" };
    const wrap = document.createElement("div");
    wrap.className = "agent-daemon-bar";
    const inner = document.createElement("div");
    inner.className = "agent-daemon-bar-inner";
    const info = document.createElement("div");
    info.className = "agent-daemon-info";
    info.appendChild(statusDot(m.enabled ? "ok" : "warn", m.enabled ? "Actif" : "Suspendu"));
    const text = document.createElement("span");
    const dernier = m.lastFired
      ? new Date(m.lastFired).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
      : "jamais";
    text.innerHTML = `<strong>${escapeHtml(infos.titre)}</strong> · ${escapeHtml(
      infos.texte
    )} · ${m.fired || 0} fois · dernier : ${escapeHtml(dernier)}`;
    info.appendChild(text);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = m.enabled ? "ghost btn-sm" : "primary btn-sm";
    btn.textContent = m.enabled ? "Suspendre" : "Réactiver";
    btn.addEventListener("click", () => actions.toggleSystemAgent?.(m.id));
    inner.appendChild(info);
    inner.appendChild(btn);
    wrap.appendChild(inner);
    into.appendChild(wrap);
  }
}

function renderHome(state, actions, automates) {
  const ov = state.piloteOverview;
  const body = $("agent-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  head.innerHTML = `
    <h2 class="connectors-title">Vue d’ensemble</h2>
    <p class="connectors-lead">Tout ce qui agit seul : vos agents planifiés, les gardiens et les tâches automatiques. Ce qu’ils proposent attend dans « À valider ».</p>
  `;
  const actionsRow = document.createElement("div");
  actionsRow.className = "agent-head-actions";
  const cta = document.createElement("button");
  cta.type = "button";
  cta.className = "primary btn-sm";
  cta.textContent = "+ Nouvel agent";
  cta.addEventListener("click", () => actions.openCreate());
  actionsRow.appendChild(cta);
  head.appendChild(actionsRow);
  body.appendChild(head);

  if (ov) {
    renderDaemonBar(ov.daemon || {}, actions, body);
    renderMecanismes(ov, actions, body);
  }

  // Une seule file (S3) : l'accueil y renvoie au lieu d'en tenir une copie.
  const queueSec = document.createElement("section");
  queueSec.className = "agent-section agent-a-valider";
  const h = document.createElement("h3");
  h.className = "connectors-sub";
  h.textContent = "À valider";
  queueSec.appendChild(h);
  const rang = document.createElement("div");
  rang.className = "agent-daemon-bar-inner";
  const n = state.aValiderCompte || 0;
  const texte = document.createElement("span");
  texte.className = "agent-daemon-info";
  texte.textContent = n
    ? `${n} proposition${n > 1 ? "s" : ""} attend${n > 1 ? "ent" : ""} votre accord.`
    : "Rien n’attend votre accord.";
  const ouvrir = document.createElement("button");
  ouvrir.type = "button";
  ouvrir.className = n ? "primary btn-sm" : "ghost btn-sm";
  ouvrir.textContent = "Ouvrir « À valider »";
  ouvrir.addEventListener("click", () => actions.ouvrirAValider?.());
  rang.appendChild(texte);
  rang.appendChild(ouvrir);
  queueSec.appendChild(rang);
  body.appendChild(queueSec);

  // Toutes les tâches automatiques, une seule liste.
  const autoSec = document.createElement("section");
  autoSec.className = "agent-section agent-automates";
  const h2 = document.createElement("h3");
  h2.className = "connectors-sub";
  h2.textContent = "Tâches automatiques";
  autoSec.appendChild(h2);
  const lead = document.createElement("p");
  lead.className = "agent-note";
  lead.textContent =
    "Tout ce qui se lance seul, avec sa dernière et sa prochaine exécution et sa limite. Activer une tâche reste réservé à vous.";
  autoSec.appendChild(lead);
  const conteneur = document.createElement("div");
  if (state.automates) {
    listeAutomates(conteneur, state.automates, { actions: automates, enCours: state.automateEnCours });
  } else {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Lecture des tâches automatiques…";
    conteneur.appendChild(p);
  }
  autoSec.appendChild(conteneur);
  body.appendChild(autoSec);
}

function fieldRow(label, control, hint) {
  const row = document.createElement("label");
  row.className = "agent-form-row";
  const lab = document.createElement("span");
  lab.className = "agent-form-label";
  lab.textContent = label;
  row.appendChild(lab);
  row.appendChild(control);
  if (hint) {
    control.title = hint;
    control.setAttribute("aria-description", hint);
  }
  return row;
}

function renderCreate(state, actions) {
  const body = $("agent-detail-body");
  if (!body) return;
  body.innerHTML = "";
  const form = state.agentCreateForm || {};

  const enEdition = !!form.editId;
  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h2 = document.createElement("h2");
  h2.className = "connectors-title";
  h2.textContent = enEdition ? "Modifier l’agent" : "Nouvel agent";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent = enEdition
    ? `Les modifications remplacent la configuration de « ${form.editName || ""} ». Son historique et sa session sont conservés.`
    : "Un outil qui s’exécute selon un horaire et vous propose des actions à valider.";
  head.appendChild(h2);
  head.appendChild(lead);
  body.appendChild(head);

  const el = document.createElement("form");
  el.className = "agent-create-form";
  el.addEventListener("submit", (e) => {
    e.preventDefault();
    actions.submitCreate();
  });

  const name = document.createElement("input");
  name.type = "text";
  name.required = true;
  name.autocomplete = "off";
  name.placeholder = "Ex. Veille dépôts";
  name.value = form.name || "";
  name.addEventListener("input", () => actions.patchCreate({ name: name.value }));
  el.appendChild(fieldRow("Nom", name));

  const desc = document.createElement("input");
  desc.type = "text";
  desc.placeholder = "Ex. Surveille les commits et résume les alertes";
  desc.value = form.desc || "";
  desc.addEventListener("input", () => actions.patchCreate({ desc: desc.value }));
  el.appendChild(fieldRow("Description", desc));

  const mission = document.createElement("textarea");
  mission.rows = 4;
  mission.placeholder = "Ce que l’agent doit faire à chaque passage…";
  mission.value = form.mission || "";
  mission.addEventListener("input", () =>
    actions.patchCreate({ mission: mission.value })
  );
  el.appendChild(fieldRow("Consignes", mission));

  // La selection d'outils se compose ici. Un profil existant ne sert qu'a
  // pre-cocher : c'est un raccourci, pas le passage oblige.
  const profile = document.createElement("select");
  const aucun = document.createElement("option");
  aucun.value = "";
  aucun.textContent = "Choisir moi-même";
  profile.appendChild(aucun);
  for (const o of form.profileOptions || []) {
    if (!o.value) continue;
    const opt = document.createElement("option");
    opt.value = o.value;
    opt.textContent = o.label;
    if (o.value === (form.profile || "")) opt.selected = true;
    profile.appendChild(opt);
  }
  profile.addEventListener("change", () => actions.applyProfile(profile.value));
  el.appendChild(
    fieldRow("Partir d’un profil", profile, "Optionnel — pré-coche les outils")
  );

  const picker = renderToolPicker({
    builtins: form.builtins || [],
    catalog: state.mcpOverview?.catalog,
    toolsByService: form.toolsByService || [],
    selection: form.toolSelection || new Set(),
    onPersonnaliser: (outil) => actions.personnaliserOutil(outil),
  });
  el.appendChild(fieldRow("Outils", picker));

  const project = document.createElement("select");
  for (const o of form.projectOptions || []) {
    const opt = document.createElement("option");
    opt.value = o.value;
    opt.textContent = o.label;
    if (o.value === (form.project || "")) opt.selected = true;
    project.appendChild(opt);
  }
  project.addEventListener("change", () =>
    actions.patchCreate({ project: project.value })
  );
  el.appendChild(fieldRow("Projet (optionnel)", project));

  const freqWrap = document.createElement("div");
  freqWrap.className = "agent-form-freq";
  const freq = document.createElement("select");
  const freqVal = form.freqPreset || form.freq || "0 8 * * *";
  const isCustom =
    form.freqPreset === "__custom__" ||
    !FREQ_PRESETS.some((p) => p.value === freqVal && p.value !== "__custom__");
  for (const o of FREQ_PRESETS) {
    const opt = document.createElement("option");
    opt.value = o.value;
    opt.textContent = o.label;
    if (
      (isCustom && o.value === "__custom__") ||
      (!isCustom && o.value === freqVal)
    ) {
      opt.selected = true;
    }
    freq.appendChild(opt);
  }
  freq.addEventListener("change", () => {
    if (freq.value === "__custom__") {
      actions.patchCreate(
        {
          freqPreset: "__custom__",
          freq: form.freqCustom || form.freq || "0 8 * * *",
        },
        { rerender: true }
      );
    } else {
      actions.patchCreate(
        { freqPreset: freq.value, freq: freq.value },
        { rerender: true }
      );
    }
  });
  freqWrap.appendChild(freq);
  if (isCustom || freq.value === "__custom__") {
    const custom = document.createElement("input");
    custom.type = "text";
    custom.className = "agent-form-cron";
    custom.placeholder = "cron · ex. 0 8 * * 1-5";
    custom.value = form.freqCustom || form.freq || "";
    custom.addEventListener("input", () =>
      actions.patchCreate({
        freqPreset: "__custom__",
        freqCustom: custom.value,
        freq: custom.value,
      })
    );
    freqWrap.appendChild(custom);
  }
  el.appendChild(fieldRow("Quand", freqWrap));

  const model = document.createElement("select");
  for (const o of form.modelOptions || []) {
    const opt = document.createElement("option");
    opt.value = o.value;
    opt.textContent = o.label;
    if (o.value === (form.model || "")) opt.selected = true;
    model.appendChild(opt);
  }
  model.addEventListener("change", () =>
    actions.patchCreate({ model: model.value })
  );
  el.appendChild(fieldRow("Modèle", model));

  if (state.agentCreateError) {
    const err = document.createElement("p");
    err.className = "agent-form-error";
    err.textContent = state.agentCreateError;
    el.appendChild(err);
  }

  const foot = document.createElement("div");
  foot.className = "agent-form-actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost btn-sm";
  cancel.textContent = "Annuler";
  cancel.addEventListener("click", () => actions.cancelCreate());
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "primary btn-sm";
  submit.textContent = state.agentCreateBusy
    ? (enEdition ? "Enregistrement…" : "Création…")
    : (enEdition ? "Enregistrer" : "Créer l’agent");
  submit.disabled = !!state.agentCreateBusy;
  foot.appendChild(cancel);
  foot.appendChild(submit);
  el.appendChild(foot);

  body.appendChild(el);
}

function renderTabs(agent, state, actions) {
  const nav = document.createElement("nav");
  nav.className = "agent-tabs";
  nav.setAttribute("aria-label", "Sections agent");
  const pend = pendingCount(agent);
  const tabs = [
    { id: "discussion", label: "Discussion" },
    { id: "queue", label: "À valider", badge: pend },
    { id: "settings", label: "Réglages" },
  ];
  for (const t of tabs) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "agent-tab" + (state.agentTab === t.id ? " active" : "");
    btn.textContent = t.label;
    if (t.badge) {
      const b = document.createElement("span");
      b.className = "agent-tab-badge";
      b.textContent = String(t.badge);
      btn.appendChild(b);
    }
    btn.addEventListener("click", () => actions.setTab(t.id));
    nav.appendChild(btn);
  }
  return nav;
}

/**
 * Fil de l'agent — les derniers tours de sa session Claude, relayes par le
 * pilote. Lecture seule : le pilote ne transmet pas de message libre, on ne
 * peut que relancer l'agent sur sa session.
 */
function renderDiscussionTab(agent, state, actions) {
  const sec = document.createElement("section");
  sec.className = "agent-section";

  const tr = state.agentTranscript;
  const aJour = tr && tr.agentId === agent.id;

  const barre = document.createElement("div");
  barre.className = "agent-head-actions";
  const relancer = document.createElement("button");
  relancer.type = "button";
  relancer.className = "primary btn-sm";
  relancer.textContent = "Reprendre la conversation";
  relancer.disabled = !agent.canResume;
  relancer.title = agent.canResume
    ? "Relance l’agent là où il s’était arrêté"
    : "Aucune session à reprendre — lancez d’abord l’agent";
  relancer.addEventListener("click", () => actions.resume(agent.id));
  const recharger = document.createElement("button");
  recharger.type = "button";
  recharger.className = "ghost btn-sm";
  recharger.textContent = "Actualiser";
  recharger.addEventListener("click", () => actions.loadTranscript(agent.id));
  barre.appendChild(relancer);
  barre.appendChild(recharger);
  sec.appendChild(barre);

  const fil = document.createElement("div");
  fil.className = "agent-thread";

  if (state.agentTranscriptBusy && !aJour) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Lecture du fil…";
    fil.appendChild(p);
  } else if (aJour && tr.error) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = `Fil indisponible : ${tr.error}`;
    fil.appendChild(p);
  } else if (aJour && tr.turns?.length) {
    for (const tour of tr.turns) {
      const texte = tour.text || "";
      const estOutil = texte.startsWith("→ ") || texte.startsWith("← ");
      const div = document.createElement("div");
      div.className = estOutil
        ? "msg tool"
        : `msg ${tour.role === "user" ? "user" : "assistant"}`;
      const label = document.createElement("span");
      label.className = "role";
      label.textContent = estOutil
        ? (texte.startsWith("→ ") ? "outil" : "retour")
        : tour.role === "user"
          ? "consigne"
          : "agent";
      div.appendChild(label);
      const corps = document.createElement("div");
      corps.className = "msg-body";
      corps.textContent = estOutil ? texte.slice(2) : texte;
      div.appendChild(corps);
      fil.appendChild(div);
    }
  } else {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent =
      (aJour && tr.note) ||
      (agent.fired
        ? "Aucun tour enregistré pour cet agent."
        : "Cet agent n’a jamais tourné. Lancez-le depuis Réglages pour voir son travail ici.");
    fil.appendChild(p);
  }
  sec.appendChild(fil);

  // Rattachement de la session, en secondaire.
  const meta = document.createElement("ul");
  meta.className = "agent-kv agent-thread-meta";
  meta.appendChild(kv("Dernier passage", dateHuman(agent.lastFired)));
  meta.appendChild(kv("Passages", String(agent.fired ?? 0)));
  if (aJour && tr.sessionId) meta.appendChild(kv("Session", tr.sessionId));
  if (agent.memory?.recover) meta.appendChild(kv("Reprise", agent.memory.recover));
  sec.appendChild(meta);

  return sec;
}

function renderQueueTab(agent, actions) {
  const sec = document.createElement("section");
  sec.className = "agent-section";
  const qUl = document.createElement("ul");
  qUl.className = "agent-queue";
  const pending = (agent.queue || []).filter(
    (a) => (a.status || "pending") === "pending"
  );
  if (!pending.length) {
    const li = document.createElement("li");
    li.className = "mcp-empty";
    li.textContent = "Aucune proposition en attente pour cet agent.";
    qUl.appendChild(li);
  } else {
    for (const item of pending) {
      qUl.appendChild(renderQueueItem(agent.id, item, actions));
    }
  }
  sec.appendChild(qUl);
  return sec;
}

/** « registry:wikichat » se lit « wikichat ». */
function toolLabel(nom) {
  return String(nom || "")
    .replace(/^registry:/, "")
    .replace(/^mcp__/, "")
    .replace(/^claude_ai_/, "")
    .replace(/__/g, " · ");
}

/** Date lisible : « 29/08 à 14:12 » plutot qu'un horodatage ISO. */
function dateHuman(iso) {
  if (!iso) return "jamais";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} à ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** « Recommandé » plutot que « qwen3-6-35b-moe ». */
function modelLabel(state, id) {
  if (!id) return "—";
  const trouve = (state?.modelsCatalog?.models || []).find((m) => m.id === id);
  return trouve ? `${trouve.label} (${id})` : id;
}

function renderSettingsTab(agent, actions, state) {
  const wrap = document.createElement("div");

  const toolbar = document.createElement("div");
  toolbar.className = "agent-head-actions";
  const fire = document.createElement("button");
  fire.type = "button";
  fire.className = "primary btn-sm";
  fire.textContent = "Lancer maintenant";
  fire.addEventListener("click", () => actions.fire(agent.id));
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "ghost btn-sm";
  toggle.textContent = agent.enabled ? "Désactiver" : "Activer";
  toggle.addEventListener("click", () => actions.toggle(agent.id));
  const del = document.createElement("button");
  del.type = "button";
  del.className = "ghost btn-sm agent-profile-del";
  del.textContent = "Supprimer";
  del.addEventListener("click", () => {
    if (confirm(`Supprimer l'agent « ${agent.name || agent.id} » ?`)) {
      actions.remove(agent.id);
    }
  });
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "ghost btn-sm";
  edit.textContent = "Modifier";
  edit.addEventListener("click", () => actions.openEdit(agent));
  toolbar.appendChild(fire);
  toolbar.appendChild(edit);
  toolbar.appendChild(toggle);
  toolbar.appendChild(del);
  wrap.appendChild(toolbar);

  const grid = document.createElement("div");
  grid.className = "agent-detail-grid";

  const scope = document.createElement("section");
  scope.className = "agent-section";
  scope.innerHTML = `<h3 class="connectors-sub">Périmètre</h3>`;
  const scopeUl = document.createElement("ul");
  scopeUl.className = "agent-kv";
  scopeUl.appendChild(kv("Dossier", agent.scope?.dir || "—"));
  scopeUl.appendChild(kv("Prochain run", agent.next || "—"));
  scopeUl.appendChild(kv("Planning", cronHuman(agent.cron) || agent.cron || "—"));
  scopeUl.appendChild(kv("Cron", agent.cron || "—"));
  scopeUl.appendChild(kv("Modèle", modelLabel(state, agent.memory?.budget)));
  const outils = (agent.scope?.tools || []).map((t) => toolLabel(t.name)).filter(Boolean);
  scopeUl.appendChild(kv("Outils", outils.length ? outils.join(", ") : "—"));
  scope.appendChild(scopeUl);
  grid.appendChild(scope);

  const mission = document.createElement("section");
  mission.className = "agent-section";
  mission.innerHTML = `<h3 class="connectors-sub">Consignes</h3>`;
  const pre = document.createElement("pre");
  pre.className = "agent-mission";
  const lines = Array.isArray(agent.mission) ? agent.mission : [agent.mission || ""];
  pre.textContent = lines.join("\n");
  mission.appendChild(pre);
  grid.appendChild(mission);
  wrap.appendChild(grid);

  const channels = document.createElement("p");
  channels.className = "agent-note";
  channels.textContent =
    "Canaux de messagerie (ex. webmessage) : configuration à venir ici.";
  wrap.appendChild(channels);

  if (agent.history?.length) {
    const hist = document.createElement("section");
    hist.className = "agent-section";
    hist.innerHTML = `<h3 class="connectors-sub">Historique récent</h3>`;
    const hUl = document.createElement("ul");
    hUl.className = "agent-history";
    for (const row of agent.history) {
      const li = document.createElement("li");
      li.textContent = `${row.date || "—"} · ${row.text || (row.mails != null ? `mails ${row.mails}` : "")}`;
      hUl.appendChild(li);
    }
    hist.appendChild(hUl);
    wrap.appendChild(hist);
  }

  return wrap;
}

function renderDetail(agent, state, actions) {
  const body = $("agent-detail-body");
  if (!body) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const titleRow = document.createElement("div");
  titleRow.className = "agent-card-title-row";
  const daemon = state.piloteOverview?.daemon || {};
  const st = agentStatus(agent, daemon);
  titleRow.appendChild(statusDot(st.tone, st.label));
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = agent.name || agent.id;
  titleRow.appendChild(h);
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent = agent.desc || "";
  head.appendChild(titleRow);
  head.appendChild(lead);
  body.appendChild(head);

  body.appendChild(renderTabs(agent, state, actions));

  if (state.agentTab === "queue") {
    body.appendChild(renderQueueTab(agent, actions));
  } else if (state.agentTab === "settings") {
    body.appendChild(renderSettingsTab(agent, actions, state));
  } else {
    body.appendChild(renderDiscussionTab(agent, state, actions));
  }
}

/**
 * @param {object} ctx
 */
export function createAgentView(ctx) {
  const { state, actions } = ctx;
  // Gestes sur les gardiens et les tâches automatiques (controllers/automates.js).
  const automates = ctx.automates || {};

  function renderAgentList() {
    const ul = $("agent-list");
    if (!ul) return;
    ul.innerHTML = "";
    const ov = state.piloteOverview;
    const agents = ov?.agents || [];
    const daemon = ov?.daemon || {};
    const panel = state.agentPanel || "home";

    // Deux questions se posaient en même temps, et n'ont pas la même
    // réponse : qui a créé cet agent — vous, ou la plateforme — et sur quoi
    // il travaille — un projet, ou l'Atelier lui-même. Les confondre rangeait
    // mal un agent que vous avez écrit pour entretenir le savoir commun :
    // il reste le vôtre, modifiable et supprimable, mais il ne sert aucun
    // livrable. Trois rangs plutôt que deux.
    const dePlateforme = (a) =>
      a.kind === "platform" || String(a.id || "").startsWith("team-");
    const dEntretien = (a) => a.kind === "entretien";
    const travail = agents.filter((a) => !dePlateforme(a) && !dEntretien(a));
    const entretien = agents.filter(dEntretien);
    const plateforme = agents.filter(dePlateforme);

    // Le titre est là même quand la plateforme n'a rien installé : sans lui,
    // rien ne dit que ces agents-là sont les vôtres — ceux que vous pouvez
    // modifier et supprimer.
    const titreMiens = document.createElement("li");
    titreMiens.className = "agent-list-section";
    titreMiens.textContent = "Mes agents";
    ul.appendChild(titreMiens);

    if (!travail.length) {
      const li = document.createElement("li");
      li.className = "mcp-empty";
      // « Aucun agent » sonnerait faux quand la liste en montre plus bas :
      // ce rang-ci est vide, pas la page.
      li.textContent = agents.length
        ? "Aucun agent de projet — utilisez + pour en créer un."
        : "Aucun agent — utilisez + pour en créer un.";
      ul.appendChild(li);
    }
    for (const agent of travail) {
      ul.appendChild(
        renderAgentCard(agent, state.selectedAgentId, daemon, actions, panel, state)
      );
    }

    // Les gardiens : des agents spécifiques (J-i), sans IA, qui surveillent.
    const vueGardiens = state.gardiens;
    if (vueGardiens) {
      const titre = document.createElement("li");
      titre.className = "agent-list-section";
      titre.textContent = "Gardiens";
      titre.title = "Des vérifications automatiques, sans IA, qui surveillent l’Atelier et vous préviennent.";
      ul.appendChild(titre);
      const gardiens = vueGardiens.gardiens || [];
      if (!gardiens.length) {
        const li = document.createElement("li");
        li.className = "mcp-empty";
        li.textContent = vueGardiens.joignable === false
          ? "Les gardiens ne répondent pas."
          : "Aucun gardien déclaré.";
        ul.appendChild(li);
      }
      for (const g of gardiens) {
        ul.appendChild(
          carteGardien(g, {
            choisi: panel === "gardien" && state.selectedGardienId === g.id,
            onChoisir: (id) => automates.choisirGardien?.(id),
          })
        );
      }
    }

    if (entretien.length) {
      const titre = document.createElement("li");
      titre.className = "agent-list-section";
      titre.textContent = "Entretien de l’Atelier";
      titre.title =
        "Les vôtres aussi, mais ils font vivre le savoir commun plutôt qu’un projet.";
      ul.appendChild(titre);
      for (const agent of entretien) {
        ul.appendChild(
          renderAgentCard(agent, state.selectedAgentId, daemon, actions, panel, state)
        );
      }
    }

    if (plateforme.length) {
      const titre = document.createElement("li");
      titre.className = "agent-list-section";
      titre.textContent = "Agents de la plateforme";
      titre.title = "Installés par la plateforme : ils ne se créent ni ne se suppriment ici.";
      ul.appendChild(titre);
      for (const agent of plateforme) {
        ul.appendChild(
          renderAgentCard(agent, state.selectedAgentId, daemon, actions, panel, state)
        );
      }
    }
  }

  function selectedAgent() {
    const agents = state.piloteOverview?.agents || [];
    if (!state.selectedAgentId) return null;
    return agents.find((a) => a.id === state.selectedAgentId) || null;
  }

  function renderAgent() {
    renderAgentList();
    const panel = state.agentPanel || "home";
    const mode = state.shellModeByView?.agent || "detail";
    const view = $("view-agent");
    if (view) {
      view.classList.toggle("agent-panel-home", panel === "home");
      view.classList.toggle("agent-panel-create", panel === "create");
      view.classList.toggle("agent-panel-detail", panel === "detail");
    }

    const back = $("btn-shell-back-agent");
    const forward = $("btn-shell-forward-agent");
    const toHome = $("btn-agent-to-home");

    // Accueil → aller vers la liste (flèche droite)
    // Liste → revenir à l’accueil (flèche gauche, dans la sidebar)
    // Détail / création → retour arrière
    if (forward) {
      const showForward = panel === "home";
      forward.hidden = !showForward;
      forward.textContent = "Liste →";
    }
    if (back) {
      if (panel === "create") {
        back.hidden = false;
        back.textContent = "← Annuler";
      } else if (panel === "detail" || panel === "gardien") {
        back.hidden = false;
        back.textContent = "← Liste";
      } else {
        back.hidden = true;
      }
    }
    if (toHome) {
      toHome.hidden = mode !== "list";
    }

    if (panel === "create") {
      renderCreate(state, actions);
      return;
    }
    if (panel === "gardien") {
      const g = (state.gardiens?.gardiens || []).find((x) => x.id === state.selectedGardienId);
      const body = $("agent-detail-body");
      if (g && body) {
        ficheGardien(body, g, { actions: automates, enCours: state.automateEnCours });
        return;
      }
    }
    const agent = selectedAgent();
    if (panel === "detail" && agent) {
      renderDetail(agent, state, actions);
      return;
    }
    renderHome(state, actions, automates);
  }

  return { renderAgent };
}
