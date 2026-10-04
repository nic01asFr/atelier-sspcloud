// Les erreurs dites en français, avec quoi faire — et rien d'inventé pour les autres.

import { bilan, egal, verifier } from "./verifier.mjs";
import { messagePourUtilisateur } from "../../mcp_gateway/atelier/web/js/ui/messages-erreur.js";

verifier("une coupure réseau dit de vérifier le réseau", () => {
  for (const brut of ["Failed to fetch", "NetworkError when attempting to fetch resource.", "Load failed"]) {
    egal(messagePourUtilisateur(new Error(brut)).startsWith("Connexion perdue"), true);
  }
});

verifier("la coupure du flux dit que le message est peut-être parti", () => {
  const m = messagePourUtilisateur(new Error("SSE connection error"));
  egal(m.includes("peut-être parti"), true);
  egal(m.includes("SSE"), false);
});

verifier("une clé refusée dit de se reconnecter, sans parler de clé propriétaire", () => {
  const m = messagePourUtilisateur('{"detail":"Bearer owner key required"}');
  egal(m.startsWith("Votre session a expiré"), true);
});

verifier("une erreur serveur dit de réessayer", () => {
  egal(messagePourUtilisateur("Internal Server Error").startsWith("L’Atelier a rencontré"), true);
  egal(messagePourUtilisateur(new Error("Bad Gateway")).includes("Réessayez"), true);
});

verifier("un détail JSON est lu, un message précis passe tel quel", () => {
  egal(messagePourUtilisateur('{"detail":"Le projet existe déjà"}'), "Le projet existe déjà");
  egal(messagePourUtilisateur(new Error("Mode non appliqué : refusé")), "Mode non appliqué : refusé");
});

verifier("un JSON sans texte lisible ne s'affiche pas brut", () => {
  const m = messagePourUtilisateur('{"x":1}');
  egal(m.includes("{"), false);
  egal(m.length > 0, true);
});

verifier("le vide reste vide, et tout type est accepté", () => {
  egal(messagePourUtilisateur(""), "");
  egal(messagePourUtilisateur(null), "");
  egal(messagePourUtilisateur(undefined), "");
  egal(messagePourUtilisateur({ message: "Failed to fetch" }).startsWith("Connexion perdue"), true);
});

verifier("une conversation rangée ou disparue est dite simplement", () => {
  egal(messagePourUtilisateur("session is archived").includes("rangée"), true);
  egal(messagePourUtilisateur("session not found").includes("n’existe plus"), true);
});

bilan();
