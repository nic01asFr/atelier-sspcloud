/**
 * « Nouveau projet » : le nom se donne avant la création.
 *
 * Le bouton créait d'abord un dossier « Projet sans nom », puis passait son nom en
 * édition dans la liste : rien ne s'ouvrait à l'écran, et un projet jamais nommé
 * restait (`projet-sans-nom-8`). Désormais une fenêtre demande le nom, rien n'est
 * créé avant sa validation, et la conversation s'ouvre dans le projet.
 */

export const LONGUEUR_MAX = 80;

function sansAccents(texte) {
  return String(texte || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** Le nom, nettoyé : espaces resserrés, rien d'autre ne change. */
export function nettoyerLeNom(nom) {
  return String(nom || "").replace(/\s+/g, " ").trim();
}

/**
 * Pourquoi ce nom n'est pas bon, en une phrase — ou "" s'il l'est.
 * Les projets rangés comptent : leur nom reste pris.
 */
export function verifierLeNom(nom, projets) {
  const propre = nettoyerLeNom(nom);
  if (!propre) return "Donnez un nom au projet.";
  if (propre.length > LONGUEUR_MAX) return `Le nom est trop long (${LONGUEUR_MAX} caractères au plus).`;
  const cle = sansAccents(propre);
  const pris = (projets || []).some((p) => sansAccents(p.title || p.slug) === cle);
  if (pris) return "Un projet porte déjà ce nom : choisissez-en un autre.";
  return "";
}
