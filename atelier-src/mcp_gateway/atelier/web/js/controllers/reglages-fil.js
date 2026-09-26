/**
 * « Détails techniques » : les deux réglages d'affichage du fil.
 *
 * Une icône engrenage dans la barre de conversation ouvre un petit panneau à
 * deux cases, décochées par défaut : montrer le raisonnement de l'agent,
 * montrer ses actions et leurs résultats bruts. Ils valent pour Code et pour
 * l'Assistant, et sont retenus par le service (`PUT /v1/meta`), pour suivre
 * la personne d'un appareil à l'autre.
 *
 * Le panneau se referme par Échap, par un clic ailleurs, ou par l'engrenage ;
 * le focus revient alors à l'engrenage.
 */

import { poserReglagesDuFil, reglagesDuFil } from "../ui/etapes.js";

/** Les réglages tels que le service les rend dans `meta.ui`. */
export function reglagesDepuisMeta(meta) {
  const ui = meta?.ui || {};
  return { raisonnement: ui.fil_raisonnement === true, actions: ui.fil_actions === true };
}

/**
 * @param {object} ctx
 * @param {object} ctx.api — `enregistrerReglagesFil`
 * @param {() => void} ctx.rendreLeFil
 * @param {(msg: string) => void} ctx.erreur
 * @param {Document} [ctx.doc]
 */
export function createReglagesFil(ctx) {
  const doc = ctx.doc || document;
  const $ = (id) => doc.getElementById(id);

  function synchroniserCases() {
    const r = reglagesDuFil();
    const raisonnement = $("reglage-raisonnement");
    const actions = $("reglage-actions");
    if (raisonnement) raisonnement.checked = r.raisonnement;
    if (actions) actions.checked = r.actions;
  }

  function ouvert() {
    return !$("reglages-fil")?.hidden;
  }

  function basculer(ouvrir) {
    const panneau = $("reglages-fil");
    const bouton = $("btn-reglages-fil");
    if (!panneau || !bouton) return;
    const voulu = ouvrir ?? panneau.hidden;
    panneau.hidden = !voulu;
    bouton.setAttribute("aria-expanded", voulu ? "true" : "false");
    if (voulu) {
      synchroniserCases();
      $("reglage-raisonnement")?.focus();
    }
  }

  function fermer({ rendreLeFocus = false } = {}) {
    if (!ouvert()) return;
    basculer(false);
    if (rendreLeFocus) $("btn-reglages-fil")?.focus();
  }

  /** Pose les réglages, redessine le fil, puis les retient côté service. */
  async function changer(partiel) {
    const avant = { ...reglagesDuFil() };
    poserReglagesDuFil(partiel);
    ctx.rendreLeFil();
    try {
      await ctx.api.enregistrerReglagesFil(partiel);
    } catch (err) {
      // Non retenu : l'affichage revient à ce qui est enregistré, et on le dit.
      poserReglagesDuFil(avant);
      synchroniserCases();
      ctx.rendreLeFil();
      ctx.erreur(`Réglage non enregistré : ${err?.message || err}`);
    }
  }

  function bind() {
    $("btn-reglages-fil")?.addEventListener("click", (e) => {
      e.stopPropagation();
      basculer();
    });
    $("reglage-raisonnement")?.addEventListener("change", (e) => changer({ raisonnement: !!e.target.checked }));
    $("reglage-actions")?.addEventListener("change", (e) => changer({ actions: !!e.target.checked }));
    $("reglages-fil")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        fermer({ rendreLeFocus: true });
      }
    });
    doc.addEventListener("click", (e) => {
      const zone = $("reglages-fil-zone");
      if (ouvert() && zone && !zone.contains(e.target)) fermer();
    });
  }

  /** À l'entrée : les réglages retenus par le service. */
  function appliquerMeta(meta) {
    poserReglagesDuFil(reglagesDepuisMeta(meta));
    synchroniserCases();
  }

  return { bind, appliquerMeta, changer, basculer, fermer };
}
