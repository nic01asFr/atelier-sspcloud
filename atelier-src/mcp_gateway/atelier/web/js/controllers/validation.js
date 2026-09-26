/**
 * « À valider » et le journal : lire, trancher, filtrer, et tenir le badge.
 *
 * Le badge de la navigation se relit à l'entrée, après chaque décision, et
 * toutes les trente secondes tant que l'onglet est visible : une proposition
 * déposée par un gardien doit se voir sans recharger la page.
 */

import * as S from "../state.js";

/**
 * @param {object} ctx
 * @param {object} ctx.state
 * @param {object} ctx.api  listerAValider, deciderAValider, lireJournal
 * @param {() => void} ctx.render
 * @param {() => void} [ctx.renderBadge]
 * @param {(msg: string) => void} [ctx.logout]
 */
export function createValidationActions(ctx) {
  const { state, api, render } = ctx;
  const renderBadge = ctx.renderBadge || render;
  let veille = null;

  /**
   * Le catalogue rend parfois sa raison dans un dict Python recopié
   * (« … : {'erreur': 'projet inconnu : x', 'classe': … } ») : on n'en garde
   * que la phrase.
   */
  function messageLisible(err) {
    const brut = String(err?.message || err || "");
    const m = brut.match(/'erreur': '([^']*)'/);
    if (m) {
      const avant = brut.split(" : {")[0].replace(/\s*\((refus|erreur|apercu)\)/, "");
      return `${avant.charAt(0).toUpperCase()}${avant.slice(1)} : ${m[1]}.`;
    }
    return brut;
  }

  function nonAutorise(err) {
    if (err?.status === 401) {
      ctx.logout?.("Clé invalide");
      return true;
    }
    return false;
  }

  async function rafraichirCompte() {
    try {
      const r = await api.listerAValider({ statut: "en_attente" });
      S.setAValiderCompte(state, r?.resultat?.nombre ?? (r?.resultat?.propositions || []).length);
    } catch (err) {
      if (nonAutorise(err)) return;
      /* le badge garde sa dernière valeur */
    }
    renderBadge();
  }

  async function charger() {
    const statut = state.aValider.statut || "en_attente";
    try {
      const r = await api.listerAValider({ statut });
      const resultat = r?.resultat || {};
      S.patchAValider(state, {
        propositions: resultat.propositions || [],
        note: resultat.note || "",
        charge: true,
      });
      if (statut === "en_attente") {
        S.setAValiderCompte(state, resultat.nombre ?? (resultat.propositions || []).length);
      }
    } catch (err) {
      if (nonAutorise(err)) return;
      S.patchAValider(state, { erreur: err?.message || String(err), charge: true });
    }
    render();
  }

  function statut(valeur) {
    S.patchAValider(state, { statut: valeur, charge: false, ouverte: null, erreur: "" });
    render();
    return charger();
  }

  function ouvrir(id) {
    S.patchAValider(state, { ouverte: id || null });
    render();
  }

  /** Garder la saisie sans redessiner : le champ garde le focus. */
  function motiver(id, texte) {
    S.patchAValider(state, { motifs: { ...state.aValider.motifs, [id]: texte } });
  }

  function preciser(id, chemin, valeur) {
    const courantes = state.aValider.completes || {};
    S.patchAValider(state, {
      completes: { ...courantes, [id]: { ...(courantes[id] || {}), [chemin]: valeur } },
    });
  }

  async function decider(id, decision) {
    S.patchAValider(state, { enCours: id, erreur: "" });
    render();
    try {
      if (decision === "accepter") {
        await api.deciderAValider(id, "accepter", { complete: state.aValider.completes?.[id] || null });
      } else {
        await api.deciderAValider(id, "refuser", { motif: state.aValider.motifs?.[id] || "" });
      }
      const motifs = { ...state.aValider.motifs };
      delete motifs[id];
      S.patchAValider(state, { motifs, ouverte: null });
    } catch (err) {
      if (nonAutorise(err)) return;
      S.patchAValider(state, { erreur: messageLisible(err) });
    } finally {
      S.patchAValider(state, { enCours: "" });
    }
    await charger();
    await rafraichirCompte();
  }

  const accepter = (id) => decider(id, "accepter");
  const refuser = (id) => decider(id, "refuser");

  // ── Journal ───────────────────────────────────────────────────────────

  async function chargerJournal() {
    const f = state.journal.filtres || {};
    try {
      const r = await api.lireJournal({ source: f.source || "", acteur: f.acteur || "", limite: 300 });
      S.patchJournal(state, { evenements: r?.evenements || [], charge: true, erreur: "" });
    } catch (err) {
      if (nonAutorise(err)) return;
      S.patchJournal(state, { erreur: err?.message || String(err), charge: true });
    }
    render();
  }

  /** Le projet se filtre ici ; l'acteur et la source, au service. */
  function filtrer(partiel) {
    const filtres = { ...state.journal.filtres, ...partiel };
    S.patchJournal(state, { filtres });
    if ("acteur" in partiel || "source" in partiel) {
      S.patchJournal(state, { charge: false });
      render();
      return chargerJournal();
    }
    render();
    return Promise.resolve();
  }

  function veiller(intervalleMs = 30000) {
    if (veille) return;
    veille = setInterval(() => {
      if (globalThis.document?.visibilityState === "hidden" || !state.token) return;
      rafraichirCompte();
    }, intervalleMs);
  }

  return {
    rafraichirCompte,
    charger,
    statut,
    ouvrir,
    motiver,
    preciser,
    accepter,
    refuser,
    chargerJournal,
    filtrer,
    recharger: chargerJournal,
    veiller,
  };
}
