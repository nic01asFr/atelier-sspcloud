// La vue Assistant (vague 3, équipe A) : un vrai fil, et les cartes d'action.
//
//   - l'Assistant parle dans l'écran des conversations : `?view=assistant` y
//     mène, la navigation le montre actif, et passer d'un espace à l'autre ne
//     garde pas le fil de l'autre ;
//   - « Ouvrir l'Atelier sur l'Assistant » est désactivé par défaut (A-3) ;
//   - la colonne de gauche ne montre que ses conversations ;
//   - une carte d'action offre « Voir » et « Annuler », un aperçu offre
//     « Oui » ; les boutons annoncent, le contrôleur appelle le service au nom
//     de la personne, et la carte garde l'issue ;
//   - le lexique S2 : aucun mot interne à l'écran.

import { berceau, cliquer, ecouter, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

const stockage = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
};
globalThis.localStorage = stockage();
globalThis.sessionStorage = stockage();

const S = await import("../../mcp_gateway/atelier/web/js/state.js");
const { createAssistantView, createAssistantActions, LIBELLES } = await import(
  "../../mcp_gateway/atelier/web/js/views/assistant.js"
);
const { carteDAction, createCartesActions, oublierLesIssues } = await import(
  "../../mcp_gateway/atelier/web/js/views/assistant-cartes.js"
);
const rendu = await import("../../mcp_gateway/atelier/web/js/ui/message-render.js");

const MOTS_INTERNES = ["artefact", "MCP", "jeton", "composition", "gabarit", "extension", "production"];

// ── L'espace Assistant dans l'état ─────────────────────────────────────
{
  const state = S.createState();
  egal(state.espace, "projets", "on arrive dans les projets");
  S.setView(state, "assistant");
  egal(state.view, "code", "l'Assistant emprunte l'écran des conversations");
  verifier(S.estAssistant(state), "et c'est bien l'Assistant");
  egal(S.vueAffichee(state), "assistant", "la navigation montre l'onglet Assistant");

  S.setSessionId(state, "a-1");
  S.setMessages(state, [{ role: "user", text: "bonjour" }]);
  S.setView(state, "assistant");
  egal(state.sessionId, "a-1", "rester dans l'Assistant garde le fil");
  S.setView(state, "code");
  egal(state.sessionId, null, "passer aux projets ne garde pas le fil de l'Assistant");
  egal(state.messages.length, 0, "ni ses messages");
  verifier(!S.estAssistant(state), "on est dans les projets");
  S.setView(state, "journal");
  egal(S.vueAffichee(state), "journal", "les autres vues restent ce qu'elles sont");

  state.meta = { assistant_slug: "wikichat-memory" };
  state.sessions = [
    { session_id: "a-1", kind: "assistant", slug: "wikichat-memory", state: "idle", title: "Point du lundi" },
    { session_id: "c-1", kind: "code", slug: "alpha", state: "idle", title: "Correction" },
    { session_id: "a-2", kind: "assistant", slug: "wikichat-memory", state: "archived", title: "Rangée" },
  ];
  egal(S.assistantSessions(state).map((s) => s.session_id), ["a-1"], "ses conversations seulement, sans les rangées");
}

// ── La vue d'arrivée : le réglage est désactivé par défaut ─────────────
{
  egal(S.vueDArrivee("", { ui: {} }), "code", "sans réglage, l'Atelier s'ouvre sur les projets");
  egal(S.vueDArrivee("", { ui: { accueil_assistant: true } }), "assistant", "avec le réglage, sur l'Assistant");
  egal(S.vueDArrivee("?view=journal", { ui: { accueil_assistant: true } }), "journal", "l'adresse l'emporte");
  egal(S.vueDArrivee("?session=c-1", { ui: { accueil_assistant: true } }), "code", "un lien vers une conversation aussi");
}

// ── La colonne de gauche ───────────────────────────────────────────────
{
  const arbre = berceau();
  arbre.id = "project-tree";
  document.body.appendChild(arbre);
  const state = S.createState();
  state.meta = { assistant_slug: "wikichat-memory", ui: {} };
  state.sessions = [
    { session_id: "a-1", kind: "assistant", slug: "wikichat-memory", state: "running", title: "Point du lundi", turns: 3 },
    { session_id: "c-1", kind: "code", slug: "alpha", state: "idle", title: "Correction du projet" },
  ];
  S.setView(state, "assistant");
  const appels = [];
  const vue = createAssistantView({
    state,
    render: () => {},
    actions: {
      selectSession: (id) => appels.push(["ouvrir", id]),
      nouvelle: () => appels.push(["nouvelle"]),
      reglerAccueil: (actif) => appels.push(["reglage", actif]),
    },
  });
  vue.render();
  porte(texte(arbre), "Point du lundi", "sa conversation est listée");
  nePorte(texte(arbre), "Correction du projet", "pas celle d'un projet");
  porte(texte(arbre), LIBELLES.reglage, "le réglage d'accueil est là");
  const reglage = arbre.querySelector("input");
  verifier(reglage && reglage.checked === false, "et il est décoché par défaut");
  cliquer(arbre.querySelector("#assistant-nouvelle"));
  cliquer(arbre.querySelector(".session-btn"));
  reglage.checked = true;
  reglage.dispatchEvent(new CustomEvent("change", { bubbles: true }));
  egal(appels, [["nouvelle"], ["ouvrir", "a-1"], ["reglage", true]], "chaque geste appelle son action");
  for (const mot of MOTS_INTERNES) {
    nePorte(Object.values(LIBELLES).join(" "), mot, `lexique S2 : « ${mot} » n'apparaît pas`);
  }
  arbre.remove();
}

// ── Le réglage, par le service ─────────────────────────────────────────
{
  const state = S.createState();
  state.meta = { ui: {} };
  let recu = null;
  const actions = createAssistantActions({
    state,
    render: () => {},
    writeQuery: () => {},
    api: { reglerAccueilAssistant: async (actif) => ((recu = actif), { accueil_assistant: actif }) },
  });
  await actions.reglerAccueil(true);
  egal(recu, true, "le réglage part au service");
  egal(state.meta.ui.accueil_assistant, true, "et l'état le retient");
  actions.nouvelle();
  verifier(S.estAssistant(state) && state.sessionId === null, "« Nouvelle conversation » ouvre un fil vide de l'Assistant");
}

// ── La carte d'une action faite : « Voir » et « Annuler » ──────────────
{
  oublierLesIssues();
  egal(rendu.carteDAction, carteDAction, "le fil rend les cartes par ce module");
  const sortie = JSON.stringify({
    projet: { slug: "carte" },
    carte: {
      titre: "Projet créé",
      resume: "Carte logements",
      voir: { libelle: "Voir", lien: "/?slug=carte" },
      annuler: { libelle: "Annuler", commande: "atelier_annuler", arguments: { action: "20260926-abc" }, inverse: "atelier_projet_ranger" },
      action: "20260926-abc",
    },
  });
  const fil = berceau();
  const carte = carteDAction(sortie);
  fil.appendChild(carte);
  porte(texte(carte), "Projet créé", "le titre de la commande");
  egal(carte.querySelectorAll("a").length, 1, "« Voir »");
  const annuler = carte.querySelector(".msg-carte-annuler");
  verifier(!!annuler && texte(annuler) === "Annuler", "« Annuler »");
  const recus = ecouter(fil, "atelier:carte-annuler");
  cliquer(annuler);
  egal(recus.length, 1, "le bouton annonce, il n'appelle rien");
  egal(recus[0]?.detail, { action: "20260926-abc", commande: "atelier_annuler", arguments: { action: "20260926-abc" } }, "avec l'action à défaire");

  const sansInverse = carteDAction({ carte: { titre: "Arrêté", action: "x-1" } });
  egal(sansInverse.querySelectorAll(".msg-carte-annuler").length, 0, "pas d'« Annuler » sans inverse");
  egal(carteDAction({ carte: { titre: "Vue", voir: { lien: "javascript:alert(1)" } } }).querySelectorAll("a").length, 0, "jamais un lien javascript:");
}

// ── L'aperçu d'une commande engageante : « Oui » ───────────────────────
{
  oublierLesIssues();
  const apercu = {
    confirmation_requise: true,
    commande: "atelier_lancer_agent",
    classe: "engageante",
    apercu: { projet: "alpha", duree_s: 600, mode: "acceptEdits", message: "Objectif : corriger le test." },
    confirmation: "jeton-123",
  };
  const fil = berceau();
  const carte = carteDAction(JSON.stringify(apercu));
  fil.appendChild(carte);
  porte(texte(carte), "Confier ce travail à un agent", "l'aperçu dit ce qui est demandé, avec les mots de l'écran");
  porte(texte(carte), "Rien n’est fait", "et que rien n'est fait");
  porte(texte(carte), "10 min", "la durée se lit");
  nePorte(texte(carte), "jeton-123", "le jeton n'est pas affiché");
  nePorte(texte(carte), "atelier_lancer_agent", "ni le nom de la commande");
  const oui = carte.querySelector(".msg-carte-oui");
  verifier(!!oui, "« Oui »");
  const recus = ecouter(fil, "atelier:carte-oui");
  cliquer(oui);
  egal(recus[0]?.detail, { jeton: "jeton-123", commande: "atelier_lancer_agent" }, "le « Oui » porte le jeton");

  const refus = carteDAction({ ...apercu, apercu: { refus: "projet inconnu : beta" } });
  egal(refus.querySelectorAll(".msg-carte-oui").length, 0, "un aperçu qui refuse n'offre pas « Oui »");
  porte(texte(refus), "projet inconnu : beta", "et dit pourquoi");
}

// ── Le contrôleur : au nom de la personne, et la carte garde l'issue ───
{
  oublierLesIssues();
  const fil = berceau();
  const appels = [];
  const erreurs = [];
  const cartes = createCartesActions({
    api: {
      executerCommande: async (nom, args) => {
        appels.push([nom, args]);
        return { statut: "fait" };
      },
      confirmerCommande: async (jeton) => {
        appels.push(["confirmer", jeton]);
        return { statut: "fait", resultat: { carte: { titre: "Agent lancé", resume: "dans alpha", voir: { lien: "/?session=s-9" } } } };
      },
    },
    cible: fil,
    racine: () => fil,
    erreur: (m) => erreurs.push(m),
  });
  cartes.bind();

  const faite = carteDAction({ carte: { titre: "Projet créé", action: "act-1", annuler: { commande: "atelier_annuler", arguments: { action: "act-1" } } } });
  fil.appendChild(faite);
  cliquer(faite.querySelector(".msg-carte-annuler"));
  await new Promise((r) => setTimeout(r, 0));
  egal(appels[0], ["atelier_annuler", { action: "act-1" }], "« Annuler » passe par la commande d'annulation");
  porte(texte(faite), "Annulé", "la carte le dit, sans recharger le fil");
  egal(faite.querySelectorAll(".msg-carte-annuler").length, 0, "et n'offre plus « Annuler »");
  const redessinee = carteDAction({ carte: { titre: "Projet créé", action: "act-1", annuler: { commande: "atelier_annuler", arguments: { action: "act-1" } } } });
  porte(texte(redessinee), "Annulé", "un fil redessiné garde l'issue");

  const apercu = carteDAction({ confirmation_requise: true, commande: "atelier_lancer_agent", apercu: { projet: "alpha" }, confirmation: "j-2" });
  fil.appendChild(apercu);
  cliquer(apercu.querySelector(".msg-carte-oui"));
  await new Promise((r) => setTimeout(r, 0));
  egal(appels[1], ["confirmer", "j-2"], "« Oui » confirme l'aperçu au nom de la personne");
  porte(texte(apercu), "Agent lancé", "la carte de l'action faite apparaît sous l'aperçu");
  egal(apercu.querySelectorAll(".msg-carte-oui").length, 0, "« Oui » ne se clique qu'une fois");
  egal(erreurs, [], "aucune erreur");
}

bilan("assistant");
