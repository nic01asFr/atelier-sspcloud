/** Shell — écrans login/hub, navigation onglets, dispatch des vues. */

import * as S from "../state.js";
import { $, showBanner } from "../core/dom.js";
import { rendreBadge } from "./a-valider.js";

const VIEW_IDS = {
  code: "view-code",
  assistant: "view-assistant",
  connecteurs: "view-connecteurs",
  agent: "view-agent",
  "a-valider": "view-a-valider",
  journal: "view-journal",
};

/**
 * @param {object} ctx
 * @param {ReturnType<typeof import("../state.js").createState>} ctx.state
 * @param {object} ctx.views
 */
export function createShellView(ctx) {
  const { state } = ctx;

  function renderScreens() {
    const logged = !!state.token;
    $("login").classList.toggle("hidden", logged);
    $("hub").classList.toggle("hidden", !logged);
  }

  function renderShellNav() {
    const nav = $("app-nav");
    if (!nav) return;
    for (const btn of nav.querySelectorAll("[data-view]")) {
      const v = btn.getAttribute("data-view");
      btn.classList.toggle("active", v === state.view);
    }
    renderBadge();
  }

  /** Le nombre en attente, sur l'onglet « À valider », d'où qu'on soit. */
  function renderBadge() {
    rendreBadge($("nav-badge-a-valider"), state.aValiderCompte);
  }

  function renderViews() {
    for (const [name, id] of Object.entries(VIEW_IDS)) {
      const el = $(id);
      if (!el) continue;
      const show = state.view === name;
      el.classList.toggle("hidden", !show);
      el.hidden = !show;
    }
  }

  function applyShellModes() {
    S.syncShellModeFromSelection(state);
    for (const name of Object.keys(VIEW_IDS)) {
      const el = $(VIEW_IDS[name]);
      if (!el) continue;
      const mode = S.getShellMode(state, name);
      el.classList.toggle("shell-mode-list", mode === "list");
      el.classList.toggle("shell-mode-detail", mode === "detail");
    }
  }

  function renderApp() {
    renderScreens();
    if (!state.token) return;

    renderShellNav();
    renderViews();
    applyShellModes();

    if (state.view === "code") {
      ctx.views.codeTree.renderProjectTree();
      ctx.views.codeChat.renderCodeChat();
      ctx.views.composerMcp?.renderComposerMcp();
      showBanner(state.error);
    } else if (state.view === "connecteurs") {
      ctx.views.connectors.renderMcp();
      showBanner(state.error);
    } else if (state.view === "agent") {
      ctx.views.agent.renderAgent();
      showBanner(state.error);
    } else if (state.view === "a-valider") {
      ctx.views.aValider?.render();
      showBanner(state.error);
    } else if (state.view === "journal") {
      ctx.views.journal?.render();
      showBanner(state.error);
    } else {
      showBanner(state.error);
    }
  }

  return { renderApp, renderScreens, applyShellModes, renderBadge };
}
