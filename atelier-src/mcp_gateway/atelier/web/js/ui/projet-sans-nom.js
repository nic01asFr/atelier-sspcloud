/**
 * Les projets « sans nom » d'avant la fenêtre « Nouveau projet ».
 *
 * Le bouton créait un dossier « Projet sans nom » dont le nom passait en édition.
 * Il ne le fait plus (le nom se donne avant la création), mais ceux qui existent
 * déjà prennent le nom de leur premier message, comme un projet créé à l'envoi.
 */

export const TITRE_PAR_DEFAUT = "Projet sans nom";

/** Le projet porte-t-il encore le nom de départ, jamais choisi par la personne ? */
export function estSansNom(projet) {
  if (!projet) return false;
  const titre = String(projet.title || "").trim();
  return titre === TITRE_PAR_DEFAUT || (!titre && /^projet-sans-nom(-\d+)?$/.test(String(projet.slug || "")));
}

/**
 * Le titre à donner au projet quand le premier message part, ou "" s'il n'y a
 * rien à changer (un nom choisi par la personne ne se touche jamais).
 */
export function titreAuPremierMessage(projet, texte, nomDuMessage) {
  if (!estSansNom(projet)) return "";
  return nomDuMessage(texte) || "";
}
