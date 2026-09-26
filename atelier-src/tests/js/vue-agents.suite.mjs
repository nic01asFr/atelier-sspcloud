// La vue Agents (vague 2) : les gardiens comme agents spécifiques, toutes les
// tâches automatiques, l'écran « À valider » et le journal.
//
// Ce qu'elle doit tenir :
//   - un gardien est une carte dans la liste des agents, et sa fiche montre
//     état, alertes, constats, échéances, gestes, avec « Lancer maintenant »
//     et « Couper / Réactiver » ;
//   - couper demande confirmation ; refusée, rien ne part ;
//   - la liste des tâches automatiques montre dernière, prochaine, plafond et
//     état ; « Activer » n'est proposé que pour une tâche coupée, et dit qu'il
//     est réservé à la personne ; sans pilote, pas de geste sur ses tâches ;
//   - « À valider » : refuser en un clic, motif facultatif ; accepter envoie
//     les précisions demandées ; le badge suit le nombre en attente ;
//   - le journal se lit en phrases, filtrable par projet, acteur et source ;
//   - le lexique : jamais « trigger », « routine », « artefact », « MCP ».

import { cliquer, saisir, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

const stockage = () => {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
};
globalThis.localStorage = stockage();
globalThis.sessionStorage = stockage();

const S = await import("../../mcp_gateway/atelier/web/js/state.js");
const {
  carteGardien,
  dateHumaine,
  ficheGardien,
  listeAutomates,
  plafondHumain,
  quandHumain,
} = await import("../../mcp_gateway/atelier/web/js/views/gardiens.js");
const { rendreAValider, rendreBadge, ceQueFaitAccepter } = await import(
  "../../mcp_gateway/atelier/web/js/views/a-valider.js"
);
const { phraseDeLEvenement, rendreJournal, concerneLeProjet, libelleCommande } = await import(
  "../../mcp_gateway/atelier/web/js/views/journal.js"
);
const { createAutomatesActions } = await import("../../mcp_gateway/atelier/web/js/controllers/automates.js");
const { createValidationActions } = await import("../../mcp_gateway/atelier/web/js/controllers/validation.js");
const { createAgentView } = await import("../../mcp_gateway/atelier/web/js/views/agent.js");

async function attendre() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

const MAINTENANT = Date.parse("2026-09-26T10:00:00Z");
const MOTS_INTERNES = ["trigger", "routine", "artefact", "MCP", "cron", "pilote"];

function boutons(noeud) {
  return noeud.querySelectorAll("button");
}

function bouton(noeud, libelle) {
  return boutons(noeud).find((b) => texte(b) === libelle) || null;
}

function sansMotsInternes(t, ou) {
  for (const mot of MOTS_INTERNES) nePorte(t, mot, `lexique (${ou}) : pas de « ${mot} » à l'écran`);
}

const SANTE = {
  id: "sante",
  etat: "alerte",
  controles: [
    { id: "sante.wikichat", quand: { toutes_les_min: 1 }, derniere: "2026-09-26T09:59:00Z", prochaine: "2026-09-26T10:01:00Z", etat: "alerte", actif: true, actif_declare: true, coupe: null, en_cours: false },
    { id: "sante.relais", quand: { toutes_les_min: 1 }, derniere: "2026-09-26T09:59:00Z", prochaine: null, etat: "ok", actif: false, actif_declare: true, coupe: { par: "personne", quand: "2026-09-26T09:00:00Z" }, en_cours: false },
    { id: "sante.image-main", quand: { cron: "15 7 * * *", tz: "Europe/Paris" }, derniere: null, prochaine: "2026-09-27T05:15:00Z", etat: null, actif: true, actif_declare: true, coupe: null, en_cours: false },
  ],
  alertes: [
    { empreinte: "sante.wikichat:ne-repond-pas", controle: "sante.wikichat", objet: "sante.wikichat", resume: "wikichat ne répond pas", preuve: "http://127.0.0.1:3777/health : refus", niveau: "alerte", depuis: "2026-09-26T09:40:00Z", compte: 20 },
  ],
  constats: [{ controle: "sante.wikichat", resume: "wikichat ne répond pas", niveau: "alerte", quand: "2026-09-26T09:59:00Z" }],
  derniere: "2026-09-26T09:59:00Z",
  prochaine: "2026-09-26T10:01:00Z",
  gestes: [{ quand: "2026-09-26T09:45:00Z", gardien: "sante", nom: "relancer_wikichat", apres: { etat: "alerte" }, resultat: "fait" }],
  actions: { lancer: true, couper: true, reactiver: true },
};

// ── Mots et dates ──────────────────────────────────────────────────────
{
  egal(quandHumain({ toutes_les_min: 1 }), "chaque minute", "une minute");
  egal(quandHumain({ toutes_les_min: 15 }), "toutes les 15 min", "un quart d'heure");
  egal(quandHumain({ toutes_les_min: 60 }), "toutes les heures", "une heure");
  egal(quandHumain({ cron: "15 7 * * *" }), "chaque jour à 07:15", "un horaire quotidien");
  egal(quandHumain({ cron: "0 */4 * * *" }), "toutes les 4 h", "toutes les quatre heures");
  egal(dateHumaine("2026-09-26T09:57:00Z", MAINTENANT), "il y a 3 min", "passé proche");
  egal(dateHumaine("2026-09-26T10:12:00Z", MAINTENANT), "dans 12 min", "futur proche");
  egal(dateHumaine(null, MAINTENANT), "jamais", "jamais");
  egal(plafondHumain({ genre: "gardien", plafond: { jetons: 0 } }), "sans IA, aucune dépense", "un gardien ne coûte rien");
  egal(
    plafondHumain({ genre: "trigger", plafond: { par_jour: 6, budget: null } }),
    "6 fois par jour au plus, sans limite de dépense",
    "une tâche sans budget le dit"
  );
}

// ── Un gardien : sa carte, sa fiche, ses gestes ────────────────────────
{
  let choisi = null;
  const carte = carteGardien(SANTE, { onChoisir: (id) => (choisi = id), maintenant: MAINTENANT });
  porte(texte(carte), "Santé", "la carte nomme le gardien");
  porte(texte(carte), "1 alerte ouverte", "la carte compte les alertes");
  porte(texte(carte), "prochaine vérification dans 1 min", "la carte dit la prochaine échéance");
  cliquer(carte);
  egal(choisi, "sante", "cliquer la carte ouvre le gardien");

  const appels = [];
  const actions = {
    agir: (id, geste) => appels.push(["agir", id, geste]),
    couper: (id, nom) => appels.push(["couper", id, nom]),
  };
  const corps = document.createElement("div");
  ficheGardien(corps, SANTE, { actions, maintenant: MAINTENANT });
  const t = texte(corps);
  porte(t, "Gardien santé", "le titre dit gardien");
  porte(t, "sans IA", "la fiche dit qu'il ne coûte rien");
  porte(t, "wikichat ne répond pas", "l'alerte ouverte est lisible");
  porte(t, "vu 20 fois", "une alerte revue se compte");
  porte(t, "Le relais du modèle répond", "les contrôles sont nommés en clair");
  porte(t, "coupé à la main", "un contrôle coupé le dit");
  porte(t, "chaque jour à 07:15", "le rythme d'un contrôle en mots");
  porte(t, "Relancer wikichat · sans effet", "un geste récent et son issue");
  sansMotsInternes(t, "fiche gardien");

  cliquer(bouton(corps, "Lancer maintenant"));
  egal(appels.at(-1), ["agir", "gardien.sante", "lancer"], "lancer tout le gardien");
  cliquer(bouton(corps, "Couper"));
  egal(appels.at(-1), ["couper", "gardien.sante", "Santé"], "couper passe par la confirmation");
  cliquer(bouton(corps, "Réactiver"));
  egal(appels.at(-1), ["agir", "gardien.sante", "reactiver"], "réactiver ce qui est coupé");
  const ligneRelais = corps.querySelectorAll("li").find((li) => li.dataset.controle === "sante.relais");
  cliquer(bouton(ligneRelais, "Réactiver"));
  egal(appels.at(-1), ["agir", "controle.sante.relais", "reactiver"], "réactiver un seul contrôle");
  const ligneWikichat = corps.querySelectorAll("li").find((li) => li.dataset.controle === "sante.wikichat");
  cliquer(bouton(ligneWikichat, "Lancer"));
  egal(appels.at(-1), ["agir", "controle.sante.wikichat", "lancer"], "lancer un seul contrôle");

  const coupe = {
    ...SANTE,
    etat: "coupe",
    controles: SANTE.controles.map((c) => ({ ...c, actif: false, prochaine: null, coupe: { par: "personne", quand: "2026-09-26T09:00:00Z" } })),
    actions: { lancer: false, couper: false, reactiver: true },
  };
  ficheGardien(corps, coupe, { actions, maintenant: MAINTENANT });
  verifier(!bouton(corps, "Couper"), "un gardien coupé ne propose plus de le couper");
  verifier(bouton(corps, "Lancer maintenant").disabled, "ni de le lancer");
  porte(texte(corps), "Coupé", "son état le dit");

  ficheGardien(corps, SANTE, { actions, enCours: "gardien.sante", maintenant: MAINTENANT });
  verifier(bouton(corps, "Lancer maintenant").disabled, "pendant un geste, les boutons attendent");
}

// ── Toutes les tâches automatiques ─────────────────────────────────────
const AUTOMATES = {
  automates: [
    { id: "gardien.sante", genre: "gardien", titre: "sante", derniere: "2026-09-26T09:59:00Z", prochaine: "2026-09-26T10:01:00Z", plafond: { jetons: 0 }, etat: "alerte", gestes: ["lancer", "couper"] },
    { id: "trigger.cron-routine-4h", genre: "trigger", titre: "Recherche paradoxes", derniere: "2026-09-25T20:00:00Z", prochaine: "2026-09-26T12:00:00Z", plafond: { par_jour: 6, budget: null }, etat: "sans_declaration", gestes: ["lancer", "couper"] },
    { id: "trigger.veille", genre: "trigger", agent: true, titre: "Veille dépôts", derniere: null, prochaine: null, prochaine_texte: "demain 8h", plafond: { par_jour: 24 }, etat: "coupe", gestes: ["activer"] },
    { id: "routine.paradox-research", genre: "routine", titre: "Paradoxes", derniere: null, prochaine: null, plafond: { budget: null }, etat: "sans_declaration", gestes: [] },
    { id: "creation.demo/carte", genre: "creation", titre: "carte", projet: "demo", plafond: { redemarrages: 5, fenetre_min: 10 }, etat: "actif", gestes: [] },
  ],
  sources: { gardiens: true, inventaire: true, pilote: true },
  notes: [],
};
{
  const appels = [];
  const actions = { agir: (id, g) => appels.push([id, g]), choisirGardien: (n) => appels.push(["voir", n]) };
  const c = document.createElement("div");
  listeAutomates(c, AUTOMATES, { actions, maintenant: MAINTENANT });
  const t = texte(c);
  porte(t, "Gardien santé", "les gardiens sont dans la liste");
  porte(t, "Recherche paradoxes", "une tâche de wikichat");
  porte(t, "Agent planifié", "un agent planifié se reconnaît");
  porte(t, "Tâche en plusieurs étapes", "une routine, dite en mots");
  porte(t, "carte (projet demo)", "une création servie");
  porte(t, "6 fois par jour au plus, sans limite de dépense", "le plafond d'une tâche");
  porte(t, "prochaine : demain 8h", "la prochaine, en mots du pilote");
  porte(t, "Sans limite de dépense", "l'état d'une tâche sans budget");
  sansMotsInternes(t, "tâches automatiques");

  const ligne = (id) => c.querySelectorAll("li").find((li) => li.dataset.automate === id);
  verifier(!bouton(ligne("gardien.sante"), "Couper"), "un gardien ne se coupe que depuis sa fiche");
  cliquer(bouton(ligne("gardien.sante"), "Voir"));
  egal(appels.at(-1), ["voir", "sante"], "voir ouvre la fiche du gardien");
  cliquer(bouton(ligne("trigger.cron-routine-4h"), "Couper"));
  egal(appels.at(-1), ["trigger.cron-routine-4h", "couper"], "couper une tâche");
  const activer = bouton(ligne("trigger.veille"), "Activer");
  verifier(activer, "une tâche coupée propose Activer");
  porte(activer.title, "Réservé à vous", "Activer dit qu'il est réservé à la personne (J-b2)");
  verifier(!bouton(ligne("trigger.cron-routine-4h"), "Activer"), "une tâche active ne propose pas Activer");
  egal(boutons(ligne("routine.paradox-research")).length, 0, "une routine ne se pilote pas d'ici");

  listeAutomates(c, { ...AUTOMATES, sources: { gardiens: true, pilote: false }, notes: ["Le pilote de wikichat n'est pas branché ici (mode factice)."] }, { actions });
  verifier(!bouton(ligne("trigger.veille"), "Activer"), "sans pilote, pas de geste sur ses tâches");
  porte(texte(c), "mode factice", "la note dit pourquoi");
}

// ── Les gestes : confirmation, appel, relecture ────────────────────────
{
  const state = S.createState();
  state.token = "session";
  const appels = [];
  const api = {
    getGardiens: async () => (appels.push("gardiens"), { joignable: true, gardiens: [SANTE] }),
    getAutomates: async () => (appels.push("automates"), AUTOMATES),
    agirSurAutomate: async (id, g) => {
      appels.push(["agir", id, g]);
      if (g === "activer") {
        const e = new Error("activer une tâche automatique est réservé à la personne");
        e.status = 403;
        throw e;
      }
      return {};
    },
  };
  let reponse = false;
  const a = createAutomatesActions({ state, api, render: () => {}, confirmer: () => reponse });
  await a.couper("gardien.sante", "Santé");
  verifier(!appels.some((x) => Array.isArray(x)), "couper refusé à la confirmation : rien ne part");
  reponse = true;
  await a.couper("gardien.sante", "Santé");
  egal(appels.find((x) => Array.isArray(x)), ["agir", "gardien.sante", "couper"], "couper confirmé part au service");
  verifier(appels.includes("gardiens") && appels.includes("automates"), "l'état se relit après un geste");
  egal(state.automateEnCours, "", "le geste fini libère les boutons");
  await a.agir("trigger.veille", "activer");
  porte(state.error, "réservé à la personne", "le refus du service se lit");
  a.choisirGardien("sante");
  egal([state.agentPanel, state.selectedGardienId], ["gardien", "sante"], "choisir un gardien ouvre sa fiche");
}

// ── « À valider » : refuser en un clic, accepter avec précisions ───────
{
  const state = S.createState();
  state.token = "session";
  const PROPOSITIONS = [
    { id: "av-1", source: "gardien", titre: "Port ouvert à tous : 8000", resume: "Fermer l'écoute sur toutes les interfaces", acteur: "gardiens", projet: "", detail: { port: 8000 }, action: { commande: "atelier_projet_ranger", arguments: { projet: "vieux" } }, creee_le: "2026-09-26T09:00:00Z", occurrences: 3, statut: "en_attente" },
    { id: "pilote:depenses:a1", source: "pilote", titre: "Ajouter la dépense", resume: "Courses 42 €", acteur: "agent:Dépenses", detail: { agent: "depenses", a_completer: [{ field: "Categorie", path: "apply.fields.Categorie", question: "Quelle catégorie ?", options: ["Alimentation", "Loisirs"] }] }, action: null, creee_le: "2026-09-26T09:30:00Z", occurrences: 1, statut: "en_attente" },
  ];
  let file = [...PROPOSITIONS];
  const decisions = [];
  const api = {
    listerAValider: async ({ statut }) => ({ statut: "fait", resultat: { propositions: statut === "en_attente" ? file : [], nombre: statut === "en_attente" ? file.length : 0 } }),
    deciderAValider: async (id, decision, opts) => {
      decisions.push([id, decision, opts]);
      file = file.filter((p) => p.id !== id);
      return { statut: "fait" };
    },
    lireJournal: async () => ({ evenements: [] }),
  };
  const corps = document.createElement("div");
  const badge = document.createElement("span");
  let v;
  const render = () => rendreAValider(corps, state, v, { maintenant: MAINTENANT });
  v = createValidationActions({ state, api, render, renderBadge: () => rendreBadge(badge, state.aValiderCompte) });

  await v.rafraichirCompte();
  egal(badge.textContent, "2", "le badge compte ce qui attend");
  verifier(!badge.hidden, "le badge se voit");

  await v.charger();
  const t = texte(corps);
  porte(t, "Port ouvert à tous : 8000", "la proposition d'un gardien");
  porte(t, "Gardien", "sa source");
  porte(t, "vu 3 fois", "une proposition revue se compte");
  porte(t, "Agent planifié", "la proposition d'un agent de wikichat, dans la même file");
  sansMotsInternes(t, "À valider");

  // Le rendu général repasse sans cesse : sans changement, rien ne se
  // reconstruit, et le champ du motif garde sa frappe et son focus.
  const champ = corps.querySelectorAll("input")[0];
  render();
  render();
  verifier(corps.querySelectorAll("input")[0] === champ, "un rendu sans changement ne recrée pas le champ du motif");

  // Le détail : qui, quoi, ce qu'accepter fera.
  const tete = corps.querySelectorAll("button").find((b) => b.className === "proposition-tete");
  cliquer(tete);
  porte(texte(corps), "Accepter va ranger le projet (projet : vieux)", "ce qu'accepter fera, en mots");
  porte(texte(corps), "Le gardien", "qui l'a proposée");

  // Refuser : un clic, sans motif.
  const premiere = () => corps.querySelectorAll("li").find((li) => li.dataset.proposition === "av-1");
  cliquer(bouton(premiere(), "Refuser"));
  await attendre();
  egal(decisions[0], ["av-1", "refuser", { motif: "" }], "refuser en un clic, motif vide");
  egal(badge.textContent, "1", "le badge suit la décision");

  // Accepter une proposition qui demande une précision.
  const seconde = () => corps.querySelectorAll("li").find((li) => li.dataset.proposition === "pilote:depenses:a1");
  cliquer(seconde().querySelectorAll("button").find((b) => b.className === "proposition-tete"));
  porte(texte(seconde()), "Quelle catégorie ?", "la précision attendue est demandée");
  porte(texte(seconde()), "L’agent appliquera sa proposition", "ce qu'accepter fera pour un agent planifié");
  const choix = seconde().querySelectorAll("select")[0];
  choix.value = "Loisirs";
  choix.dispatchEvent(new Event("change"));
  cliquer(bouton(seconde(), "Accepter"));
  await attendre();
  egal(decisions[1], ["pilote:depenses:a1", "accepter", { complete: { "apply.fields.Categorie": "Loisirs" } }], "accepter envoie la précision");
  egal(badge.textContent, "0", "plus rien n'attend");
  verifier(badge.hidden, "le badge se cache à zéro");
  porte(texte(corps), "Rien n’attend votre accord.", "l'écran vide le dit");

  // Un refus avec motif.
  file = [{ ...PROPOSITIONS[0], id: "av-2" }];
  await v.charger();
  const ligne = corps.querySelectorAll("li").find((li) => li.dataset.proposition === "av-2");
  saisir(ligne.querySelectorAll("input")[0], "déjà traité");
  cliquer(bouton(ligne, "Refuser"));
  await attendre();
  egal(decisions[2], ["av-2", "refuser", { motif: "déjà traité" }], "le motif, s'il est donné, part avec le refus");

  // Un refus du service (accepter réservé) se lit.
  api.deciderAValider = async () => {
    throw new Error("l'action proposée n'a pas abouti (refus) : {'erreur': 'projet inconnu : vieux', 'classe': 'reversible'}");
  };
  file = [{ ...PROPOSITIONS[0], id: "av-4" }];
  await v.charger();
  cliquer(bouton(corps.querySelectorAll("li").find((li) => li.dataset.proposition === "av-4"), "Accepter"));
  await attendre();
  porte(texte(corps), "L'action proposée n'a pas abouti : projet inconnu : vieux.", "la raison d'un échec se lit sans code");
  nePorte(texte(corps), "'classe'", "sans le dict recopié");

  api.deciderAValider = async () => {
    const e = new Error("commande réservée à la personne");
    e.status = 403;
    throw e;
  };
  file = [{ ...PROPOSITIONS[0], id: "av-3" }];
  await v.charger();
  cliquer(bouton(corps.querySelectorAll("li").find((li) => li.dataset.proposition === "av-3"), "Accepter"));
  await attendre();
  porte(texte(corps), "réservée à la personne", "le refus du service s'affiche");

  egal(ceQueFaitAccepter({ source: "agent", action: null }), "Accepter ne lance rien : cela vaut accord, et la proposition est close.", "sans action, accepter ne lance rien");
  nePorte(ceQueFaitAccepter({ source: "creation", action: { commande: "atelier_artefact_demarrer", arguments: {} } }), "artefact", "lexique : création, pas artefact");
}

// ── Le journal, en phrases ─────────────────────────────────────────────
{
  const sessions = [{ session_id: "s1", slug: "demo", title: "Carte des logements" }];
  const e1 = { quand: "2026-09-26T09:50:00Z", source: "commande", acteur: "conversation:s1", objet: { type: "projet", id: "demo" }, action: { commande: "atelier_projet_creer", arguments: { titre: "Demo" } }, resultat: "fait" };
  const e2 = { quand: "2026-09-26T09:40:00Z", source: "controle", acteur: "gardiens", objet: { type: "pod", id: "sante.wikichat" }, action: { commande: "sante.wikichat", origine: "sante", apres: { alerte: "ouverte", resume: "wikichat ne répond pas" } }, resultat: "alerte" };
  const e3 = { quand: "2026-09-26T09:45:00Z", source: "geste", acteur: "gardiens", objet: { type: "pod", id: "relancer_wikichat" }, action: { commande: "relancer_wikichat", origine: "sante" }, resultat: "fait" };
  const e4 = { quand: "2026-09-26T09:30:00Z", source: "automate", acteur: "personne", objet: { type: "gardien", id: "securite" }, action: { commande: "automate_couper" }, resultat: "fait" };
  const e5 = { quand: "2026-09-26T09:20:00Z", source: "automate", acteur: "cle-proprietaire", objet: { type: "tache", id: "veille" }, action: { commande: "automate_activer" }, resultat: "refus" };
  const e6 = { quand: "2026-09-26T09:10:00Z", source: "commande", acteur: "conversation:zz", objet: { type: "creation", id: "x" }, action: { commande: "atelier_artefact_creer" }, resultat: "apercu" };

  egal(phraseDeLEvenement(e1, { sessions }).texte, "La conversation « Carte des logements » a créé le projet « demo »", "une commande en phrase");
  egal(phraseDeLEvenement(e2).texte, "Le gardien santé a ouvert une alerte : wikichat ne répond pas", "une alerte d'un gardien");
  egal(phraseDeLEvenement(e3).texte, "Le gardien santé a fait le geste « Relancer wikichat »", "un geste d'un gardien");
  egal(phraseDeLEvenement(e4).texte, "Vous avez coupé le gardien sécurité", "votre geste sur un gardien");
  const refus = phraseDeLEvenement(e5);
  egal([refus.texte, refus.resultat], ["Un agent (clé du propriétaire) a voulu activer la tâche automatique « veille »", "refusé"], "un refus dit ce qui était voulu, pas ce qui a été fait");
  egal(phraseDeLEvenement(e6).resultat, "en attente de votre accord", "un aperçu attend l'accord");
  const e7 = { source: "controle", acteur: "gardiens", objet: { id: "wikichat.trigger.x" }, action: { origine: "entretien", apres: { resume: "trigger actif sans budget déclaré" } }, resultat: "alerte" };
  egal(phraseDeLEvenement(e7).texte, "Le gardien entretien a ouvert une alerte : tâche automatique active sans limite de dépense", "le résumé de l'inventaire suit le lexique");
  egal(phraseDeLEvenement({ ...e1, acteur: "gardiens", source: "validation", action: { geste: "deposer" } }).texte, "Le gardien a déposé une proposition", "un gardien, au singulier");
  nePorte(libelleCommande("atelier_artefact_verifier"), "artefact", "une commande inconnue garde le lexique");
  verifier(concerneLeProjet(e1, "demo", sessions), "par l'objet");
  verifier(!concerneLeProjet(e2, "demo", sessions), "une alerte du pod n'est pas du projet");

  const state = S.createState();
  state.token = "session";
  state.sessions = sessions;
  state.projects = [{ slug: "demo", title: "Démo" }, { slug: "autre", title: "Autre" }];
  const lus = [];
  const api = {
    lireJournal: async (f) => (lus.push(f), { evenements: [e1, e2, e3, e4, e5, e6] }),
    listerAValider: async () => ({ resultat: { propositions: [], nombre: 0 } }),
  };
  const corps = document.createElement("div");
  let v;
  const render = () => rendreJournal(corps, state, v, { maintenant: MAINTENANT });
  v = createValidationActions({ state, api, render });
  await v.chargerJournal();
  const t = texte(corps);
  porte(t, "Le gardien santé a fait le geste « Relancer wikichat »", "le journal se lit en phrases");
  porte(t, "Gardiens : alertes", "la source en mots");
  sansMotsInternes(t, "journal");

  await v.filtrer({ projet: "demo" });
  egal(corps.querySelectorAll("li").filter((li) => li.className.includes("journal-ligne")).length, 1, "le filtre projet garde ce qui le touche");
  porte(texte(corps), "a créé le projet", "et c'est la bonne ligne");
  egal(lus.length, 1, "filtrer par projet ne relit pas le service");

  await v.filtrer({ projet: "", source: "automate", acteur: "personne" });
  egal(lus.at(-1), { source: "automate", acteur: "personne", limite: 300 }, "acteur et source filtrent au service");
  const selects = corps.querySelectorAll("select");
  egal(selects.length, 3, "trois filtres : projet, acteur, source");
}

// ── La vue Agents : une section Gardiens, leur fiche, les tâches ───────
{
  for (const id of ["agent-list", "agent-detail-body", "view-agent", "btn-shell-back-agent", "btn-shell-forward-agent", "btn-agent-to-home", "context-menu"]) {
    const n = document.createElement(id.startsWith("btn") ? "button" : "div");
    n.id = id;
    document.body.appendChild(n);
  }
  const state = S.createState();
  state.token = "session";
  state.view = "agent";
  state.piloteOverview = { agents: [], daemon: {}, system_agents: [] };
  state.gardiens = { joignable: true, gardiens: [SANTE, { ...SANTE, id: "securite", etat: "ok", alertes: [], constats: [], gestes: [] }] };
  state.automates = AUTOMATES;
  state.aValiderCompte = 2;
  const vus = [];
  const automates = { choisirGardien: (id) => vus.push(id), agir: () => {}, couper: () => {} };
  const actionsAgent = { ouvrirAValider: () => vus.push("a-valider") };
  const vue = createAgentView({ state, actions: actionsAgent, automates });
  vue.renderAgent();
  const liste = document.getElementById("agent-list");
  porte(texte(liste), "Gardiens", "la liste a une section Gardiens");
  porte(texte(liste), "Sécurité", "chaque gardien y a sa carte");
  cliquer(liste.querySelectorAll("li").find((li) => li.dataset.gardien === "securite"));
  egal(vus.at(-1), "securite", "cliquer un gardien le choisit");

  const accueil = document.getElementById("agent-detail-body");
  porte(texte(accueil), "Tâches automatiques", "l'accueil liste toutes les tâches automatiques");
  porte(texte(accueil), "2 propositions attendent votre accord.", "l'accueil renvoie à la file unique");
  cliquer(bouton(accueil, "Ouvrir « À valider »"));
  egal(vus.at(-1), "a-valider", "et y mène");
  sansMotsInternes(texte(accueil).replace("Planificateur", ""), "accueil Agents");

  state.agentPanel = "gardien";
  state.selectedGardienId = "sante";
  vue.renderAgent();
  porte(texte(document.getElementById("agent-detail-body")), "Gardien santé", "la fiche du gardien s'ouvre dans la vue Agents");
  verifier(!document.getElementById("btn-shell-back-agent").hidden, "on revient à la liste depuis la fiche");

  // Le pilote absent : la vue garde les gardiens.
  state.piloteOverview = null;
  state.agentPanel = "home";
  state.gardiens = { joignable: false, gardiens: [], note: "Les gardiens ne répondent pas" };
  vue.renderAgent();
  porte(texte(document.getElementById("agent-list")), "Les gardiens ne répondent pas.", "un exécuteur arrêté se dit");
}

bilan("vue-agents");
