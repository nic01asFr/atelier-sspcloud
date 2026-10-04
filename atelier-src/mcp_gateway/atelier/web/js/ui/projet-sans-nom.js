/**
 * Le projet « sans nom » que crée le bouton « Nouveau projet ».
 *
 * Le dossier naît tout de suite, son nom passe en édition ; la conversation, elle,
 * ne naît qu'au premier message. Deux choses manquaient : un projet jamais
 * renommé gardait « Projet sans nom » même après le premier message (alors que
 * sans dossier préexistant, le projet prend le nom du message), et chaque clic
 * sur « Nouveau projet » en laissait un de plus (`projet-sans-nom-8`).
 */

export const TITRE_PAR_DEFAUT = "Projet sans nom";

/** Le projet porte-t-il encore le nom de départ, jamais choisi par la personne ? */
export function estSansNom(projet) {
  if (!projet) return false;
  const titre = String(projet.title || "").trim();
  return titre === TITRE_PAR_DEFAUT || (!titre && /^projet-sans-nom(-\d+)?$/.test(String(projet.slug || "")));
}

/** Un projet sans nom, vide et rangé nulle part : « Nouveau projet » le reprend au lieu d'en créer un autre. */
export function projetVideReutilisable(state) {
  const occupes = new Set((state.sessions || []).map((s) => s.slug));
  return (state.projects || []).find((p) => estSansNom(p) && !p.archived && !occupes.has(p.slug)) || null;
}

/**
 * Le titre à donner au projet quand le premier message part, ou "" s'il n'y a
 * rien à changer (un nom choisi par la personne ne se touche jamais).
 */
export function titreAuPremierMessage(projet, texte, nomDuMessage) {
  if (!estSansNom(projet)) return "";
  return nomDuMessage(texte) || "";
}
