/** Connecteurs MCP — sélection, toggle, import, suppression. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { refreshMcpOverview } from "../services/catalog.js";
import { openModal } from "../ui/modal.js";
import { ouvrirVariante } from "../ui/tool-variant.js";
import { etapeVierge } from "../views/composition-builder.js";

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

  // ---- Fabrique d'une composition ------------------------------------

  function ouvrirBuilder() {
    S.setSelectedCompositionId(state, null);
    S.setSelectedConnectorId(state, null);
    S.setCompositionDraft(state, {
      name: "",
      description: "",
      steps: [etapeVierge()],
      erreur: "",
    });
    S.setConnectorPanel(state, "composer");
    S.setShellMode(state, "connecteurs", "detail");
    render();
  }

  function majBrouillon(champs) {
    const d = state.compositionDraft;
    if (!d) return;
    Object.assign(d, champs, { erreur: "" });
    // Pas de rendu ici : réécrire le formulaire à chaque frappe ferait
    // perdre le curseur. Seul l'état du bouton d'envoi en dépend.
    majBoutonEnvoi();
  }

  function majEtape(i, champs) {
    const d = state.compositionDraft;
    if (!d?.steps?.[i]) return;
    Object.assign(d.steps[i], champs, { erreur: "" });
    majBoutonEnvoi();
  }

  /** Le seul élément dont l'aspect dépend de la saisie en cours. */
  function majBoutonEnvoi() {
    const d = state.compositionDraft;
    const btn = [...document.querySelectorAll("#connectors-detail-body button")].find(
      (b) => b.textContent === "Enregistrer en brouillon"
    );
    if (!btn || !d) return;
    btn.disabled =
      !String(d.name || "").trim() ||
      !(d.steps || []).some((e) => String(e.tool || "").trim());
  }

  function ajouterEtape() {
    state.compositionDraft?.steps.push(etapeVierge());
    render();
  }

  function retirerEtape(i) {
    const d = state.compositionDraft;
    if (!d || d.steps.length <= 1) return;
    d.steps.splice(i, 1);
    render();
  }

  function deplacerEtape(i, sens) {
    const d = state.compositionDraft;
    const j = i + sens;
    if (!d || j < 0 || j >= d.steps.length) return;
    [d.steps[i], d.steps[j]] = [d.steps[j], d.steps[i]];
    render();
  }

  function annulerComposition() {
    S.setCompositionDraft(state, null);
    S.setConnectorPanel(state, "detail");
    S.setSelectedConnectorId(state, "atelier:compositions");
    render();
  }

  async function enregistrerComposition() {
    const d = state.compositionDraft;
    if (!d) return;
    // Les paramètres sont saisis en JSON : on le dit à l'étape fautive
    // plutôt qu'en bas du formulaire, où l'utilisateur devrait chercher.
    const steps = [];
    let fautive = false;
    d.steps.forEach((e, i) => {
      if (!String(e.tool || "").trim()) return;
      let parametres = {};
      const brut = String(e.parametersTexte ?? "{}").trim() || "{}";
      try {
        parametres = JSON.parse(brut);
        if (parametres === null || typeof parametres !== "object" || Array.isArray(parametres)) {
          throw new Error("attendu un objet");
        }
      } catch (err) {
        e.erreur = "Paramètres illisibles : " + (err.message || err);
        fautive = true;
        return;
      }
      steps.push({ tool: e.tool.trim(), label: (e.label || "").trim(), parameters: parametres });
    });
    if (fautive) return render();
    if (!steps.length) {
      d.erreur = "Aucune étape utilisable : renseignez au moins un outil.";
      return render();
    }
    try {
      const cree = await api.createComposition(state.token, {
        name: d.name.trim(),
        description: d.description.trim(),
        steps,
      });
      S.setCompositionDraft(state, null);
      S.setConnectorPanel(state, "detail");
      await refreshAll();
      if (cree?.id) await selectComposition(cree.id);
    } catch (err) {
      if (err.status === 401) return logout("Clé invalide");
      d.erreur = err.message || String(err);
      render();
    }
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
    ouvrirBuilder,
    majBrouillon,
    majEtape,
    ajouterEtape,
    retirerEtape,
    deplacerEtape,
    annulerComposition,
    enregistrerComposition,
  };
}
