/**
 * Le thème de l'interface : suivre le système (défaut), clair ou sombre.
 *
 * Retenu par personne, par le service (`PUT /v1/meta`, `theme`), comme les
 * réglages du fil. Ce navigateur en garde une copie (`atelier.theme`) que
 * `theme-initial.js` applique avant le premier rendu, pour qu'aucun éclair
 * du mauvais thème ne passe au chargement.
 *
 * Le choix se fait dans « Affichage » (en-tête) : un petit panneau à trois
 * choix, qui se referme par Échap, un clic ailleurs ou son bouton.
 */

export const THEMES = Object.freeze(["systeme", "clair", "sombre"]);
const CLE_LOCALE = "atelier.theme";

/** Un choix valable, ou « systeme ». */
export function themeValable(choix) {
  const c = String(choix || "").trim().toLowerCase();
  return THEMES.includes(c) ? c : "systeme";
}

/** Le thème tel que le service le rend dans `meta.ui` (absent : le système). */
export function themeDepuisMeta(meta) {
  return themeValable(meta?.ui?.theme);
}

/**
 * Applique un thème à la page, et en garde la copie locale.
 *
 * @param {string} choix
 * @param {Document} [doc]
 * @param {Storage} [stockage]
 */
export function appliquerTheme(choix, doc = globalThis.document, stockage = globalThis.localStorage) {
  const theme = themeValable(choix);
  const racine = doc?.documentElement;
  if (racine) {
    if (theme === "systeme") racine.removeAttribute("data-theme");
    else racine.setAttribute("data-theme", theme);
  }
  try {
    if (theme === "systeme") stockage?.removeItem(CLE_LOCALE);
    else stockage?.setItem(CLE_LOCALE, theme);
  } catch {
    /* stockage refusé : le thème vaut pour cette page */
  }
  return theme;
}

/**
 * @param {object} ctx
 * @param {object} ctx.api — `enregistrerTheme`
 * @param {(msg: string) => void} ctx.erreur
 * @param {Document} [ctx.doc]
 */
export function createTheme(ctx) {
  const doc = ctx.doc || document;
  const $ = (id) => doc.getElementById(id);
  let courant = "systeme";

  function cocher() {
    for (const radio of doc.querySelectorAll('input[name="theme"]')) {
      radio.checked = radio.value === courant;
    }
  }

  function ouvert() {
    return !$("affichage")?.hidden;
  }

  function basculer(ouvrir) {
    const panneau = $("affichage");
    const bouton = $("btn-affichage");
    if (!panneau || !bouton) return;
    const voulu = ouvrir ?? panneau.hidden;
    panneau.hidden = !voulu;
    bouton.setAttribute("aria-expanded", voulu ? "true" : "false");
    if (voulu) {
      cocher();
      doc.querySelector('input[name="theme"]:checked')?.focus();
    }
  }

  function fermer({ rendreLeFocus = false } = {}) {
    if (!ouvert()) return;
    basculer(false);
    if (rendreLeFocus) $("btn-affichage")?.focus();
  }

  /** Change de thème tout de suite, puis le retient ; revient en arrière si refusé. */
  async function choisir(choix) {
    const avant = courant;
    courant = appliquerTheme(choix, doc);
    cocher();
    try {
      await ctx.api.enregistrerTheme(courant);
    } catch (err) {
      courant = appliquerTheme(avant, doc);
      cocher();
      ctx.erreur(`Thème non enregistré : ${err?.message || err}`);
    }
  }

  function bind() {
    $("btn-affichage")?.addEventListener("click", (e) => {
      e.stopPropagation();
      basculer();
    });
    for (const radio of doc.querySelectorAll('input[name="theme"]')) {
      radio.addEventListener("change", () => {
        if (radio.checked) choisir(radio.value);
      });
    }
    $("affichage")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        fermer({ rendreLeFocus: true });
      }
    });
    doc.addEventListener("click", (e) => {
      const zone = $("affichage-zone");
      if (ouvert() && zone && !zone.contains(e.target)) fermer();
    });
  }

  /** À l'entrée : le thème retenu par le service fait foi. */
  function appliquerMeta(meta) {
    courant = appliquerTheme(themeDepuisMeta(meta), doc);
    cocher();
  }

  return { bind, appliquerMeta, choisir, fermer, basculer };
}
