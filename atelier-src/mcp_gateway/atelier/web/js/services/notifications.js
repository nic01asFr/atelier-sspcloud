/**
 * Les notifications côté navigateur : ce qu'on sait faire, ce qu'on dit quand on ne sait pas.
 *
 * Ce module ne touche pas au DOM. Il décide de la situation de l'appareil —
 * activée, à activer, bloquée, impossible — et du mot juste pour chacune, parce
 * que c'est là que se joue le « grand public » : une notification qui ne
 * marche pas sans qu'on sache pourquoi est pire qu'une absence de notification.
 */

/** La clé publique (base64url) sous la forme que `pushManager.subscribe` attend. */
export function cleVersOctets(base64url) {
  const rempli = String(base64url || "").replace(/-/g, "+").replace(/_/g, "/");
  const complet = rempli + "=".repeat((4 - (rempli.length % 4)) % 4);
  const binaire = atob(complet);
  const octets = new Uint8Array(binaire.length);
  for (let i = 0; i < binaire.length; i += 1) octets[i] = binaire.charCodeAt(i);
  return octets;
}

/** Un nom que la personne reconnaît dans la liste de ses appareils. */
export function nomDeLAppareil(ua = "") {
  const texte = String(ua);
  const systeme = /iPhone/i.test(texte)
    ? "iPhone"
    : /iPad/i.test(texte)
      ? "iPad"
      : /Android/i.test(texte)
        ? "Android"
        : /Windows/i.test(texte)
          ? "Windows"
          : /Mac OS X|Macintosh/i.test(texte)
            ? "Mac"
            : /Linux|X11/i.test(texte)
              ? "Linux"
              : "Appareil";
  const navigateur = /Edg\//i.test(texte)
    ? "Edge"
    : /OPR\/|Opera/i.test(texte)
      ? "Opera"
      : /Firefox\//i.test(texte)
        ? "Firefox"
        : /Chrome\//i.test(texte)
          ? "Chrome"
          : /Safari\//i.test(texte)
            ? "Safari"
            : "";
  return navigateur ? `${systeme} · ${navigateur}` : systeme;
}

/**
 * Où en est cet appareil.
 *
 * @param {{
 *   serveur: boolean,            // le service sait envoyer (pywebpush, clés)
 *   supporte: boolean,           // service worker + Push + Notification présents
 *   ios: boolean,                // iPhone ou iPad
 *   installee: boolean,          // lancée depuis l'écran d'accueil
 *   permission: string,          // « default », « granted », « denied »
 *   abonne: boolean,             // une inscription existe sur cet appareil
 * }} entree
 * @returns {{ etat: string, message: string }}
 */
export function situation({ serveur, supporte, ios, installee, permission, abonne }) {
  if (!serveur) {
    return {
      etat: "indisponible",
      message: "Les notifications ne sont pas disponibles sur ce service pour le moment.",
    };
  }
  if (ios && !installee) {
    return {
      etat: "installer",
      message:
        "Sur iPhone et iPad, il faut d’abord ajouter l’Atelier à l’écran d’accueil : touchez « Partager », puis « Sur l’écran d’accueil ». Rouvrez ensuite l’Atelier depuis cette icône.",
    };
  }
  if (!supporte) {
    return {
      etat: "non_supporte",
      message: "Ce navigateur ne sait pas envoyer de notifications. Essayez avec Chrome, Edge, Firefox ou Safari récent.",
    };
  }
  if (permission === "denied") {
    return {
      etat: "bloque",
      message:
        "Les notifications sont bloquées pour ce site. Autorisez-les dans les réglages du navigateur (le cadenas à côté de l’adresse), puis revenez ici.",
    };
  }
  if (permission === "granted" && abonne) {
    return { etat: "actif", message: "Cet appareil sera prévenu." };
  }
  return { etat: "inactif", message: "Cet appareil n’est pas prévenu." };
}

/** Le texte qui dit ce que fait la fenêtre de silence, ou rien si elle est coupée. */
export function resumeDesHeuresCalmes(calme) {
  if (!calme?.actif) return "";
  return `De ${calme.de} à ${calme.a} : pas de son ni de vibration, les notifications restent lisibles.`;
}
