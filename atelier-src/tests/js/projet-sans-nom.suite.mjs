// Un projet « sans nom » déjà existant se nomme au premier message.

import { bilan, egal, verifier } from "./verifier.mjs";
import {
  estSansNom,
  titreAuPremierMessage,
} from "../../mcp_gateway/atelier/web/js/ui/projet-sans-nom.js";
import { projectNameFromMessage } from "../../mcp_gateway/atelier/web/js/state.js";

verifier("seul le nom de départ est « sans nom »", () => {
  egal(estSansNom({ slug: "projet-sans-nom-8", title: "Projet sans nom" }), true);
  egal(estSansNom({ slug: "projet-sans-nom-8", title: "" }), true);
  egal(estSansNom({ slug: "projet-sans-nom-8", title: "BigStarter" }), false);
  egal(estSansNom({ slug: "carte", title: "" }), false);
  egal(estSansNom(null), false);
});

verifier("le premier message nomme le projet sans nom", () => {
  const projet = { slug: "projet-sans-nom-8", title: "Projet sans nom" };
  egal(titreAuPremierMessage(projet, "Je veux une carte des écoles de Montpellier", projectNameFromMessage),
    "Je veux une carte des écoles de");
});

verifier("un nom choisi par la personne ne se touche jamais", () => {
  egal(titreAuPremierMessage({ slug: "x", title: "Mon atlas" }, "bonjour", projectNameFromMessage), "");
});

verifier("un message vide ne renomme pas", () => {
  egal(titreAuPremierMessage({ slug: "p", title: "Projet sans nom" }, "   ", projectNameFromMessage), "");
});

bilan();
