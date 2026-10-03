import { messagePourUtilisateur } from "./ui/messages-erreur.js";
import { appliquerLesVerdicts, idDeLOutil, rattacherLeVerdict } from "./ui/verdict-decision.js";
/** État applicatif pur — pas de fetch, pas de DOM. */

// L'ancien emplacement de la clé propriétaire. On ne l'écrit plus jamais : le
// script de n'importe quelle page servie dans l'origine de l'Atelier la lisait
// là. On ne le lit plus que pour migrer — échanger la clé contre le cookie de
// session, puis l'effacer (voir `api.migrerAncienneCle`).
const KEY_OWNER_ANCIENNE = "atelier.ownerKey";
const KEY_EXPANDED = "atelier.expandedSlugs";

// Ce que vaut `state.token` quand l'interface est connectée. Ce n'est plus la
// clé : la session vit dans un cookie `HttpOnly` que ce script ne voit pas.
// Le champ garde son nom pour ne pas changer les cent appels qui le passent.
export const SESSION_OUVERTE = "session";

function turnsKey(sessionId) {
  return `atelier.turns.${sessionId}`;
}

/** La clé laissée par une version précédente de l'interface, s'il en reste une. */
export function lireAncienneCle() {
  try {
    return localStorage.getItem(KEY_OWNER_ANCIENNE) || "";
  } catch {
    return "";
  }
}

export function oublierAncienneCle() {
  try {
    localStorage.removeItem(KEY_OWNER_ANCIENNE);
  } catch {
    /* stockage indisponible : rien à effacer */
  }
}

export function loadExpandedSlugs() {
  try {
    const raw = localStorage.getItem(KEY_EXPANDED);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveExpandedSlugs(slugs) {
  localStorage.setItem(KEY_EXPANDED, JSON.stringify(slugs));
}

export function loadTurns(sessionId) {
  if (!sessionId) return [];
  try {
    const raw = sessionStorage.getItem(turnsKey(sessionId));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveTurns(sessionId, messages) {
  if (!sessionId) return;
  sessionStorage.setItem(turnsKey(sessionId), JSON.stringify(messages));
}

/** Vues shell Atelier — alignées avec atelier-wikichat-alignment.md */
export const VIEWS = ["code", "assistant", "connecteurs", "agent", "a-valider", "journal", "memoire"];

export function normalizeView(view) {
  const v = (view || "").trim().toLowerCase();
  return VIEWS.includes(v) ? v : "code";
}

export function createState() {
  return {
    // Montrer ce qui a été rangé : éteint par défaut, comme un tiroir fermé.
    montrerArchives: false,
    // Vide tant que la session n'est pas confirmée par le service (au
    // démarrage, `enterHub` le vérifie par le cookie) ; `SESSION_OUVERTE` ensuite.
    token: "",
    view: "code",
    // `projets` ou `assistant` : quel fil l'écran de conversation montre.
    espace: "projets",
    slug: "",
    sessionId: null,
    projects: [],
    sessions: [],
    expandedSlugs: new Set(loadExpandedSlugs()),
    messages: [],
    // La conversation dont le fil est en cours de lecture : le fil montre un
    // squelette plutôt que « aucun message » tant que le transcrit n'est pas là.
    chargementFil: null,
    // Ce qu'on a écrit pendant qu'un tour travaillait : déposé côté service,
    // pas encore parti. On le garde ici pour le montrer, et pour pouvoir le
    // retirer tant qu'il n'a pas quitté la file.
    enFile: [],
    // Ce que la page Connecteurs est en train de faire. Ajouter un service
    // suppose de le joindre et de lui demander ses outils : c'est long, et
    // rien ne le disait — on ne savait pas s'il était analysé ou ignoré.
    mcpTravail: "",
    mcpServers: {},
    mcpOverview: null,
    mcpProfiles: null,
    piloteOverview: null,
    selectedAgentId: null,
    // Les gardiens, un agent chacun (`GET /v1/gardiens`), et toutes les
    // tâches automatiques dans une liste (`GET /v1/automates`).
    gardiens: null,
    automates: null,
    selectedGardienId: null,
    // Un geste en cours sur un gardien ou une tâche : son id, pour griser.
    automateEnCours: "",
    // Les agents lancés par l'Atelier (`GET /v1/lancements`), et celui
    // qu'on est en train d'arrêter.
    lancements: null,
    lancementEnCours: "",
    // Ce que vaut le dernier changement de mode : `{sessionId, note}`.
    modeProcessus: null,
    // La file « À valider » : une seule, pour tout ce qui attend la personne.
    aValider: {
      statut: "en_attente",
      propositions: [],
      note: "",
      charge: false,
      ouverte: null,
      motifs: {},
      completes: {},
      enCours: "",
      erreur: "",
    },
    // Le nombre en attente, pour le badge de la navigation.
    aValiderCompte: 0,
    // Le journal unique, lu en langage humain.
    journal: {
      filtres: { projet: "", acteur: "", source: "" },
      evenements: [],
      charge: false,
      erreur: "",
    },
    selectedConnectorId: null,
    // Conversation neuve en cours de redaction :
    //   null   = aucune, la liste est a l'ecran
    //   ""     = nouvelle conversation, projet cree a l'envoi
    //   "slug" = nouvelle conversation dans ce projet
    pendingProjectSlug: null,
    // Projet dont le nom est en cours d'edition dans la liste laterale.
    editingProjectSlug: null,
    // Conversation dont le titre est en cours d'edition.
    editingSessionId: null,
    // Fil de l'agent ouvert : { agentId, turns, note, sessionId, at }
    agentTranscript: null,
    agentTranscriptBusy: false,
    connectorPanel: "home",
    // Brouillon du builder de compositions : nom, description, étapes.
    compositionDraft: null,
    // Résultat de la dernière exécution lancée depuis l'écran : on lançait
    // sans rien montrer d'autre qu'un mot d'état.
    compositionRun: null,
    // Composition ouverte dans l'onglet Connecteurs.
    compositions: [],
    // Les clients distants branchés sur cet Atelier (Claude et consorts).
    clientsDistants: [],
    toolsByService: [],
    selectedCompositionId: null,
    /** @type {"home" | "create" | "detail"} */
    agentPanel: "home",
    agentTab: "discussion",
    agentCreateForm: null,
    agentCreateBusy: false,
    agentCreateError: "",
    modelsCatalog: null,
    /** @type {Record<string, "list" | "detail">} */
    shellModeByView: {
      code: "list",
      assistant: "list",
      connecteurs: "detail",
      agent: "detail",
      "a-valider": "detail",
      journal: "detail",
      memoire: "detail",
    },
    sessionMcp: null,
    meta: {
      vscode_url: null,
      projects_root: "",
      assistant_slug: "wikichat-memory",
    },
    composerAttachments: [],
    busy: false,
    mcpOverlayBusy: false,
    error: "",
    contextMenu: null,
    modal: null,
  };
}

export function setMeta(state, meta) {
  state.meta = meta || {
    vscode_url: null,
    projects_root: "",
    assistant_slug: "wikichat-memory",
  };
}

/** Connecté ou non. Rien n'est écrit dans le navigateur : la session est un cookie. */
export function setToken(state, token) {
  state.token = token ? SESSION_OUVERTE : "";
}

export function setError(state, msg) {
  // Dite en français, avec quoi faire : les erreurs arrivent brutes de partout.
  state.error = messagePourUtilisateur(msg);
}

export function setBusy(state, busy) {
  state.busy = !!busy;
}

export function setMcpOverlayBusy(state, busy) {
  state.mcpOverlayBusy = !!busy;
}

/**
 * L'Assistant est un fil de conversation comme ceux des projets : il en
 * emprunte l'écran (fil, composeur, panneau), et `state.view` y vaut `code`.
 * Ce qui le distingue est l'espace : `assistant` ou `projets`. L'adresse, elle,
 * dit `?view=assistant` (voir `core/router.js` et `views/assistant.js`).
 */
export const ESPACE_ASSISTANT = "assistant";
export const ESPACE_PROJETS = "projets";

export function setView(state, view) {
  const v = normalizeView(view);
  const avant = state.espace || ESPACE_PROJETS;
  if (v === "assistant") {
    state.view = "code";
    state.espace = ESPACE_ASSISTANT;
  } else {
    if (v === "code") state.espace = ESPACE_PROJETS;
    state.view = v;
  }
  if (state.view === "code" && state.espace !== avant) {
    // Passer des projets à l'Assistant (ou l'inverse) ne garde pas le fil de
    // l'autre espace : il n'y a pas sa place.
    // Par `setSessionId` : « occupé » est celui de la conversation affichée.
    // Le laisser tel quel rendait l'Assistant muet (champ désactivé, « Arrêter »
    // affiché) quand on y passait pendant un tour d'une conversation de projet.
    setSessionId(state, null);
    state.messages = [];
    state.pendingProjectSlug = null;
    oublierLesChoixConnecteurs(state);
  }
}

export function estAssistant(state) {
  return state.view === "code" && state.espace === ESPACE_ASSISTANT;
}

/** La vue telle que la navigation la montre : `assistant` pour le fil de l'Assistant. */
export function vueAffichee(state) {
  return estAssistant(state) ? "assistant" : state.view;
}

/** Les conversations de l'Assistant, les plus récentes d'abord (le service les trie). */
export function assistantSessions(state) {
  return (state.sessions || []).filter(
    (s) => !isCodeSession(s, state) && (state.montrerArchives || s.state !== "archived")
  );
}

/**
 * La vue d'arrivée : celle de l'adresse, sinon l'Assistant si la personne a
 * choisi « Ouvrir l'Atelier sur l'Assistant » (désactivé par défaut, A-3).
 */
export function vueDArrivee(recherche, meta) {
  const q = new URLSearchParams(recherche || "");
  if (q.get("view") || q.get("session") || q.get("slug")) return normalizeView(q.get("view"));
  return meta?.ui?.accueil_assistant === true ? "assistant" : "code";
}

export function setSlug(state, slug) {
  state.slug = (slug || "").trim();
}

export function setModal(state, modal) {
  state.modal = modal || null;
}

export function assistantSlug(state) {
  return (state.meta?.assistant_slug || "wikichat-memory").trim();
}

export function isAssistantProject(project, state) {
  if (!project) return false;
  return project.kind === "assistant" || project.slug === assistantSlug(state);
}

export function isCodeProject(project, state) {
  return project && !isAssistantProject(project, state);
}

export function codeProjects(state) {
  return state.projects.filter((p) => isCodeProject(p, state));
}

export function isCodeSession(session, state) {
  if (!session) return false;
  if (session.kind === "assistant") return false;
  if (session.kind === "code") return true;
  return session.slug !== assistantSlug(state);
}

export function codeSessions(state) {
  return state.sessions.filter(
    (s) => isCodeSession(s, state) && (state.montrerArchives || s.state !== "archived")
  );
}

/** Montrer, ou non, ce qui a été rangé — projets comme conversations. */
export function setMontrerArchives(state, montrer) {
  state.montrerArchives = !!montrer;
}

export function setProjects(state, projects) {
  state.projects = projects || [];
}

export function setSessions(state, sessions) {
  state.sessions = sessions || [];
}

export function setMcpServers(state, servers) {
  state.mcpServers = servers || {};
}

export function setMcpOverview(state, overview) {
  state.mcpOverview = overview;
}

export function setPiloteOverview(state, overview) {
  state.piloteOverview = overview;
}

export function setSelectedAgentId(state, id) {
  state.selectedAgentId = id || null;
}

export function setGardiens(state, vue) {
  state.gardiens = vue || null;
}

export function setAutomates(state, liste) {
  state.automates = liste || null;
}

export function setSelectedGardienId(state, id) {
  state.selectedGardienId = id || null;
}

/** Fusionne dans l'état de l'écran « À valider ». */
export function patchAValider(state, partiel) {
  state.aValider = { ...state.aValider, ...(partiel || {}) };
}

export function setAValiderCompte(state, n) {
  state.aValiderCompte = Math.max(0, Number(n) || 0);
}

export function patchJournal(state, partiel) {
  state.journal = { ...state.journal, ...(partiel || {}) };
}

export function setAgentPanel(state, panel) {
  const p = (panel || "").toLowerCase();
  state.agentPanel = ["home", "create", "detail", "gardien"].includes(p) ? p : "home";
}

export function setAgentCreateForm(state, form) {
  state.agentCreateForm = form || null;
}

export function setAgentCreateBusy(state, busy) {
  state.agentCreateBusy = !!busy;
}

export function setAgentCreateError(state, msg) {
  state.agentCreateError = msg || "";
}

export function setModelsCatalog(state, catalog) {
  state.modelsCatalog = catalog || null;
}

export function setSelectedConnectorId(state, id) {
  state.selectedConnectorId = id || null;
}

export function setToolsByService(state, services) {
  state.toolsByService = Array.isArray(services) ? services : [];
}

export function setCompositions(state, liste) {
  state.compositions = Array.isArray(liste) ? liste : [];
}

export function setClientsDistants(state, liste) {
  state.clientsDistants = Array.isArray(liste) ? liste : [];
}

export function setSelectedCompositionId(state, id) {
  state.selectedCompositionId = id || null;
}

export function setCompositionRun(state, run) {
  state.compositionRun = run;
}

export function setCompositionDraft(state, draft) {
  state.compositionDraft = draft;
}

export function setConnectorPanel(state, panel) {
  const p = (panel || "").toLowerCase();
  state.connectorPanel = ["home", "new", "detail", "composer"].includes(p)
    ? p
    : "home";
}

export function setAgentTab(state, tab) {
  const t = (tab || "").toLowerCase();
  state.agentTab = ["discussion", "queue", "settings"].includes(t)
    ? t
    : "discussion";
}

export function getShellMode(state, view) {
  const v = normalizeView(view || state.view);
  return state.shellModeByView[v] || "list";
}

export function setShellMode(state, view, mode) {
  const v = normalizeView(view || state.view);
  state.shellModeByView[v] = mode === "detail" ? "detail" : "list";
}

/** Sync list/detail from selection for the current view. */
export function syncShellModeFromSelection(state) {
  if (state.view === "code") {
    const enPanneau = !!state.sessionId || state.pendingProjectSlug != null;
    setShellMode(state, "code", enPanneau ? "detail" : "list");
  } else if (state.view === "agent") {
    if (
      state.agentPanel === "create" ||
      state.agentPanel === "detail" ||
      state.agentPanel === "gardien"
    ) {
      setShellMode(state, "agent", "detail");
    } else if (state.selectedAgentId) {
      setShellMode(state, "agent", "detail");
    }
  } else if (state.view === "connecteurs") {
    if (
      state.selectedConnectorId ||
      state.connectorPanel === "new" ||
      state.connectorPanel === "composer"
    ) {
      setShellMode(state, "connecteurs", "detail");
    }
  } else if (state.view === "assistant") {
    setShellMode(state, "assistant", state.sessionId ? "detail" : "list");
  }
}

export function setSessionId(state, id) {
  const change = (id || null) !== (state.sessionId || null);
  state.sessionId = id || null;
  if (!id) state.sessionMcp = null;
  if (change) {
    // « Occupé » est l'état de la conversation affichée, pas de l'écran : le
    // flux d'une autre ne la rend pas occupée, et ce qui attendait dans la
    // file de l'une ne s'affiche pas dans l'autre.
    state.busy = false;
    state.enFile = [];
  }
}

export function setSessionMcp(state, data) {
  state.sessionMcp = data || null;
}

export function setMessages(state, messages) {
  // Les verdicts déjà rendus se remettent sur les outils : le journal ne les dit pas.
  state.messages = appliquerLesVerdicts(messages || [], state.verdicts);
}

/**
 * Une demande tranchée : sa carte se retire et son verdict rejoint la ligne de
 * l'outil, puis se retient pour les relectures du journal. Vrai si le fil a changé.
 */
/** Un choix de connecteur fait avant le premier message : il attend la conversation. */
export function noterChoixConnecteur(state, id, active) {
  state.mcpEnAttente = { ...(state.mcpEnAttente || {}), [id]: !!active };
}

/** Les choix attendent d'être posés ou d'être oubliés (autre espace, autre projet). */
export function oublierLesChoixConnecteurs(state) {
  state.mcpEnAttente = {};
  if (state.sessionMcp?.apercu) state.sessionMcp = null;
}

/** Retient de quel outil une demande parle : la carte peut disparaître avant son verdict. */
export function noterLaDemande(state, demande) {
  const rid = demande?.request_id;
  const tid = demande?.tool_use_id;
  if (!rid || !tid || demande?.genre === "question") return;
  state.outilsDesDemandes = { ...(state.outilsDesDemandes || {}), [rid]: tid };
}

/**
 * Une demande tranchée : sa carte se retire et son verdict rejoint la ligne de
 * l'outil, puis se retient pour les relectures du journal. Vrai si le fil a changé.
 *
 * L'outil se lit sur la carte ; si une relecture du journal l'a déjà emportée,
 * sur ce qu'on avait retenu (`noterLaDemande`).
 */
export function rattacherUnVerdict(state, requestId, etat) {
  if (etat !== "allow" && etat !== "deny") return false;
  const avant = state.messages;
  const id = idDeLOutil(avant, requestId) || state.outilsDesDemandes?.[requestId] || "";
  if (!id) return false;
  state.verdicts = { ...(state.verdicts || {}), [id]: etat };
  const retiree = rattacherLeVerdict(avant, requestId, etat);
  const posee = appliquerLesVerdicts(retiree, state.verdicts);
  if (posee === avant) return false;
  state.messages = posee;
  return true;
}

export function setChargementFil(state, sessionId) {
  state.chargementFil = sessionId || null;
}

export function setMcpTravail(state, quoi) {
  state.mcpTravail = quoi || "";
}

export function setEnFile(state, messages) {
  state.enFile = messages || [];
}

export function ajouterEnFile(state, message) {
  state.enFile = [...(state.enFile || []), message];
}

/**
 * Retire de la file le message qui vient de partir.
 *
 * Le service annonce son départ par son texte, non par son identifiant : ce
 * qu'il écrit dans le tour, c'est le texte. On retire donc le premier qui
 * correspond — l'ordre de la file est celui du départ.
 */
export function retirerDeLaFile(state, texte) {
  const rang = (state.enFile || []).findIndex((m) => m.texte === texte);
  if (rang < 0) return null;
  const parti = state.enFile[rang];
  state.enFile = state.enFile.filter((_, i) => i !== rang);
  return parti;
}

export function retirerDeLaFileParId(state, id) {
  state.enFile = (state.enFile || []).filter((m) => m.id !== id);
}

export function toggleExpanded(state, slug) {
  if (state.expandedSlugs.has(slug)) {
    state.expandedSlugs.delete(slug);
  } else {
    state.expandedSlugs.add(slug);
  }
  saveExpandedSlugs([...state.expandedSlugs]);
}

export function ensureExpanded(state, slug) {
  if (!state.expandedSlugs.has(slug)) {
    state.expandedSlugs.add(slug);
    saveExpandedSlugs([...state.expandedSlugs]);
  }
}

export function appendMessage(state, msg) {
  state.messages = [...state.messages, msg];
}

export function updateLastAssistant(state, payload) {
  const text =
    typeof payload === "string" ? payload : (payload?.text ?? "");
  const blocks =
    typeof payload === "object" && payload?.blocks ? payload.blocks : undefined;

  const msgs = [...state.messages];
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === "assistant" && msgs[i].streaming) {
      msgs[i] = {
        ...msgs[i],
        text,
        ...(blocks ? { blocks: [...blocks] } : {}),
        // Où en est le tour, pour que la bulle le dise tant qu'elle n'a rien
        // d'autre à montrer.
        ...(typeof payload === "object" && payload?.phase
          ? { phase: payload.phase }
          : {}),
      };
      state.messages = msgs;
      return;
    }
  }
  msgs.push({
    role: "assistant",
    text,
    blocks: blocks ? [...blocks] : [],
    streaming: true,
  });
  state.messages = msgs;
}

export function finalizeAssistant(state) {
  const maintenant = new Date().toISOString();
  state.messages = state.messages.map((m) =>
    m.streaming ? { ...m, streaming: false, horodatage: m.horodatage || maintenant } : m
  );
}

export function persistUserTurns(state) {
  const users = state.messages.filter((m) => m.role === "user");
  saveTurns(state.sessionId, users);
}

export function sessionsForSlug(state, slug) {
  return codeSessions(state).filter((s) => s.slug === slug);
}

export function orphanCodeSessions(state) {
  const slugs = new Set(codeProjects(state).map((p) => p.slug));
  return codeSessions(state).filter((s) => !slugs.has(s.slug));
}

export function setPendingProjectSlug(state, slug) {
  state.pendingProjectSlug = slug == null ? null : String(slug);
}

export function setEditingProjectSlug(state, slug) {
  state.editingProjectSlug = slug || null;
}

export function setEditingSessionId(state, id) {
  state.editingSessionId = id || null;
}

export function setAgentTranscript(state, data) {
  state.agentTranscript = data || null;
}

export function setAgentTranscriptBusy(state, busy) {
  state.agentTranscriptBusy = !!busy;
}

/**
 * ProjectStore.create() fait mkdir(exist_ok=True) : deux projets de meme nom
 * reutiliseraient le meme dossier. On garantit donc l'unicite ici.
 */
export function uniqueProjectSlug(state, base) {
  const pris = new Set((state.projects || []).map((p) => p.slug));
  const racine = base || "projet";
  if (!pris.has(racine)) return racine;
  for (let i = 2; i < 500; i += 1) {
    const essai = `${racine}-${i}`;
    if (!pris.has(essai)) return essai;
  }
  return `${racine}-${Date.now()}`;
}

/** Titre de projet derive du premier message envoye. */
export function projectNameFromMessage(text) {
  const mots = String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
  if (!mots.length) return "";
  let titre = "";
  for (const mot of mots) {
    const suivant = titre ? `${titre} ${mot}` : mot;
    if (suivant.length > 40) break;
    titre = suivant;
  }
  if (!titre) titre = mots[0].slice(0, 40);
  return titre.charAt(0).toUpperCase() + titre.slice(1);
}

export function slugifyProjectName(name) {
  const s = (name || "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s;
}

export function sessionLabel(session) {
  const title = (session?.title || "").trim();
  if (title) return title;
  const sid = session?.session_id || "";
  return sid.slice(0, 8) || "session";
}

// Ce qu'un état vaut en français. Le service parle la langue du CLI ; l'écran
// parle celle de qui le lit, et les deux disaient autre chose l'un que l'autre
// — la pastille annonçait « au repos » quand la ligne en dessous lisait
// « idle ».
export const ETATS = {
  running: "en réponse",
  failed: "en erreur",
  timeout: "en erreur",
  interrupted: "interrompue",
  archived: "rangée",
  created: "jamais lancée",
  idle: "au repos",
  done: "au repos",
};

export function etatLisible(etat) {
  return ETATS[etat] || etat || "";
}

export function sessionMetaLine(session) {
  const parts = [];
  if (session?.attend_une_decision) parts.push("autorisation demandée");
  else if (session?.state) parts.push(etatLisible(session.state));
  if (session?.turns != null) {
    parts.push(session.turns === 1 ? "1 tour" : `${session.turns} tours`);
  }
  return parts.join(" · ");
}
