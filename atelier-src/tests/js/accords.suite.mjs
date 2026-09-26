// Les accords réservés à la personne (équipe K, branche v2-creations) :
// activer un agent (`atelier_agent_activer`), accorder un secret à un
// connecteur (`atelier_connecteur_accorder`).
//
// Écrit contre le contrat, avec une fausse route :
//   - un agent désactivé montre « Activer », qui appelle la commande réservée ;
//     « Désactiver » appelle son inverse ; un refus du service se lit ;
//   - dans la liste des tâches automatiques, « Activer » sur un agent du
//     Pilote passe par la même commande, pas par la bascule brute ;
//   - « Accorder un secret » liste des noms de fichiers, jamais de valeurs,
//     et envoie nom, champ (headers.<Nom> ou env.<NOM>) et secret ;
//   - une proposition « À valider » dont l'action est l'une d'elles dit ce
//     qu'elle fera et s'accepte par le même chemin que les autres.

import { cliquer, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

const stockage = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
};
globalThis.localStorage = stockage();
globalThis.sessionStorage = stockage();

const S = await import("../../mcp_gateway/atelier/web/js/state.js");
const { createAccordsActions, champsPourAccorder, argumentsDAccord, blocDuConnecteur } = await import(
  "../../mcp_gateway/atelier/web/js/controllers/accords.js"
);
const { createAutomatesActions } = await import("../../mcp_gateway/atelier/web/js/controllers/automates.js");
const { createAgentView } = await import("../../mcp_gateway/atelier/web/js/views/agent.js");
const { ceQueFaitAccepter } = await import("../../mcp_gateway/atelier/web/js/views/a-valider.js");
const { phraseDeLEvenement } = await import("../../mcp_gateway/atelier/web/js/views/journal.js");

async function attendre() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

/** La fausse route `POST /v1/commandes/<nom>` : réservées acceptées, le reste inconnu. */
function fausseRoute() {
  const appels = [];
  return {
    appels,
    executerCommande: async (nom, args) => {
      appels.push([nom, args]);
      if (!["atelier_agent_activer", "atelier_agent_desactiver", "atelier_connecteur_accorder"].includes(nom)) {
        const e = new Error(`Cette action n’est pas encore disponible ici (${nom}).`);
        e.status = 404;
        throw e;
      }
      if (nom === "atelier_agent_activer" && args.agent === "sans-budget") {
        const e = new Error("sans-budget n'a pas de budget lisible : fixez-le avant de l'activer");
        e.status = 403;
        throw e;
      }
      return { statut: "fait", resultat: {} };
    },
    listerNomsDesSecrets: async () => ({ noms: [{ nom: "grist_api_key", protege: true }, { nom: "n8n_jeton", protege: false }] }),
    agirSurAutomate: async (id, g) => (appels.push(["bascule", id, g]), {}),
    getGardiens: async () => ({ joignable: true, gardiens: [] }),
    getAutomates: async () => ({ automates: [], sources: { pilote: true } }),
  };
}

// ── Activer un agent désactivé ─────────────────────────────────────────
{
  for (const id of ["agent-list", "agent-detail-body", "view-agent", "btn-shell-back-agent", "btn-shell-forward-agent", "btn-agent-to-home", "context-menu"]) {
    const n = document.createElement("div");
    n.id = id;
    document.body.appendChild(n);
  }
  const state = S.createState();
  state.token = "session";
  state.view = "agent";
  const agent = { id: "veille", name: "Veille", enabled: false, cron: "0 8 * * *", queue: [], scope: {}, memory: {} };
  state.piloteOverview = { agents: [agent], daemon: {}, system_agents: [] };
  state.selectedAgentId = "veille";
  state.agentPanel = "detail";
  state.agentTab = "settings";

  const route = fausseRoute();
  let relu = 0;
  const accords = createAccordsActions({ state, api: route, render: () => {}, openModal: () => {}, apresAgent: async () => { relu += 1; } });
  const actions = {
    activer: (id) => accords.activerAgent(id),
    desactiver: (id) => accords.desactiverAgent(id),
    setTab: () => {},
    fire: () => {},
    openEdit: () => {},
    remove: () => {},
    loadTranscript: () => {},
    resume: () => {},
  };
  const vue = createAgentView({ state, actions, automates: {} });
  vue.renderAgent();
  const corps = document.getElementById("agent-detail-body");
  porte(texte(corps), "Cet agent est désactivé", "un agent désactivé le dit en tête de sa fiche");
  const boutons = corps.querySelectorAll("button").filter((b) => texte(b) === "Activer");
  verifier(boutons.length >= 1, "un bouton Activer");
  porte(boutons[0].title, "Réservé à vous", "Activer dit qu'il est réservé à la personne");
  cliquer(boutons[0]);
  await attendre();
  egal(route.appels.at(-1), ["atelier_agent_activer", { agent: "veille" }], "Activer appelle la commande réservée");
  egal(relu, 1, "la liste se relit après");

  agent.enabled = true;
  vue.renderAgent();
  nePorte(texte(corps), "Cet agent est désactivé", "un agent actif n'a pas de bandeau");
  cliquer(corps.querySelectorAll("button").find((b) => texte(b) === "Désactiver"));
  await attendre();
  egal(route.appels.at(-1), ["atelier_agent_desactiver", { agent: "veille" }], "Désactiver appelle son inverse");
  verifier(!route.appels.some((a) => a[0] === "bascule"), "jamais la bascule brute du Pilote");

  await accords.activerAgent("sans-budget");
  porte(state.error, "pas de budget lisible", "le refus du service se lit");
}

// ── Activer depuis la liste des tâches automatiques ────────────────────
{
  const state = S.createState();
  state.token = "session";
  state.automates = {
    automates: [
      { id: "trigger.veille", genre: "trigger", agent: true, gestes: ["activer"] },
      { id: "trigger.evt-wake-any", genre: "trigger", gestes: ["activer"] },
    ],
    sources: { pilote: true },
  };
  const route = fausseRoute();
  const a = createAutomatesActions({ state, api: route, render: () => {} });
  await a.agir("trigger.veille", "activer");
  egal(route.appels[0], ["atelier_agent_activer", { agent: "veille" }], "un agent du Pilote s'active par la commande réservée");
  await a.agir("trigger.evt-wake-any", "activer");
  egal(route.appels.at(-1), ["bascule", "trigger.evt-wake-any", "activer"], "une tâche de la plateforme passe par le relais de l'Atelier");
}

// ── Accorder un secret : des noms, jamais des valeurs ──────────────────
{
  const distant = { id: "grist", name: "Grist", config: { url: "https://grist.example/mcp" } };
  const local = { id: "outil", config: { command: "node" } };
  egal(blocDuConnecteur(distant), "headers", "un service distant reçoit un en-tête");
  egal(blocDuConnecteur(local), "env", "un serveur local reçoit une variable");

  const champs = champsPourAccorder(distant, [{ nom: "grist_api_key", protege: true }, { nom: "n8n_jeton", protege: false }]);
  const secret = champs.find((c) => c.name === "secret");
  egal(secret.options.map((o) => o.value), ["", "grist_api_key", "n8n_jeton"], "la liste propose les noms de fichiers");
  porte(secret.options[2].label, "chmod 600", "un fichier trop ouvert est signalé avant l'envoi");
  egal(champs.find((c) => c.name === "cle").value, "Authorization", "l'en-tête par défaut");

  egal(
    argumentsDAccord(distant, { secret: "grist_api_key", cle: "Authorization", schema: "Bearer" }),
    { nom: "grist", champ: "headers.Authorization", secret: "grist_api_key", schema: "Bearer" },
    "les arguments du contrat"
  );
  egal(argumentsDAccord(local, { secret: "cle_outil", cle: "API_KEY", schema: "" }), { nom: "outil", champ: "env.API_KEY", secret: "cle_outil" }, "une variable, sans préfixe");
  let refus = "";
  try {
    argumentsDAccord(distant, { secret: "", cle: "Authorization" });
  } catch (e) {
    refus = e.message;
  }
  egal(refus, "Choisissez un secret.", "sans secret, rien ne part");

  const state = S.createState();
  state.token = "session";
  const route = fausseRoute();
  let ouverte = null;
  let relu = 0;
  const accords = createAccordsActions({
    state,
    api: route,
    render: () => {},
    openModal: (_s, opts) => (ouverte = opts),
    apresConnecteur: async () => { relu += 1; },
  });
  await accords.accorderSecret(distant);
  verifier(ouverte, "la fenêtre s'ouvre");
  porte(ouverte.title, "Grist", "elle nomme le connecteur");
  egal(ouverte.fields.find((c) => c.name === "secret").type, "select", "le secret se choisit dans une liste, il ne se tape pas");
  verifier(!ouverte.fields.some((c) => c.type === "password" || c.type === "textarea"), "aucun champ où coller une valeur");
  await ouverte.onSubmit({ secret: "grist_api_key", cle: "Authorization", schema: "Bearer" });
  egal(route.appels.at(-1), ["atelier_connecteur_accorder", { nom: "grist", champ: "headers.Authorization", secret: "grist_api_key", schema: "Bearer" }], "Accorder appelle la commande réservée");
  egal(relu, 1, "les connecteurs se relisent");
}

// ── « À valider » et le journal parlent de ces commandes ───────────────
{
  egal(
    ceQueFaitAccepter({ source: "agent", action: { commande: "atelier_agent_activer", arguments: { agent: "veille" } } }),
    "Accepter va activer l’agent (agent : veille).",
    "une proposition d'activer un agent dit ce qu'elle fera"
  );
  egal(
    ceQueFaitAccepter({ source: "agent", action: { commande: "atelier_connecteur_accorder", arguments: { nom: "grist", champ: "headers.Authorization", secret: "grist_api_key" } } }),
    "Accepter va accorder un secret au connecteur (nom : grist, champ : headers.Authorization, secret : grist_api_key).",
    "une proposition d'accorder un secret nomme le fichier, pas la valeur"
  );
  egal(
    phraseDeLEvenement({ source: "commande", acteur: "conversation:x", objet: { type: "agent", id: "veille" }, action: { commande: "atelier_agent_activer" }, resultat: "refus" }).texte,
    "Une conversation a voulu activer l’agent « veille »",
    "un modèle qui tente d'activer : refusé, et le journal le dit"
  );
}

bilan("accords");
