/**
 * Dire une erreur en français, avec ce qu'on peut faire.
 *
 * Les erreurs arrivent brutes : `Failed to fetch` du navigateur, `Internal Server
 * Error`, le détail JSON d'un refus, le message anglais d'un service. La personne
 * n'a rien à en tirer. Ici, les cas connus deviennent une phrase qui dit quoi
 * faire ; tout le reste passe tel quel, car un message précis vaut mieux qu'un
 * message vague.
 */

const CAS = [
  [/failed to fetch|networkerror|load failed|network request failed|err_internet|err_network/i,
    "Connexion perdue avec l’Atelier. Vérifiez votre réseau, puis réessayez."],
  [/sse connection error|eventsource/i,
    "Le suivi en direct s’est interrompu. Votre message est peut-être parti : vérifiez la conversation."],
  [/owner key required|invalid.*(key|token)|unauthori[sz]ed|\b401\b/i,
    "Votre session a expiré. Reconnectez-vous avec votre code d’accès."],
  [/session is archived/i,
    "Cette conversation est rangée : sortez-la des archives pour continuer."],
  [/session not found/i,
    "Cette conversation n’existe plus."],
  [/internal server error|bad gateway|service unavailable|gateway time-?out|\b50[0-4]\b/i,
    "L’Atelier a rencontré un problème. Réessayez dans un instant."],
  [/timeout|timed out/i,
    "L’opération a pris trop de temps. Réessayez."],
];

/** Le texte lisible d'une erreur : une chaîne, un `Error`, ou un détail JSON. */
export function messagePourUtilisateur(erreur) {
  let texte = "";
  if (erreur && typeof erreur === "object" && "message" in erreur) texte = String(erreur.message || "");
  else texte = String(erreur ?? "");
  texte = texte.trim();
  if (!texte) return "";
  // Un détail JSON brut (`{"detail":"…"}`) : on en lit le texte.
  if (texte.startsWith("{") || texte.startsWith("[")) {
    try {
      const corps = JSON.parse(texte);
      const detail = corps && (corps.detail ?? corps.message ?? corps.error);
      texte = typeof detail === "string" ? detail : "";
    } catch {
      /* pas du JSON : on garde le texte */
    }
    if (!texte) return "Une erreur est survenue. Réessayez, ou actualisez la page.";
  }
  for (const [motif, phrase] of CAS) {
    if (motif.test(texte)) return phrase;
  }
  return texte;
}
