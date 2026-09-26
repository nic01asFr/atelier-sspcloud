// Agents lancés et processus vivants (équipe L, branche v2-lancements),
// écrits contre le contrat avec de fausses routes :
//   - `GET /v1/lancements` : la vue Agents montre « En cours et récents »,
//     l'origine en mots, le projet, l'état, la durée, la branche ; « Arrêter »
//     tant qu'un agent tourne ; « Voir sa proposition » pour un réparateur ;
//   - la route absente (branche non fusionnée) se dit, sans casser la vue ;
//   - `GET /v1/sessions/{id}/processus` : la note près du sélecteur de mode,
//     et l'écart quand l'onglet VS Code vivant est plus permissif.

import { cliquer, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

const stockage = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
};
globalThis.localStorage = stockage();
globalThis.sessionStorage = stockage();

const S = await import("../../mcp_gateway/atelier/web/js/state.js");
const { libelleOrigine, dureeHumaine, listeLancements, trierLancements } = await import(
  "../../mcp_gateway/atelier/web/js/views/lancements.js"
);
const { createAutomatesActions } = await import("../../mcp_gateway/atelier/web/js/controllers/automates.js");
const { createAgentView } = await import("../../mcp_gateway/atelier/web/js/views/agent.js");
const { noteDuMode, rendreNoteDuMode, plusPermissif } = await import("../../mcp_gateway/atelier/web/js/ui/mode-processus.js");

const MAINTENANT = Date.parse("2026-09-26T10:00:00Z");

function bouton(noeud, libelle) {
  return noeud.querySelectorAll("button").find((b) => texte(b) === libelle) || null;
}

const LANCEMENTS = {
  lancements: [
    { id: "lc-20260926-00000001", origine: "wikichat:trigger:evt-wake-any:mention", projet: "carte", etat: "fini", cree_le: "2026-09-26T08:00:00Z", fini_le: "2026-09-26T08:03:12Z", conversation: "s-1" },
    { id: "lc-20260926-00000002", origine: "gardien:sante.ci-main", projet: "atelier", etat: "fini", cree_le: "2026-09-26T09:00:00Z", fini_le: "2026-09-26T09:20:00Z", branche: "gardien/sante/ci-main", reparation: { resume: "la CI de main est rouge" }, proposition: "av-20260926-abcd", conversation: "s-2" },
    { id: "lc-20260926-00000003", origine: "wikichat:routine:revue-plan", projet: "carte", etat: "en_cours", cree_le: "2026-09-26T09:55:00Z", conversation: "s-3" },
    { id: "lc-20260926-00000004", origine: "wikichat:trigger:veille-depots-cron", projet: "veille", etat: "echec", cree_le: "2026-09-26T07:00:00Z", fini_le: "2026-09-26T07:00:30Z", erreur: "plafond du jour atteint" },
  ],
  nombre: 4,
};

// ── Les mots ───────────────────────────────────────────────────────────
{
  egal(libelleOrigine("wikichat:trigger:evt-wake-any:mention"), "Réveil sur mention", "un réveil");
  egal(libelleOrigine("wikichat:trigger:veille-depots-cron"), "Tâche automatique « veille-depots-cron »", "une tâche automatique");
  egal(libelleOrigine("wikichat:routine:revue-plan"), "Tâche en plusieurs étapes « revue-plan »", "une routine, en mots");
  egal(libelleOrigine("routine:revue-plan"), "Tâche en plusieurs étapes « revue-plan »", "une routine sans préfixe");
  egal(libelleOrigine("gardien:sante.ci-main"), "Gardien réparateur (« Les tests de la version principale passent »)", "un réparateur");
  egal(dureeHumaine("2026-09-26T08:00:00Z", "2026-09-26T08:03:12Z"), "3 min 12 s", "une durée finie");
  egal(dureeHumaine("2026-09-26T09:55:00Z", "", MAINTENANT), "5 min 00 s", "une durée en cours");
  egal(dureeHumaine("2026-09-26T07:00:00Z", "2026-09-26T08:04:00Z"), "1 h 04", "plus d'une heure");
  egal(trierLancements(LANCEMENTS.lancements).map((l) => l.id.slice(-1)), ["3", "2", "1", "4"], "en cours d'abord, puis les plus récents");
}

// ── La liste : états, branche, Arrêter, proposition ────────────────────
{
  const appels = [];
  const actions = {
    arreter: (id) => appels.push(["arreter", id]),
    ouvrirProposition: (id) => appels.push(["proposition", id]),
    ouvrirConversation: (p, id) => appels.push(["conversation", p, id]),
  };
  const c = document.createElement("div");
  listeLancements(c, LANCEMENTS, { actions, maintenant: MAINTENANT });
  const t = texte(c);
  porte(t, "Réveil sur mention", "l'origine en mots");
  porte(t, "projet carte", "le projet");
  porte(t, "durée 3 min 12 s", "la durée d'un agent fini");
  porte(t, "depuis 5 min 00 s", "la durée d'un agent en cours");
  porte(t, "branche gardien/sante/ci-main", "la branche d'un réparateur");
  porte(t, "Constat : la CI de main est rouge", "le constat qui l'a fait naître");
  porte(t, "Échec", "un échec se lit");
  porte(t, "plafond du jour atteint", "et sa raison");
  for (const mot of ["trigger", "routine", "wikichat:"]) nePorte(t, mot, `lexique : pas de « ${mot} »`);

  const ligne = (id) => c.querySelectorAll("li").find((li) => li.dataset.lancement === id);
  const enCours = ligne("lc-20260926-00000003");
  cliquer(bouton(enCours, "Arrêter"));
  egal(appels.at(-1), ["arreter", "lc-20260926-00000003"], "Arrêter un agent en cours");
  verifier(!bouton(ligne("lc-20260926-00000001"), "Arrêter"), "un agent fini ne s'arrête plus");
  cliquer(bouton(ligne("lc-20260926-00000002"), "Voir sa proposition"));
  egal(appels.at(-1), ["proposition", "av-20260926-abcd"], "un réparateur mène à sa proposition");
  verifier(!bouton(ligne("lc-20260926-00000001"), "Voir sa proposition"), "pas de lien sans proposition");
  cliquer(bouton(ligne("lc-20260926-00000001"), "Ouvrir"));
  egal(appels.at(-1), ["conversation", "carte", "s-1"], "ouvrir la conversation de l'agent");

  listeLancements(c, { lancements: [], absent: true }, { actions });
  porte(texte(c), "pas encore servis ici", "la route absente se dit");
  listeLancements(c, { lancements: [] }, { actions });
  porte(texte(c), "Aucun agent lancé récemment", "rien de lancé se dit");
}

// ── Le contrôleur : lire, arrêter avec confirmation ────────────────────
{
  const state = S.createState();
  state.token = "session";
  const appels = [];
  const api = {
    getGardiens: async () => ({ joignable: true, gardiens: [] }),
    getAutomates: async () => ({ automates: [], sources: {} }),
    listerLancements: async (f) => (appels.push(["lister", f]), LANCEMENTS),
    arreterLancement: async (id) => (appels.push(["arreter", id]), { lancement: { id, etat: "arrete" } }),
  };
  let accord = false;
  const a = createAutomatesActions({ state, api, render: () => {}, confirmer: () => accord });
  await a.rafraichir();
  egal(state.lancements.nombre, 4, "les lancements se lisent avec les gardiens");
  await a.arreter("lc-20260926-00000003");
  verifier(!appels.some((x) => x[0] === "arreter"), "arrêt refusé à la confirmation : rien ne part");
  accord = true;
  await a.arreter("lc-20260926-00000003");
  egal(appels.find((x) => x[0] === "arreter"), ["arreter", "lc-20260926-00000003"], "arrêt confirmé");
  egal(state.lancementEnCours, "", "le bouton se libère");

  // La vue Agents a la section.
  for (const id of ["agent-list", "agent-detail-body", "view-agent", "btn-shell-back-agent", "btn-shell-forward-agent", "btn-agent-to-home", "context-menu"]) {
    const n = document.createElement("div");
    n.id = id;
    document.body.appendChild(n);
  }
  state.view = "agent";
  state.piloteOverview = { agents: [], daemon: {}, system_agents: [] };
  const vue = createAgentView({ state, actions: {}, automates: a });
  vue.renderAgent();
  const accueil = document.getElementById("agent-detail-body");
  porte(texte(accueil), "En cours et récents", "la section est sur l'accueil de la vue Agents");
  porte(texte(accueil), "Gardien réparateur", "avec ses lignes");
}

// ── Le mode : note et écart, près du sélecteur ─────────────────────────
{
  verifier(plusPermissif("bypassPermissions", "default"), "sans garde-fou est plus permissif que demande");
  verifier(!plusPermissif("plan", "acceptEdits"), "plan ne l'est pas");
  egal(noteDuMode({ vscode_vivant: false, processus: [] }), null, "sans onglet VS Code, rien à dire");
  const note = noteDuMode({
    vscode_vivant: true,
    note: "Un onglet VS Code de cette conversation est ouvert : un changement de mode s'applique à la prochaine ouverture dans VS Code.",
  });
  porte(note.texte, "prochaine ouverture dans VS Code", "la note du service");
  verifier(!note.alerte, "sans écart, pas d'alerte");
  const ecart = noteDuMode({ vscode_vivant: true, note: "Un onglet est ouvert.", ecart: { vivant: "bypassPermissions", choisi: "default" } });
  porte(ecart.texte, "« Sans garde-fou », plus permissif que « Demande »", "l'écart dit en mots");
  verifier(ecart.alerte, "un écart plus permissif se marque");
  const doux = noteDuMode({ vscode_vivant: true, note: "Un onglet est ouvert.", ecart: { vivant: "plan", choisi: "acceptEdits" } });
  verifier(!doux.alerte, "un onglet plus prudent n'alerte pas");
  nePorte(ecart.texte, "bypassPermissions", "pas de nom interne");

  const el = document.createElement("p");
  rendreNoteDuMode(el, ecart);
  verifier(!el.hidden && el.classList.contains("composer-mode-note-alerte"), "la note se montre, marquée");
  rendreNoteDuMode(el, null);
  verifier(el.hidden && el.textContent === "", "sans note, rien ne reste");
}

bilan("lancements");
