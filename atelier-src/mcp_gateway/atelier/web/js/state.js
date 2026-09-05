/** État applicatif pur — pas de fetch, pas de DOM. */

const KEY_OWNER = "atelier.ownerKey";
const KEY_EXPANDED = "atelier.expandedSlugs";

function turnsKey(sessionId) {
  return `atelier.turns.${sessionId}`;
}

export function loadOwnerKey() {
  try {
    return localStorage.getItem(KEY_OWNER) || "";
  } catch {
    return "";
  }
}

export function saveOwnerKey(token) {
  localStorage.setItem(KEY_OWNER, token);
}

export function clearOwnerKey() {
  localStorage.removeItem(KEY_OWNER);
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
export const VIEWS = ["code", "assistant", "connecteurs", "agent"];

export function normalizeView(view) {
  const v = (view || "").trim().toLowerCase();
  return VIEWS.includes(v) ? v : "code";
}

export function createState() {
  return {
    token: loadOwnerKey(),
    view: "code",
    slug: "",
    sessionId: null,
    projects: [],
    sessions: [],
    expandedSlugs: new Set(loadExpandedSlugs()),
    messages: [],
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

export function setToken(state, token) {
  state.token = token;
  if (token) saveOwnerKey(token);
  else clearOwnerKey();
}

export function setError(state, msg) {
  state.error = msg || "";
}

export function setBusy(state, busy) {
  state.busy = !!busy;
}

export function setMcpOverlayBusy(state, busy) {
  state.mcpOverlayBusy = !!busy;
}

export function setView(state, view) {
  state.view = normalizeView(view);
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
  return state.sessions.filter((s) => isCodeSession(s, state) && s.state !== "archived");
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

export function setAgentPanel(state, panel) {
  const p = (panel || "").toLowerCase();
  state.agentPanel = ["home", "create", "detail"].includes(p) ? p : "home";
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
    if (state.agentPanel === "create" || state.agentPanel === "detail") {
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
  state.sessionId = id || null;
  if (!id) state.sessionMcp = null;
}

export function setSessionMcp(state, data) {
  state.sessionMcp = data || null;
}

export function setMessages(state, messages) {
  state.messages = messages || [];
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
  state.messages = state.messages.map((m) =>
    m.streaming ? { ...m, streaming: false } : m
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

export function sessionMetaLine(session) {
  const parts = [];
  if (session?.state) parts.push(session.state);
  if (session?.turns != null) parts.push(`${session.turns} tour(s)`);
  return parts.join(" · ");
}
