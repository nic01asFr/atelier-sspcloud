/** Auth — login, logout, entrée hub. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { readQuery } from "../core/router.js";
import { closeModal } from "../ui/modal.js";
import {
  refreshMcp,
  refreshProjects,
  refreshSessions,
  refreshMcpOverview,
  refreshPiloteOverview,
  veillerLesSessions,
} from "../services/catalog.js";

/**
 * @param {object} ctx
 */
export function createAuthController(ctx) {
  const { state, render, writeQuery, sessionActions, connectorActions } = ctx;

  function logout(msg) {
    // La session de navigation vit côté serveur : l'oublier ici ne
    // l'invaliderait pas. On la ferme sans attendre — se déconnecter ne doit
    // pas dépendre du réseau.
    api.clearAuthCookie();
    S.setToken(state, "");
    S.setSessionId(state, null);
    S.setProjects(state, []);
    S.setSessions(state, []);
    S.setMcpServers(state, {});
    S.setMessages(state, []);
    S.setBusy(state, false);
    S.setView(state, "code");
    S.setError(state, msg || "");
    closeModal(state);
    history.replaceState(null, "", "/");
    if (msg) {
      $("login-error").hidden = false;
      $("login-error").textContent = msg;
    }
    render();
  }

  async function enterHub() {
    const q = readQuery();
    S.setView(state, q.view);
    if (q.slug) S.setSlug(state, q.slug);
    try {
      const meta = await api.getMeta(state.token);
      S.setMeta(state, meta);
      // « Ouvrir l'Atelier sur l'Assistant » : l'accueil, quand l'adresse ne dit rien.
      S.setView(state, S.vueDArrivee(location.search, meta));
      await refreshProjects(state);
      await refreshSessions(state);
      veillerLesSessions(state, render);
      // Ce qui se lit partout : le badge « À valider », et la vue d'arrivée.
      ctx.apresEntree?.();
      if (state.view === "connecteurs") {
        await refreshMcp(state);
        await refreshMcpOverview(state);
        // Les compositions font partie du pool : les charger avec lui.
        try {
          await connectorActions?.chargerCompositions?.();
        } catch {
          /* la liste restera vide */
        }
      }
      // Arriver directement sur ?view=agent doit charger la liste, comme un
      // clic sur l'onglet le ferait.
      if (state.view === "agent") {
        try {
          await refreshPiloteOverview(state);
        } catch {
          /* pilote indisponible : l'écran le signalera */
        }
      }
      if (q.slug && state.view === "code") S.ensureExpanded(state, q.slug);
      if (q.session && state.view === "code") {
        await sessionActions.selectSession(q.session);
      } else {
        render();
      }
    } catch (err) {
      if (err.status === 401) {
        logout("Session expirée : saisissez à nouveau la clé.");
        return;
      }
      S.setError(state, err.message || String(err));
      render();
    }
  }

  async function onLogin(ev) {
    ev.preventDefault();
    const champ = $("owner-key");
    const key = champ.value.trim();
    // La clé ne sert qu'à ouvrir la session : on la retire du champ tout de
    // suite, et on ne la garde nulle part — ni état, ni stockage.
    champ.value = "";
    if (!key) return;
    $("login-error").hidden = true;
    try {
      await api.ouvrirSession(key);
      S.setToken(state, S.SESSION_OUVERTE);
      await enterHub();
    } catch (err) {
      S.setToken(state, "");
      $("login-error").hidden = false;
      $("login-error").textContent =
        err.status === 401 ? "Clé invalide" : err.message || String(err);
      render();
    }
  }

  /**
   * Au démarrage : une session déjà ouverte se reprend par son cookie.
   *
   * Une clé laissée dans `localStorage` par une version précédente est
   * d'abord échangée contre ce cookie, puis effacée. Rend vrai si l'interface
   * est connectée.
   */
  async function reprendre() {
    await api.migrerAncienneCle(S.lireAncienneCle, S.oublierAncienneCle);
    try {
      await api.getMeta("");
    } catch {
      S.setToken(state, "");
      return false;
    }
    S.setToken(state, S.SESSION_OUVERTE);
    return true;
  }

  return { logout, enterHub, onLogin, reprendre };
}
