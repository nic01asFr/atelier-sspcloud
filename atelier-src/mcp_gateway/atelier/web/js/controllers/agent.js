/** Agent pilote — actions via API Atelier (/v1/agent/*). */

import * as api from "../api.js?v=modal";
import * as S from "../state.js";
import { openModal } from "../ui/modal.js";
import { ouvrirVariante } from "../ui/tool-variant.js";
import {
  refreshAgentProfiles,
  refreshMcpOverview,
  refreshPiloteOverview,
  refreshProjects,
} from "../services/catalog.js";

/**
 * @param {object} ctx
 */
export function createAgentActions(ctx) {
  const { state, render, renderAgent, logout } = ctx;

  async function refreshAll() {
    try {
      await refreshPiloteOverview(state);
    } catch (err) {
      // Le pilote absent (mode factice, wikichat arrêté) n'efface pas le
      // reste de la vue : gardiens et tâches se lisent ailleurs.
      if (err?.status === 401) throw err;
    }
    await ctx.rafraichirAutomates?.();
    S.syncShellModeFromSelection(state);
    render();
  }

  async function withErr(fn) {
    try {
      await fn();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
      render();
    }
  }

  function select(agentId) {
    S.setSelectedGardienId(state, null);
    S.setSelectedAgentId(state, agentId);
    S.setAgentPanel(state, "detail");
    S.setAgentTab(state, "discussion");
    S.setShellMode(state, "agent", "detail");
    S.setAgentTranscript(state, null);
    render();
    ensureModelsCatalog().then(() => renderAgent());
    loadTranscript(agentId);
  }

  /**
   * Le catalogue sert aussi au detail, pour nommer le modele en clair plutot
   * que d'afficher son identifiant.
   */
  async function ensureModelsCatalog() {
    if (state.modelsCatalog) return;
    try {
      S.setModelsCatalog(state, await api.listModels(state.token));
    } catch {
      /* le detail retombera sur l'identifiant brut */
    }
  }

  /** Derniers tours de la session Claude de l'agent, via le pilote. */
  async function loadTranscript(agentId) {
    if (!agentId) return;
    S.setAgentTranscriptBusy(state, true);
    renderAgent();
    try {
      const data = await api.agentTranscript(state.token, agentId);
      S.setAgentTranscript(state, { agentId, ...data });
    } catch (err) {
      S.setAgentTranscript(state, {
        agentId,
        turns: [],
        error: err.message || String(err),
      });
    } finally {
      S.setAgentTranscriptBusy(state, false);
      renderAgent();
    }
  }

  /**
   * Relance l'agent sur sa session precedente. Le pilote ne transmet aucun
   * message : c'est une reprise, pas un echange.
   */
  async function resume(agentId) {
    await withErr(async () => {
      await api.continueAgent(state.token, agentId);
      await refreshAll();
      await loadTranscript(agentId);
    });
  }

  function clearSelection() {
    S.setSelectedAgentId(state, null);
    S.setAgentPanel(state, "home");
    S.setShellMode(state, "agent", "detail");
    render();
  }

  function showAgentList() {
    S.setSelectedAgentId(state, null);
    S.setSelectedGardienId(state, null);
    S.setAgentPanel(state, "home");
    S.setShellMode(state, "agent", "list");
    render();
  }

  function showAgentHome() {
    S.setSelectedAgentId(state, null);
    S.setSelectedGardienId(state, null);
    S.setAgentPanel(state, "home");
    S.setAgentCreateForm(state, null);
    S.setAgentCreateError(state, "");
    S.setShellMode(state, "agent", "detail");
    render();
  }

  function setTab(tab) {
    S.setAgentTab(state, tab);
    renderAgent();
    if (tab === "discussion" && state.selectedAgentId) {
      loadTranscript(state.selectedAgentId);
    }
  }

  async function setDaemonPaused(paused) {
    await withErr(async () => {
      await api.setAgentDaemon(state.token, paused);
      await refreshAll();
    });
  }

  async function fire(agentId) {
    await withErr(async () => {
      await api.fireAgent(state.token, agentId);
      await refreshAll();
    });
  }

  async function toggle(agentId) {
    await withErr(async () => {
      await api.toggleAgent(state.token, agentId);
      await refreshAll();
    });
  }

  /**
   * Suspendre ou réactiver un agent de la plateforme.
   *
   * Même route que pour les autres : ce sont les mêmes déclencheurs côté
   * coordinateur. Seule la présentation diffère — on ne propose pas de les
   * modifier ni de les supprimer.
   */
  async function toggleSystemAgent(agentId) {
    await withErr(async () => {
      await api.toggleAgent(state.token, agentId);
      await refreshAll();
    });
  }

  async function remove(agentId) {
    await withErr(async () => {
      await api.deleteAgent(state.token, agentId);
      S.setSelectedAgentId(state, null);
      S.setAgentPanel(state, "home");
      S.setShellMode(state, "agent", "detail");
      await refreshAll();
    });
  }

  async function decide(agentId, actionId, decision) {
    await withErr(async () => {
      // La file unique (S3) : la décision passe par la commande réservée,
      // et va au journal avec son acteur, comme depuis « À valider ».
      await api.deciderAValider(
        `pilote:${agentId}:${actionId}`,
        decision === "reject" ? "refuser" : "accepter"
      );
      await refreshAll();
      ctx.apresDecision?.();
    });
  }

  function profileOptions() {
    const profiles = state.mcpProfiles;
    const opts = [{ value: "", label: "Outils de base seulement" }];
    if (!profiles) return opts;
    for (const p of profiles.org || []) {
      opts.push({
        value: `org:${p.id}`,
        label: p.label || p.id,
      });
    }
    for (const p of profiles.custom || []) {
      opts.push({
        value: `custom:${p.id}`,
        label: p.label || p.id,
      });
    }
    return opts;
  }

  function projectOptions() {
    const opts = [{ value: "", label: "Aucun (recommandé)" }];
    for (const p of S.codeProjects(state)) {
      opts.push({
        value: p.slug,
        label: p.title || p.slug,
      });
    }
    return opts;
  }

  async function modelOptions() {
    try {
      const data = await api.listModels(state.token);
      S.setModelsCatalog(state, data);
      const models = data.models || [];
      if (!models.length) {
        return {
          default: data.default || "",
          options: [{ value: "", label: "Modèle par défaut du pod" }],
        };
      }
      return {
        default: data.default || models[0].id,
        options: models.map((m) => ({
          value: m.id,
          label: m.default ? `${m.label} (défaut)` : m.label || m.id,
        })),
      };
    } catch {
      return {
        default: "",
        options: [{ value: "", label: "Modèle par défaut du pod" }],
      };
    }
  }

  function resolveProjectDir(projectValue) {
    if (projectValue) {
      const hit = state.projects.find((p) => p.slug === projectValue);
      return hit?.path || "";
    }
    const slug = S.assistantSlug(state);
    const hit =
      state.projects.find((p) => p.slug === slug) ||
      state.projects.find((p) => p.kind === "assistant");
    return hit?.path || "";
  }

  function patchCreate(partial, { rerender = false } = {}) {
    const cur = state.agentCreateForm || {};
    S.setAgentCreateForm(state, { ...cur, ...partial });
    if (state.agentCreateError) {
      S.setAgentCreateError(state, "");
      // Retire le message sans reconstruire le formulaire.
      document.querySelector(".agent-form-error")?.remove();
    }
    if (rerender) renderAgent();
  }

  async function openCreate() {
    await refreshAgentProfiles(state);
    try {
      await refreshProjects(state);
    } catch {
      /* ignore */
    }
    const models = await modelOptions();
    let builtins = ["Bash", "Read"];
    try {
      const t = await api.agentTools(state.token);
      if (t.builtins?.length) builtins = t.builtins;
    } catch {
      /* on retombe sur le socle minimal */
    }
    let toolsByService = [];
    try {
      await refreshMcpOverview(state);
      toolsByService = (await api.mcpTools(state.token)).services || [];
    } catch {
      /* le pool restera vide dans le sélecteur */
    }
    S.setSelectedAgentId(state, null);
    S.setAgentPanel(state, "create");
    S.setAgentCreateError(state, "");
    S.setAgentCreateBusy(state, false);
    S.setAgentCreateForm(state, {
      name: "",
      desc: "",
      mission: "",
      profile: "",
      project: "",
      freq: "0 8 * * *",
      freqPreset: "0 8 * * *",
      freqCustom: "",
      model: models.default || "",
      modelOptions: models.options,
      profileOptions: profileOptions(),
      projectOptions: projectOptions(),
      builtins,
      toolsByService,
      // Socle de depart : lecture seule, comme le proposeur du pilote.
      toolSelection: new Set(["Bash", "Read"]),
    });
    S.setShellMode(state, "agent", "detail");
    render();
  }

  function cancelCreate() {
    S.setAgentCreateForm(state, null);
    S.setAgentCreateError(state, "");
    S.setAgentPanel(state, "home");
    S.setShellMode(state, "agent", "detail");
    render();
  }

  /**
   * Raccourci : reprend les outils et les consignes d'un profil existant dans
   * le formulaire. L'utilisateur reste libre de les ajuster ensuite.
   */
  /**
   * Ouvre le formulaire sur un agent existant. Le remplacement en place
   * conserve son historique et sa session ; les outils sont relus depuis
   * `scope.servers`, la selection telle qu'elle a ete enregistree.
   */
  async function openEdit(agent) {
    if (!agent) return;
    await refreshAgentProfiles(state);
    try {
      await refreshProjects(state);
    } catch {
      /* ignore */
    }
    const models = await modelOptions();
    let builtins = ["Bash", "Read"];
    try {
      const t = await api.agentTools(state.token);
      if (t.builtins?.length) builtins = t.builtins;
    } catch {
      /* socle minimal */
    }
    let toolsByService = [];
    try {
      await refreshMcpOverview(state);
      toolsByService = (await api.mcpTools(state.token)).services || [];
    } catch {
      /* pool vide */
    }
    const servers = agent.scope?.servers;
    const mission = Array.isArray(agent.mission)
      ? agent.mission.join(String.fromCharCode(10))
      : String(agent.mission || "");
    const projet = state.projects.find((p) => p.path === agent.scope?.dir);
    S.setAgentPanel(state, "create");
    S.setAgentCreateError(state, "");
    S.setAgentCreateBusy(state, false);
    S.setAgentCreateForm(state, {
      editId: agent.id,
      editName: agent.name || agent.id,
      name: agent.name || "",
      desc: agent.desc || "",
      mission,
      profile: "",
      project: projet?.slug || "",
      dir: agent.scope?.dir || "",
      freq: agent.cron || "0 8 * * *",
      freqPreset: agent.cron || "0 8 * * *",
      freqCustom: agent.cron || "",
      model: agent.memory?.budget || models.default || "",
      modelOptions: models.options,
      profileOptions: profileOptions(),
      projectOptions: projectOptions(),
      builtins,
      toolsByService,
      toolSelection: new Set(
        Array.isArray(servers) && servers.length ? servers : ["Bash", "Read"]
      ),
    });
    S.setShellMode(state, "agent", "detail");
    render();
  }

  /** Fige des paramètres d'un outil, puis coche la variante obtenue. */
  async function personnaliserOutil(outil) {
    await ouvrirVariante({
      state,
      outil,
      render,
      onCreated: async (creee) => {
        // On vient de la fabriquer depuis ce formulaire : la cocher évite
        // de la créer puis d'oublier de s'en servir.
        if (creee?.tool) {
          state.agentCreateForm?.toolSelection?.add(creee.tool);
        }
        try {
          await refreshMcpOverview(state);
          const cur = state.agentCreateForm || {};
          S.setAgentCreateForm(state, {
            ...cur,
            toolsByService: (await api.mcpTools(state.token)).services || [],
          });
        } catch {
          /* la variante existe même si le rafraîchissement échoue */
        }
        renderAgent();
      },
    });
  }

  async function applyProfile(valeur) {
    const form = state.agentCreateForm || {};
    const [kind, id] = String(valeur || "").split(":");
    S.setAgentCreateForm(state, { ...form, profile: valeur || "" });
    if (!kind || !id) {
      renderAgent();
      return;
    }
    try {
      const bindings = await api.getProfilePiloteBindings(state.token, kind, id);
      const sel = new Set(bindings.tools?.length ? bindings.tools : ["Bash", "Read"]);
      const cur = state.agentCreateForm || {};
      const mission =
        bindings.mission_prefix && !cur.mission ? bindings.mission_prefix : cur.mission;
      S.setAgentCreateForm(state, { ...cur, toolSelection: sel, mission });
    } catch (err) {
      S.setAgentCreateError(state, err.message || String(err));
    }
    renderAgent();
  }

  async function submitCreate() {
    const data = state.agentCreateForm || {};
    if (!String(data.name || "").trim()) {
      S.setAgentCreateError(state, "Indiquez un nom.");
      renderAgent();
      return;
    }
    const freq =
      data.freqPreset === "__custom__"
        ? String(data.freqCustom || data.freq || "").trim()
        : String(data.freq || data.freqPreset || "0 8 * * *").trim();
    if (!freq || freq.split(/\s+/).length !== 5) {
      S.setAgentCreateError(
        state,
        "Indiquez une fréquence valide (5 champs cron) ou choisissez un preset."
      );
      renderAgent();
      return;
    }

    S.setAgentCreateBusy(state, true);
    S.setAgentCreateError(state, "");
    renderAgent();

    try {
      // La selection cochee fait foi. Un profil n'est qu'un raccourci de
      // pre-remplissage (voir applyProfile), pas une indirection ici.
      let tools = [...(data.toolSelection || new Set())];
      if (!tools.length) tools = ["Bash", "Read"];
      const mission = data.mission || "";
      const [profile_kind = "", profile_id = ""] = String(data.profile || "").split(":");
      const dir = data.editId
        ? data.dir || resolveProjectDir(data.project)
        : resolveProjectDir(data.project);
      if (!dir) {
        throw new Error(
          "Espace de travail introuvable. Créez d’abord un projet dans Code."
        );
      }
      const created = await api.createAgent(state.token, {
        ...(data.editId ? { id: data.editId } : {}),
        name: data.name.trim(),
        desc: data.desc || "",
        dir,
        freq,
        model: data.model || "",
        mission,
        tools,
        profile_kind,
        profile_id,
      });
      S.setAgentCreateForm(state, null);
      S.setAgentCreateBusy(state, false);
      S.setError(state, "");
      await refreshPiloteOverview(state);
      const newId = created?.id || created?.agent?.id;
      if (newId) {
        S.setSelectedAgentId(state, newId);
        S.setAgentPanel(state, "detail");
        S.setAgentTab(state, "settings");
      } else {
        S.setAgentPanel(state, "home");
      }
      S.setShellMode(state, "agent", "detail");
      render();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setAgentCreateBusy(state, false);
      S.setAgentCreateError(state, err.message || String(err));
      renderAgent();
    }
  }

  /** @deprecated alias */
  const openCreateModal = openCreate;

  return {
    select,
    clearSelection,
    showAgentList,
    showAgentHome,
    setTab,
    loadTranscript,
    resume,
    setDaemonPaused,
    fire,
    toggle,
    toggleSystemAgent,
    remove,
    decide,
    openCreate,
    openCreateModal,
    cancelCreate,
    patchCreate,
    applyProfile,
    personnaliserOutil,
    openEdit,
    submitCreate,
    refreshAll,
  };
}
