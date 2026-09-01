/** Helpers DOM minimalistes — pas d'état applicatif. */

export const $ = (id) => document.getElementById(id);

/**
 * Rend une ligne de liste actionnable au clavier autant qu'à la souris.
 *
 * Une carte qui porte ses propres boutons ne peut pas être un `<button>` — on
 * n'imbrique pas deux commandes. Elle reste donc un `<li>`, à qui il faut dire
 * ce qu'un bouton dit tout seul : qu'elle se déclenche, qu'on peut l'atteindre
 * par tabulation, et qu'Entrée ou Espace valent un clic.
 *
 * Sans cela la ligne n'existe que pour la souris : ni tabulation, ni lecteur
 * d'écran.
 *
 * @param {HTMLElement} el
 * @param {(e: Event) => void} action
 */
export function rendreActivable(el, action) {
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  el.addEventListener("click", action);
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    // Espace fait défiler la page si on le laisse passer.
    e.preventDefault();
    action(e);
  });
}

export function showBanner(msg) {
  const el = $("banner");
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}
