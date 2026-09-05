/** Chargement catalogue partagé (projets, sessions, MCP). */

import * as api from "../api.js";
import * as S from "../state.js";

export async function refreshProjects(state) {
  const projects = await api.listProjects(state.token);
  S.setProjects(state, projects);
}

export async function refreshSessions(state) {
  const sessions = await api.listSessions(state.token, { syncTitles: true });
  S.setSessions(state, sessions);
}

export async function refreshMcp(state) {
  const servers = await api.listMcpServers(state.token);
  S.setMcpServers(state, servers);
}

export async function refreshMcpOverview(state) {
  const overview = await api.getMcpOverview(state.token);
  S.setMcpOverview(state, overview);
  const personal = overview?.catalog?.personal || [];
  const map = {};
  for (const row of personal) {
    map[row.id] = {
      enabled: row.enabled !== false,
      command: row.config?.command,
      url: row.url || row.config?.url,
      transport: row.transport,
      state: row.state,
      online: row.online,
      tools: row.tools,
      error: row.error,
    };
  }
  S.setMcpServers(state, map);
}

/** Profils gateway (config agents pilote). */
export async function refreshAgentProfiles(state) {
  state.mcpProfiles = await api.getMcpProfiles(state.token);
}

export async function refreshPiloteOverview(state) {
  const overview = await api.getAgentOverview(state.token);
  S.setPiloteOverview(state, overview);
  if (
    state.selectedAgentId &&
    overview?.agents?.length &&
    !overview.agents.some((a) => a.id === state.selectedAgentId)
  ) {
    S.setSelectedAgentId(state, null);
  }
}

export async function buildMessagesFromServer(state, sessionId) {
  const stored = S.loadTurns(sessionId);
  const { transcript } = await api.getTranscript(state.token, sessionId);
  const parsed = api.messagesFromTranscript(transcript || "");
  const messages = api.mergeChatMessages(stored, parsed);
  return [...messages, ...(await questionsRestees(state, sessionId))];
}

/**
 * Les questions qu'un tour attend encore, retrouvées à l'ouverture.
 *
 * Sans cela, fermer l'onglet perdrait la question : le tour continuerait
 * d'attendre sur le pod, sans plus personne pour la voir. C'est très
 * exactement ce que « une décision en attente doit pouvoir le rester »
 * interdit.
 *
 * Une question dont le processus a disparu — service redémarré depuis — se
 * dit telle quelle : elle reste lisible, mais ce tour-là ne reprendra pas.
 */
async function questionsRestees(state, sessionId) {
  let liste;
  try {
    liste = await api.decisionsEnAttente(state.token, sessionId);
  } catch {
    return [];
  }
  const cartes = [];
  for (const d of liste?.vives || []) {
    cartes.push({ role: "system", blocks: [{ type: "decision", demande: d, etat: "en_attente" }] });
  }
  for (const d of liste?.orphelines || []) {
    cartes.push({
      role: "system",
      blocks: [{ type: "decision", demande: d, etat: "orpheline" }],
    });
  }
  return cartes;
}
