/**
 * Où en est le tour de la conversation affichée.
 *
 * Plusieurs conversations peuvent tourner à la fois ; l'écran n'en montre
 * qu'une. Ce qui compte pour le bouton « Arrêter » et pour le libellé du
 * bouton d'envoi, c'est donc l'état de CELLE-LÀ : son propre flux dans cet
 * onglet (`state.busy`), ou un tour lancé ailleurs — un autre onglet, VS
 * Code, un agent — que dit la liste des conversations (`running`).
 */
export function tourDeLaConversation(state) {
  const fiche = (state?.sessions || []).find((s) => s.session_id === state?.sessionId);
  const ici = !!state?.busy;
  const ailleurs = !ici && fiche?.state === "running";
  return { ici, ailleurs, enCours: ici || ailleurs };
}
