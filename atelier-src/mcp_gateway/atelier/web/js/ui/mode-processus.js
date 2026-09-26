/**
 * Ce que vaut un changement de mode, d'après les processus vivants.
 *
 * `GET /v1/sessions/{id}/processus` (équipe L) dit si un onglet VS Code de la
 * conversation tourne encore : il garde son mode jusqu'à sa fermeture. On le
 * dit près du sélecteur, sobrement, et l'on marque l'écart quand le processus
 * vivant est plus permissif que le mode choisi.
 */

const LIBELLES = {
  plan: "Plan",
  default: "Demande",
  acceptEdits: "Édite",
  bypassPermissions: "Sans garde-fou",
};

// Du plus prudent au plus permissif.
const ORDRE = ["plan", "default", "acceptEdits", "bypassPermissions"];

export function libelleMode(mode) {
  return LIBELLES[mode] || String(mode || "—");
}

/** Plus permissif : plus loin dans l'ordre. Un mode inconnu ne compte pas. */
export function plusPermissif(a, b) {
  const ia = ORDRE.indexOf(a);
  const ib = ORDRE.indexOf(b);
  return ia >= 0 && ib >= 0 && ia > ib;
}

/**
 * `{texte, alerte}` à afficher, ou null s'il n'y a rien à dire.
 * `alerte` : un processus vivant agit avec plus de liberté que le mode choisi.
 */
export function noteDuMode(processus) {
  if (!processus) return null;
  const morceaux = [];
  if (processus.note) morceaux.push(String(processus.note));
  let alerte = false;
  const ecart = processus.ecart;
  if (ecart && ecart.vivant && ecart.choisi && ecart.vivant !== ecart.choisi) {
    alerte = plusPermissif(ecart.vivant, ecart.choisi);
    morceaux.push(
      alerte
        ? `En attendant, l’onglet ouvert agit encore en « ${libelleMode(ecart.vivant)} », plus permissif que « ${libelleMode(ecart.choisi)} ».`
        : `En attendant, l’onglet ouvert reste en « ${libelleMode(ecart.vivant)} ».`
    );
  }
  if (!morceaux.length) return null;
  return { texte: morceaux.join(" "), alerte };
}

/** Pose la note dans son élément (texte seul, jamais du HTML). */
export function rendreNoteDuMode(el, note) {
  if (!el) return;
  el.hidden = !note;
  el.textContent = note ? note.texte : "";
  el.classList.toggle("composer-mode-note-alerte", !!note?.alerte);
}
