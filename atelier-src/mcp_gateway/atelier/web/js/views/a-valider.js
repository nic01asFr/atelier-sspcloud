/**
 * L'écran « À valider » : la liste unique de ce qui attend votre accord (S3).
 *
 * Propositions des gardiens, des agents et des créations, mémoire proposée,
 * décisions de l'Assistant, et actions proposées par les agents planifiés de
 * wikichat : une seule file, lue à `GET /v1/a-valider`.
 *
 * - Accepter est réservé à la personne : le service le vérifie (commande
 *   réservée), l'écran ne fait que le proposer.
 * - Refuser se fait en un clic ; le motif est facultatif.
 * - Une proposition qui attend des précisions (un agent qui n'a pas su
 *   trancher un champ) les demande ici, avant d'accepter.
 */

import { dateHumaine } from "./gardiens.js";
import { infinitifCommande, libelleActeur } from "./journal.js";

const SOURCES = {
  gardien: "Gardien",
  agent: "Agent",
  creation: "Création",
  memoire: "Mémoire",
  assistant: "Assistant",
  pilote: "Agent planifié",
};

export function libelleSourceProposition(source) {
  return SOURCES[source] || "Proposition";
}

const STATUTS = [
  { valeur: "en_attente", texte: "En attente" },
  { valeur: "acceptee", texte: "Acceptées" },
  { valeur: "refusee", texte: "Refusées" },
];

/** Ce qu'accepter fera, en une phrase. */
export function ceQueFaitAccepter(p) {
  if (p?.source === "pilote") {
    return "L’agent appliquera sa proposition à son prochain passage.";
  }
  const action = p?.action;
  if (!action || !action.commande) {
    return "Accepter ne lance rien : cela vaut accord, et la proposition est close.";
  }
  const verbe = infinitifCommande(action.commande);
  const args = action.arguments && typeof action.arguments === "object" ? action.arguments : {};
  const cles = Object.keys(args);
  const precision = cles.length
    ? ` (${cles.slice(0, 4).map((k) => `${k} : ${String(args[k]).slice(0, 60)}`).join(", ")})`
    : "";
  return `Accepter va ${verbe}${precision}.`;
}

function ligne(k, v) {
  const li = document.createElement("li");
  const a = document.createElement("span");
  a.className = "agent-kv-k";
  a.textContent = k;
  const b = document.createElement("span");
  b.className = "agent-kv-v";
  b.textContent = v;
  li.appendChild(a);
  li.appendChild(b);
  return li;
}

function valeurLisible(v) {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** Les précisions qu'attend une proposition du pilote : `{field, path, question, options}`. */
export function precisionsAttendues(p) {
  const besoins = p?.detail?.a_completer;
  if (!Array.isArray(besoins)) return [];
  return besoins.filter((n) => n && typeof n === "object" && n.path);
}

function champDePrecision(p, besoin, valeur, actions) {
  const wrap = document.createElement("label");
  wrap.className = "agent-form-row";
  const lab = document.createElement("span");
  lab.className = "agent-form-label";
  lab.textContent = besoin.question || besoin.field || besoin.path;
  wrap.appendChild(lab);
  let champ;
  if (Array.isArray(besoin.options) && besoin.options.length) {
    champ = document.createElement("select");
    const vide = document.createElement("option");
    vide.value = "";
    vide.textContent = "Choisir…";
    champ.appendChild(vide);
    for (const o of besoin.options) {
      const opt = document.createElement("option");
      opt.value = String(o);
      opt.textContent = String(o);
      if (String(o) === valeur) opt.selected = true;
      champ.appendChild(opt);
    }
    champ.value = valeur || "";
    champ.addEventListener("change", () => actions.preciser(p.id, besoin.path, champ.value));
  } else {
    champ = document.createElement("input");
    champ.type = "text";
    champ.value = valeur || "";
    champ.addEventListener("input", () => actions.preciser(p.id, besoin.path, champ.value));
  }
  wrap.appendChild(champ);
  return wrap;
}

function rendreProposition(p, state, actions, maintenant) {
  const av = state.aValider || {};
  const ouverte = av.ouverte === p.id;
  const enCours = av.enCours === p.id;
  const li = document.createElement("li");
  li.className = "proposition" + (ouverte ? " proposition-ouverte" : "");
  li.dataset.proposition = p.id;

  const tete = document.createElement("button");
  tete.type = "button";
  tete.className = "proposition-tete";
  tete.setAttribute("aria-expanded", ouverte ? "true" : "false");
  tete.addEventListener("click", () => actions.ouvrir(ouverte ? null : p.id));
  const source = document.createElement("span");
  source.className = `proposition-source proposition-source-${p.source || "autre"}`;
  source.textContent = libelleSourceProposition(p.source);
  const titre = document.createElement("strong");
  titre.className = "proposition-titre";
  titre.textContent = p.titre || "Proposition";
  const quand = document.createElement("span");
  quand.className = "proposition-quand";
  const bouts = [];
  if (p.creee_le) bouts.push(dateHumaine(p.creee_le, maintenant));
  if (p.occurrences > 1) bouts.push(`vu ${p.occurrences} fois`);
  quand.textContent = bouts.join(" · ");
  tete.appendChild(source);
  tete.appendChild(titre);
  tete.appendChild(quand);
  li.appendChild(tete);

  if (p.resume) {
    const r = document.createElement("p");
    r.className = "proposition-resume";
    r.textContent = p.resume;
    li.appendChild(r);
  }

  if (ouverte) {
    const detail = document.createElement("div");
    detail.className = "proposition-detail";
    const kv = document.createElement("ul");
    kv.className = "agent-kv";
    kv.appendChild(ligne("Proposée par", libelleActeur(p.acteur, { sessions: state.sessions || [] })));
    if (p.projet) kv.appendChild(ligne("Projet", p.projet));
    for (const [k, v] of Object.entries(p.detail || {})) {
      if (k === "a_completer" || k === "agent" || v == null || v === "") continue;
      kv.appendChild(ligne(k, valeurLisible(v)));
    }
    detail.appendChild(kv);
    const effet = document.createElement("p");
    effet.className = "proposition-effet";
    effet.textContent = ceQueFaitAccepter(p);
    detail.appendChild(effet);
    if (p.statut === "en_attente") {
      for (const besoin of precisionsAttendues(p)) {
        const valeur = (av.completes?.[p.id] || {})[besoin.path] ?? (besoin.value != null ? String(besoin.value) : "");
        detail.appendChild(champDePrecision(p, besoin, valeur, actions));
      }
    }
    li.appendChild(detail);
  }

  if (p.statut === "en_attente") {
    const barre = document.createElement("div");
    barre.className = "proposition-actions";
    const accepter = document.createElement("button");
    accepter.type = "button";
    accepter.className = "primary btn-sm";
    accepter.textContent = enCours ? "…" : "Accepter";
    accepter.disabled = enCours;
    accepter.title = "Réservé à vous : un agent ne peut pas accepter à votre place.";
    accepter.addEventListener("click", () => actions.accepter(p.id));
    const motif = document.createElement("input");
    motif.type = "text";
    motif.className = "proposition-motif";
    motif.placeholder = "Motif (facultatif)";
    motif.setAttribute("aria-label", "Motif du refus, facultatif");
    motif.value = av.motifs?.[p.id] || "";
    motif.addEventListener("input", () => actions.motiver(p.id, motif.value));
    const refuser = document.createElement("button");
    refuser.type = "button";
    refuser.className = "ghost btn-sm";
    refuser.textContent = "Refuser";
    refuser.disabled = enCours;
    refuser.addEventListener("click", () => actions.refuser(p.id));
    barre.appendChild(accepter);
    barre.appendChild(motif);
    barre.appendChild(refuser);
    li.appendChild(barre);
  } else if (p.decision) {
    const d = document.createElement("p");
    d.className = "proposition-decision";
    const qui = libelleActeur(p.decision.par, { sessions: state.sessions || [] });
    const verbe = p.statut === "acceptee" ? "Acceptée" : "Refusée";
    d.textContent = `${verbe} ${dateHumaine(p.decision.quand, maintenant)} par ${qui.toLowerCase() === "vous" ? "vous" : qui}${p.decision.motif ? ` — ${p.decision.motif}` : ""}`;
    li.appendChild(d);
  }
  return li;
}

/**
 * L'écran entier. `actions` : `statut(v)`, `ouvrir(id|null)`, `accepter(id)`,
 * `refuser(id)`, `motiver(id, texte)`, `preciser(id, chemin, valeur)`, `recharger()`.
 */
export function rendreAValider(corps, state, actions, { maintenant } = {}) {
  const av = state.aValider || {};
  // Le rendu général repasse toutes les quinze secondes (veille des
  // conversations) : sans changement, on ne reconstruit rien, sinon le champ
  // du motif perdrait le focus au milieu de la frappe. Les motifs et
  // précisions saisis n'entrent pas dans l'empreinte : le champ les tient déjà.
  const empreinte = JSON.stringify([
    av.statut, av.propositions, av.note, av.charge, av.ouverte, av.enCours, av.erreur,
    state.aValiderCompte, Math.floor((maintenant ?? Date.now()) / 60000),
  ]);
  if (corps.dataset.empreinte === empreinte) return corps;
  corps.dataset.empreinte = empreinte;
  corps.innerHTML = "";

  const tete = document.createElement("header");
  tete.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "À valider";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Tout ce qui attend votre accord : corrections proposées par les gardiens, propositions des agents, installations. Accepter est réservé à vous ; refuser se fait en un clic.";
  tete.appendChild(h);
  tete.appendChild(lead);
  corps.appendChild(tete);

  const onglets = document.createElement("nav");
  onglets.className = "agent-tabs";
  onglets.setAttribute("aria-label", "Statut des propositions");
  for (const s of STATUTS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "agent-tab" + (av.statut === s.valeur ? " active" : "");
    b.textContent = s.texte;
    if (s.valeur === "en_attente" && state.aValiderCompte) {
      const n = document.createElement("span");
      n.className = "agent-tab-badge";
      n.textContent = String(state.aValiderCompte);
      b.appendChild(n);
    }
    b.addEventListener("click", () => actions.statut(s.valeur));
    onglets.appendChild(b);
  }
  corps.appendChild(onglets);

  if (av.erreur) {
    const p = document.createElement("p");
    p.className = "agent-form-error";
    p.setAttribute("role", "alert");
    p.textContent = av.erreur;
    corps.appendChild(p);
  }
  if (av.note) {
    const p = document.createElement("p");
    p.className = "agent-note";
    p.textContent = av.note;
    corps.appendChild(p);
  }

  if (!av.charge) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Lecture de la file…";
    corps.appendChild(p);
    return corps;
  }
  const propositions = av.propositions || [];
  if (!propositions.length) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent =
      av.statut === "en_attente" ? "Rien n’attend votre accord." : "Aucune proposition ici.";
    corps.appendChild(p);
    return corps;
  }
  const ul = document.createElement("ul");
  ul.className = "propositions";
  for (const p of propositions) ul.appendChild(rendreProposition(p, state, actions, maintenant));
  corps.appendChild(ul);
  return corps;
}

/** Le badge de la navigation : le nombre en attente, caché à zéro. */
export function rendreBadge(el, compte) {
  if (!el) return;
  const n = Math.max(0, Number(compte) || 0);
  el.hidden = n === 0;
  el.textContent = n > 99 ? "99+" : String(n);
  el.setAttribute("aria-label", `${n} en attente`);
}
