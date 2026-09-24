/** Overlay MCP conversation — fetch + toggle composer +. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { openModal } from "../ui/modal.js";

/**
 * @param {object} ctx
 */
export function createComposerMcpController(ctx) {
  const { state, render, composerMcp, navigateView } = ctx;

  async function refreshSessionMcp() {
    if (!state.token || !state.sessionId) {
      state.sessionMcp = null;
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
    // Ce qu'un service apporte se dit en clair ; son identifiant technique
    // n'apparaît qu'en second, pour qui a besoin de le reconnaître.
    const APPORTS = {
      "Accès aux outils": "chercher un outil, lancer une composition",
      "Coordination et mémoire": "messages, mémoire, agents",
      "Navigateur web": "pages, captures, bureau",
    };
    const options = connecteurs.map((c) => ({
      value: c.id,
      label: c.name,
      checked: !!c.active,
      hint: c.system
        ? (c.scope || []).length
          ? `ouvre ${c.scope[0]}`
          : APPORTS[c.group] || "socle de l’Atelier"
        : `service branché · ${c.id_technique || c.id}`,
    }));
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
            "Ce que l’Atelier fournit se décoche aussi : la conversation perdrait alors ces outils pour tout le projet.",
          options,
        },
      ],
      onSubmit: async (data) => {
        await api.putProjectMcp(state.token, slug, data.servers || []);
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

  return { refreshSessionMcp, toggleConnector, onManage, onAdvanced, bind };
}
