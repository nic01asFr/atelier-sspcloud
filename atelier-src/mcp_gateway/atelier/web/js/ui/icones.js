/**
 * Les icônes de l'interface : un seul jeu, dessiné au trait.
 *
 * L'interface montrait des emoji en guise d'icônes (dossier, clé, sablier,
 * coche, loupe) : leur rendu change d'un système à l'autre, leur taille ne
 * suit pas le texte, et ils ne prennent pas la couleur du thème. Chaque icône
 * est ici un tracé SVG de 24 unités, au trait de 2, qui prend la couleur du
 * texte (`currentColor`) et la taille de la police (`1em`).
 *
 * Règle : une icône seule dans un bouton porte un `aria-label` sur le bouton ;
 * l'icône elle-même est toujours décorative (`aria-hidden`).
 */

const TRACES = {
  dossier: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  "chevron-droite": '<path d="m9 6 6 6-6 6"/>',
  "chevron-bas": '<path d="m6 9 6 6 6-6"/>',
  "fleche-gauche": '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
  "fleche-droite": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  points: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  trombone:
    '<path d="m20 11.5-8.2 8.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/>',
  engrenage:
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  fichier: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  crayon: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  terminal: '<path d="m5 8 4 4-4 4"/><path d="M12 17h7"/>',
  loupe: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"/>',
  outil:
    '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3.6 17.4a1.4 1.4 0 0 0 2 2l5.7-5.7a4 4 0 0 0 5.4-5.4l-2.5 2.5-2-.5-.5-2z"/>',
  agent: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 7V4"/><circle cx="9" cy="13" r="1"/><circle cx="15" cy="13" r="1"/>',
  liste: '<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="m3.5 6 1 1 2-2"/><path d="m3.5 12 1 1 2-2"/><path d="m3.5 18 1 1 2-2"/>',
  coche: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  croix: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
  horloge: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  interdit: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  alerte: '<path d="M12 3 2 20h20z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
  question: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.3"/><path d="M12 17h.01"/>',
  reflexion: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z"/>',
  copier: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  relancer: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>',
  envoyer: '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
  arret: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  micro: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
  lien: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  panneau: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M14 4v16"/>',
  detacher: '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  cle: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9"/><path d="m17 6 3 3"/>',
};

/** Les noms connus, pour les tests et pour le guide. */
export const NOMS_ICONES = Object.freeze(Object.keys(TRACES));

/** Le balisage SVG d'une icône ; une icône inconnue rend l'outil générique. */
export function svgIcone(nom) {
  const trace = TRACES[nom] || TRACES.outil;
  return (
    '<svg class="icone-svg" viewBox="0 0 24 24" width="1em" height="1em" fill="none" '
    + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    + `aria-hidden="true" focusable="false">${trace}</svg>`
  );
}

/**
 * Une icône prête à poser dans un nœud : un `<span class="icone">`.
 *
 * @param {string} nom
 * @param {string} [classe] classe de plus, pour la placer
 */
export function icone(nom, classe = "") {
  const span = document.createElement("span");
  span.className = classe ? `icone icone-${nom} ${classe}` : `icone icone-${nom}`;
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = svgIcone(nom);
  return span;
}
