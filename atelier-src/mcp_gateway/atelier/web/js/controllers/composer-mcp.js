/** Overlay MCP conversation — fetch + toggle composer +. */

import { optionsDesServices } from "../ui/services-du-projet.js";
import { apercuPossible } from "../ui/connecteurs-avant-envoi.js";
import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { openModal } from "../ui/modal.js";

/**
 * @param {object} ctx
 */
export function createComposerMcpController(ctx) {
  const { state, render, composerMcp, navigateView } = ctx;

  /**
   * Avant le premier message, la conversation n'existe pas : on montre ce
   * qu'elle recevra (l'aperçu du service, qui ne crée rien). Une fois tous les
   * minutes au plus, tant que l'écran n'a pas changé d'espace ou de projet.
   */
  async function chargerApercu() {
    if (!apercuPossible(state) || state.sessionMcp?.apercu || state.apercuEnCours) return;
    const maintenant = Date.now();
    if (state.apercuEssai && maintenant - state.apercuEssai < 60000) return;
    state.apercuEssai = maintenant;
    state.apercuEnCours = true;
    try {
      const kind = S.estAssistant(state) ? "assistant" : "code";
      const slug = kind === "code" ? state.slug || state.pendingProjectSlug || "" : "";
      const apercu = await api.getMcpApercu(state.token, { kind, slug });
      // L'écran a pu changer pendant l'attente : on ne pose pas l'aperçu d'un autre.
      if (apercuPossible(state)) state.sessionMcp = apercu;
    } catch {
      /* le « + » reste inactif : rien n'est promis */
    } finally {
      state.apercuEnCours = false;
    }
    composerMcp.renderComposerMcp();
  }

  async function refreshSessionMcp() {
    if (!state.token) {
      state.sessionMcp = null;
      return;
    }
    if (!state.sessionId) {
      await chargerApercu();
      return;
    }
    try {
      state.sessionMcp = await api.getSessionMcp(state.token, state.sessionId);
    } catch (err) {
      if (err.status === 401) return;
      state.sessionMcp = null;
    }
    // Le classement des services vient de la même source que partout
    // ailleurs ; sans lui, le popover retomberait sur une liste à plat.
    if (!state.toolsByService?.length) {
      try {
        const t = await api.mcpTools(state.token);
        S.setToolsByService(state, t.services || []);
      } catch {
        /* liste à plat, sans groupes */
      }
    }
  }

  async function toggleConnector(id, active) {
    if (!state.sessionId && state.sessionMcp?.apercu) {
      // Conversation pas encore née : le choix attend le premier message.
      S.noterChoixConnecteur(state, id, active);
      composerMcp.renderComposerMcp();
      return;
    }
    if (!state.token || !state.sessionId || state.mcpOverlayBusy) return;
    S.setMcpOverlayBusy(state, true);
    composerMcp.renderComposerMcp();
    try {
      state.sessionMcp = await api.patchSessionMcp(state.token, state.sessionId, {
        overlay: { [id]: active },
      });
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
    } finally {
      S.setMcpOverlayBusy(state, false);
      composerMcp.renderComposerMcp();
    }
  }

  function onMcpButtonClick(e) {
    e.preventDefault();
    e.stopPropagation();
    if ($("btn-composer-mcp")?.disabled) return;
    if (composerMcp.isOpen()) {
      composerMcp.close();
    } else {
      composerMcp.setOpen(true);
      refreshSessionMcp().then(() => composerMcp.renderComposerMcp());
    }
  }

  async function onAdvanced() {
    // Le fil ne peut que retirer ce que le projet lui donne. Élargir se
    // décide un cran au-dessus : c'est le projet qui ouvre ou ferme un
    // service, pour toutes ses conversations.
    const slug = state.slug;
    if (!state.token || !slug) return;
    composerMcp.close();
    composerMcp.renderComposerMcp();
    let etat;
    try {
      etat = await api.getProjectMcp(state.token, slug);
    } catch (err) {
      S.setError(state, err.message || String(err));
      return render();
    }
    const connecteurs = etat.connectors || [];
    // Ce que l'agent reçoit se dit en clair : un service choisi mais non livré
    // (Onyxia sans déploiement, refus d'authentification) l'explique au lieu de
    // se cocher comme les autres, et son choix est gardé pour plus tard.
    const { options, retenus } = optionsDesServices(connecteurs);
    openModal(state, {
      // Ouverte depuis le fil, la question porte sur le fil : la modale
      // reste dans son cadre plutôt que de recouvrir l'application.
      scope: "#view-code .shell-main",
      title: "Services du projet",
      lead: etat.inherits_pool
        ? "Ce projet prend tout ce qui est branché. Valider fixera la liste ci-dessous."
        : "Ce que les conversations de ce projet peuvent employer. Chaque fil peut ensuite en retirer, jamais en ajouter.",
      size: "md",
      submitLabel: "Enregistrer",
      fields: [
        {
          type: "checklist",
          name: "servers",
          label: "Services disponibles",
          hint:
            "Ce que l’Atelier fournit se décoche aussi (sauf l’accès aux outils) : la conversation perdrait alors ces outils pour tout le projet, sur toutes les surfaces.",
          options,
        },
      ],
      onSubmit: async (data) => {
        const choisis = new Set([...(data.servers || []), ...retenus]);
        await api.putProjectMcp(state.token, slug, [...choisis]);
        await refreshSessionMcp();
        composerMcp.renderComposerMcp();
      },
    });
  }

  function onManage() {
    composerMcp.close();
    navigateView("connecteurs");
  }

  function bind() {
    $("btn-composer-mcp")?.addEventListener("click", onMcpButtonClick);
    document.addEventListener("click", (e) => {
      if (!composerMcp.isOpen()) return;
      const wrap = document.querySelector(".composer-input-wrap");
      if (wrap && !wrap.contains(e.target)) {
        composerMcp.close();
        composerMcp.renderComposerMcp();
      }
    });
  }

  return { refreshSessionMcp, chargerApercu, toggleConnector, onManage, onAdvanced, bind };
}
