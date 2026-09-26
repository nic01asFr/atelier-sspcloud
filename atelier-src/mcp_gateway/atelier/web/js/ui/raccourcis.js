/**
 * Les raccourcis clavier de l'Atelier. Peu nombreux, et documentés dans
 * `docs/ui/guide-interface.md` :
 *
 *   /        aller au composeur (hors d'un champ de saisie)
 *   Alt+N    nouvelle conversation (Code ou Assistant, selon l'écran)
 *   Échap    refermer le panneau ou le menu ouvert
 *   Entrée   envoyer ; Maj+Entrée pour aller à la ligne (dans le composeur)
 *
 * Aucun raccourci ne se déclenche pendant qu'on écrit dans un champ, sauf
 * Échap, qui ne fait que refermer.
 */

/** La cible est-elle un endroit où l'on écrit ? */
export function onEcrit(cible) {
  if (!cible) return false;
  const balise = String(cible.tagName || "").toLowerCase();
  if (balise === "textarea" || balise === "select") return true;
  if (balise === "input") {
    const type = String(cible.type || "text").toLowerCase();
    return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"].includes(type);
  }
  return cible.isContentEditable === true;
}

/**
 * Ce que vaut une touche, sans rien faire : le nom du geste, ou "".
 *
 * @param {{ key: string, altKey?: boolean, ctrlKey?: boolean, metaKey?: boolean, target?: unknown }} ev
 */
export function gesteDuClavier(ev) {
  if (ev.key === "Escape") return "fermer";
  if (ev.ctrlKey || ev.metaKey) return "";
  if (ev.altKey && String(ev.key).toLowerCase() === "n") return "nouvelle";
  if (onEcrit(ev.target)) return "";
  if (ev.key === "/" && !ev.altKey) return "composeur";
  return "";
}

/**
 * @param {object} ctx
 * @param {object} ctx.state
 * @param {() => void} ctx.nouvelleConversation
 * @param {() => void} ctx.fermerLesPanneaux
 * @param {Document} [ctx.doc]
 */
export function installerRaccourcis(ctx) {
  const doc = ctx.doc || document;
  doc.addEventListener("keydown", (ev) => {
    const geste = gesteDuClavier(ev);
    if (!geste || !ctx.state.token) return;
    if (geste === "fermer") {
      ctx.fermerLesPanneaux?.();
      return;
    }
    if (ctx.state.view !== "code") return;
    if (geste === "composeur") {
      const champ = doc.getElementById("composer-input");
      if (champ && !champ.disabled) {
        ev.preventDefault();
        champ.focus();
      }
    } else if (geste === "nouvelle") {
      ev.preventDefault();
      ctx.nouvelleConversation?.();
      doc.getElementById("composer-input")?.focus();
    }
  });
}
