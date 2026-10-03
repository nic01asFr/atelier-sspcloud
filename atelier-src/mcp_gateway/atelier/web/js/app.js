/** Point d'entrée — assemble modules et démarre l'app. */

import * as api from "./api.js";
import * as S from "./state.js";
import { $ } from "./core/dom.js";
import { readQuery, writeQuery as writeQueryState } from "./core/router.js";
import { bindContextMenu } from "./ui/context-menu.js";
import { bindModal } from "./ui/modal.js?v=modal2";
import { refreshMcpOverview, refreshPiloteOverview } from "./services/catalog.js";
import { createShellView } from "./views/shell.js?v=vague3";
import { createCodeTreeView } from "./views/code-tree.js";
import { createCodeChatView } from "./views/code-chat.js";
import { createConnectorsView } from "./views/connectors.js?v=modal";
import { createAgentView } from "./views/agent.js?v=vague2";
import { rendreAValider } from "./views/a-valider.js";
import { rendreJournal } from "./views/journal.js";
import { createMemoireActions, rendreMemoire } from "./views/memoire.js";
import { createComposerMcpView } from "./views/composer-mcp.js";
import { createPanneauView } from "./views/panneau.js";
import { createFilsView } from "./views/fils.js";
import { createAssistantView, createAssistantActions } from "./views/assistant.js";
import { createCartesActions } from "./views/assistant-cartes.js";
import { createProjectActions } from "./controllers/projects.js";
import { createSessionActions } from "./controllers/sessions.js";
import { createChatController } from "./controllers/chat.js";
import { createConnectorActions } from "./controllers/connectors.js?v=modal";
import { createAgentActions } from "./controllers/agent.js?v=vague2";
import { createAutomatesActions } from "./controllers/automates.js";
import { createValidationActions } from "./controllers/validation.js";
import { createAccordsActions } from "./controllers/accords.js";
import { openModal } from "./ui/modal.js?v=modal2";
import { createComposerMcpController } from "./controllers/composer-mcp.js";
import { createComposerInputController } from "./controllers/composer-input.js";
import { createAuthController } from "./controllers/auth.js";
import { createReglagesFil } from "./controllers/reglages-fil.js";
import { createTheme } from "./controllers/theme.js";
import { installerRaccourcis } from "./ui/raccourcis.js";

function createApp() {
  const state = S.createState();
  const ctx = { state, views: {} };

  const writeQuery = () => writeQueryState(state);

  const shell = createShellView(ctx);
  // Le contrôleur de chat naît plus bas, mais le rendu doit pouvoir lui
  // demander de suivre la conversation ouverte. On le laisse s'installer.
  let chat = null;
  const render = () => {
    shell.renderApp();
    // Hors du fil : le panneau et les échanges ne se redessinent que dans
    // ce qui change, et ne recréent jamais un cadre ouvert.
    ctx.views.panneau?.renderPanneau();
    ctx.views.fils?.renderFils();
    // Une conversation qu'on regarde sans l'avoir lancée doit se remplir
    // quand même : c'est ici qu'on branche l'écoute, à chaque rendu, puisque
    // c'est le rendu qui suit le changement de fil. L'appel est sans effet
    // si l'on écoute déjà le bon.
    chat?.observer?.(state.view === "code" ? state.sessionId : null);
  };

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
    basculerArchives: projectActions.basculerArchives,
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
    onApercu: () => composerMcpHolder.chargerApercu?.(),
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
  connectorActionsHolder.accorderSecret = (entry) => accords.accorderSecret(entry);

  const agentActionsHolder = {};
  const automatesHolder = {};
  const agent = createAgentView({
    state,
    actions: agentActionsHolder,
    automates: automatesHolder,
  });

  // Gardiens et tâches automatiques (vue Agents), « À valider » et journal.
  const automatesActions = createAutomatesActions({
    state,
    api,
    render,
    renderAgent: () => {
      if (state.view === "agent") agent.renderAgent();
    },
    logout: (msg) => logout(msg),
    // Un réparateur a déposé sa proposition : on l'ouvre dans la file.
    ouvrirProposition: (id) => {
      S.patchAValider(state, { statut: "en_attente", ouverte: id });
      navigateView("a-valider");
    },
    ouvrirConversation: (projet, id) => {
      if (projet) S.setSlug(state, projet);
      navigateView("code");
      sessionActions.selectSession(id);
    },
  });
  Object.assign(automatesHolder, automatesActions);
  const validation = createValidationActions({
    state,
    api,
    render,
    renderBadge: () => shell.renderBadge(),
    logout: (msg) => logout(msg),
  });

  agentActionsHolder.ouvrirAValider = () => navigateView("a-valider");
  // Les accords réservés à la personne : activer un agent, accorder un secret.
  const accords = createAccordsActions({
    state,
    api,
    render,
    openModal,
    logout: (msg) => logout(msg),
    apresAgent: async () => {
      try {
        await refreshPiloteOverview(state);
      } catch {
        /* le pilote absent : l'erreur de la commande est déjà affichée */
      }
      await automatesActions.rafraichir();
    },
    apresConnecteur: () => refreshMcpOverview(state).catch(() => {}),
  });
  const agentActions = createAgentActions({
    state,
    render,
    renderAgent: () => agent.renderAgent(),
    logout: (msg) => logout(msg),
    rafraichirAutomates: () => automatesActions.rafraichir(),
    apresDecision: () => validation.rafraichirCompte(),
    accords,
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

  const panneau = createPanneauView({ state, api, render });
  const fils = createFilsView({ state, api });
  const aValider = { render: () => rendreAValider($("a-valider-corps"), state, validation) };
  const journal = { render: () => rendreJournal($("journal-corps"), state, validation) };
  const memoireActions = createMemoireActions({ state, api, render, naviguer: (v) => navigateView(v) });
  const memoire = { render: () => rendreMemoire($("memoire-corps"), state, memoireActions) };
  const assistantActions = createAssistantActions({ state, render, writeQuery, api });
  // Une conversation neuve de l'Assistant abandonne, elle aussi, une lecture
  // en route (voir `abandonnerLOuverture`).
  const nouvelleDeLAssistant = assistantActions.nouvelle;
  assistantActions.nouvelle = () => {
    sessionActions.abandonnerLOuverture();
    nouvelleDeLAssistant();
  };
  const assistant = createAssistantView({
    state,
    render,
    actions: { selectSession: sessionActions.selectSession, ...assistantActions },
  });
  const cartes = createCartesActions({
    api,
    racine: () => $("thread"),
    erreur: (msg) => {
      S.setError(state, msg);
      render();
    },
  });
  ctx.views = { codeTree, codeChat, connectors, composerMcp, agent, panneau, fils, aValider, journal, assistant, memoire };

  // « Détails techniques » : raisonnement et actions brutes, dans le fil.
  const reglagesFil = createReglagesFil({
    api,
    rendreLeFil: () => ctx.views.codeChat?.renderThread(),
    erreur: (msg) => {
      S.setError(state, msg);
      render();
    },
  });

  // « Affichage » : le thème, suivi du système par défaut, clair ou sombre.
  const theme = createTheme({
    api,
    erreur: (msg) => {
      S.setError(state, msg);
      render();
    },
  });

  const auth = createAuthController({
    state,
    render,
    writeQuery,
    sessionActions,
    connectorActions,
    apresMeta: (meta) => {
      reglagesFil.appliquerMeta(meta);
      theme.appliquerMeta(meta);
    },
    apresEntree: () => {
      validation.rafraichirCompte();
      validation.veiller();
      chargerLaVue(state.view);
      veillerLesGardiens();
    },
  });
  logout = auth.logout;

  chat = createChatController({
    state,
    render,
    views: ctx.views,
    composerInput,
    writeQuery,
  });

  /**
   * Les gardiens tournent chaque minute : leur fiche et la liste des tâches
   * se relisent toutes les trente secondes tant qu'on les regarde. Jamais
   * pendant la création d'un agent, dont le formulaire perdrait sa saisie.
   */
  let veilleGardiens = null;
  function veillerLesGardiens() {
    if (veilleGardiens) return;
    veilleGardiens = setInterval(() => {
      if (document.visibilityState !== "visible" || !state.token) return;
      if (state.view !== "agent" || !["home", "gardien"].includes(state.agentPanel)) return;
      automatesActions.rafraichirEtRendre();
    }, 30000);
  }

  /** Ce que chaque vue relit en arrivant (hors Code et Connecteurs). */
  function chargerLaVue(view) {
    if (view === "agent") {
      automatesActions.rafraichirEtRendre();
      validation.rafraichirCompte();
    } else if (view === "a-valider") {
      validation.charger();
    } else if (view === "journal") {
      validation.chargerJournal();
    } else if (view === "memoire") {
      memoireActions.charger();
    }
  }

  function navigateView(view) {
    S.setView(state, S.normalizeView(view));
    writeQuery();
    render();
    if (state.token) chargerLaVue(state.view);
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
      refreshPiloteOverview(state)
        .catch(() => {
          /* pilote absent : gardiens et tâches se lisent quand même */
        })
        .then(() => {
          if (!state.selectedAgentId && !state.selectedGardienId) {
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
      sessionActions.abandonnerLOuverture();
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
    ctx.views.panneau.bind();
    ctx.views.fils.bind();
    cartes.bind();
    composerInput.bind();
    $("composer").addEventListener("submit", chat.onSend);
    // Le fil est reconstruit à chaque rendu : on écoute sur le document, que
    // les cartes ne survivent pas mais qui, lui, reste.
    document.addEventListener("atelier:annuler-file", (e) => {
      chat.annulerEnFile(e.detail?.id);
    });
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
    reglagesFil.bind();
    theme.bind();
    installerRaccourcis({
      state,
      naviguer: (v) => navigateView(v),
      nouvelleConversation: () =>
        S.estAssistant(state) ? assistantActions.nouvelle() : sessionActions.newConversation(),
      fermerLesPanneaux: () => {
        reglagesFil.fermer({ rendreLeFocus: true });
        theme.fermer({ rendreLeFocus: true });
      },
    });
  }

  async function boot() {
    bind();
    const q = readQuery();
    S.setView(state, q.view);
    if (q.slug) S.setSlug(state, q.slug);
    // Un lien vers un projet sans conversation veut dire « écris ici » : le
    // premier message y ouvre une conversation. Sans cela il créait un projet
    // neuf, nommé d'après ses premiers mots — un dossier fantôme par lien.
    if (q.slug && !q.session) S.setPendingProjectSlug(state, q.slug);
    if (await auth.reprendre()) {
      await auth.enterHub();
    } else {
      render();
    }
  }

  return { boot };
}

createApp().boot();
