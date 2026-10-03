// Les connecteurs réglés avant le premier message : l'aperçu, les choix en
// attente, et ce qui part réellement à la création.

import { bilan, egal, verifier } from "./verifier.mjs";
import {
  apercuPossible,
  choixAEnvoyer,
  fusionnerLesChoix,
} from "../../mcp_gateway/atelier/web/js/ui/connecteurs-avant-envoi.js";

const lignes = [
  { id: "wikichat", active: true },
  { id: "onyxia", active: false },
  { id: "atelier", active: true, fixe: true },
];

verifier("les choix en attente passent par-dessus l'aperçu", () => {
  const sortie = fusionnerLesChoix(lignes, { onyxia: true });
  egal(sortie.find((c) => c.id === "onyxia").active, true);
  egal(sortie.find((c) => c.id === "wikichat").active, true);
});

verifier("sans choix ni aperçu, rien ne casse", () => {
  egal(fusionnerLesChoix(null, null), []);
  egal(fusionnerLesChoix(lignes, undefined).length, 3);
});

verifier("on n'envoie que ce qui change quelque chose", () => {
  egal(choixAEnvoyer(lignes, { onyxia: true, wikichat: true }), { onyxia: true });
});

verifier("un connecteur fixe n'est jamais envoyé", () => {
  egal(choixAEnvoyer(lignes, { atelier: false }), {});
});

verifier("cocher puis décocher n'envoie rien", () => {
  egal(choixAEnvoyer(lignes, { onyxia: false }), {});
});

verifier("l'aperçu est possible sur une conversation neuve seulement", () => {
  const base = { token: "t", view: "code", sessionId: null, espace: "assistant" };
  egal(apercuPossible(base), true);
  egal(apercuPossible({ ...base, sessionId: "s" }), false);
  egal(apercuPossible({ ...base, token: "" }), false);
  egal(apercuPossible({ ...base, espace: "projets", slug: "" }), false);
  egal(apercuPossible({ ...base, espace: "projets", slug: "p" }), true);
  egal(apercuPossible({ ...base, espace: "projets", pendingProjectSlug: "p" }), true);
});

bilan();
