/** Point d'entrée — assemble modules et démarre l'app. */

import * as api from "./api.js";
import * as S from "./state.js";
import { $ } from "./core/dom.js";
import { readQuery, writeQuery as writeQueryState } from "./core/router.js";
import { bindContextMenu } from "./ui/context-menu.js";
import { bindModal } from "./ui/modal.js?v=modal2";
import { refreshMcpOverview, refreshPiloteOverview } from "./services/catalog.js";
import { createShellView } from "./views/shell.js?v=modal";
import { createCodeTreeView } from "./views/code-tree.js";
import { createCodeChatView } from "./views/code-chat.js";
import { createConnectorsView } from "./views/connectors.js?v=modal";
import { createAgentView } from "./views/agent.js?v=shell6";
import { createComposerMcpView } from "./views/composer-mcp.js";
import { createProjectActions } from "./controllers/projects.js";
import { createSessionActions } from "./controllers/sessions.js";
import { createChatController } from "./controllers/chat.js";
import { createConnectorActions } from "./controllers/connectors.js?v=modal";
import { createAgentActions } from "./controllers/agent.js?v=shell6";
import { createComposerMcpController } from "./controllers/composer-mcp.js";
import { createComposerInputController } from "./controllers/composer-input.js";
import { createAuthController } from "./controllers/auth.js";

function createApp() {
  const state = S.createState();
  const ctx = { state, views: {} };

  const writeQuery = () => writeQueryState(state);

  const shell = createShellView(ctx);
  const render = () => shell.renderApp();

  let logout = (msg) => {
    S.setToken(state, "");
    render();
    if (msg) console.warn(msg);
  };

  const sessionActions = createSessionActions({
    state,
    render,
    writeQuery,
    logout: (msg) => logout(msg),
  });

  const projectActions = createProjectActions({ state, render, writeQuery });

  const treeActions = {
    ...sessionActions,
    newProject: projectActions.newProject,
    startRenameProject: projectActions.startRename,
    archiveProject: projectActions.archiveProject,
    deleteProject: projectActions.deleteProject,
    cancelRenameProject: projectActions.cancelRename,
    commitRenameProject: projectActions.commitRename,
  };

  const codeTree = createCodeTreeView({
    state,
    render,
    writeQuery,
    actions: treeActions,
  });
  const composerInput = createComposerInputController({ state, render });
  // Rempli une fois le contrôleur de conversation créé : la vue doit
  // pouvoir reprendre un fil, ce qui demande d'envoyer, donc de connaître
  // un contrôleur qui n'existe pas encore ici.
  const filActions = {};
  const codeChat = createCodeChatView({
    state,
    render,
    composerInput,
    actions: filActions,
  });

  const composerMcpHolder = {};
  const composerMcp = createComposerMcpView({
    state,
    onToggle: (id, active) => composerMcpHolder.toggleConnector?.(id, active),
    onManage: () => composerMcpHolder.onManage?.(),
    onAdvanced: () => composerMcpHolder.onAdvanced?.(),
  });

  const connectorActionsHolder = {};
  const connectors = createConnectorsView({
    state,
    actions: connectorActionsHolder,
  });

  const connectorActions = createConnectorActions({
    state,
    render,
    renderMcp: () => connectors.renderMcp(),
    logout: (msg) => logout(msg),
  });
  Object.assign(connectorActionsHolder, connectorActions);

  const agentActionsHolder = {};
  const agent = createAgentView({
    state,
    actions: agentActionsHolder,
  });

  const agentActions = createAgentActions({
    state,
    render,
    renderAgent: () => agent.renderAgent(),
    logout: (msg) => logout(msg),
  });
  Object.assign(agentActionsHolder, agentActions);

  // « Reprendre ici » : on ne corrige pas un message — une session Claude ne
  // se rembobine pas — on repart d'avant lui dans une conversation qui garde
  // tout l'acquis, puis on envoie la version corrigée.
  filActions.reprendreIci = async (rang, texte) => {
    try {
      S.setError(state, "");
      const fork = await api.forkSession(state.token, state.sessionId, rang);
      await sessionActions.selectSession(fork.session_id);
      const champ = $("composer-input");
      if (!champ) return;
      champ.value = texte;
      champ.dispatchEvent(new Event("input", { bubbles: true }));
      $("composer").requestSubmit();
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
    }
  };

  ctx.views = { codeTree, codeChat, connectors, composerMcp, agent };

  const auth = createAuthController({
    state,
    render,
    writeQuery,
    sessionActions,
    connectorActions,
  });
  logout = auth.logout;

  const chat = createChatController({
    state,
    render,
    views: ctx.views,
    composerInput,
    writeQuery,
  });

  function navigateView(view) {
    S.setView(state, S.normalizeView(view));
    writeQuery();
    render();
    if (state.view === "connecteurs" && state.token) {
      connectorActions.chargerCompositions().then(render);
      refreshMcpOverview(state).then(() => {
        if (!state.selectedConnectorId) {
          S.setShellMode(state, "connecteurs", "detail");
        }
        render();
      });
    }
    if (state.view === "agent" && state.token) {
      refreshPiloteOverview(state).then(() => {
        if (!state.selectedAgentId) {
          S.setShellMode(state, "agent", "detail");
        }
        S.syncShellModeFromSelection(state);
        render();
      });
    }
  }

  const composerMcpCtrl = createComposerMcpController({
    state,
    render,
    composerMcp,
    navigateView,
  });
  Object.assign(composerMcpHolder, composerMcpCtrl);

  function bind() {
    $("login-form").addEventListener("submit", auth.onLogin);
    $("btn-logout").addEventListener("click", () => logout());
    $("btn-mcp-reprobe")?.addEventListener("click", connectorActions.reprobePool);
    $("btn-connector-new")?.addEventListener("click", () => connectorActions.openNew());
    $("connectors-sidebar-title")?.addEventListener("click", () => connectorActions.showHome());
    $("connectors-sidebar-title")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        connectorActions.showHome();
      }
    });
    $("btn-agent-new")?.addEventListener("click", () => agentActions.openCreate());
    $("btn-agent-refresh")?.addEventListener("click", () => agentActions.refreshAll());
    $("agent-sidebar-title")?.addEventListener("click", () => agentActions.showAgentHome());
    $("agent-sidebar-title")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        agentActions.showAgentHome();
      }
    });
    $("btn-agent-to-home")?.addEventListener("click", () => agentActions.showAgentHome());
    $("btn-shell-forward-agent")?.addEventListener("click", () =>
      agentActions.showAgentList()
    );
    $("btn-shell-back-code")?.addEventListener("click", () => {
      S.setSessionId(state, null);
      S.setMessages(state, []);
      S.setPendingProjectSlug(state, null);
      S.setShellMode(state, "code", "list");
      writeQuery();
      render();
    });

    // Choix du projet d'accueil : « Nouveau projet » ou un projet existant.
    $("session-project-select")?.addEventListener("change", (e) => {
      S.setPendingProjectSlug(state, e.target.value);
      render();
    });
    $("btn-shell-back-agent")?.addEventListener("click", () => {
      if (state.agentPanel === "create") agentActions.cancelCreate();
      else if (state.agentPanel === "detail") agentActions.showAgentList();
      else agentActions.showAgentList();
    });
    $("btn-shell-back-connecteurs")?.addEventListener("click", () => {
      if (state.connectorPanel === "new") connectorActions.cancelNew();
      else if (state.selectedCompositionId) {
        S.setSelectedCompositionId(state, null);
        S.setShellMode(state, "connecteurs", "list");
        render();
      } else if (state.selectedConnectorId) connectorActions.clearSelection();
      else {
        S.setShellMode(state, "connecteurs", "list");
        render();
      }
    });
    composerMcpCtrl.bind();
    composerInput.bind();
    $("composer").addEventListener("submit", chat.onSend);
    // Le bouton Envoyer suit la saisie. Rendu cible : un render() complet
    // reconstruirait le panneau et ferait perdre le focus a chaque frappe.
    $("composer-input").addEventListener("input", () => {
      ctx.views.codeChat?.renderComposer();
    });
    $("composer-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        $("composer").requestSubmit();
      }
    });
    for (const btn of $("app-nav").querySelectorAll("[data-view]")) {
      btn.addEventListener("click", () =>
        navigateView(btn.getAttribute("data-view"))
      );
    }
    bindModal(state);
    bindContextMenu(state);
  }

  async function boot() {
    bind();
    const q = readQuery();
    S.setView(state, q.view);
    if (q.slug) S.setSlug(state, q.slug);
    if (state.token) {
      await auth.enterHub();
    } else {
      render();
    }
  }

  return { boot };
}

createApp().boot();
