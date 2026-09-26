/**
 * Le journal unique, lu en langage humain.
 *
 * Une ligne par événement : qui, a fait quoi, sur quoi, avec quel résultat.
 * Filtrable par projet, acteur et source. Les mots suivent le lexique
 * (decisions.md S2) : jamais « artefact », « trigger » ni « MCP » à l'écran.
 */

import { dateHumaine, libelleControle, libelleGeste, nomDuGardien, resumeLisible } from "./gardiens.js";

// Chaque commande : ce qu'elle a fait (passé composé), et ce qu'on a voulu
// faire (infinitif) quand elle a été refusée ou a échoué.
const COMMANDES = {
  atelier_ouvrir: ["a ouvert une conversation", "ouvrir une conversation"],
  atelier_envoyer: ["a envoyé un message", "envoyer un message"],
  atelier_interrompre: ["a arrêté un tour", "arrêter un tour"],
  atelier_decider: ["a répondu à une demande d’autorisation", "répondre à une demande d’autorisation"],
  atelier_artefact_creer: ["a fabriqué une création", "fabriquer une création"],
  atelier_artefact_demarrer: ["a démarré une création", "démarrer une création"],
  atelier_artefact_arreter: ["a arrêté une création", "arrêter une création"],
  atelier_projet_creer: ["a créé le projet", "créer le projet"],
  atelier_projet_modifier: ["a modifié le projet", "modifier le projet"],
  atelier_projet_ranger: ["a rangé le projet", "ranger le projet"],
  atelier_projet_ressortir: ["a ressorti le projet", "ressortir le projet"],
  atelier_projet_publier: ["a partagé le projet", "partager le projet"],
  atelier_conversation_ranger: ["a rangé une conversation", "ranger une conversation"],
  atelier_conversation_ressortir: ["a ressorti une conversation", "ressortir une conversation"],
  atelier_a_valider_accepter: ["a accepté une proposition", "accepter une proposition"],
  atelier_a_valider_refuser: ["a refusé une proposition", "refuser une proposition"],
  atelier_a_valider_rouvrir: ["a remis une proposition en attente", "remettre une proposition en attente"],
  atelier_annuler: ["a annulé une action", "annuler une action"],
  atelier_montrer: ["a montré quelque chose dans le panneau", "montrer quelque chose dans le panneau"],
  atelier_navigateur_ouvrir: ["a ouvert le navigateur", "ouvrir le navigateur"],
  atelier_agent_creer: ["a créé un agent", "créer un agent"],
  atelier_agent_modifier: ["a modifié un agent", "modifier un agent"],
  atelier_agent_supprimer: ["a supprimé un agent", "supprimer un agent"],
  atelier_agent_activer: ["a activé l’agent", "activer l’agent"],
  atelier_agent_desactiver: ["a désactivé l’agent", "désactiver l’agent"],
  atelier_connecteur_ajouter: ["a ajouté le connecteur", "ajouter le connecteur"],
  atelier_connecteur_retirer: ["a retiré le connecteur", "retirer le connecteur"],
  atelier_connecteur_choisir: ["a choisi les connecteurs d’un projet", "choisir les connecteurs d’un projet"],
  atelier_connecteur_accorder: ["a accordé un secret au connecteur", "accorder un secret au connecteur"],
  atelier_projets_lier: ["a relié des projets", "relier des projets"],
  atelier_projet_structurer: ["a mis le projet à la structure type", "mettre le projet à la structure type"],
  atelier_projet_destructurer: ["a remis le projet comme avant", "remettre le projet comme avant"],
  atelier_memoire_proposer: ["a proposé de retenir quelque chose", "proposer de retenir quelque chose"],
  atelier_memoire_retenir: ["a retenu dans votre mémoire", "retenir dans votre mémoire"],
  atelier_memoire_corriger: ["a corrigé votre mémoire", "corriger votre mémoire"],
  atelier_memoire_oublier: ["a oublié un élément de votre mémoire", "oublier un élément de votre mémoire"],
  automate_lancer: ["a lancé maintenant", "lancer maintenant"],
  automate_couper: ["a coupé", "couper"],
  automate_reactiver: ["a réactivé", "réactiver"],
  automate_activer: ["a activé", "activer"],
};

function nomLisible(nom) {
  return String(nom || "")
    .replace(/^atelier_/, "")
    .replace(/artefact/g, "création")
    .replace(/_/g, " ")
    .trim();
}

/** Ce qu'une commande a fait, en mots ; les noms internes ne s'affichent pas bruts. */
export function libelleCommande(nom) {
  if (COMMANDES[nom]) return COMMANDES[nom][0];
  const lisible = nomLisible(nom);
  return lisible ? `a utilisé « ${lisible} »` : "a agi";
}

/** Ce qu'une commande voulait faire, à l'infinitif. */
export function infinitifCommande(nom) {
  if (COMMANDES[nom]) return COMMANDES[nom][1];
  const lisible = nomLisible(nom);
  return lisible ? `utiliser « ${lisible} »` : "agir";
}

export const SOURCES = [
  { valeur: "", texte: "Toutes les sources" },
  { valeur: "commande", texte: "Actions" },
  { valeur: "controle", texte: "Gardiens : alertes" },
  { valeur: "geste", texte: "Gestes" },
  { valeur: "automate", texte: "Tâches automatiques" },
  { valeur: "validation", texte: "À valider" },
  { valeur: "capacite", texte: "Autorisations" },
  { valeur: "promotion", texte: "Installations" },
  { valeur: "vue", texte: "Panneau" },
];

export function libelleSource(source) {
  return SOURCES.find((s) => s.valeur === source)?.texte || String(source || "");
}

/**
 * Qui a agi, en mots. `sessions` sert à nommer une conversation par son titre.
 */
export function libelleActeur(acteur, { sessions = [], origine = "" } = {}) {
  const a = String(acteur || "");
  if (a === "personne") return "Vous";
  if (a === "cle-proprietaire") return "Un agent (clé du propriétaire)";
  if (a === "gardiens") return `Le gardien${origine ? ` ${nomDuGardien(origine).toLowerCase()}` : ""}`;
  if (a.startsWith("conversation:")) {
    const sid = a.slice("conversation:".length);
    const s = sessions.find((x) => x.session_id === sid || x.id === sid);
    const titre = s?.title || s?.titre;
    return titre ? `La conversation « ${titre} »` : "Une conversation";
  }
  if (a.startsWith("agent:")) return `L’agent « ${a.slice("agent:".length)} »`;
  return a || "Quelqu’un";
}

function nomDeLObjet(objet) {
  if (!objet || typeof objet !== "object") return "";
  const id = String(objet.id || "");
  if (!id) return "";
  switch (objet.type) {
    case "gardien":
      return `le gardien ${nomDuGardien(id).toLowerCase()}`;
    case "controle":
      return `la vérification « ${libelleControle(id)} »`;
    case "tache":
      return `la tâche automatique « ${id} »`;
    case "projet":
    case "agent":
    case "connecteur":
      return `« ${id} »`;
    case "validation":
      return "";
    default:
      return "";
  }
}

const RESULTATS = {
  fait: "",
  apercu: "en attente de votre accord",
  refus: "refusé",
  refuse: "retenu",
  erreur: "échec",
};

/** Une phrase par événement, plus son résultat et sa source. */
export function phraseDeLEvenement(e, { sessions = [] } = {}) {
  const action = e?.action && typeof e.action === "object" ? e.action : {};
  const qui = libelleActeur(e?.acteur, { sessions, origine: action.origine });
  const objet = e?.objet && typeof e.objet === "object" ? e.objet : {};
  let texte;
  if (e?.source === "controle") {
    const sujet = libelleControle(objet.id || action.commande);
    if (e.resultat === "resolue") texte = `${qui} ne voit plus le problème : ${sujet}`;
    else texte = `${qui} a ouvert une alerte : ${resumeLisible(action.apres?.resume) || sujet}`;
  } else if (e?.source === "geste" && e?.acteur === "gardiens") {
    texte = `${qui} a fait le geste « ${libelleGeste(action.commande)} »`;
  } else if (e?.source === "validation") {
    const verbes = {
      deposer: "a déposé une proposition",
      accepter: "a accepté une proposition",
      refuser: "a refusé une proposition",
      rouvrir: "a remis une proposition en attente",
    };
    texte = `${qui} ${verbes[action.geste] || "a agi sur une proposition"}`;
  } else {
    // Refusée, échouée ou en attente d'accord : elle n'a rien fait, on dit
    // ce qui était voulu.
    const abouti = !["refus", "erreur", "apercu"].includes(e?.resultat);
    const verbe = abouti ? libelleCommande(action.commande) : `a voulu ${infinitifCommande(action.commande)}`;
    const cible = nomDeLObjet(objet);
    texte = cible ? `${qui} ${verbe} ${cible}` : `${qui} ${verbe}`;
  }
  // « Vous a créé » : la personne se conjugue à la deuxième personne.
  if (texte.startsWith("Vous a ")) texte = `Vous avez ${texte.slice("Vous a ".length)}`;
  const resultat = e?.resultat === "alerte" || e?.resultat === "resolue" ? "" : RESULTATS[e?.resultat] ?? String(e?.resultat || "");
  return { texte, resultat, source: libelleSource(e?.source) };
}

/** Cet événement concerne-t-il ce projet ? Par l'objet, les arguments ou la conversation. */
export function concerneLeProjet(e, slug, sessions = []) {
  if (!slug) return true;
  const objet = e?.objet || {};
  if (objet.type === "projet" && objet.id === slug) return true;
  const args = e?.action?.arguments || {};
  if (args.projet === slug || args.slug === slug) return true;
  const acteur = String(e?.acteur || "");
  if (acteur.startsWith("conversation:")) {
    const sid = acteur.slice("conversation:".length);
    const s = sessions.find((x) => x.session_id === sid || x.id === sid);
    if (s && (s.slug === slug || s.project === slug)) return true;
  }
  return false;
}

function choix(options, valeur, onChange, etiquette) {
  const sel = document.createElement("select");
  sel.className = "journal-filtre";
  sel.setAttribute("aria-label", etiquette);
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o.valeur;
    opt.textContent = o.texte;
    if (o.valeur === valeur) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.value = valeur;
  sel.addEventListener("change", () => onChange(sel.value));
  return sel;
}

/**
 * L'écran Journal. `actions.filtrer({projet|acteur|source})`, `actions.recharger()`.
 */
export function rendreJournal(corps, state, actions, { maintenant } = {}) {
  const j = state.journal || {};
  const filtres = j.filtres || {};
  const sessions = state.sessions || [];
  // Rien de changé, rien de reconstruit : une liste déroulante ouverte ne se
  // referme pas sous le doigt au passage de la veille des conversations.
  const empreinte = JSON.stringify([
    j.evenements, j.charge, j.erreur, filtres, (state.projects || []).length, sessions.length,
    Math.floor((maintenant ?? Date.now()) / 60000),
  ]);
  if (corps.dataset.empreinte === empreinte) return corps;
  corps.dataset.empreinte = empreinte;
  corps.innerHTML = "";

  const tete = document.createElement("header");
  tete.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "Journal";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Tout ce qui s’est passé dans l’Atelier, le plus récent d’abord : ce que vous avez fait, ce que les agents et les gardiens ont fait.";
  tete.appendChild(h);
  tete.appendChild(lead);
  corps.appendChild(tete);

  const barre = document.createElement("div");
  barre.className = "journal-filtres";
  const projets = [{ valeur: "", texte: "Tous les projets" }];
  for (const p of state.projects || []) {
    projets.push({ valeur: p.slug, texte: p.title || p.slug });
  }
  barre.appendChild(choix(projets, filtres.projet || "", (v) => actions.filtrer({ projet: v }), "Projet"));

  const acteurs = [
    { valeur: "", texte: "Tout le monde" },
    { valeur: "personne", texte: "Vous" },
    { valeur: "gardiens", texte: "Les gardiens" },
    { valeur: "cle-proprietaire", texte: "Agents (clé du propriétaire)" },
  ];
  const vus = new Set(acteurs.map((a) => a.valeur));
  for (const e of j.evenements || []) {
    const a = String(e.acteur || "");
    if (a && !vus.has(a)) {
      vus.add(a);
      acteurs.push({ valeur: a, texte: libelleActeur(a, { sessions }) });
    }
  }
  if (filtres.acteur && !vus.has(filtres.acteur)) {
    acteurs.push({ valeur: filtres.acteur, texte: libelleActeur(filtres.acteur, { sessions }) });
  }
  barre.appendChild(choix(acteurs, filtres.acteur || "", (v) => actions.filtrer({ acteur: v }), "Acteur"));
  barre.appendChild(choix(SOURCES, filtres.source || "", (v) => actions.filtrer({ source: v }), "Source"));
  const recharger = document.createElement("button");
  recharger.type = "button";
  recharger.className = "ghost btn-sm";
  recharger.textContent = "Actualiser";
  recharger.addEventListener("click", () => actions.recharger());
  barre.appendChild(recharger);
  corps.appendChild(barre);

  if (j.erreur) {
    const p = document.createElement("p");
    p.className = "agent-form-error";
    p.textContent = j.erreur;
    corps.appendChild(p);
  }

  const visibles = (j.evenements || []).filter((e) => concerneLeProjet(e, filtres.projet, sessions));
  if (!j.charge) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Lecture du journal…";
    corps.appendChild(p);
    return corps;
  }
  if (!visibles.length) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Rien dans le journal pour ces filtres.";
    corps.appendChild(p);
    return corps;
  }

  const ul = document.createElement("ul");
  ul.className = "journal-liste";
  for (const e of visibles) {
    const phrase = phraseDeLEvenement(e, { sessions });
    const li = document.createElement("li");
    li.className = "journal-ligne" + (e.resultat === "refus" || e.resultat === "erreur" || e.resultat === "alerte" ? " journal-ligne-marquee" : "");
    const quand = document.createElement("span");
    quand.className = "journal-quand";
    quand.textContent = dateHumaine(e.quand, maintenant);
    quand.title = String(e.quand || "");
    const texte = document.createElement("span");
    texte.className = "journal-texte";
    texte.textContent = phrase.texte;
    li.appendChild(quand);
    li.appendChild(texte);
    if (phrase.resultat) {
      const r = document.createElement("span");
      r.className = "journal-resultat";
      r.textContent = phrase.resultat;
      li.appendChild(r);
    }
    const s = document.createElement("span");
    s.className = "journal-source";
    s.textContent = phrase.source;
    li.appendChild(s);
    ul.appendChild(li);
  }
  corps.appendChild(ul);
  return corps;
}
