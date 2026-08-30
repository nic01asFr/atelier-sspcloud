/** Connecteurs MCP — sélection, toggle, import, suppression. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { refreshMcpOverview } from "../services/catalog.js";
import { openModal } from "../ui/modal.js";
import { ouvrirVariante } from "../ui/tool-variant.js";

/**
 * @param {object} ctx
 */
export function createConnectorActions(ctx) {
  const { state, render, renderMcp, logout } = ctx;

  async function refreshAll() {
    await refreshMcpOverview(state);
    await chargerCompositions();
    S.syncShellModeFromSelection(state);
    render();
  }

  async function chargerCompositions() {
    try {
      const j = await api.listCompositions(state.token);
      S.setCompositions(state, j.compositions || []);
    } catch {
      S.setCompositions(state, []);
    }
    // Le classement des services vient de la même source que la sélection
    // d'outils d'un agent : une seule taxonomie pour toute l'application.
    try {
      const t = await api.mcpTools(state.token);
      S.setToolsByService(state, t.services || []);
    } catch {
      S.setToolsByService(state, []);
    }
  }

  async function selectComposition(id) {
    S.setSelectedCompositionId(state, id);
    S.setSelectedConnectorId(state, null);
    S.setConnectorPanel(state, "detail");
    S.setShellMode(state, "connecteurs", "detail");
    state.compositionDetail = null;
    render();
    try {
      state.compositionDetail = await api.getComposition(state.token, id);
    } catch (err) {
      S.setError(state, err.message || String(err));
    }
    render();
  }

  /** Activer une composition la rend appelable ; la désactiver la retire. */
  async function toggleComposition(comp) {
    await withErreur(async () => {
      if (comp.status === "production") {
        await api.actOnComposition(state.token, comp.id, "demote");
      } else {
        const verdict = await api.actOnComposition(state.token, comp.id, "validate");
        if (verdict && verdict.ok === false) {
          throw new Error(
            "validation échouée : " + (verdict.errors || []).join(", ")
          );
        }
        await api.actOnComposition(state.token, comp.id, "promote");
      }
      await chargerCompositions();
      if (state.selectedCompositionId === comp.id) {
        state.compositionDetail = await api.getComposition(state.token, comp.id);
      }
    });
  }

  async function runComposition(comp) {
    await withErreur(async () => {
      const res = await api.actOnComposition(state.token, comp.id, "execute", {
        inputs: {},
      });
      const etat = res?.status || (res?.ok === false ? "échec" : "terminée");
      S.setError(state, `Composition « ${comp.name} » : ${etat}`);
    });
  }

  async function deleteComposition(comp) {
    if (!confirm(`Supprimer la composition « ${comp.name} » ?`)) return;
    await withErreur(async () => {
      await api.deleteComposition(state.token, comp.id);
      if (state.selectedCompositionId === comp.id) {
        S.setSelectedCompositionId(state, null);
        state.compositionDetail = null;
        S.setConnectorPanel(state, "home");
      }
      await chargerCompositions();
    });
  }

  /** Enveloppe commune : une erreur s'affiche, elle n'interrompt pas l'écran. */
  async function withErreur(fn) {
    try {
      S.setError(state, "");
      await fn();
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      S.setError(state, err.message || String(err));
    }
    render();
  }

  function select(kind, id) {
    S.setSelectedCompositionId(state, null);
    S.setSelectedConnectorId(state, `${kind}:${id}`);
    S.setConnectorPanel(state, "detail");
    S.setShellMode(state, "connecteurs", "detail");
    render();
  }

  /**
   * Fabriquer une composition depuis la page Connecteurs.
   *
   * On commence par l'outil : une composition à une étape n'est rien
   * d'autre qu'un outil dont on a figé des paramètres. L'enchaînement de
   * plusieurs étapes viendra s'ajouter ici.
   */
  async function newComposition() {
    if (!state.toolsByService?.length) {
      try {
        S.setToolsByService(state, (await api.mcpTools(state.token)).services || []);
      } catch (err) {
        S.setError(state, err.message || String(err));
        return render();
      }
    }
    // Les compositions déjà fabriquées ne sont pas des points de départ :
    // en composer une sur une autre n'apporterait qu'un niveau d'indirection.
    const outils = [];
    for (const svc of state.toolsByService || []) {
      if (String(svc.key).startsWith("meta:compositions")) continue;
      for (const t of svc.tools || []) {
        outils.push({
          value: t.name,
          label: `${t.label || t.short} — ${svc.label || svc.key}`,
        });
      }
    }
    openModal(state, {
      title: "Nouvelle composition",
      lead: "Choisissez l’outil de départ. Vous figerez ensuite ce qui doit l’être.",
      size: "md",
      submitLabel: "Continuer",
      fields: [
        {
          name: "outil",
          label: "Outil de départ",
          hint: "Tapez pour filtrer parmi les outils disponibles.",
          datalist: outils,
          placeholder: "nom de l’outil",
          required: true,
          full: true,
        },
      ],
      onSubmit: async (data) => {
        const nom = String(data.outil || "").trim();
        const connu = outils.find((o) => o.value === nom || o.label === nom);
        if (!connu) throw new Error("Choisissez un outil de la liste.");
        // La modale suivante doit s'ouvrir sur une pile vide : celle-ci se
        // referme d'elle-même dès que ce rappel a rendu la main.
        setTimeout(
          () =>
            ouvrirVariante({
              state,
              outil: { name: connu.value, short: connu.label },
              render,
              onCreated: async () => {
                await refreshAll();
                S.setSelectedConnectorId(state, "atelier:compositions");
                render();
              },
            }),
          0
        );
      },
    });
  }

  function clearSelection() {
    S.setSelectedConnectorId(state, null);
    S.setConnectorPanel(state, "home");
    S.setShellMode(state, "connecteurs", "list");
    render();
  }

  function showHome() {
    S.setSelectedCompositionId(state, null);
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
    chargerCompositions,
    selectComposition,
    toggleComposition,
    runComposition,
    deleteComposition,
    clearSelection,
    showHome,
    openNew,
    cancelNew,
    toggleMcp,
    deleteMcp,
    importMcp,
    reprobePool,
    newComposition,
  };
}
