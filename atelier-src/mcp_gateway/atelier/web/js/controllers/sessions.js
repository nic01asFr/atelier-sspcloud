/** Actions sessions code — sélection, CRUD, copie id. */

import * as api from "../api.js";
import * as S from "../state.js";
import { showBanner } from "../core/dom.js";
import {
  buildMessagesFromServer,
  refreshSessions,
} from "../services/catalog.js";
import { openVscode as openVscodeService } from "../services/vscode.js";

/**
 * @param {object} ctx
 */
export function createSessionActions(ctx) {
  const { state, render, writeQuery, logout } = ctx;

  async function selectSession(sessionId) {
    try {
      S.setError(state, "");
      const rec = await api.getSession(state.token, sessionId);
      // Une conversation de l'Assistant s'ouvre dans son fil, celle d'un
      // projet dans le sien : même écran, espace différent.
      S.setView(state, S.isCodeSession(rec, state) ? "code" : "assistant");
      S.setSlug(state, rec.slug);
      S.ensureExpanded(state, rec.slug);
      S.setSessionId(state, sessionId);
      S.setPendingProjectSlug(state, null);
      S.setShellMode(state, "code", "detail");
      const msgs = await buildMessagesFromServer(state, sessionId);
      S.setMessages(state, msgs);
      // Ce qui attend son tour se retrouve à l'ouverture : un message déposé
      // depuis un autre écran, ou avant qu'on ferme celui-ci, doit se voir.
      try {
        const file = await api.fileDesMessages(state.token, sessionId);
        S.setEnFile(state, file.messages || []);
      } catch {
        S.setEnFile(state, []);
      }
      try {
        S.setSessionMcp(state, await api.getSessionMcp(state.token, sessionId));
      } catch {
        S.setSessionMcp(state, null);
      }
      await refreshSessions(state);
      writeQuery();
      render();
    } catch (err) {
      if (err.status === 404) {
        S.setSessionId(state, null);
        S.setMessages(state, []);
        writeQuery();
        S.setError(state, "Session introuvable");
      } else if (err.status === 401) {
        logout("Clé invalide");
        return;
      } else {
        S.setError(state, err.message || String(err));
      }
      render();
    }
  }

  function newConversation() {
    S.setError(state, "");
    S.setView(state, "code");
    S.setSessionId(state, null);
    S.setMessages(state, []);
    S.setSessionMcp(state, null);
    S.setPendingProjectSlug(state, "");
    writeQuery();
    render();
  }

  function newSessionForSlug(slug) {
    S.setError(state, "");
    S.setView(state, "code");
    S.setSlug(state, slug);
    S.ensureExpanded(state, slug);
    S.setSessionId(state, null);
    S.setMessages(state, []);
    S.setSessionMcp(state, null);
    S.setPendingProjectSlug(state, slug);
    writeQuery();
    render();
  }

  function startRenameSession(session) {
    S.setEditingSessionId(state, session.session_id);
    render();
  }

  function cancelRenameSession() {
    S.setEditingSessionId(state, null);
    render();
  }

  async function commitRenameSession(session, nom) {
    const titre = (nom || "").trim();
    S.setEditingSessionId(state, null);
    if (!titre || titre === S.sessionLabel(session)) {
      render();
      return;
    }
    try {
      await api.patchSession(state.token, session.session_id, { title: titre });
      await refreshSessions(state);
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
    }
    render();
  }

  async function archiveSession(sessionId) {
    try {
      await api.patchSession(state.token, sessionId, { archived: true });
      if (state.sessionId === sessionId) {
        S.setSessionId(state, null);
        S.setMessages(state, []);
        S.setSessionMcp(state, null);
        writeQuery();
      }
      await refreshSessions(state);
      render();
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
    }
  }

  async function deleteSession(sessionId) {
    if (!confirm("Supprimer cette session et son historique ?")) return;
    try {
      await api.deleteSession(state.token, sessionId);
      if (state.sessionId === sessionId) {
        S.setSessionId(state, null);
        S.setMessages(state, []);
        S.setSessionMcp(state, null);
        writeQuery();
      }
      await refreshSessions(state);
      render();
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
    }
  }

  async function copySessionId(sessionId) {
    try {
      await navigator.clipboard.writeText(sessionId);
      showBanner("Identifiant copié");
      setTimeout(() => showBanner(state.error), 1200);
    } catch {
      showBanner("Copie impossible");
    }
  }

  function openVscode(slug, sessionId) {
    return openVscodeService(state, slug, sessionId);
  }

  return {
    newConversation,
    selectSession,
    newSessionForSlug,
    startRenameSession,
    cancelRenameSession,
    commitRenameSession,
    archiveSession,
    deleteSession,
    copySessionId,
    openVscode,
  };
}
