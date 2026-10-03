/**
 * Régler les connecteurs avant le premier message.
 *
 * Une conversation neuve n'existe pas encore : le « + » montre ce qu'elle
 * recevra (l'aperçu du service), la personne coche, et les choix attendent, côté
 * écran, jusqu'à la naissance de la conversation. Rien n'est écrit avant.
 */

/** Les lignes de l'aperçu, avec les choix en attente par-dessus (`{ id: bool }`). */
export function fusionnerLesChoix(connecteurs, enAttente) {
  const liste = Array.isArray(connecteurs) ? connecteurs : [];
  const choix = enAttente && typeof enAttente === "object" ? enAttente : {};
  return liste.map((c) => (Object.prototype.hasOwnProperty.call(choix, c.id) ? { ...c, active: !!choix[c.id] } : c));
}

/** Ce qui part à la création : seuls les choix qui changent quelque chose. */
export function choixAEnvoyer(connecteurs, enAttente) {
  const choix = enAttente && typeof enAttente === "object" ? enAttente : {};
  const parId = new Map((connecteurs || []).map((c) => [c.id, c]));
  const sortie = {};
  for (const [id, active] of Object.entries(choix)) {
    const ligne = parId.get(id);
    if (ligne && ligne.fixe) continue;
    if (ligne && !!ligne.active === !!active) continue; // déjà tel quel
    sortie[id] = !!active;
  }
  return sortie;
}

/** Peut-on régler les connecteurs d'une conversation qui n'existe pas encore ? */
export function apercuPossible(state) {
  if (!state?.token || state.view !== "code" || state.sessionId) return false;
  return state.espace === "assistant" || !!(state.slug || state.pendingProjectSlug);
}
