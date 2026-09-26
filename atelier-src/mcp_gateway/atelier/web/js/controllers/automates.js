/**
 * Gardiens et tâches automatiques : lire, choisir, lancer, couper, réactiver.
 *
 * Le service tranche les droits (couper un gardien, activer une tâche : la
 * personne seule) ; ici on n'ajoute que la confirmation d'un geste qui retire
 * un filet, et l'on relit l'état après chaque geste.
 */

import * as S from "../state.js";

/**
 * @param {object} ctx
 * @param {object} ctx.state
 * @param {object} ctx.api  getGardiens, getAutomates, agirSurAutomate
 * @param {() => void} ctx.render
 * @param {() => void} [ctx.renderAgent]
 * @param {(msg: string) => void} [ctx.logout]
 * @param {(msg: string) => boolean} [ctx.confirmer]
 */
export function createAutomatesActions(ctx) {
  const { state, api, render } = ctx;
  const renderAgent = ctx.renderAgent || render;
  const confirmer = ctx.confirmer || ((msg) => globalThis.confirm?.(msg) ?? true);

  function erreur(err) {
    if (err?.status === 401) return ctx.logout?.("Clé invalide");
    S.setError(state, err?.message || String(err));
    render();
  }

  /** Relit gardiens, tâches et lancements ; une source absente n'empêche pas les autres. */
  async function rafraichir() {
    const [gardiens, automates, lancements] = await Promise.allSettled([
      api.getGardiens(),
      api.getAutomates(),
      api.listerLancements ? api.listerLancements({ limite: 30 }) : Promise.resolve(null),
    ]);
    if (gardiens.status === "fulfilled") S.setGardiens(state, gardiens.value);
    else if (gardiens.reason?.status === 401) return erreur(gardiens.reason);
    if (automates.status === "fulfilled") S.setAutomates(state, automates.value);
    if (lancements.status === "fulfilled" && lancements.value) state.lancements = lancements.value;
    if (
      state.selectedGardienId &&
      state.gardiens?.gardiens &&
      !state.gardiens.gardiens.some((g) => g.id === state.selectedGardienId)
    ) {
      S.setSelectedGardienId(state, null);
      if (state.agentPanel === "gardien") S.setAgentPanel(state, "home");
    }
  }

  async function rafraichirEtRendre() {
    await rafraichir();
    renderAgent();
  }

  function choisirGardien(id) {
    S.setSelectedAgentId(state, null);
    S.setSelectedGardienId(state, id);
    S.setAgentPanel(state, "gardien");
    S.setShellMode(state, "agent", "detail");
    render();
    rafraichirEtRendre();
  }

  /** `id` : `gardien.<nom>`, `controle.<id>` ou `trigger.<id>`. */
  async function agir(id, geste) {
    state.automateEnCours = id;
    renderAgent();
    try {
      const fiche = (state.automates?.automates || []).find((a) => a.id === id);
      if (geste === "activer" && fiche?.agent && api.executerCommande) {
        // Un agent du Pilote s'active par la commande réservée : elle vérifie
        // aussi qu'il a un budget lisible avant de le laisser partir seul.
        await api.executerCommande("atelier_agent_activer", { agent: id.replace(/^trigger\./, "") });
      } else {
        await api.agirSurAutomate(id, geste);
      }
      S.setError(state, "");
      await rafraichir();
    } catch (err) {
      erreur(err);
    } finally {
      state.automateEnCours = "";
      renderAgent();
    }
  }

  /** Couper retire un filet : on le dit avant, en clair. */
  async function couper(id, nom) {
    const quoi = id.startsWith("gardien.") ? `le gardien ${String(nom).toLowerCase()}` : `« ${nom} »`;
    const ok = confirmer(
      `Couper ${quoi} ? Il ne vérifiera plus rien jusqu’à ce que vous le réactiviez.`
    );
    if (!ok) return;
    await agir(id, "couper");
  }

  /** Arrêter un agent lancé : ce qu'il a déjà fait reste. */
  async function arreter(id) {
    const ok = confirmer(
      "Arrêter cet agent ? Ce qu’il a déjà fait reste ; une réparation sur branche ne sera pas proposée."
    );
    if (!ok) return;
    state.lancementEnCours = id;
    renderAgent();
    try {
      await api.arreterLancement(id);
      S.setError(state, "");
      await rafraichir();
    } catch (err) {
      erreur(err);
    } finally {
      state.lancementEnCours = "";
      renderAgent();
    }
  }

  const ouvrirProposition = (id) => ctx.ouvrirProposition?.(id);
  const ouvrirConversation = (projet, id) => ctx.ouvrirConversation?.(projet, id);

  return {
    rafraichir,
    rafraichirEtRendre,
    choisirGardien,
    agir,
    couper,
    arreter,
    ouvrirProposition,
    ouvrirConversation,
  };
}
