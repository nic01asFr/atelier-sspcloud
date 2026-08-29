/** Connecteurs MCP — sélection, toggle, import, suppression. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { refreshMcpOverview } from "../services/catalog.js";

/**
 * @param {object} ctx
 */
export function createConnectorActions(ctx) {
  const { state, render, renderMcp, logout } = ctx;

  async function refreshAll() {
    await refreshMcpOverview(state);
    S.syncShellModeFromSelection(state);
    render();
  }

  function select(kind, id) {
    S.setSelectedConnectorId(state, `${kind}:${id}`);
    S.setConnectorPanel(state, "detail");
    S.setShellMode(state, "connecteurs", "detail");
    render();
  }

  function clearSelection() {
    S.setSelectedConnectorId(state, null);
    S.setConnectorPanel(state, "home");
    S.setShellMode(state, "connecteurs", "list");
    render();
  }

  function showHome() {
    S.setSelectedConnectorId(state, null);
    S.setConnectorPanel(state, "home");
    S.setShellMode(state, "connecteurs", "detail");
    render();
  }

  function openNew() {
    S.setSelectedConnectorId(state, null);
    S.setConnectorPanel(state, "new");
    S.setShellMode(state, "connecteurs", "detail");
    S.setError(state, "");
    render();
  }

  function cancelNew() {
    S.setConnectorPanel(state, "home");
    S.setError(state, "");
    render();
  }

  async function toggleMcp(name, enabled) {
    try {
      await api.setMcpEnabled(state.token, name, enabled);
      await refreshAll();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
      render();
    }
  }

  async function deleteMcp(name) {
    try {
      await api.deleteMcpServer(state.token, name);
      S.setSelectedConnectorId(state, null);
      S.setShellMode(state, "connecteurs", "list");
      await refreshAll();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
      render();
    }
  }

  async function importMcp() {
    const raw = $("mcp-import")?.value.trim();
    if (!raw) return;
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      S.setError(state, "JSON invalide");
      render();
      return;
    }
    const block = parsed.mcpServers || parsed;
    if (!block || typeof block !== "object" || Array.isArray(block)) {
      S.setError(state, "Attendu { mcpServers: { … } }");
      render();
      return;
    }
    try {
      await api.importMcpServers(state.token, block);
      S.setError(state, "");
      S.setConnectorPanel(state, "home");
      await refreshAll();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
      render();
    }
  }

  async function reprobePool() {
    try {
      await api.reprobeMcpPool(state.token);
      await refreshAll();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
      render();
    }
  }

  return {
    select,
    clearSelection,
    showHome,
    openNew,
    cancelNew,
    toggleMcp,
    deleteMcp,
    importMcp,
    reprobePool,
  };
}
