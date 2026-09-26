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
const { carteDAction, createCartesActions, oublierLesIssues, affirmeUnResultat, nonVerifie, marquerNonVerifie } = await import(
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

  const avecPreuve = carteDAction({
    carte: {
      titre: "Agent réglé",
      preuve: { actif: false, horaire: "à la demande", pool: { present: true } },
    },
  });
  const preuve = avecPreuve.querySelector(".msg-carte-preuve");
  porte(texte(preuve.children[0]), "Actif : non.", "une preuve booléenne se lit comme une phrase");
  porte(texte(preuve.children[1]), "Horaire : à la demande.", "une valeur se lit sans syntaxe JSON");
  porte(texte(preuve.children[2]), "Pool · Présent : oui.", "une preuve imbriquée garde un chemin lisible");
  const technique = preuve.querySelector(".msg-carte-preuve-technique");
  verifier(!!technique && technique.open === false, "le JSON de preuve reste replié sous « Détails techniques »");
  porte(texte(technique.querySelector("summary")), "Détails techniques", "le détail brut est nommé");
  porte(texte(technique.querySelector("pre")), '"actif": false', "le JSON exact reste disponible pour diagnostiquer");
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

// ── « Non vérifié » : une affirmation sans carte dans le tour ──────────
{
  for (const t of ["Lien créé : Lecteur Grist → BigStarter. Vérifié par la carte.", "C’est fait.", "Le projet est créé.", "J’ai lancé l’agent."]) {
    verifier(affirmeUnResultat(t), `affirme un résultat : ${t}`);
  }
  for (const t of ["Rien n’est fait tant que vous n’avez pas dit oui.", "Refusé : en attente de votre Oui.", "Non vérifié : 3 communes.",
                   "Voici l’aperçu du projet Budget 2027.", "Quand ce sera créé, je vous préviens.", "Je le lance dès que vous dites oui."]) {
    verifier(!affirmeUnResultat(t), `n'affirme rien : ${t}`);
  }
  const carte = JSON.stringify({ carte: { titre: "Projets reliés", action: "a-1" } });
  const refus = "Claude requested permissions to use mcp__atelier__atelier_projets_lier, but you haven't granted it yet.";
  const invente = [
    { role: "user", text: "Relie X et Y" },
    { role: "assistant", text: "Lien créé : X → Y. Vérifié.", blocks: [{ type: "tool", name: "mcp__atelier__atelier_projets_lier", output: refus, status: "denied" }] },
  ];
  verifier(nonVerifie(invente, 1), "après un refus, « lien créé » est non vérifié (l'essai d4-a du pod)");
  const prouve = [
    { role: "user", text: "Relie X et Y" },
    { role: "assistant", text: "", blocks: [{ type: "tool", output: carte }] },
    { role: "assistant", text: "Lien créé : X → Y." },
  ];
  verifier(!nonVerifie(prouve, 2), "une carte plus tôt dans le même tour vaut preuve");
  const tourSuivant = [...prouve, { role: "user", text: "Et Z ?" }, { role: "assistant", text: "C’est fait." }];
  verifier(nonVerifie(tourSuivant, 4), "la carte d'un tour précédent ne prouve rien pour celui-ci");
  verifier(!nonVerifie([{ role: "user" }, { role: "assistant", text: "C’est fait.", streaming: true }], 1), "un message en cours n'est pas jugé");

  const noeud = berceau();
  marquerNonVerifie(noeud, true);
  marquerNonVerifie(noeud, true);
  egal(noeud.querySelectorAll(".msg-non-verifie").length, 1, "une seule marque, même redessiné");
  porte(texte(noeud), "non vérifié", "la marque se lit");
  marquerNonVerifie(noeud, false);
  egal(noeud.querySelectorAll(".msg-non-verifie").length, 0, "et s'enlève");
}

// ── Essais du 26/09 : résultats repliés dans le fil de l'Assistant ─────
//
// Le JSON brut d'`atelier_carte` s'affichait déplié dans le fil de
// l'Assistant. Code et l'Assistant partagent le rendu des outils : dans le
// fil de l'Assistant, le résultat est replié et la carte d'action reste
// visible ; en Code, un résultat court reste déplié, un long se replie.
{
  const { createCodeChatView } = await import("../../mcp_gateway/atelier/web/js/views/code-chat.js");
  globalThis.requestAnimationFrame = (f) => f();
  const fil = berceau();
  fil.id = "thread";
  document.body.appendChild(fil);
  const carteLongue = JSON.stringify({
    carte: { titre: "Projet créé", action: "x-2" },
    detail: "x".repeat(3000),
  });
  const outilDe = (id, output, name = "mcp__atelier__atelier_carte") => ({
    type: "tool", id, name, input: {}, output, status: "done",
  });
  const resultats = () =>
    fil.querySelectorAll(".msg-tool-section").filter((d) => d.querySelector("summary")?.textContent === "Résultat");

  const state = S.createState();
  state.meta = { assistant_slug: "wikichat-memory", ui: {} };
  S.setView(state, "assistant");
  S.setSessionId(state, "a-1");
  S.setMessages(state, [
    { role: "user", text: "Où en est Lecteur Grist ?" },
    { role: "assistant", text: "", blocks: [outilDe("t1", '{"forme": "projet"}'), outilDe("t2", carteLongue)] },
  ]);
  const vue = createCodeChatView({ state, render: () => {}, composerInput: null, actions: {} });
  const { poserReglagesDuFil } = await import("../../mcp_gateway/atelier/web/js/ui/etapes.js");
  // Par défaut, le brut reste dans « Voir les étapes », construit seulement
  // quand on déplie : rien n'est rendu, la carte d'action est là.
  poserReglagesDuFil({ raisonnement: false, actions: false });
  vue.renderThread();
  egal(resultats().length, 0, "par défaut, aucun résultat brut dans le fil");
  porte(texte(fil), "Projet créé", "la carte d'action se voit sans rien déplier");
  // « Montrer les actions et leurs résultats bruts » : les règles de repli
  // des résultats s'appliquent alors comme avant.
  poserReglagesDuFil({ actions: true });
  vue.renderThread();
  egal(resultats().length, 2, "deux résultats rendus");
  verifier(resultats().every((d) => d.open === false), "dans l'Assistant, tout résultat est replié, même court");
  porte(texte(fil), "Projet créé", "la carte d'action reste visible");

  S.setView(state, "code");
  S.setSessionId(state, "c-1");
  S.setMessages(state, [
    { role: "user", text: "Liste les fichiers" },
    {
      role: "assistant", text: "",
      blocks: [outilDe("c1", "trois fichiers", "Bash"), outilDe("c2", "ligne\n".repeat(200), "Bash")],
    },
  ]);
  vue.renderThread();
  egal(resultats().map((d) => d.open), [true, false], "en Code : court déplié, long replié");
  poserReglagesDuFil({ actions: false });
  fil.remove();
}

// ── Essais du 26/09 : le libellé de la colonne suit la vue ─────────────
{
  const { createCodeTreeView } = await import("../../mcp_gateway/atelier/web/js/views/code-tree.js");
  const arbre = berceau();
  arbre.id = "project-tree";
  arbre.setAttribute("aria-label", "Projets et conversations");
  document.body.appendChild(arbre);
  const state = S.createState();
  state.meta = { assistant_slug: "wikichat-memory", ui: {} };
  S.setView(state, "assistant");
  createAssistantView({ state, render: () => {}, actions: {} }).render();
  egal(arbre.getAttribute("aria-label"), "Conversations de l’Assistant", "dans l'Assistant");
  S.setView(state, "code");
  createCodeTreeView({ state, render: () => {}, writeQuery: () => {}, actions: {} }).renderProjectTree();
  egal(arbre.getAttribute("aria-label"), "Projets et conversations", "revenu en Code, le libellé suit la vue");
  arbre.remove();
}

bilan("assistant");
