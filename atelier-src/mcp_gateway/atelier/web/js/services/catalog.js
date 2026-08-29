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
  return api.mergeChatMessages(stored, parsed);
}
