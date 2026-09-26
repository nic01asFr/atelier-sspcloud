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

  // Le rang de la dernière ouverture demandée. Deux clics rapprochés lancent
  // deux lectures ; la plus lente arrivait parfois la dernière et remplaçait
  // le fil qu'on venait de choisir par le précédent.
  let ouverture = 0;

  /** Place l'écran sur une conversation : espace, projet, fil. */
  function placer(rec, sessionId) {
    // Une conversation de l'Assistant s'ouvre dans son fil, celle d'un
    // projet dans le sien : même écran, espace différent.
    S.setView(state, S.isCodeSession(rec, state) ? "code" : "assistant");
    S.setSlug(state, rec.slug);
    S.ensureExpanded(state, rec.slug);
    S.setSessionId(state, sessionId);
    S.setPendingProjectSlug(state, null);
    S.setShellMode(state, "code", "detail");
  }

  /**
   * Ouvre une conversation.
   *
   * Le clic se voit tout de suite : la conversation connue de la liste suffit
   * à ouvrir son fil (titre, ligne active, squelette de chargement), et le
   * transcrit vient le remplir quand il arrive. On attendait sa lecture avant
   * de rien montrer — mesuré : 3,3 s pour une conversation de 24 tours —, et
   * le fil restait sur « Nouvelle conversation » : on croyait le clic perdu.
   */
  async function selectSession(sessionId) {
    const rang = ++ouverture;
    const aJour = () => rang === ouverture;
    S.setError(state, "");
    const connue = (state.sessions || []).find((s) => s.session_id === sessionId);
    if (connue) {
      placer(connue, sessionId);
      S.setMessages(state, []);
      S.setEnFile(state, []);
      S.setChargementFil(state, sessionId);
      writeQuery();
      render();
    }
    try {
      const [rec, msgs] = await Promise.all([
        api.getSession(state.token, sessionId),
        buildMessagesFromServer(state, sessionId),
      ]);
      if (!aJour()) return;
      placer(rec, sessionId);
      S.setMessages(state, msgs);
      S.setChargementFil(state, null);
      // Ce qui attend son tour se retrouve à l'ouverture : un message déposé
      // depuis un autre écran, ou avant qu'on ferme celui-ci, doit se voir.
      const [file, mcp] = await Promise.allSettled([
        api.fileDesMessages(state.token, sessionId),
        api.getSessionMcp(state.token, sessionId),
      ]);
      if (!aJour()) return;
      S.setEnFile(state, file.status === "fulfilled" ? file.value?.messages || [] : []);
      S.setSessionMcp(state, mcp.status === "fulfilled" ? mcp.value : null);
      writeQuery();
      render();
      // La liste se relit ensuite, sans retenir l'ouverture : elle ne
      // change rien au fil qu'on vient d'ouvrir.
      refreshSessions(state)
        .then(() => {
          if (aJour()) render();
        })
        .catch(() => {});
    } catch (err) {
      if (!aJour()) return;
      S.setChargementFil(state, null);
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

  /**
   * Quitter le fil qu'on chargeait : une lecture encore en route ne doit pas
   * y ramener. Sans cela, ouvrir une conversation neuve pendant qu'une autre
   * se chargeait (au démarrage, par l'adresse) rendait l'écran à l'ancienne
   * quand sa lecture aboutissait — et le premier message partait dedans.
   */
  function abandonnerLOuverture() {
    ouverture += 1;
    S.setChargementFil(state, null);
  }

  function newConversation() {
    abandonnerLOuverture();
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
    abandonnerLOuverture();
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
    abandonnerLOuverture,
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
